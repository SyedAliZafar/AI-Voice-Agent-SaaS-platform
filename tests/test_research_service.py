"""Tests for research_service — mocks the HTTP fetch and DeepSeek call entirely;
verifies our orchestration (fallback on scrape failure, contract with llm_service).
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services import research_service


@pytest.mark.asyncio
async def test_research_company_uses_scraped_text_and_llm_output():
    fake_completion = {
        "summary": "Acme sells dental supplies.",
        "industry": "Healthcare",
        "size_hint": "50-200 employees",
        "pain_points": ["Slow supplier response times"],
        "hooks": ["They recently opened a second location"],
        "talking_points": [],
        "do_not_mention": [],
        "sources": [],
    }

    with (
        patch.object(
            research_service, "_fetch_website_text", AsyncMock(return_value="Acme site text")
        ),
        patch(
            "backend.services.llm_service.complete_json",
            AsyncMock(return_value=fake_completion),
        ),
    ):
        research = await research_service.research_company(
            "Acme Dental", "https://acmedental.com", "Berlin"
        )

    assert research.summary == "Acme sells dental supplies."
    assert research.hooks == ["They recently opened a second location"]
    assert research.sources == ["https://acmedental.com"]


@pytest.mark.asyncio
async def test_research_company_degrades_gracefully_on_scrape_failure():
    fake_completion = {"summary": "Name-only research.", "sources": []}

    with (
        patch.object(
            research_service,
            "_fetch_website_text",
            AsyncMock(side_effect=httpx.ConnectTimeout("timed out")),
        ),
        patch(
            "backend.services.llm_service.complete_json",
            AsyncMock(return_value=fake_completion),
        ),
    ):
        research = await research_service.research_company(
            "Acme Dental", "https://unreachable.example", None
        )

    # Doesn't raise — falls back to name-only research with no sources.
    assert research.summary == "Name-only research."
    assert research.sources == []


@pytest.mark.asyncio
async def test_research_company_skips_fetch_when_no_website():
    fetch_mock = AsyncMock()
    with (
        patch.object(research_service, "_fetch_website_text", fetch_mock),
        patch(
            "backend.services.llm_service.complete_json",
            AsyncMock(return_value={"summary": "No website on file."}),
        ),
    ):
        research = await research_service.research_company("Acme Dental", None, "Berlin")

    fetch_mock.assert_not_awaited()
    assert research.summary == "No website on file."
