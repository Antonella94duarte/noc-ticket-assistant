import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.llm.client import LLMError, LLMResult
from app.main import app
from app.schemas import TicketClassification, TicketDiagnosis

# A separate database, so tests never touch the development data.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://noc:noc@localhost:5433/noc_tickets_test"
)

SAMPLE_CLASSIFICATION = {
    "category": "connectivity_loss",
    "severity": "critical",
    "severity_reason": "Core site down with no failover.",
    "entities": {
        "sites": ["SITE-NORTE-01"],
        "devices": ["rtr-norte-01"],
        "interfaces": ["TenGigE0/0/0/1"],
        "ip_addresses": ["10.20.0.2"],
        "event_time": "03:00",
    },
    "missing_information": [],
}

SAMPLE_DIAGNOSIS = {
    "reasoning": [
        "TenGigE0/0/0/1 went down at 03:10 and BFD to 10.20.0.2 dropped right after.",
        "Link and BFD failing together point to the physical path, not routing.",
    ],
    "probable_causes": [
        {"cause": "Fiber cut", "likelihood": "high", "evidence": "Link down with no flapping."},
    ],
    "diagnostic_steps": [
        {
            "action": "Check optical power on the interface",
            "command": "show controllers TenGigE0/0/0/1 phy",
            "expected_result": "No RX light confirms a fiber or optic problem.",
        }
    ],
    "recommended_actions": ["Dispatch field team to the fiber route"],
    "customer_reply": "Estamos trabajando en la falla que afecta su servicio.",
}

SAMPLE_AGENT_REPORT = {
    **SAMPLE_DIAGNOSIS,
    "severity": "major",
    "severity_reason": "One customer is down: alarm 11 on its access port.",
}


class FakeLLM:
    """Stands in for the real client: returns a canned answer per output schema and records the
    messages it was sent. `fail_on` makes it raise `error` only for that schema."""

    def __init__(
        self,
        outputs: dict[type, dict] | None = None,
        error: LLMError | None = None,
        fail_on: type | None = None,
    ):
        self.outputs = {
            TicketClassification: SAMPLE_CLASSIFICATION,
            TicketDiagnosis: SAMPLE_DIAGNOSIS,
            **(outputs or {}),
        }
        self.error = error
        self.fail_on = fail_on
        self.calls: list[list[dict]] = []
        self.output_models: list[type] = []

    def parse(self, messages, output_model):
        self.calls.append(messages)
        self.output_models.append(output_model)
        if self.error and self.fail_on in (None, output_model):
            raise self.error
        return LLMResult(
            parsed=output_model.model_validate(self.outputs[output_model]),
            model="fake-model",
            input_tokens=1200,
            output_tokens=150,
            reasoning_tokens=40,
            reasoning_effort="low",
        )


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def sample_classification() -> TicketClassification:
    return TicketClassification.model_validate(SAMPLE_CLASSIFICATION)


def _create_database_if_missing(url: str) -> None:
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        # Fail fast when nothing listens: without it a dropped connection can hang for minutes.
        connect_args={"connect_timeout": 5},
    )
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def _database_unreachable() -> str | None:
    """Try to reach PostgreSQL once per run, not once per test that needs it."""
    try:
        _create_database_if_missing(TEST_DATABASE_URL)
    except OperationalError as exc:
        return f"PostgreSQL not reachable at {TEST_DATABASE_URL}: {exc.__class__.__name__}"
    return None


@pytest.fixture(scope="session")
def db_engine(_database_unreachable):
    """Test database migrated with Alembic, so the migrations themselves are exercised."""
    if _database_unreachable:
        # Locally, skipping lets the rest of the suite run without Docker. In CI (GitHub Actions
        # sets CI=true) a skip would hide a broken setup behind a green build, so fail instead.
        if os.environ.get("CI"):
            pytest.fail(_database_unreachable)
        pytest.skip(_database_unreachable)

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")

    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Session inside a transaction that is rolled back after the test.

    Commits made by the code under test only release a savepoint, so nothing persists.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def db_client(client, db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return client
