"""Human-escalation desk: tickets opened when the rebooking hook denies an action."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone

_ticket_counter = itertools.count(1)


@dataclass
class EscalationTicket:
    ticket_id: str
    pnr: str
    reason: str
    details: dict
    created_at: str


@dataclass
class EscalationDesk:
    """Collects escalation tickets opened during a single coordinator run."""

    tickets: list[EscalationTicket] = field(default_factory=list)

    def open_ticket(self, *, pnr: str, reason: str, **details) -> EscalationTicket:
        ticket = EscalationTicket(
            ticket_id=f"ESC-{next(_ticket_counter):04d}",
            pnr=pnr,
            reason=reason,
            details=details,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self.tickets.append(ticket)
        return ticket
