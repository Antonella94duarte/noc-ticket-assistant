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
from app.schemas import TicketClassification

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


class FakeLLM:
    """Stands in for the real client: returns a canned answer and records what it was sent."""

    def __init__(self, output: dict | None = None, error: LLMError | None = None):
        self.output = output if output is not None else SAMPLE_CLASSIFICATION
        self.error = error
        self.calls: list[list[dict]] = []

    def parse(self, messages, output_model):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return LLMResult(
            parsed=output_model.model_validate(self.output),
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
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def db_engine():
    """Test database migrated with Alembic, so the migrations themselves are exercised."""
    try:
        _create_database_if_missing(TEST_DATABASE_URL)
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}: {exc.__class__.__name__}")

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
