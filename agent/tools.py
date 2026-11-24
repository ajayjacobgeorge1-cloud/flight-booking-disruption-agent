"""The 5 domain tools, exposed as an in-process SDK MCP server.

Backed by the mock data in mock_data.py. `rebook_itinerary` is the one
sensitive action -- it is gated by the PreToolUse hook in hooks.py, which
runs before this module's handler and can deny the call outright.
"""
from __future__ import annotations

import json
from typing import Annotated, Any

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import mock_data


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data, indent=2)}]}


def _err(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "is_error": True}


@tool(
    "lookup_booking",
    "Look up a passenger's booking by PNR: passenger name, fare class, and booked flight segments.",
    {"pnr": Annotated[str, "5-8 character alphanumeric booking reference"]},
)
async def lookup_booking(args: dict[str, Any]) -> dict[str, Any]:
    pnr = (args.get("pnr") or "").strip().upper()
    booking = mock_data.BOOKINGS.get(pnr)
    if booking is None:
        return _err(f"No booking found for PNR '{pnr}'.")
    return _ok(booking)


@tool(
    "get_flight_status",
    "Get the live operational status (on_time / delayed / cancelled) of a single flight segment.",
    {
        "flight_number": Annotated[str, "Flight number, e.g. AA123"],
        "date": Annotated[str, "Departure date, YYYY-MM-DD"],
    },
)
async def get_flight_status(args: dict[str, Any]) -> dict[str, Any]:
    flight_number = (args.get("flight_number") or "").strip().upper()
    date = (args.get("date") or "").strip()
    status = mock_data.FLIGHT_STATUS.get((flight_number, date))
    if status is None:
        return _err(f"No status on file for flight {flight_number} on {date}.")
    return _ok(status)


FIND_REBOOKING_OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "origin": {"type": "string", "description": "3-letter origin IATA code"},
        "destination": {"type": "string", "description": "3-letter destination IATA code"},
        "date": {"type": "string", "description": "Date to search, YYYY-MM-DD"},
        "cabin_class": {
            "type": "string",
            "description": "Optional cabin filter: Economy, Premium Economy, or Business",
        },
    },
    "required": ["origin", "destination", "date"],
}


@tool(
    "find_rebooking_options",
    "Find candidate rebooking flights between an origin and destination on a given date, with fares.",
    FIND_REBOOKING_OPTIONS_SCHEMA,
)
async def find_rebooking_options(args: dict[str, Any]) -> dict[str, Any]:
    origin = (args.get("origin") or "").strip().upper()
    destination = (args.get("destination") or "").strip().upper()
    date = (args.get("date") or "").strip()
    cabin_class = (args.get("cabin_class") or "").strip()

    candidates = mock_data.ALTERNATIVES.get((origin, destination, date), [])
    if cabin_class:
        candidates = [c for c in candidates if c["cabin_class"].lower() == cabin_class.lower()]
    return _ok({"origin": origin, "destination": destination, "date": date, "candidates": candidates})


@tool(
    "get_policy",
    "Get the IRROPS policy clause and citation for a topic: rebooking, hotel, compensation, or escalation.",
    {"topic": Annotated[str, "One of: rebooking, hotel, compensation, escalation"]},
)
async def get_policy(args: dict[str, Any]) -> dict[str, Any]:
    topic = (args.get("topic") or "").strip().lower()
    policy = mock_data.POLICIES.get(topic)
    if policy is None:
        valid = ", ".join(sorted(mock_data.POLICIES))
        return _err(f"Unknown policy topic '{topic}'. Valid topics: {valid}.")
    return _ok({"topic": topic, **policy})


@tool(
    "rebook_itinerary",
    "Rebook a passenger's PNR onto a new flight for a given fare difference in USD. "
    "Sensitive action: fare differences at or above the configured autonomy threshold "
    "are denied by policy before this tool runs, and routed to human escalation instead.",
    {
        "pnr": Annotated[str, "Passenger's PNR"],
        "new_flight_number": Annotated[str, "Flight number to rebook onto, e.g. AA125"],
        "fare_difference_usd": Annotated[float, "Fare difference to charge, in USD (0 if no additional cost)"],
    },
)
async def rebook_itinerary(args: dict[str, Any]) -> dict[str, Any]:
    pnr = (args.get("pnr") or "").strip().upper()
    booking = mock_data.BOOKINGS.get(pnr)
    if booking is None:
        return _err(f"Cannot rebook: no booking found for PNR '{pnr}'.")

    new_flight_number = (args.get("new_flight_number") or "").strip().upper()
    fare_difference_usd = float(args.get("fare_difference_usd") or 0)
    booking["segments"][0]["flight_number"] = new_flight_number
    return _ok(
        {
            "pnr": pnr,
            "rebooked_to": new_flight_number,
            "fare_difference_usd": fare_difference_usd,
            "status": "confirmed",
        }
    )


FDA_TOOLS_SERVER = create_sdk_mcp_server(
    name="fda_tools",
    version="1.0.0",
    tools=[
        lookup_booking,
        get_flight_status,
        find_rebooking_options,
        get_policy,
        rebook_itinerary,
    ],
)
