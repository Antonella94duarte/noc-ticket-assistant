from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.schemas import TicketAnalyzeRequest
from app.services import tickets as ticket_service
from app.services.analyzer import TicketAnalyzer
from tests.conftest import FakeLLM


def test_content_hash_ignores_line_endings_and_edge_whitespace():
    base = ticket_service.content_hash("Enlace caído\nen SITE-SUR-02", "log line")

    assert ticket_service.content_hash("  Enlace caído  \r\nen SITE-SUR-02\n", "log line\n") == base


def test_content_hash_depends_on_text_and_logs():
    base = ticket_service.content_hash("Enlace caído", None)

    assert ticket_service.content_hash("Enlace caido", None) != base
    assert ticket_service.content_hash("Enlace caído", "algo") != base
    # Moving text between the ticket and the logs is a different input.
    assert ticket_service.content_hash("ab", "c") != ticket_service.content_hash("a", "bc")


def test_missing_and_empty_logs_hash_the_same():
    assert ticket_service.content_hash("Enlace caído", None) == ticket_service.content_hash(
        "Enlace caído", "  "
    )


class RaceSession:
    """Session whose commit fails as if another request stored the same ticket first."""

    def __init__(self):
        self.rolled_back = False

    def add(self, obj):
        pass

    def commit(self):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    def rollback(self):
        self.rolled_back = True


def test_concurrent_identical_request_returns_the_stored_ticket(monkeypatch):
    winner = SimpleNamespace(id="stored-by-the-other-request")
    lookups = iter([None, winner])  # miss before calling the model, hit after the conflict
    monkeypatch.setattr(ticket_service.repository, "find_by_content", lambda *a: next(lookups))
    session = RaceSession()
    request = TicketAnalyzeRequest(ticket_text="El enlace hacia SITE-SUR-02 está caído.")

    ticket, cached = ticket_service.analyze_ticket(session, TicketAnalyzer(FakeLLM()), request)

    assert ticket is winner
    assert cached is True
    assert session.rolled_back
