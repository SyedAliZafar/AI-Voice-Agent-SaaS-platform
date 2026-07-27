"""Agent 2 — the researcher. Scrapes a prospect's website and distills it into a
CompanyResearch knowledge base via DeepSeek.

This is the in-app research path (see phase2.md discussion): kept behind a narrow
`research_company()` contract so it can be swapped for an external research system
(e.g. a dedicated crawler) later without touching prospect_tasks or script_service.
"""

import httpx
from bs4 import BeautifulSoup

from backend.config import get_settings
from backend.schemas.prospect import CompanyResearch
from backend.services import llm_service

settings = get_settings()

SYSTEM_PROMPT = (
    "You are a B2B sales researcher. Given a company's name and their website text, "
    "produce a concise, factual briefing a sales rep can use to personalize an outbound "
    "cold call. Only state things you can support from the text — if something is unclear, "
    "omit it rather than guessing. Respond ONLY as strict JSON with keys: "
    "summary (string), industry (string), size_hint (string), pain_points (string[]), "
    "hooks (string[] — concrete, specific opening-line angles referencing real details), "
    "talking_points (string[]), do_not_mention (string[] — sensitive/competitor topics to "
    "avoid), sources (string[])."
)


async def _fetch_website_text(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=settings.research_http_timeout_sec, follow_redirects=True
    ) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (research bot)"})
        resp.raise_for_status()
        content = resp.content[: settings.research_max_page_bytes]

    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())
    return text[:8000]  # keep the DeepSeek prompt bounded regardless of page size


async def research_company(name: str, website: str | None, address: str | None) -> CompanyResearch:
    """Fetch what's available about a company and distill it into a CompanyResearch
    brief. Never raises for scrape failures — falls back to name/address-only research
    so one bad website doesn't fail the whole pipeline (caller sets research_status).
    """
    site_text = ""
    sources: list[str] = []
    if website:
        try:
            site_text = await _fetch_website_text(website)
            sources.append(website)
        except Exception:  # noqa: BLE001 — degrade to name-only research on any scrape failure
            site_text = ""

    user_prompt = (
        f"Company name: {name}\n"
        f"Address: {address or 'unknown'}\n"
        f"Website: {website or 'unknown'}\n\n"
        f"Website text (may be empty if unreachable):\n{site_text or '(no website text available)'}"
    )

    data = await llm_service.complete_json(SYSTEM_PROMPT, user_prompt)
    research = CompanyResearch.model_validate(data)
    if not research.sources:
        research.sources = sources
    return research
