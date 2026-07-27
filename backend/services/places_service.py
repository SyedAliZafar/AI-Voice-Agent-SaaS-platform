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
    ]
)


def _normalize(place: dict[str, Any]) -> dict[str, Any]:
    return {
        "google_place_id": place.get("id", ""),
        "name": place.get("displayName", {}).get("text", "") or "",
        "address": place.get("formattedAddress"),
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
