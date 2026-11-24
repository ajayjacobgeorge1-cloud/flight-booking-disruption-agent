#!/usr/bin/env python3
"""CLI entry point for the flight-disruption customer-support agent.

Usage:
    python main.py "PNR ABC123, my flight AA123 to London was cancelled. What are my options?"
"""
from __future__ import annotations

import asyncio
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent.coordinator import handle_request


def _print_section(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} \"<customer message>\"", file=sys.stderr)
        return 1

    message = " ".join(sys.argv[1:])

    _print_section("LIVE ACTIVITY")

    streaming_text = {"active": False}

    def on_trace_line(line: str) -> None:
        if streaming_text["active"]:
            print()  # break out of the in-progress coordinator line first
            streaming_text["active"] = False
        print(line, flush=True)

    def on_text_delta(delta: str) -> None:
        if delta == "\n[coordinator] ":
            streaming_text["active"] = True
        elif delta == "\n":
            streaming_text["active"] = False
        print(delta, end="", flush=True)

    result = asyncio.run(handle_request(message, on_trace_line=on_trace_line, on_text_delta=on_text_delta))
    print()

    if result.escalation_desk.tickets:
        _print_section("ESCALATION TICKETS")
        for ticket in result.escalation_desk.tickets:
            print(f"{ticket.ticket_id} | PNR {ticket.pnr} | opened {ticket.created_at}")
            print(f"  reason:  {ticket.reason}")
            print(f"  details: {ticket.details}")

    _print_section("CUSTOMER-FACING RESPONSE")
    print(result.final_response)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
