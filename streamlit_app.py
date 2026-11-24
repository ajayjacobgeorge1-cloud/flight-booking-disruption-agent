"""Conversational web UI for the flight-disruption coordinator agent.

Thin presentation layer on top of `agent.coordinator.handle_request` -- it
does not duplicate any agent/tool/hook logic. Dispatch-trace lines and the
coordinator's own streamed text both land in a `st.status` box live, the
same two callbacks `main.py` uses for the terminal version; only the final,
grounded answer is shown in the chat bubble itself.

Run with:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent.coordinator import handle_request
from agent.mock_data import reset_mock_state

st.set_page_config(page_title="Flight Disruption Support", page_icon="✈️")

st.title("✈️ Flight Disruption Support")
st.caption(
    "Describe a PNR and what happened (cancellation, delay, ...) -- the coordinator "
    "dispatches subagents for status, rebooking options, and policy, then synthesizes "
    "one grounded response."
)

with st.sidebar:
    st.subheader("Session")
    st.write(f"**Model:** `{os.environ.get('CLAUDE_MODEL') or '(CLI default)'}`")
    st.write(
        f"**Rebooking autonomy threshold:** "
        f"${float(os.environ.get('REBOOKING_AUTONOMY_THRESHOLD_USD', 750)):,.0f}"
    )
    st.caption(
        "PNRs to try: **ABC123** (AA123 JFK→LHR, cancelled) and "
        "**XYZ789** (AA456 ORD→SFO, delayed)."
    )

    if st.button("Reset conversation + mock data", use_container_width=True):
        reset_mock_state()
        st.session_state.messages = []
        st.session_state.escalation_tickets = []
        st.session_state.session_id = None
        st.rerun()

    if st.session_state.get("escalation_tickets"):
        st.subheader("Escalation tickets")
        for ticket in st.session_state.escalation_tickets:
            st.json(
                {
                    "ticket_id": ticket.ticket_id,
                    "pnr": ticket.pnr,
                    "reason": ticket.reason,
                    "details": ticket.details,
                    "created_at": ticket.created_at,
                },
                expanded=False,
            )

if "messages" not in st.session_state:
    st.session_state.messages = []
if "escalation_tickets" not in st.session_state:
    st.session_state.escalation_tickets = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_message = st.chat_input(
    "e.g. PNR ABC123, AA123 was cancelled. What are my rebooking options, and am I covered for a hotel?"
)

if user_message:
    st.session_state.messages.append({"role": "user", "content": user_message})
    with st.chat_message("user"):
        st.markdown(user_message)

    with st.chat_message("assistant"):
        status = st.status("Working on your request...", expanded=True)

        current_turn: dict = {"placeholder": None, "text": ""}

        def on_trace_line(line: str) -> None:
            status.write(line)

        def on_text_delta(delta: str) -> None:
            if delta == "\n[coordinator] ":
                current_turn["placeholder"] = status.empty()
                current_turn["text"] = ""
                return
            if delta == "\n":
                if current_turn["placeholder"] is not None:
                    current_turn["placeholder"].markdown(current_turn["text"])
                current_turn["placeholder"] = None
                return
            current_turn["text"] += delta
            if current_turn["placeholder"] is not None:
                current_turn["placeholder"].markdown(current_turn["text"] + "▌")

        try:
            result = asyncio.run(
                handle_request(
                    user_message,
                    resume=st.session_state.session_id,
                    on_trace_line=on_trace_line,
                    on_text_delta=on_text_delta,
                )
            )
        except Exception:  # noqa: BLE001 -- surface to the user, never a raw traceback
            status.update(label="Something went wrong", state="error", expanded=True)
            display_text = (
                "Something went wrong while processing your request (a CLI/API "
                "error). See the box above for detail, and check that the "
                "`claude` CLI is installed and logged in."
            )
            st.markdown(display_text)
            with st.expander("Technical detail"):
                st.exception(sys.exc_info()[1])
            st.session_state.messages.append({"role": "assistant", "content": display_text})
            st.stop()

        status.update(label="Done", state="complete", expanded=False)
        st.session_state.session_id = result.session_id

        if result.escalation_desk.tickets:
            st.session_state.escalation_tickets.extend(result.escalation_desk.tickets)
            with st.expander(
                f"⚠️ {len(result.escalation_desk.tickets)} escalation ticket(s) opened", expanded=True
            ):
                for ticket in result.escalation_desk.tickets:
                    st.markdown(f"**{ticket.ticket_id}** | PNR {ticket.pnr} | opened {ticket.created_at}")
                    st.markdown(f"- reason: {ticket.reason}")
                    st.markdown(f"- details: {ticket.details}")

        st.markdown(result.final_response)

    st.session_state.messages.append({"role": "assistant", "content": result.final_response})
