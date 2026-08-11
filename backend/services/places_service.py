"""Google Places API (v1) integration — all Places HTTP isolated here, same
adapter discipline as the voice-platform adapters (ADR-002): callers get
normalized dicts, never raw Google response shapes, and never call the
Places API directly from services/tasks.
"""

from typing import Any

import httpx

from backend.config import get_settings

settings = get_settings()

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
# Place Details (New) — GET {DETAILS_URL}/{place_id}, used by the city/country backfill.
DETAILS_URL = "https://places.googleapis.com/v1/places"
AUTOCOMPLETE_URL = "https://places.googleapis.com/v1/places:autocomplete"

# Only request the fields we actually use — Places v1 bills by field mask.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.rating",
        "places.userRatingCount",
        "places.primaryTypeDisplayName",
        # Typed address parts (locality/country/...), the source of Prospect.city and
        # .country. Same Pro SKU as formattedAddress/displayName above, and this mask
        # already reaches the Enterprise tier via rating/websiteUri — so asking for it
        # adds no billing tier. Structured components beat parsing formattedAddress,
        # whose component order varies by country.
        "places.addressComponents",
    ]
)

# Google's own type tags on each address component. "locality" is the usual city tag,
# but UK addresses frequently carry the town as "postal_town" with no locality at all —
# every current row in this database is UK, so without the fallback city would come back
# null for all of them.
_CITY_TYPES = ("locality", "postal_town")


def _extract_city_country(components: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Pull (city, country) out of Places' typed addressComponents.

    Uses `longText` for both — the full name ("Bristol", "United Kingdom") rather than
    `shortText`'s abbreviation ("GB"), because these are shown directly as grouping
    headers in the operator UI. Returns None for anything Google didn't tag; a missing
    component is normal (some places have no locality at all) and must not be guessed at.
    """
    by_type: dict[str, str] = {}
    for component in components:
        text = component.get("longText") or None
        if not text:
            continue
        for type_name in component.get("types") or []:
            # First component carrying a given type wins; Google can repeat a type
            # across components and the earlier one is the more specific.
            by_type.setdefault(type_name, text)

    # Indexed by type rather than scanned in array order, so _CITY_TYPES' preference
    # actually holds: a real "locality" beats a "postal_town" even when Google lists
    # the postal_town component first.
    city = next((by_type[t] for t in _CITY_TYPES if t in by_type), None)
    return city, by_type.get("country")


def _normalize(place: dict[str, Any]) -> dict[str, Any]:
    city, country = _extract_city_country(place.get("addressComponents") or [])
    return {
        "google_place_id": place.get("id", ""),
        "name": place.get("displayName", {}).get("text", "") or "",
        "address": place.get("formattedAddress"),
        "city": city,
        "country": country,
        "phone": place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount", 0) or 0,
        "category": (place.get("primaryTypeDisplayName") or {}).get("text"),
    }


async def search_places(
    query: str, location: str | None = None, radius_m: int = 20_000, limit: int = 20
) -> list[dict[str, Any]]:
    """Text-search Google Places. `location` is a free-text bias hint (e.g. "Berlin,
    Germany") appended to the query — Places v1 text search resolves it without needing
    us to geocode separately, keeping this a single API call per discovery run.

    `radius_m` is accepted for API stability but not yet applied: doing so properly needs
    a geocoded lat/lng center for locationBias, which would add a second Google call. Revisit
    if text-query bias proves too loose in practice.
    """
    if not settings.google_places_api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY is not set")

    text_query = f"{query} in {location}" if location else query

    async with httpx.AsyncClient(timeout=settings.research_http_timeout_sec) as client:
        resp = await client.post(
            SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": FIELD_MASK,
            },
            json={"textQuery": text_query, "maxResultCount": min(limit, 20)},
        )
        resp.raise_for_status()
        data = resp.json()

    return [_normalize(p) for p in data.get("places", [])]


async def get_place_city_country(google_place_id: str) -> tuple[str | None, str | None]:
    """Look one place up by its exact id and return (city, country).

    For backfilling rows discovered before addressComponents was in the field mask.
    Deliberately an id lookup rather than re-running a text search: a search could
    match a *different* business than the one already stored, silently writing the
    wrong city onto a real prospect. Requests only addressComponents, keeping this the
    cheapest call that answers the question (this file's existing field-mask discipline).
    """
    if not settings.google_places_api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY is not set")

    async with httpx.AsyncClient(timeout=settings.research_http_timeout_sec) as client:
        resp = await client.get(
            f"{DETAILS_URL}/{google_place_id}",
            headers={
                "X-Goog-Api-Key": settings.google_places_api_key,
                "X-Goog-FieldMask": "addressComponents",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    return _extract_city_country(data.get("addressComponents") or [])


async def autocomplete_cities(
    input_text: str, session_token: str, region_code: str | None = None
) -> list[dict[str, str]]:
    """Type-ahead city suggestions for the discovery "Where" field.

    `session_token` groups the keystrokes of one autocomplete session with whatever
    Place Details call eventually follows, for Google's session-based Autocomplete SKU
    billing — the caller mints one per typing session (frontend responsibility; this
    function just forwards it). `region_code` is accepted for a future country-narrowed
    search but unused today (v1 stays global — see the discovery UI's own reasoning).

    Never returns Google's raw suggestion shape past this file (ADR-002 discipline,
    same as _normalize()): callers get {place_id, label}, not Places' nested
    placePrediction/structuredFormat structure.
    """
    if not settings.google_places_api_key:
        raise ValueError("GOOGLE_PLACES_API_KEY is not set")

    body: dict[str, Any] = {
        "input": input_text,
        "includedPrimaryTypes": ["(cities)"],
        "sessionToken": session_token,
    }
    if region_code:
        body["regionCode"] = region_code

    async with httpx.AsyncClient(timeout=settings.research_http_timeout_sec) as client:
        resp = await client.post(
            AUTOCOMPLETE_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": settings.google_places_api_key,
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()

    suggestions = []
    for item in data.get("suggestions") or []:
        prediction = item.get("placePrediction") or {}
        place_id = prediction.get("placeId")
        # mainText is the city name, secondaryText the disambiguating region/country
        # ("Bristol" / "United Kingdom") — joined the way an operator would type it.
        structured = prediction.get("structuredFormat") or {}
        main = (structured.get("mainText") or {}).get("text")
        secondary = (structured.get("secondaryText") or {}).get("text")
        if not place_id or not main:
            continue
        label = f"{main}, {secondary}" if secondary else main
        suggestions.append({"place_id": place_id, "label": label})

    return suggestions
