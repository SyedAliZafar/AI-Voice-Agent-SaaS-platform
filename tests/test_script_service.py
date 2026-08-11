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


# --- operator notes ---------------------------------------------------------------


def test_build_prospect_prompt_includes_operator_notes():
    result = script_service.build_prospect_prompt(
        "[ROLE] base",
        "Acme",
        CompanyResearch(summary="A dental clinic."),
        prospect_notes="Gatekeeper is Maria. Owner only answers before 9am.",
    )

    assert "OPERATOR NOTES" in result
    assert "Gatekeeper is Maria." in result
    assert "Owner only answers before 9am." in result


def test_operator_notes_come_after_the_researched_brief():
    """Ordering is load-bearing: the notes block tells the model to trust it over the
    brief, which only makes sense once the brief has already been stated.
    """
    result = script_service.build_prospect_prompt(
        "[ROLE] base",
        "Acme",
        CompanyResearch(summary="Scraped summary."),
        prospect_notes="Hand-written.",
    )

    assert result.index("COMPANY BRIEF") < result.index("OPERATOR NOTES")


def test_no_notes_block_when_notes_are_absent_or_blank():
    """An empty section would be noise in every un-annotated prospect's prompt."""
    for notes in (None, "", "   \n  "):
        result = script_service.build_prospect_prompt(
            "[ROLE] base", "Acme", CompanyResearch(), prospect_notes=notes
        )
        assert "OPERATOR NOTES" not in result


def test_notes_are_purely_additive_to_the_base_script_and_brief():
    base = "[ROLE] You are Alex, an SDR for Acme.\n[GUARDRAILS] Never lie."
    research = CompanyResearch(summary="They sell dental supplies.", hooks=["New Berlin location"])

    without = script_service.build_prospect_prompt(base, "Acme Dental", research)
    with_notes = script_service.build_prospect_prompt(
        base, "Acme Dental", research, prospect_notes="Call after lunch."
    )

    assert with_notes.startswith(without)  # appended last, nothing above it disturbed
