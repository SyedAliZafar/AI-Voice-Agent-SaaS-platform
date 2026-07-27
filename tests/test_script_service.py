"""Tests for [COMPANY BRIEF] injection — the "read the script and modify it
according to the knowledge base" personalization path.
"""

from backend.schemas.prospect import CompanyResearch
from backend.services import script_service


def test_build_prospect_prompt_preserves_base_script():
    base = "[ROLE] You are Alex, an SDR for Acme.\n[GUARDRAILS] Never lie."
    research = CompanyResearch(summary="They sell dental supplies.")

    result = script_service.build_prospect_prompt(base, "Acme Dental", research)

    assert result.startswith(base)


def test_build_prospect_prompt_includes_company_details():
    research = CompanyResearch(
        summary="A growing dental clinic chain.",
        industry="Healthcare",
        pain_points=["Long patient wait times"],
        hooks=["Mention their new Berlin location"],
        talking_points=["We integrate with their booking software"],
    )

    result = script_service.build_prospect_prompt("[ROLE] base script", "Acme Dental", research)

    assert "Acme Dental" in result
    assert "A growing dental clinic chain." in result
    assert "Long patient wait times" in result
    assert "Mention their new Berlin location" in result
    assert "We integrate with their booking software" in result


def test_build_prospect_prompt_includes_global_and_company_rules():
    research = CompanyResearch(do_not_mention=["their recent lawsuit"])

    result = script_service.build_prospect_prompt("[ROLE] base", "Acme", research)

    assert "guaranteed" in result  # global never-say
    assert "their recent lawsuit" in result  # company-specific never-promise/mention


def test_build_prospect_prompt_handles_empty_research_gracefully():
    result = script_service.build_prospect_prompt("[ROLE] base", "Acme", CompanyResearch())

    assert "Acme" in result
    assert "no specific hook found" in result.lower() or "none identified" in result.lower()
