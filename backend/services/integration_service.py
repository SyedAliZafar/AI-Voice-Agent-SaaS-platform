"""Third-party integrations: CRM sync, calendar booking, custom webhooks.

Keep each integration's API quirks isolated in its own function — tools/
call into these rather than making raw HTTP calls themselves.
"""

from typing import Any

import httpx


async def create_hubspot_contact(email: str, phone: str, notes: str, api_key: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"properties": {"email": email, "phone": phone, "notes": notes}},
        )
        resp.raise_for_status()
        return resp.json()


async def book_calendar_slot(
    calendar_id: str, start_time: str, duration_min: int, attendee_email: str, api_key: str
) -> dict[str, Any]:
    """Books via Cal.com API. Swap for Google Calendar API as needed."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.cal.com/v1/bookings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "eventTypeId": calendar_id,
                "start": start_time,
                "attendee": {"email": attendee_email},
            },
        )
        resp.raise_for_status()
        return resp.json()
