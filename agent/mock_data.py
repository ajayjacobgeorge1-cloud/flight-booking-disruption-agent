"""In-memory mock backend data. Stands in for a GDS / PSS / ops-feed integration."""
from __future__ import annotations

# Original flight number for each booking's one segment, used by reset_mock_state()
# to undo a rebook_itinerary mutation (e.g. between turns in the Streamlit app,
# which keeps this module's state alive for the whole server process).
_ORIGINAL_FLIGHT_NUMBERS: dict[str, str] = {"ABC123": "AA123", "XYZ789": "AA456"}

BOOKINGS: dict[str, dict] = {
    "ABC123": {
        "pnr": "ABC123",
        "passenger_name": "Dana Whitfield",
        "fare_class": "Economy Flex",
        "ticket_status": "confirmed",
        "segments": [
            {
                "flight_number": "AA123",
                "origin": "JFK",
                "destination": "LHR",
                "departure_date": "2026-12-05",
                "departure_time": "21:10",
            }
        ],
    },
    "XYZ789": {
        "pnr": "XYZ789",
        "passenger_name": "Marcus Oyelaran",
        "fare_class": "Economy Basic",
        "ticket_status": "confirmed",
        "segments": [
            {
                "flight_number": "AA456",
                "origin": "ORD",
                "destination": "SFO",
                "departure_date": "2026-12-06",
                "departure_time": "08:40",
            }
        ],
    },
}

FLIGHT_STATUS: dict[tuple[str, str], dict] = {
    ("AA123", "2026-12-05"): {
        "flight_number": "AA123",
        "date": "2026-12-05",
        "status": "cancelled",
        "reason": "mechanical",
        "gate": None,
        "estimated_departure": None,
    },
    ("AA456", "2026-12-06"): {
        "flight_number": "AA456",
        "date": "2026-12-06",
        "status": "delayed",
        "reason": "weather",
        "gate": "B14",
        "estimated_departure": "11:55",
    },
}

ALTERNATIVES: dict[tuple[str, str, str], list[dict]] = {
    ("JFK", "LHR", "2026-12-05"): [
        {
            "flight_number": "AA125",
            "departure_time": "23:55",
            "arrival_time_next_day": "11:40",
            "cabin_class": "Economy",
            "seats_available": 5,
            "fare_difference_usd": 0,
        },
        {
            "flight_number": "BA178",
            "departure_time": "22:30",
            "arrival_time_next_day": "10:15",
            "cabin_class": "Premium Economy",
            "seats_available": 2,
            "fare_difference_usd": 340,
        },
        {
            "flight_number": "AA129",
            "departure_time": "07:15",
            "arrival_time_next_day": None,
            "cabin_class": "Business",
            "seats_available": 1,
            "fare_difference_usd": 1250,
        },
    ],
    ("ORD", "SFO", "2026-12-06"): [
        {
            "flight_number": "AA460",
            "departure_time": "13:05",
            "arrival_time_next_day": None,
            "cabin_class": "Economy",
            "seats_available": 6,
            "fare_difference_usd": 0,
        },
    ],
}

POLICIES: dict[str, dict] = {
    "rebooking": {
        "clause": (
            "When a flight is cancelled or delayed more than 90 minutes for a "
            "carrier-controlled reason, the airline rebooks the passenger on the "
            "next available flight in the same cabin at no cost. A passenger may "
            "request a higher cabin, in which case the fare difference applies "
            "and requires agent approval above $750."
        ),
        "source": "IRROPS Policy v1 - Rebooking",
    },
    "hotel": {
        "clause": (
            "Passengers on an overnight misconnect caused by a carrier-controlled "
            "disruption are entitled to a hotel voucher (up to $150/night) and two "
            "meal vouchers ($25 each) per affected night. Weather-caused "
            "disruptions are not eligible for hotel compensation, though the "
            "airline offers a discounted hotel rate as a courtesy."
        ),
        "source": "IRROPS Policy v1 - Hotel & Meals",
    },
    "compensation": {
        "clause": (
            "Cash compensation is owed under EU261/UK261 for flights departing "
            "the EU/UK, or under the carrier's Customer Service Plan for "
            "controllable delays over 3 hours on US domestic flights. Weather and "
            "ATC-driven delays are excluded from cash compensation in all cases."
        ),
        "source": "IRROPS Policy v1 - Compensation",
    },
    "escalation": {
        "clause": (
            "Any rebooking with a fare difference at or above $750, any request "
            "for a cabin upgrade beyond business class, or any compensation claim "
            "disputing the carrier's weather/ATC classification must be escalated "
            "to a human agent rather than resolved autonomously."
        ),
        "source": "IRROPS Policy v1 - Escalation",
    },
}


def reset_mock_state() -> None:
    """Undoes any rebook_itinerary mutation. A fresh `python main.py` call
    never needs this (each run is its own process), but the Streamlit app
    keeps this module alive across chat turns, so it offers a reset button."""
    for pnr, flight_number in _ORIGINAL_FLIGHT_NUMBERS.items():
        BOOKINGS[pnr]["segments"][0]["flight_number"] = flight_number
