from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


class FakeSession:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def execute(self, *args, **kwargs):
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_health_ok(client):
    app.dependency_overrides[get_db] = lambda: FakeSession()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


def test_health_reports_database_down(client):
    app.dependency_overrides[get_db] = lambda: FakeSession(fail=True)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "unavailable",
        "version": "0.1.0",
    }
