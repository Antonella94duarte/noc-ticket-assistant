import pytest
from fastapi.testclient import TestClient

from app.llm.client import LLMError, LLMResult
from app.main import app
from app.schemas import TicketClassification

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
