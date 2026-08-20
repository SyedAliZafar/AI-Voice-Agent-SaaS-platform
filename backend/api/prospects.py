"""Prospecting endpoints — discovery, research status, and per-prospect calling.

tenant_id comes from the bearer token via Depends(get_current_tenant) — see
backend/api/deps.py. Every prospect_id arriving here is attacker-controlled, so lookups
go through prospect_service.get_prospect() (tenant-scoped), never get_prospect_unscoped().
"""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_tenant
from backend.database import get_db
from backend.schemas.agent import SandboxChatResponse, TestCallResponse
from backend.schemas.prospect import (
    CityAutocompleteResponse,
    CityAutocompleteResult,
    CompanyResearch,
    CsvImportResult,
    DiscoverRequest,
    ProspectCallRequest,
    ProspectResponse,
    ProspectSandboxChatRequest,
    ProspectStats,
    ProspectUpdate,
)
from backend.services import (
    agent_service,
    llm_service,
    places_service,
    prospect_service,
    sandbox_service,
    script_service,
    test_call_service,
)
from backend.workers.prospect_tasks import discover_prospects, research_prospect

router = APIRouter()

VALID_OUTREACH_STATUSES = {"not_reached", "reached", "callback", "do_not_call"}
VALID_STATUSES = {"not_called", "called", "booked", "flagged", "no_answer", "do_not_call"}


def _build_personalized_prompt(agent, prospect) -> str:
    """The single place /call and /sandbox-chat assemble a prospect's personalized
    script — both call only this, which is what makes the sandbox provably say what
    the real call would say (see script_service.build_prospect_prompt's docstring).
    """
    research = CompanyResearch.model_validate(prospect.research or {})
    return script_service.build_prospect_prompt(
        agent.system_prompt,
        prospect.name,
        research,
        prospect_notes=prospect.prospect_notes,
    )


@router.post("/discover", status_code=202)
async def discover(
    payload: DiscoverRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """Enqueues Agent 1 (Places discovery, auto-chaining Agent 2 research per new
    prospect). Returns immediately — poll GET / to watch rows appear and research
    flip to "ready".
    """
    discover_prospects.delay(
        str(tenant_id), payload.query, payload.location, payload.radius_m, payload.limit
    )
    return {"status": "queued"}


@router.post("/import-csv", response_model=CsvImportResult)
async def import_csv(
    file: UploadFile = File(...),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Bulk-create prospects from an operator's list, then research each imported row.

    Columns: business_name, phone (required); city, country, source, niche, website,
    address (optional). Bad rows are skipped and counted rather than failing the upload — see
    CsvImportResult, whose with_website/without_website split says how many of the
    imported rows will get degraded (name-only) research.

    Research is enqueued per imported row, the same one-task-per-prospect pattern
    discovery uses (prospect_tasks._discover). This is only non-blocking because
    CELERY_TASK_ALWAYS_EAGER is false — under eager mode .delay() runs the task body
    inline and this loop would hold the upload request open for a scrape + LLM call per
    row. See RUN.md; eager mode is documented as local-dev-only for exactly this reason.

    Declared above /{prospect_id} so the literal path wins the route match.
    """
    raw = await file.read()
    try:
        # utf-8-sig: Excel's "Save as CSV UTF-8" writes a BOM, which would otherwise
        # end up glued to the first header name and break the required-column check.
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="File must be UTF-8 encoded text") from exc

    try:
        result = await prospect_service.import_from_csv(db, tenant_id, content)
    except prospect_service.CsvImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for prospect_id in result.imported_ids:
        research_prospect.delay(str(prospect_id))
    return result


@router.get("/city-autocomplete", response_model=CityAutocompleteResponse)
async def city_autocomplete(
    input: str,
    session_token: str,
    region_code: str | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
):
    """Type-ahead suggestions for the discovery "Where" field. Declared above
    /{prospect_id} so the literal path wins the route match (same reasoning as
    /stats and /import-csv above).

    tenant_id is required even though this route reads nothing tenant-scoped: without
    auth, this would be a free, unauthenticated relay onto a billed Google SKU.

    A short input is rejected before ever reaching Google — defense in depth beyond
    the frontend's own debounce, since a client bug or a direct hit on this endpoint
    shouldn't be able to bill a request per keystroke.
    """
    if len(input.strip()) < 2:
        return CityAutocompleteResponse(suggestions=[])

    suggestions = await places_service.autocomplete_cities(input, session_token, region_code)
    return CityAutocompleteResponse(suggestions=[CityAutocompleteResult(**s) for s in suggestions])


@router.get("", response_model=list[ProspectResponse])
async def list_prospects(
    research_status: str | None = None,
    outreach_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await prospect_service.list_prospects(
        db, tenant_id, research_status, outreach_status, limit, offset
    )


@router.get("/stats", response_model=ProspectStats)
async def prospect_stats(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Counts for the /prospects strip. Declared above /{prospect_id} so the literal
    path wins the route match rather than being parsed as a UUID.
    """
    counts = await prospect_service.count_by_status(db, tenant_id)
    # Filter to known fields: a status value that predates or outlives VALID_STATUSES
    # should not turn this endpoint into a 500.
    return ProspectStats(**{k: v for k, v in counts.items() if k in ProspectStats.model_fields})


@router.get("/{prospect_id}", response_model=ProspectResponse)
async def get_prospect(
    prospect_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.post("/{prospect_id}/research", status_code=202)
async def rerun_research(
    prospect_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    research_prospect.delay(str(prospect_id))
    return {"status": "queued"}


@router.patch("/{prospect_id}", response_model=ProspectResponse)
async def update_prospect(
    prospect_id: uuid.UUID,
    payload: ProspectUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    if payload.outreach_status and payload.outreach_status not in VALID_OUTREACH_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"Invalid outreach_status: {payload.outreach_status}"
        )
    if payload.status and payload.status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status: {payload.status}")

    prospect = None
    if "prospect_notes" in payload.model_fields_set:
        # Keyed on model_fields_set, not truthiness: an explicit null/"" means "clear
        # these notes", which is indistinguishable from "not supplied" otherwise.
        prospect = await prospect_service.set_notes(
            db, prospect_id, tenant_id, payload.prospect_notes
        )
    if payload.outreach_status:
        prospect = await prospect_service.set_outreach_status(
            db, prospect_id, tenant_id, payload.outreach_status
        )
    if payload.status:
        prospect = await prospect_service.set_status(db, prospect_id, tenant_id, payload.status)
    if prospect is None and not (
        payload.outreach_status or payload.status or "prospect_notes" in payload.model_fields_set
    ):
        prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)

    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.post("/{prospect_id}/call", response_model=TestCallResponse)
async def call_prospect(
    prospect_id: uuid.UUID,
    payload: ProspectCallRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Dial this prospect. Two agent sources, and they behave differently on purpose.

    With a local `agent_id` (the normal path): personalizes that agent's campaign script
    with this prospect's research and operator notes ([COMPANY BRIEF] + [OPERATOR NOTES]
    injection — script_service.build_prospect_prompt) and places the call via the same
    Retell provisioning path as a plain test call.

    With an `external_agent_id` (ADR-012): dials a platform-native agent, which holds its
    own script in the platform's dashboard. The researched brief does **not** reach it —
    there is no channel to hand a dashboard-configured agent a whole call-scoped prompt.
    What does reach it is `dynamic_variables`, filling the `{{placeholders}}` that script
    already declares (`{{company_name}}` and friends), so the call is personalized to the
    extent the prompt's author made room for. The outreach counter advances either way,
    since the prospect was called.

    The research-ready gate applies only to the personalized path: it exists because the
    prompt needs the [COMPANY BRIEF], so with nothing to inject there is nothing to wait
    for. That also makes a CSV-imported prospect (which never reaches research_status
    "ready" — see ADR-006) dialable through a platform agent.
    """
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")

    to_number = payload.to_number or prospect.phone
    if not to_number:
        raise HTTPException(status_code=422, detail="No phone number on file for this prospect")

    if payload.external_agent_id:
        try:
            result = await test_call_service.place_platform_agent_call(
                db,
                tenant_id,
                payload.external_agent_id,
                to_number,
                dynamic_variables=payload.dynamic_variables,
            )
        except test_call_service.TestCallError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        await prospect_service.record_call(db, prospect_id, tenant_id)
        return result

    if prospect.research_status != "ready":
        raise HTTPException(
            status_code=422,
            detail=f"Prospect research is '{prospect.research_status}', not ready yet",
        )

    agent = await agent_service.get_agent(db, payload.agent_id, tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    personalized_prompt = _build_personalized_prompt(agent, prospect)

    try:
        result = await test_call_service.place_test_call(
            db,
            agent.id,
            tenant_id,
            to_number,
            system_prompt_override=personalized_prompt,
        )
    except test_call_service.TestCallError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await prospect_service.record_call(db, prospect_id, tenant_id)
    return result


@router.post("/{prospect_id}/sandbox-chat", response_model=SandboxChatResponse)
async def prospect_sandbox_chat(
    prospect_id: uuid.UUID,
    payload: ProspectSandboxChatRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """Hear how this agent would talk to this specific prospect, over text — no phone
    call, no telephony spend.

    Builds the exact same prompt /call would (agent's base script + this prospect's
    researched [COMPANY BRIEF] + [OPERATOR NOTES] via script_service.build_prospect_prompt)
    and runs it through sandbox_service.chat() — the same stateless text-chat mechanism
    /api/agents/{id}/sandbox-chat uses. What the operator sees here is provably what the
    real call would say, because both paths build the prompt through the one function.

    Lives here rather than in api/agents.py because it needs prospect_id to resolve
    research/prospect_notes via the tenant-scoped prospect_service.get_prospect() —
    exactly the same reasoning /call already follows.
    """
    prospect = await prospect_service.get_prospect(db, prospect_id, tenant_id)
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    if prospect.research_status != "ready":
        raise HTTPException(
            status_code=422,
            detail=f"Prospect research is '{prospect.research_status}', not ready yet",
        )

    agent = await agent_service.get_agent(db, payload.agent_id, tenant_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    personalized_prompt = _build_personalized_prompt(agent, prospect)

    try:
        result = await sandbox_service.chat(
            db,
            payload.agent_id,
            tenant_id,
            [m.model_dump() for m in payload.messages],
            system_prompt_override=personalized_prompt,
            model=payload.model,
            tools_enabled=False,
        )
    except sandbox_service.SandboxError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except llm_service.LLMConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result
