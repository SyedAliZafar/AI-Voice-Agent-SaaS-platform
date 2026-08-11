"""Tests for the Google Places adapter — specifically the typed-address extraction
that feeds Prospect.city / Prospect.country.

The HTTP call itself isn't exercised here (that's a billed external API); what matters
is that we read Google's addressComponents correctly, since the alternative this
replaced — parsing formattedAddress — is what these tests exist to keep us away from.
"""

import pytest

from backend.services import places_service


def _component(long_text: str, *types: str) -> dict:
    # shortText is deliberately different from longText so a test asserting on the
    # full name can't pass by accidentally reading the abbreviation.
    return {"longText": long_text, "shortText": long_text[:2].upper(), "types": list(types)}


def test_extracts_city_and_country_from_locality():
    city, country = places_service._extract_city_country(
        [
            _component("13", "street_number"),
            _component("Harbury Road", "route"),
            _component("Berlin", "locality", "political"),
            _component("Germany", "country", "political"),
        ]
    )

    assert city == "Berlin"
    assert country == "Germany"


def test_falls_back_to_postal_town_when_there_is_no_locality():
    """UK addresses routinely carry the town as postal_town with no locality at all —
    every prospect currently in this database is UK, so without this fallback city
    would come back null for all of them.
    """
    city, country = places_service._extract_city_country(
        [
            _component("Harbury Road", "route"),
            _component("Bristol", "postal_town"),
            _component("BS9 4PN", "postal_code"),
            _component("United Kingdom", "country", "political"),
        ]
    )

    assert city == "Bristol"
    assert country == "United Kingdom"


def test_locality_wins_over_postal_town_even_when_listed_later():
    """Google can send both. locality is the more precise tag, and component order is
    Google's choice — so preference must come from the type, not the array position.
    """
    city, _ = places_service._extract_city_country(
        [
            _component("Greater London", "postal_town"),
            _component("Camden", "locality"),
            _component("United Kingdom", "country"),
        ]
    )

    assert city == "Camden"


def test_uses_the_full_country_name_not_the_short_code():
    """These strings are shown directly as grouping headers in the operator UI, so
    "United Kingdom" is wanted rather than "GB".
    """
    _, country = places_service._extract_city_country(
        [{"longText": "United Kingdom", "shortText": "GB", "types": ["country"]}]
    )

    assert country == "United Kingdom"


def test_missing_components_are_none_not_guessed():
    """A place with no locality/country tagged is normal. Returning None keeps that
    honest instead of inventing a value from some other field.
    """
    city, country = places_service._extract_city_country([_component("Some Road", "route")])

    assert city is None
    assert country is None


def test_handles_no_components_at_all():
    assert places_service._extract_city_country([]) == (None, None)


def test_normalize_surfaces_city_and_country():
    """The whole point of the field-mask change — a dropped key here means every newly
    discovered prospect silently lands with no city/country.
    """
    normalized = places_service._normalize(
        {
            "id": "place_abc",
            "displayName": {"text": "Acme Solar"},
            "formattedAddress": "13 Harbury Rd, Bristol BS9 4PN, UK",
            "addressComponents": [
                _component("Bristol", "postal_town"),
                _component("United Kingdom", "country"),
            ],
        }
    )

    assert normalized["city"] == "Bristol"
    assert normalized["country"] == "United Kingdom"
    assert normalized["address"] == "13 Harbury Rd, Bristol BS9 4PN, UK"


def test_normalize_tolerates_a_response_without_address_components():
    """Defensive: rows discovered before addressComponents was in the field mask, and
    any response where Google simply omits it, must normalize rather than raise.
    """
    normalized = places_service._normalize(
        {"id": "place_abc", "displayName": {"text": "Acme Solar"}}
    )

    assert normalized["city"] is None
    assert normalized["country"] is None


@pytest.mark.asyncio
async def test_get_place_city_country_looks_up_by_id(monkeypatch):
    """The backfill path. Must be an exact-id Details lookup, not a text search — a
    search could match a different business and write the wrong city onto a real row.
    """
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "addressComponents": [
                    _component("Bristol", "postal_town"),
                    _component("United Kingdom", "country"),
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            captured.update(url=url, headers=headers or {})
            return _Resp()

    monkeypatch.setattr(places_service.settings, "google_places_api_key", "test-key")
    monkeypatch.setattr(places_service.httpx, "AsyncClient", lambda **kw: _Client())

    city, country = await places_service.get_place_city_country("place_abc")

    assert (city, country) == ("Bristol", "United Kingdom")
    assert captured["url"].endswith("/places/place_abc")
    # Only the one field is requested — everything else would be billed for nothing.
    assert captured["headers"]["X-Goog-FieldMask"] == "addressComponents"


@pytest.mark.asyncio
async def test_autocomplete_cities_normalizes_google_response(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "suggestions": [
                    {
                        "placePrediction": {
                            "placeId": "place_bristol",
                            "structuredFormat": {
                                "mainText": {"text": "Bristol"},
                                "secondaryText": {"text": "United Kingdom"},
                            },
                        }
                    },
                    {
                        "placePrediction": {
                            "placeId": "place_berlin",
                            "structuredFormat": {
                                "mainText": {"text": "Berlin"},
                                "secondaryText": {"text": "Germany"},
                            },
                        }
                    },
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers or {}, json=json or {})
            return _Resp()

    monkeypatch.setattr(places_service.settings, "google_places_api_key", "test-key")
    monkeypatch.setattr(places_service.httpx, "AsyncClient", lambda **kw: _Client())

    result = await places_service.autocomplete_cities("Bri", "session-abc")

    assert result == [
        {"place_id": "place_bristol", "label": "Bristol, United Kingdom"},
        {"place_id": "place_berlin", "label": "Berlin, Germany"},
    ]
    assert captured["json"]["input"] == "Bri"
    assert captured["json"]["includedPrimaryTypes"] == ["(cities)"]
    assert captured["json"]["sessionToken"] == "session-abc"
    assert "regionCode" not in captured["json"]  # omitted, not sent as null


@pytest.mark.asyncio
async def test_autocomplete_cities_passes_region_code_when_given(monkeypatch):
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"suggestions": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(json=json or {})
            return _Resp()

    monkeypatch.setattr(places_service.settings, "google_places_api_key", "test-key")
    monkeypatch.setattr(places_service.httpx, "AsyncClient", lambda **kw: _Client())

    await places_service.autocomplete_cities("Bri", "session-abc", region_code="GB")

    assert captured["json"]["regionCode"] == "GB"


@pytest.mark.asyncio
async def test_autocomplete_cities_skips_suggestions_missing_a_place_id_or_name(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "suggestions": [
                    {"placePrediction": {"structuredFormat": {"mainText": {"text": "No Id"}}}},
                    {"placePrediction": {"placeId": "place_no_name"}},
                ]
            }

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def post(self, url, headers=None, json=None):
            return _Resp()

    monkeypatch.setattr(places_service.settings, "google_places_api_key", "test-key")
    monkeypatch.setattr(places_service.httpx, "AsyncClient", lambda **kw: _Client())

    result = await places_service.autocomplete_cities("x", "session-abc")

    assert result == []


def test_address_components_is_in_the_field_mask():
    """Places v1 only returns what the mask asks for — if this is dropped, extraction
    silently yields None for every prospect forever.
    """
    assert "places.addressComponents" in places_service.FIELD_MASK
