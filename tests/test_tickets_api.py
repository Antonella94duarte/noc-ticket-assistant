import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import Ticket
from tests.conftest import SAMPLE_CLASSIFICATION

BASE_TIME = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def add_ticket(db, *, category: str, severity: str, minutes: int, text: str = "") -> Ticket:
    ticket = Ticket(
        created_at=BASE_TIME + timedelta(minutes=minutes),
        ticket_text=text or f"Ticket {category} {severity} {minutes}",
        logs=None,
        content_hash=uuid.uuid4().hex,
        category=category,
        severity=severity,
        analysis={
            "classification": {**SAMPLE_CLASSIFICATION, "category": category, "severity": severity}
        },
        prompt_version="classify_v1",
        model="fake-model",
        reasoning_effort="medium",
        input_tokens=100,
        output_tokens=20,
        reasoning_tokens=5,
    )
    db.add(ticket)
    db.flush()
    return ticket


@pytest.fixture
def tickets(db_session):
    return [
        add_ticket(db_session, category="connectivity_loss", severity="critical", minutes=0),
        add_ticket(db_session, category="power_alarm", severity="major", minutes=1),
        add_ticket(db_session, category="connectivity_loss", severity="minor", minutes=2),
        add_ticket(db_session, category="hardware_failure", severity="major", minutes=3),
    ]


def test_get_ticket_returns_stored_analysis(db_client, tickets):
    ticket = tickets[1]

    response = db_client.get(f"/api/v1/tickets/{ticket.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ticket.id)
    assert body["classification"]["category"] == "power_alarm"
    assert body["usage"]["total_tokens"] == 120


def test_get_unknown_ticket_returns_404(db_client):
    assert db_client.get(f"/api/v1/tickets/{uuid.uuid4()}").status_code == 404


def test_get_ticket_with_malformed_id_returns_422(db_client):
    assert db_client.get("/api/v1/tickets/not-a-uuid").status_code == 422


def test_list_returns_newest_first_with_total(db_client, tickets):
    body = db_client.get("/api/v1/tickets").json()

    assert body["total"] == 4
    assert [item["id"] for item in body["items"]] == [str(t.id) for t in reversed(tickets)]
    assert set(body["items"][0]) == {"id", "created_at", "category", "severity", "ticket_excerpt"}


@pytest.mark.parametrize(
    "query, expected_minutes",
    [
        ("category=connectivity_loss", [2, 0]),
        ("severity=major", [3, 1]),
        ("category=connectivity_loss&severity=minor", [2]),
        ("category=configuration_error", []),
    ],
)
def test_list_filters(db_client, tickets, query, expected_minutes):
    body = db_client.get(f"/api/v1/tickets?{query}").json()

    expected_ids = [str(tickets[m].id) for m in expected_minutes]
    assert [item["id"] for item in body["items"]] == expected_ids
    assert body["total"] == len(expected_ids)


def test_list_paginates(db_client, tickets):
    page = db_client.get("/api/v1/tickets?limit=2&offset=1").json()

    assert [item["id"] for item in page["items"]] == [str(tickets[2].id), str(tickets[1].id)]
    assert page["total"] == 4
    assert (page["limit"], page["offset"]) == (2, 1)


def test_list_past_the_last_page_still_reports_total(db_client, tickets):
    page = db_client.get("/api/v1/tickets?offset=10").json()

    assert page["items"] == []
    assert page["total"] == 4


def test_list_cuts_long_ticket_text(db_client, db_session):
    add_ticket(db_session, category="other", severity="warning", minutes=0, text="x" * 500)

    item = db_client.get("/api/v1/tickets").json()["items"][0]

    assert item["ticket_excerpt"] == "x" * 120


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "category=bogus", "severity=urgent"]
)
def test_list_rejects_invalid_parameters(db_client, query):
    assert db_client.get(f"/api/v1/tickets?{query}").status_code == 422
