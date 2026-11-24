"""Chronological dispatch trace, built from hook callbacks.

Each event is recorded the instant the corresponding hook fires -- while the
coordinator's query is still running -- so a caller can pass `on_event` to
print progress live instead of waiting for the whole run to finish.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


def _format(event: dict) -> str:
    ts = event["ts"]
    kind = event["kind"]
    if kind == "dispatch":
        return f"[{ts}] -> dispatch {event['agent']}: {event['description']}"
    if kind == "subagent_start":
        return f"[{ts}]    {event['agent_type']} ({event['agent_id'][:8]}) started"
    if kind == "tool_call":
        scope = event.get("agent_type") or "coordinator"
        return f"[{ts}]    [{scope}] called {event['tool']}({event['args']})"
    if kind == "subagent_stop":
        return f"[{ts}] <- {event['agent_type']} ({event['agent_id'][:8]}) finished"
    if kind == "escalation":
        return f"[{ts}] !! escalation ticket {event['ticket_id']} (PNR {event['pnr']}): {event['reason']}"
    return f"[{ts}] {kind}: {event}"


@dataclass
class DispatchTrace:
    events: list[dict] = field(default_factory=list)
    on_event: Callable[[str], None] | None = None
    """Called with the formatted line the instant an event is recorded, so a
    caller can stream progress live instead of waiting for render()."""

    def record(self, kind: str, **fields) -> None:
        event = {
            "kind": kind,
            "ts": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
            **fields,
        }
        self.events.append(event)
        if self.on_event is not None:
            self.on_event(_format(event))

    def render(self) -> str:
        return "\n".join(_format(event) for event in self.events)
