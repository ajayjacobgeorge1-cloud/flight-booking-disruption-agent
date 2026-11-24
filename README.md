# Flight Disruption Support Agent (Claude Agent SDK)

A customer-support agent for airline IRROPS (irregular operations) -- cancellations,
delays, rebooking, hotel/compensation policy -- built on the **Claude Agent SDK**
(Python) and the native **Claude Code CLI**. It is a from-scratch rebuild of an
earlier prototype that drove a third-party LLM over a hand-rolled MCP server; this
version leans entirely on SDK-native idioms (subagents, hooks, in-process tools)
and real Claude models, authenticated via the Claude Code CLI's own login --
**no separate `ANTHROPIC_API_KEY` required**.

## Architecture

```
                     ┌─────────────────────┐
   customer message  │     coordinator      │   one customer-facing
   ────────────────> │  (main SDK session)  │ ─────────────────────>
                     └──────────┬───────────┘        response
                                │  Task tool (native Agent delegation)
              ┌─────────────────┼─────────────────┐
              v                 v                 v
      ┌───────────────┐ ┌───────────────┐ ┌────────────────┐
      │ status-analyst │ │ options-finder│ │ policy-checker  │
      └───────┬────────┘ └───────┬───────┘ └────────┬────────┘
              │                 │                   │
    lookup_booking      find_rebooking_options   get_policy
    get_flight_status
              │                 │                   │
              └─────────────────┴───────────────────┘
                     in-process SDK MCP server ("fda_tools")
                            (agent/tools.py, mock data)

   coordinator-only, hook-gated:  rebook_itinerary
                                       │
                               PreToolUse hook (agent/hooks.py)
                        fare_difference_usd >= threshold?
                          │ yes -> DENY + open escalation ticket
                          │ no  -> allow, tool runs
```

- **Coordinator** (`agent/coordinator.py`) is a single `ClaudeAgentOptions` /
  `query()` session. Its system prompt tells it to decompose the customer's
  message, dispatch `status-analyst` first, then dispatch `options-finder` and
  `policy-checker` **in parallel** (two `Task` tool calls in the same turn) once
  the affected segment's origin/destination/date are known, and finally write one
  response grounded only in what the subagents actually reported.
- **Subagents** (`agent/subagents.py`) are declared with the SDK's native
  `AgentDefinition` and registered on `ClaudeAgentOptions.agents` -- the
  coordinator invokes them through Claude Code's built-in `Task` tool, no custom
  delegation plumbing needed. Each subagent's `tools` list restricts it to only
  the domain tool(s) it needs.
- **5 domain tools** (`agent/tools.py`) are plain Python async functions wrapped
  with `@tool` and bundled into one in-process MCP server via
  `create_sdk_mcp_server()` -- no separate server process, unlike the original
  project's MCP server. They read/write the in-memory mock data in
  `agent/mock_data.py`.
- **The rebooking guard** (`agent/hooks.py`) is a real `PreToolUse` hook, not a
  prompt instruction. It runs before `rebook_itinerary` executes: if
  `fare_difference_usd` is at or above `REBOOKING_AUTONOMY_THRESHOLD_USD`
  (default **$750**), the hook returns `permissionDecision: "deny"` -- the tool
  never runs -- and opens an escalation ticket. The model cannot reason its way
  around this; it is enforced in code, independent of what the model decides to
  do, and regardless of permission mode.
- **Dispatch trace**: the same hook module also registers `PreToolUse`,
  `SubagentStart`, and `SubagentStop` hooks purely to log subagent dispatches,
  tool calls, and escalations to an in-memory trace (`agent/trace.py`), which
  `main.py` prints after the run.

## Setup

1. **Install and log in to the Claude Code CLI.** This project shells out to the
   `claude` binary for every request; it does not call the Anthropic API
   directly and needs no API key.
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude
   ```
   Inside the interactive session, run `/login` once (or `claude setup-token`
   for a long-lived token) and confirm `claude` is on your `PATH`. If it isn't,
   or you want to point at a specific binary (e.g. one bundled with a desktop
   app), set `CLAUDE_CODE_CLI_PATH` in `.env` instead of relying on `PATH`.

2. **Create a virtualenv and install dependencies** (Python 3.10+):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Copy the env file** and adjust if needed:
   ```bash
   cp .env.example .env
   ```

## Running it

```bash
python main.py "PNR ABC123, my flight AA123 to London was cancelled. What are my options, and does your hotel policy cover me?"
```

The CLI streams progress live, so you can see what's happening instead of
staring at a blank terminal for the ~30-90s a full run can take:

1. **Live activity** -- a `-> dispatch ...` / `[subagent] called tool(...)` /
   `<- ... finished` line prints the instant each hook fires, interleaved with
   the coordinator's own commentary typing out token-by-token as it streams
   from the API (prefixed `[coordinator]`).
2. **Escalation tickets** -- full detail, if the rebooking guard denied anything.
3. **Customer-facing response** -- the coordinator's final answer, printed again
   in full and cleanly once the run completes, grounded in the subagents' real
   findings.

To see the hook actually deny a booking and escalate it, ask for a specific,
expensive rebooking in the same message, e.g.:

```bash
python main.py "PNR ABC123, AA123 was cancelled. Please rebook me on the AA129 business class option."
```

`AA129` carries a `$1,250` fare difference in the mock data, above the default
`$750` threshold, so the hook denies the `rebook_itinerary` call and opens an
escalation ticket instead of letting the booking happen.

### Mock data

`agent/mock_data.py` has two sample bookings to try:

| PNR      | Flight | Route    | Date       | Status    |
|----------|--------|----------|------------|-----------|
| `ABC123` | AA123  | JFK→LHR  | 2026-12-05 | cancelled |
| `XYZ789` | AA456  | ORD→SFO  | 2026-12-06 | delayed   |

Rebooking candidates for `JFK`→`LHR` on `2026-12-05` include `AA125` ($0 extra,
Economy), `BA178` ($340 extra, Premium Economy), and `AA129` ($1,250 extra,
Business) -- enough range to exercise both the auto-approved and escalated
paths.

## Web UI (Streamlit)

```bash
streamlit run streamlit_app.py
```

A conversational chat UI on top of the same `agent.coordinator.handle_request` --
no duplicated agent/tool/hook logic. Each reply shows a collapsible "Working on
your request..." box that fills in live (dispatch lines + the coordinator's own
commentary typing out token-by-token) and collapses to "Done" once finished,
followed by the clean final answer in the chat bubble.

Unlike `main.py` (a fresh process per call), the Streamlit server process stays
up across turns, so the app threads the CLI's own session-resume (`resume=` /
`ClaudeAgentOptions.resume`) through each call -- the coordinator remembers
earlier turns (e.g. a PNR given two messages ago) instead of starting fresh
every message. The sidebar shows the configured threshold, lists accumulated
escalation tickets, and has a "Reset conversation + mock data" button (clears
chat history, the resumed session, and any `rebook_itinerary` mutations to the
mock bookings).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Tests call the tool handlers and the `PreToolUse` rebooking-guard hook directly
(no CLI subprocess, no network) -- they cover the mock-data tool behavior and,
most importantly, that the fare-difference threshold is actually enforced and
that a denial opens an escalation ticket.

## Why this is simpler than the original prototype

The original project ran a smaller open model over a custom HTTP client and had
to paper over unreliable multi-step tool-calling (narrated-but-never-made tool
calls, fabricated data) with self-correction retries and narration detection.
Running real Claude models through the Agent SDK's own orchestration removes
that failure mode, so this version only needs ordinary error handling for
transient API failures -- no retry/narration-detection machinery, and no
hand-rolled subagent or hook framework, since the SDK provides both natively.
