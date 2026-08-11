"""Turns a campaign's system_prompt + a prospect's research into a personalized
script — "read the script and modify it according to the knowledge base," per the
product decision to inject rather than regenerate (cheaper, faster, preserves the
operator's crafted script; see phase2.md / CONTEXT.md prompt architecture).

Knowledge delivery: brief-in-prompt only for now (the USP — research-driven
personalization with zero extra Retell setup). A Retell Knowledge Base for
mid-call curveballs is a later hardening layer; this function is the seam —
swapping/augmenting delivery only touches this file.
"""

from backend.schemas.prospect import CompanyResearch

GLOBAL_NEVER_SAY = [
    "guaranteed",
    "risk-free",
    "instant results",
]
GLOBAL_NEVER_PROMISE = [
    "specific ROI or revenue numbers",
    "a discount or price the operator hasn't approved",
    "implementation timelines",
]


def build_prospect_prompt(
    campaign_system_prompt: str,
    company_name: str,
    research: CompanyResearch,
    extra_never_say: list[str] | None = None,
    extra_never_promise: list[str] | None = None,
    prospect_notes: str | None = None,
) -> str:
    """Inject a [COMPANY BRIEF] + [RULES] block into an existing campaign script.
    Idempotent-ish: always appends a fresh block, so re-running research and
    re-personalizing simply produces a new combined prompt (the caller decides
    whether to base off the original campaign prompt or a prior personalized one —
    test_call_service always starts from Agent.system_prompt, the source of truth).

    `prospect_notes` is the operator's own hand-written context. It lands in its own
    [OPERATOR NOTES] section *after* the researched brief and is described to the model
    as outranking it, because a human who just got off the phone with this company knows
    things the scraper cannot.

    This function is the single place personalization is assembled, which is what makes
    the sandbox test and the real call provably say the same thing — both endpoints in
    api/prospects.py go through _build_personalized_prompt(), which calls only this.
    """
    hooks = "\n".join(f"  - {h}" for h in research.hooks) or "  - (no specific hook found)"
    pain_points = "\n".join(f"  - {p}" for p in research.pain_points) or "  - (none identified)"
    talking_points = (
        "\n".join(f"  - {t}" for t in research.talking_points) or "  - (none identified)"
    )

    never_say = GLOBAL_NEVER_SAY + (extra_never_say or [])
    never_promise = GLOBAL_NEVER_PROMISE + (extra_never_promise or []) + research.do_not_mention

    notes = (prospect_notes or "").strip()
    notes_block = (
        f"""

[OPERATOR NOTES — {company_name}]
The operator added this by hand. Where it conflicts with the company brief above,
trust these notes — they are more recent and come from a human who knows this account.
{notes}"""
        if notes
        else ""
    )

    brief = f"""

[COMPANY BRIEF — {company_name}]
{research.summary or "No summary available."}
Industry: {research.industry or "unknown"}. Size: {research.size_hint or "unknown"}.

Likely pain points:
{pain_points}

Opening hooks (use one, adapt naturally — do not read verbatim):
{hooks}

Talking points to weave in if relevant:
{talking_points}

[RULES]
Never say: {", ".join(never_say)}.
Never promise: {", ".join(never_promise)}.
If the prospect raises something not covered here, fall back to the base script's
guardrails rather than guessing at facts about {company_name}."""

    return campaign_system_prompt.rstrip() + brief + notes_block
