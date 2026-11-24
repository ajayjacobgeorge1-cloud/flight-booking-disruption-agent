"""PreToolUse / SubagentStart / SubagentStop hooks.

The rebooking guard is the real enforcement point for the business rule: a
`rebook_itinerary` call with a fare difference at/above the configured
threshold is denied here, in code, before the tool ever runs -- the model
cannot reason its way around it. The other hooks only observe tool calls and
subagent lifecycle events to build the CLI's dispatch trace; they never deny
anything.
"""
from __future__ import annotations

import os
from typing import Any

from claude_agent_sdk import HookMatcher

from .escalations import EscalationDesk
from .trace import DispatchTrace

DEFAULT_THRESHOLD_USD = 750.0


def _threshold_usd() -> float:
    raw = os.environ.get("REBOOKING_AUTONOMY_THRESHOLD_USD", "")
    try:
        return float(raw) if raw else DEFAULT_THRESHOLD_USD
    except ValueError:
        return DEFAULT_THRESHOLD_USD


def build_hooks(trace: DispatchTrace, escalation_desk: EscalationDesk) -> dict[str, list[HookMatcher]]:
    threshold = _threshold_usd()

    async def rebooking_guard(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        if not tool_name.endswith("rebook_itinerary"):
            return {}

        tool_input = input_data.get("tool_input") or {}
        try:
            fare_difference = float(tool_input.get("fare_difference_usd", 0) or 0)
        except (TypeError, ValueError):
            fare_difference = 0.0

        if fare_difference < threshold:
            return {}

        pnr = (tool_input.get("pnr") or "UNKNOWN").strip().upper()
        reason = (
            f"Fare difference ${fare_difference:,.2f} is at/above the "
            f"${threshold:,.2f} autonomy threshold."
        )
        ticket = escalation_desk.open_ticket(
            pnr=pnr,
            reason=reason,
            new_flight_number=tool_input.get("new_flight_number"),
            fare_difference_usd=fare_difference,
        )
        trace.record("escalation", ticket_id=ticket.ticket_id, pnr=pnr, reason=reason)

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Denied by policy hook: {reason} Escalation ticket {ticket.ticket_id} "
                    "was opened for a human agent instead of booking this automatically."
                ),
            }
        }

    async def log_tool_call(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input") or {}
        agent_type = input_data.get("agent_type")

        if tool_name == "Task":
            trace.record(
                "dispatch",
                agent=tool_input.get("subagent_type", "?"),
                description=tool_input.get("description", ""),
            )
        elif "fda_tools" in tool_name or tool_name in {
            "lookup_booking",
            "get_flight_status",
            "find_rebooking_options",
            "get_policy",
            "rebook_itinerary",
        }:
            short_name = tool_name.rsplit("__", 1)[-1]
            trace.record("tool_call", tool=short_name, args=tool_input, agent_type=agent_type)
        return {}

    async def subagent_start(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        trace.record(
            "subagent_start",
            agent_id=input_data.get("agent_id", ""),
            agent_type=input_data.get("agent_type", ""),
        )
        return {}

    async def subagent_stop(input_data: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        trace.record(
            "subagent_stop",
            agent_id=input_data.get("agent_id", ""),
            agent_type=input_data.get("agent_type", ""),
        )
        return {}

    return {
        "PreToolUse": [HookMatcher(matcher=None, hooks=[rebooking_guard, log_tool_call])],
        "SubagentStart": [HookMatcher(hooks=[subagent_start])],
        "SubagentStop": [HookMatcher(hooks=[subagent_stop])],
    }
