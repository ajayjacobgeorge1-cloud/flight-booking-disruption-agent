# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A customer-support agent for airline IRROPS (irregular operations) -- cancellations,
delays, rebooking, hotel/compensation policy -- built on the **Claude Agent SDK**
(python3.12). It shells out to the `claude` CLI binary for every request (via
`ClaudeAgentOptions(cli_path=...)`); there is no direct Anthropic API call and no
`ANTHROPIC_API_KEY` -- auth comes from the Claude Code CLI's own login
(`claude` + `/login`, or `claude setup-token`).

## Commands

```bash
# Setup
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # + pytest/pytest-asyncio for tests
cp .env.example .env

# Run
python3.12 main.py "PNR ABC123, my flight AA123 to London was cancelled. What are my options?"

# Test
pytest                                   # whole suite
pytest tests/test_hooks.py               # one file
pytest tests/test_tools.py::test_lookup_booking_found   # one test
```

Tests call tool handlers and the `PreToolUse` hook callback directly (synthetic
hook-input dicts, see `tests/test_hooks.py`) -- no CLI subprocess, no network,
no live Claude calls. `pytest.ini` sets `asyncio_mode = auto`, so async test
functions need no `@pytest.mark.asyncio` decorator.

There is no lint/format tooling configured in this repo.

## Architecture

```
                     coordinator (agent/coordinator.py)
                     one ClaudeAgentOptions / query() session
                                │  Task tool (native Agent delegation)
              ┌─────────────────┼─────────────────┐
              v                 v                 v
      status-analyst      options-finder     policy-checker
      (agent/subagents.py -- AgentDefinition, each restricted to its own tool(s))
              │                 │                   │
    lookup_booking      find_rebooking_options   get_policy
    get_flight_status
              │                 │                   │
              └─────────────────┴───────────────────┘
              in-process SDK MCP server "fda_tools" (agent/tools.py)
                         backed by agent/mock_data.py

   coordinator-only, hook-gated:  rebook_itinerary
                                       │
                               PreToolUse hook (agent/hooks.py)
                        fare_difference_usd >= REBOOKING_AUTONOMY_THRESHOLD_USD?
                          │ yes -> DENY (permissionDecision) + open escalation ticket
                          │ no  -> allow, tool runs
```

- **Coordinator** (`agent/coordinator.py`, `handle_request()`) is the single entry
  point. Its system prompt instructs it to: dispatch `status-analyst` first; once
  the affected segment's origin/destination/date are known, dispatch
  `options-finder` and `policy-checker` **in parallel** (two `Task` calls in the
  same turn); optionally call `rebook_itinerary` itself (the only domain tool the
  coordinator is allowed to call directly -- everything else goes through
  subagents); and finally synthesize one response grounded only in what the
  subagents/tools actually returned, never inventing flight/fare/policy details.
  `options.tools`/`allowed_tools` on the coordinator are restricted to
  `["Task", "mcp__fda_tools__rebook_itinerary"]` to enforce "never call lookup
  tools directly" in code, not just in the prompt.
- **Subagents** (`agent/subagents.py`) are declared with the SDK's native
  `AgentDefinition` and registered on `ClaudeAgentOptions.agents`; the coordinator
  invokes them via Claude Code's built-in `Task` tool -- no custom delegation
  plumbing. Each subagent's `tools` list restricts it to only the domain tool(s)
  it needs, and each has `model="inherit"`.
- **Domain tools** (`agent/tools.py`) are plain async functions wrapped with
  `@tool` and bundled into one in-process MCP server via `create_sdk_mcp_server()`
  (no separate server process). They read/write the in-memory mock data in
  `agent/mock_data.py`. Tool results use the `_ok`/`_err` helpers to shape
  `{"content": [...], "is_error": ...}` MCP responses.
- **The rebooking guard** (`agent/hooks.py`, `rebooking_guard`) is a real
  `PreToolUse` hook, not a prompt instruction. It runs before `rebook_itinerary`
  executes: if `fare_difference_usd` is at or above
  `REBOOKING_AUTONOMY_THRESHOLD_USD` (default $750, read from env at hook-build
  time), it returns `hookSpecificOutput.permissionDecision: "deny"` -- the tool
  never runs -- and opens an escalation ticket via `EscalationDesk`
  (`agent/escalations.py`). This enforcement is independent of what the model
  decides to do and of permission mode.
- **Dispatch trace**: the same `build_hooks()` call also registers `PreToolUse`
  (`log_tool_call`), `SubagentStart`, and `SubagentStop` hooks purely to log
  subagent dispatches, tool calls (with which subagent made them), and
  escalations to an in-memory `DispatchTrace` (`agent/trace.py`). `main.py`
  renders and prints this trace, then any escalation tickets, then the final
  customer-facing response, in that order.
- **`main.py`** is the only CLI entry point: it loads `.env` (if `python3.12-dotenv`
  is available), runs `handle_request()`, and prints the three sections above.

### Extending this project

- A new domain tool: add it to `agent/tools.py` with `@tool(...)`, add it to the
  `tools=[...]` list passed to `create_sdk_mcp_server()`, and give the relevant
  subagent(s) in `agent/subagents.py` access via their `tools=[...]` list
  (`mcp__fda_tools__<tool_name>`).
- A new subagent: add an `AgentDefinition` to `AGENTS` in `agent/subagents.py`
  and update the coordinator's system prompt in `agent/coordinator.py` to
  describe when to dispatch it.
- A new sensitive/gated action: follow the `rebook_itinerary` pattern -- add the
  tool, then add a check in `rebooking_guard` (or a new hook function) in
  `agent/hooks.py`, registered on the `PreToolUse` `HookMatcher` list, that denies
  via `permissionDecision` and opens an escalation ticket rather than relying on
  the system prompt alone.
