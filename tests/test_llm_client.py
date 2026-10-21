from types import SimpleNamespace

import openai
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.llm import client as client_module
from app.llm.client import LLMError, LLMNotConfiguredError, OpenAIClient, get_llm_client
from app.schemas import TicketClassification


def make_response(*, status="completed", parsed=None, output=None, incomplete_reason=None):
    return SimpleNamespace(
        status=status,
        incomplete_details=SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None,
        output=output or [],
        output_parsed=parsed,
        model="gpt-test",
        usage=SimpleNamespace(
            input_tokens=900,
            output_tokens=100,
            output_tokens_details=SimpleNamespace(reasoning_tokens=30),
        ),
    )


def make_client(response=None, error=None, sent: dict | None = None) -> OpenAIClient:
    def parse(**kwargs):
        if sent is not None:
            sent.update(kwargs)
        if error:
            raise error
        return response

    llm = OpenAIClient(api_key="test-key", model="gpt-test", reasoning_effort="medium")
    llm._client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return llm


def test_parse_returns_result_with_usage(sample_classification):
    llm = make_client(make_response(parsed=sample_classification))

    result = llm.parse([], TicketClassification)

    assert result.parsed == sample_classification
    assert result.model == "gpt-test"
    assert result.total_tokens == 1000
    assert result.reasoning_tokens == 30
    assert result.reasoning_effort == "medium"


def test_parse_sends_reasoning_effort_and_disables_storage(sample_classification):
    sent: dict = {}
    llm = make_client(make_response(parsed=sample_classification), sent=sent)

    llm.parse([], TicketClassification)

    assert sent["reasoning"] == {"effort": "medium"}
    assert sent["store"] is False


def test_reasoning_effort_defaults_to_medium():
    assert Settings(_env_file=None).openai_reasoning_effort == "medium"


def test_invalid_reasoning_effort_is_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, openai_reasoning_effort="extreme")


def test_incomplete_response_raises():
    llm = make_client(make_response(status="incomplete", incomplete_reason="max_output_tokens"))

    with pytest.raises(LLMError, match="max_output_tokens"):
        llm.parse([], TicketClassification)


def test_refusal_raises():
    refusal = SimpleNamespace(type="refusal", refusal="I can't help with that.")
    llm = make_client(make_response(output=[SimpleNamespace(content=[refusal])]))

    with pytest.raises(LLMError, match="refused"):
        llm.parse([], TicketClassification)


def test_missing_parsed_output_raises():
    llm = make_client(make_response(parsed=None))

    with pytest.raises(LLMError, match="no parsed output"):
        llm.parse([], TicketClassification)


def test_provider_errors_are_wrapped():
    llm = make_client(error=openai.APIConnectionError(request=None))

    with pytest.raises(LLMError, match="APIConnectionError"):
        llm.parse([], TicketClassification)


@pytest.mark.parametrize(
    "api_key, model",
    [(None, "gpt-test"), ("", "gpt-test"), ("sk-test", None), ("sk-test", "")],
)
def test_get_llm_client_requires_key_and_model(monkeypatch, api_key, model):
    settings = Settings(_env_file=None, openai_api_key=api_key, openai_model=model)
    monkeypatch.setattr(client_module, "get_settings", lambda: settings)

    with pytest.raises(LLMNotConfiguredError):
        get_llm_client()
