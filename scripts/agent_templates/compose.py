"""Assembles a full agent system_prompt from a (style, service, industry) triple.

This is the module/template system requested in place of hand-writing each leaf's full
prompt text — adding a new industry (industries.py) or service (services.py) makes it
available to every existing style automatically, and every combination is composed from
the same shared confirmation/objection blocks (shared.py) so a real-call fix (like the
"at the rate gmail" one) only needs to change in one place.
"""

from scripts.agent_templates import shared
from scripts.agent_templates.industries import INDUSTRIES
from scripts.agent_templates.services import SERVICES
from scripts.agent_templates.styles import STYLES


def agent_name(style_key: str, service_key: str, industry_key: str) -> str:
    style = STYLES[style_key]
    service = SERVICES[service_key]
    industry = INDUSTRIES[industry_key]
    return f"{industry['label']} Outbound — {service['label']} — {style['label']} v1"


def compose(style_key: str, service_key: str, industry_key: str) -> str:
    style = STYLES[style_key]
    service = SERVICES[service_key]
    industry = INDUSTRIES[industry_key]

    validated_note = (
        "" if industry.get("validated") else (
            "\n**Note:** this industry vertical is unvalidated — vocabulary/objections "
            "are a hypothesis, not tuned on real calls yet."
        )
    )

    objection_bank = shared.GENERIC_OBJECTION_BANK.format(
        extra_rows=industry["extra_objection_rows"]
    ).rstrip()

    return f"""\
# {industry['label']} outbound knowledge base — {service['label']} / {style['label']} v1

**Context:** Cold outbound call to {industry['label']} business owners. \
{service['hook']}{validated_note}

{shared.REALISTIC_GOAL}

---

{shared.CALL_OPENING_SEQUENCE}
{style['call_shape']}

## Qualifying flow (never before Beat 3 — for Short Quick, only once the interest check \
has been cleared)

{industry['qualifying_flow']}

The point of this sequence isn't a script to read verbatim — it's to surface a real \
cost (missed job/booking value) before pitching anything. Never pitch before qualifying \
is complete.

{objection_bank}

{shared.PRICING_GUARDRAIL}

## Vocabulary (credibility markers)

{industry['vocabulary']}

{service['positioning']}

## Close sequence

Hook (opener) → qualify pain → bridge to broader automation opportunity → **confirm \
captured details** → book discovery call with Ali. Stop there.

{shared.BOOKING_CONFIRMATION}

---

{shared.STATUS_FOOTER}{"" if style_key == "long_detail" and industry.get("validated") else _extra_status_note(style_key, industry)}
"""


def _extra_status_note(style_key: str, industry: dict) -> str:
    if industry.get("validated") and style_key == "short_quick":
        return (
            "\n\n**Note:** this industry's qualifying flow/vocabulary is copied from a "
            "real-call-tested base agent, but the Short Quick interest-gate/close "
            "mechanic in this specific combination is new and untested."
        )
    return ""


def all_combinations() -> list[tuple[str, str, str]]:
    return [
        (style_key, service_key, industry_key)
        for style_key in STYLES
        for service_key in SERVICES
        for industry_key in INDUSTRIES
    ]
