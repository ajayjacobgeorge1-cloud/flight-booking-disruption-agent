"""Unit tests for the domain tool handlers, called directly without the SDK/CLI."""
from __future__ import annotations

import json

from agent.tools import (
    find_rebooking_options,
    get_flight_status,
    get_policy,
    lookup_booking,
    rebook_itinerary,
)


def _body(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


async def test_lookup_booking_found():
    result = await lookup_booking.handler({"pnr": "abc123"})
    body = _body(result)
    assert body["pnr"] == "ABC123"
    assert body["segments"][0]["flight_number"] == "AA123"


async def test_lookup_booking_not_found():
    result = await lookup_booking.handler({"pnr": "NOPE99"})
    assert result.get("is_error") is True


async def test_get_flight_status_cancelled():
    result = await get_flight_status.handler({"flight_number": "AA123", "date": "2026-12-05"})
    body = _body(result)
    assert body["status"] == "cancelled"
    assert body["reason"] == "mechanical"


async def test_get_flight_status_unknown():
    result = await get_flight_status.handler({"flight_number": "ZZ000", "date": "2026-01-01"})
    assert result.get("is_error") is True


async def test_find_rebooking_options_returns_candidates():
    result = await find_rebooking_options.handler({"origin": "jfk", "destination": "lhr", "date": "2026-12-05"})
    body = _body(result)
    flight_numbers = {c["flight_number"] for c in body["candidates"]}
    assert flight_numbers == {"AA125", "BA178", "AA129"}


async def test_find_rebooking_options_cabin_filter():
    result = await find_rebooking_options.handler(
        {"origin": "JFK", "destination": "LHR", "date": "2026-12-05", "cabin_class": "Business"}
    )
    body = _body(result)
    assert [c["flight_number"] for c in body["candidates"]] == ["AA129"]


async def test_get_policy_known_topic():
    result = await get_policy.handler({"topic": "escalation"})
    body = _body(result)
    assert "750" in body["clause"]
    assert body["source"]


async def test_get_policy_unknown_topic():
    result = await get_policy.handler({"topic": "refunds"})
    assert result.get("is_error") is True


async def test_rebook_itinerary_mutates_booking():
    result = await rebook_itinerary.handler(
        {"pnr": "XYZ789", "new_flight_number": "AA460", "fare_difference_usd": 0}
    )
    body = _body(result)
    assert body["status"] == "confirmed"
    assert body["rebooked_to"] == "AA460"

    # Confirm the mock backend state actually changed.
    lookup = _body(await lookup_booking.handler({"pnr": "XYZ789"}))
    assert lookup["segments"][0]["flight_number"] == "AA460"
