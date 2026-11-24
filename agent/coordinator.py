"""The coordinator: decomposes a customer message, delegates to subagents via the
native Agent/Task tool, and synthesizes one grounded customer-facing response.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import Callable

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, StreamEvent, TextBlock, query

from .escalations import EscalationDesk
from .hooks import build_hooks
from .subagents import AGENTS
from .tools import FDA_TOOLS_SERVER
from .trace import DispatchTrace

COORDINATOR_SYSTEM_PROMPT = """\
You are the coordinator for an airline's IRROPS (irregular operations) customer-support desk.
A customer has written in about a disruption to their trip. Decompose their request and
delegate to specialized subagents via the Task tool -- do not call the domain lookup tools
yourself, and never state a flight, fare, status, or policy detail that a subagent did not
actually report back to you.

1. Always dispatch `status-analyst` first, with the PNR the customer gave you. Wait for its
   findings: passenger info and, for every segment, the origin, destination, date, and live
   status.
2. Once you know the affected segment's origin/destination/date, dispatch -- in the SAME turn,
   so they run in parallel -- whichever of these are relevant to the customer's situation or
   request:
   - `options-finder`, with that origin/destination/date, if their flight is delayed/cancelled
     or they might need rebooking.
   - `policy-checker`, once per relevant topic (rebooking, hotel, compensation, escalation),
     for whatever the customer asked about or clearly needs to know given their situation.
   Skip a subagent only when its information is clearly not needed to answer the customer.
3. If, and only if, the customer's message explicitly asks you to confirm or execute a
   rebooking onto a specific flight that options-finder reported, call the `rebook_itinerary`
   tool yourself with that flight's number and fare difference. This tool is gated by a policy
   hook: fare differences at or above the configured autonomy threshold are automatically
   denied and routed to a human agent. If that happens, tell the customer their request was
   escalated to a human agent -- do not retry the call, and do not claim the booking changed.
4. Finally, write ONE customer-facing response that addresses everything the customer asked
   about, grounded only in what the subagents (and rebook_itinerary, if you called it) actually
   reported -- including exact policy clauses/citations and real flight/fare numbers. If a
   subagent could not find something, say so plainly instead of guessing.
"""


def _resolve_cli_path() -> str | None:
    explicit = os.environ.get("CLAUDE_CODE_CLI_PATH")
    if explicit:
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    # Falls back to the host app's own bundled CLI when one is exposed via the
    # environment (e.g. this process was itself launched by a Claude Code session).
    return os.environ.get("CLAUDE_CODE_EXECPATH") or None


@dataclass
class CoordinatorResult:
    final_response: str
    trace: DispatchTrace
    escalation_desk: EscalationDesk
    session_id: str | None


async def handle_request(
    user_message: str,
    *,
    resume: str | None = None,
    on_trace_line: Callable[[str], None] | None = None,
    on_text_delta: Callable[[str], None] | None = None,
) -> CoordinatorResult:
    """Run one coordinator turn.

    `resume` continues a prior turn's CLI session (its `session_id`, returned
    on the previous `CoordinatorResult`) so the coordinator remembers earlier
    turns -- e.g. a PNR given two messages ago -- instead of starting fresh
    every call. Each call still spawns its own `claude` subprocess regardless
    (hooks/tools/agents are Python-side and can't persist across processes),
    `resume` only tells that subprocess which prior conversation to load.

    `on_trace_line` is called the instant a dispatch/tool-call/escalation hook
    fires, so a caller can print progress live instead of waiting for the run
    to finish. `on_text_delta` is called with each raw text token of the
    coordinator's own (top-level) turns as they stream in from the API, for a
    live "typing" effect; the authoritative final answer is still returned in
    full on `CoordinatorResult.final_response` regardless of whether this is set.
    """
    trace = DispatchTrace(on_event=on_trace_line)
    escalation_desk = EscalationDesk()

    options = ClaudeAgentOptions(
        cli_path=_resolve_cli_path(),
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        mcp_servers={"fda_tools": FDA_TOOLS_SERVER},
        agents=AGENTS,
        tools=["Task", "mcp__fda_tools__rebook_itinerary"],
        allowed_tools=["Task", "mcp__fda_tools__rebook_itinerary"],
        permission_mode="bypassPermissions",
        hooks=build_hooks(trace, escalation_desk),
        model=os.environ.get("CLAUDE_MODEL") or None,
        max_turns=30,
        forward_subagent_text=True,
        include_partial_messages=on_text_delta is not None,
        resume=resume,
    )

    # Each top-level assistant turn can mix tool calls with commentary text;
    # the turn with no further tool calls (the last one) holds the actual
    # synthesized answer, so each new top-level text turn overwrites the last.
    last_text = ""
    error_text = ""
    session_id = resume
    in_text_block = False
    async for message in query(prompt=user_message, options=options):
        if on_text_delta is not None and isinstance(message, StreamEvent) and message.parent_tool_use_id is None:
            event = message.event
            event_type = event.get("type")
            if event_type == "content_block_start" and (event.get("content_block") or {}).get("type") == "text":
                in_text_block = True
                on_text_delta("\n[coordinator] ")
            elif event_type == "content_block_delta" and in_text_block:
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta":
                    on_text_delta(delta.get("text", ""))
            elif event_type == "content_block_stop" and in_text_block:
                in_text_block = False
                on_text_delta("\n")
        elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            text = "\n\n".join(
                block.text.strip() for block in message.content if isinstance(block, TextBlock) and block.text.strip()
            )
            if text:
                last_text = text
        elif isinstance(message, ResultMessage):
            session_id = message.session_id or session_id
            if message.is_error:
                error_text = f"[agent error] {message.result}"

    final_response = last_text.strip() or error_text or "(the coordinator returned no text response)"

    return CoordinatorResult(
        final_response=final_response, trace=trace, escalation_desk=escalation_desk, session_id=session_id
    )
