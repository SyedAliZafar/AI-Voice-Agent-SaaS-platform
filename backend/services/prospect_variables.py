"""Per-prospect values for a platform agent's {{placeholders}} (ADR-012).

The Python twin of `frontend/src/lib/dynamicVariables.ts`, and it exists for a reason
the per-prospect call flow never had: in a **batch** run the browser isn't in the loop
for each dial. The operator starts a run and walks away; the next call is placed by a
Celery worker minutes later (batch_service), so "fill {{company_name}} from the prospect"
has to happen server-side, once per prospect, or every company in the batch gets called
by whatever single name was typed into the form.

Keep the alias table below in sync with the frontend's — they answer the same question
in two places because the single-prospect drawer resolves variables in the browser (the
operator reads and edits each value before dialing, which is the right trade for one
call) and batch runs resolve them here. `_OPTIONAL_VARIABLE_NAMES` in test_call_service
carries the same sync note for the same reason.
"""

import re
from datetime import datetime

from backend.models.prospect import Prospect

# Canonical key -> the other spellings prompts use for it. Two prompts written by two
# people rarely agree on a name, and the operator doesn't control what a Retell
# dashboard prompt declared.
ALIASES: dict[str, list[str]] = {
    "companyname": ["company", "businessname", "business", "prospectname", "accountname"],
    "contactname": ["contact", "name", "firstname", "ownername", "customername"],
    "phonenumber": ["usernumber", "phone", "tonumber", "callernumber", "contactnumber"],
    "city": ["town", "location"],
    "industry": ["niche", "category", "vertical"],
}

# Canonical keys whose value differs per prospect — the whole point of this module.
# `contactname` is deliberately absent: research holds no named contact, so it stays
# the operator's to supply (or to leave blank, since it's optional — see
# test_call_service._is_optional_variable).
PER_PROSPECT_KEYS = frozenset({"companyname", "phonenumber", "city", "industry"})


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def canonical_key(name: str) -> str | None:
    """Resolve a declared placeholder name to one of our canonical keys, or None."""
    key = _normalize(name)
    if key in ALIASES:
        return key
    for canonical, aliases in ALIASES.items():
        if key in aliases:
            return canonical
    return None


def is_per_prospect_variable(name: str) -> bool:
    """True when this placeholder is filled from the prospect being dialed, so a
    batch-wide value typed once would be wrong for every prospect but one.
    `current_time` counts: it's resolved at dial time, not at form time.
    """
    return _normalize(name) == "currenttime" or canonical_key(name) in PER_PROSPECT_KEYS


def suggest_for_prospect(declared: list[str], prospect: Prospect) -> dict[str, str]:
    """Values for the placeholders `declared` that this prospect can fill, keyed by the
    prompt's own spelling. Names we can't map, and names with nothing to fill them from,
    are omitted rather than returned blank — a caller merging this over operator-supplied
    values must not have a blank auto-fill clobber something the operator actually typed.
    """
    research = prospect.research or {}
    values = {
        "companyname": prospect.name or "",
        "phonenumber": prospect.phone or "",
        "city": prospect.city or "",
        "industry": (research.get("industry") if isinstance(research, dict) else "")
        or prospect.category
        or "",
    }

    out: dict[str, str] = {}
    for name in declared:
        if _normalize(name) == "currenttime":
            out[name] = datetime.now().strftime("%Y-%m-%d %H:%M")
            continue
        key = canonical_key(name)
        if key and values.get(key):
            out[name] = values[key]
    return out
