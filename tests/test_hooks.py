"""Tests for the PreToolUse rebooking guard: the real enforcement point for the
fare-difference autonomy threshold. These call the hook callback directly with
synthetic PreToolUse input, the same shape the CLI sends."""
from __future__ import annotations

import os

import pytest

from agent.escalations import EscalationDesk
from agent.hooks import build_hooks
from agent.trace import DispatchTrace


def _pre_tool_use_input(tool_name: str, tool_input: dict) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_use_id": "test-tool-use-id",
    }


@pytest.fixture
def hooks(monkeypatch):
    monkeypatch.setenv("REBOOKING_AUTONOMY_THRESHOLD_USD", "750")
    trace = DispatchTrace()
    desk = EscalationDesk()
    built = build_hooks(trace, desk)
    return built, trace, desk


async def test_allows_fare_difference_below_threshold(hooks):
    built, trace, desk = hooks
    rebooking_guard = built["PreToolUse"][0].hooks[0]

    result = await rebooking_guard(
        _pre_tool_use_input("mcp__fda_tools__rebook_itinerary", {"pnr": "ABC123", "new_flight_number": "AA125", "fare_difference_usd": 0}),
        None,
        None,
    )

    assert result == {}
    assert desk.tickets == []


async def test_denies_and_escalates_fare_difference_at_threshold(hooks):
    built, trace, desk = hooks
    rebooking_guard = built["PreToolUse"][0].hooks[0]

    result = await rebooking_guard(
        _pre_tool_use_input(
            "mcp__fda_tools__rebook_itinerary",
            {"pnr": "ABC123", "new_flight_number": "AA129", "fare_difference_usd": 1250},
        ),
        None,
        None,
    )

    decision = result["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "1,250" in decision["permissionDecisionReason"] or "1250" in decision["permissionDecisionReason"]

    assert len(desk.tickets) == 1
    ticket = desk.tickets[0]
    assert ticket.pnr == "ABC123"
    assert ticket.details["fare_difference_usd"] == 1250

    assert any(event["kind"] == "escalation" for event in trace.events)


async def test_ignores_unrelated_tool_calls(hooks):
    built, trace, desk = hooks
    rebooking_guard = built["PreToolUse"][0].hooks[0]

    result = await rebooking_guard(
        _pre_tool_use_input("mcp__fda_tools__lookup_booking", {"pnr": "ABC123"}),
        None,
        None,
    )

    assert result == {}
    assert desk.tickets == []


async def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("REBOOKING_AUTONOMY_THRESHOLD_USD", "100")
    trace = DispatchTrace()
    desk = EscalationDesk()
    built = build_hooks(trace, desk)
    rebooking_guard = built["PreToolUse"][0].hooks[0]

    result = await rebooking_guard(
        _pre_tool_use_input(
            "mcp__fda_tools__rebook_itinerary",
            {"pnr": "XYZ789", "new_flight_number": "BA178", "fare_difference_usd": 340},
        ),
        None,
        None,
    )

    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert len(desk.tickets) == 1
