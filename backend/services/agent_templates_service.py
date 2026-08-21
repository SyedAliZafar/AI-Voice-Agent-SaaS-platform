"""Runtime access to the scripts/agent_templates module system.

Deliberately importing from scripts/ rather than duplicating industry/service/style
content into backend/ — that duplication is exactly the drift FRONTEND.md warns about
for lib/types.ts, and scripts/agent_templates is already the single source of truth
compose.py assembles prompts from (used today by scripts/build_agent_matrix.py for bulk
seeding). scripts/ is dev-tooling in *location* only; this module makes its content
reachable from the live API too, read-only — nothing here mutates the template module,
and adding an industry/service/style still only means editing one file in
scripts/agent_templates, same as before.
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.agent_templates.compose import agent_name, compose  # noqa: E402
from scripts.agent_templates.industries import INDUSTRIES  # noqa: E402
from scripts.agent_templates.services import SERVICES  # noqa: E402
from scripts.agent_templates.styles import STYLES  # noqa: E402


class UnknownTemplateError(ValueError):
    """Raised for a (style, service, industry) triple that isn't a real combination —
    a stale key from a client that cached the list before an industry was removed."""


def list_templates() -> list[dict]:
    """Every (style, service, industry) combination, same enumeration order as
    compose.all_combinations(), with the labels and composed name a gallery needs to
    render a card without composing the full prompt for each one up front."""
    return [
        {
            "style": style_key,
            "service": service_key,
            "industry": industry_key,
            "style_label": STYLES[style_key]["label"],
            "service_label": SERVICES[service_key]["label"],
            "industry_label": INDUSTRIES[industry_key]["label"],
            "name": agent_name(style_key, service_key, industry_key),
            # Whether this industry's qualifying flow/vocabulary is backed by a real
            # call transcript, or is a written-but-untested hypothesis (compose.py
            # injects the same distinction into the prompt itself as a note to the
            # model) — the gallery surfaces it so a demo doesn't oversell a leaf
            # nobody's actually called with yet.
            "validated": bool(INDUSTRIES[industry_key].get("validated")),
        }
        for style_key in STYLES
        for service_key in SERVICES
        for industry_key in INDUSTRIES
    ]


def compose_prompt(style: str, service: str, industry: str) -> tuple[str, str]:
    """(name, system_prompt) for one template, or UnknownTemplateError for a bad key."""
    if style not in STYLES or service not in SERVICES or industry not in INDUSTRIES:
        raise UnknownTemplateError(f"Unknown template: {style}/{service}/{industry}")
    return agent_name(style, service, industry), compose(style, service, industry)
