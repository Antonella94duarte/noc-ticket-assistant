import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.llm.providers import (
    ProviderNotConfiguredError,
    create_chat_model,
    create_chat_models,
    drop_unknown_keys,
    schema_instruction,
    structured_output,
    structured_output_method,
    with_fallbacks,
    with_instruction,
)
from app.schemas import TicketClassification
from tests.conftest import SAMPLE_CLASSIFICATION


def settings(**overrides) -> Settings:
    base = {
        "openai_api_key": "sk-test",
        "openai_model": "gpt-test",
        "deepseek_api_key": "ds-test",
        "llm_max_tokens": 1234,
    }
    return Settings(_env_file=None, **{**base, **overrides})


def test_openai_model_uses_reasoning_effort_and_no_temperature():
    model = create_chat_model("openai", settings(openai_reasoning_effort="low"))

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-test"
    assert model.reasoning_effort == "low"
    assert model.temperature is None
    assert model.max_tokens == 1234


def test_deepseek_model_points_to_deepseek():
    model = create_chat_model("deepseek", settings(llm_temperature=0.2))

    assert isinstance(model, ChatDeepSeek)
    assert model.model_name == "deepseek-flash"
    assert model.api_base == "https://api.deepseek.com"
    assert model.temperature == 0.2


def test_ollama_model_needs_no_key():
    model = create_chat_model("ollama", Settings(_env_file=None, ollama_model="qwen3:8b"))

    assert isinstance(model, ChatOllama)
    assert model.model == "qwen3:8b"
    assert model.base_url == "http://localhost:11434"


def test_default_provider_comes_from_settings():
    assert isinstance(create_chat_model(settings=settings(llm_provider="deepseek")), ChatDeepSeek)


@pytest.mark.parametrize(
    "provider, missing",
    [
        ("openai", {"openai_api_key": None}),
        ("openai", {"openai_model": ""}),
        ("deepseek", {"deepseek_api_key": ""}),
    ],
)
def test_missing_credentials_raise_a_clear_error(provider, missing):
    with pytest.raises(ProviderNotConfiguredError):
        create_chat_model(provider, settings(**missing))


def test_fallbacks_keep_order_and_skip_duplicates_and_the_primary():
    config = settings(
        llm_provider="openai", llm_fallback_providers=" DeepSeek, ollama, openai, deepseek "
    )

    assert config.fallback_providers == ["deepseek", "ollama"]
    models = create_chat_models(config)
    assert [type(m) for m in models] == [ChatOpenAI, ChatDeepSeek, ChatOllama]


def test_unknown_fallback_provider_is_rejected():
    with pytest.raises(ValueError, match="qwen"):
        _ = settings(llm_fallback_providers="qwen").fallback_providers


def test_unconfigured_fallback_fails_at_startup():
    with pytest.raises(ProviderNotConfiguredError):
        create_chat_models(settings(llm_fallback_providers="deepseek", deepseek_api_key=None))


class FailingChatModel(GenericFakeChatModel):
    def _generate(self, *args, **kwargs):
        raise ConnectionError("provider unavailable")


def test_with_fallbacks_uses_the_next_model_when_the_primary_fails():
    primary = FailingChatModel(messages=iter([]))
    backup = GenericFakeChatModel(messages=iter([AIMessage(content="from backup")]))

    answer = with_fallbacks([primary, backup]).invoke("hello")

    assert answer.content == "from backup"


def test_with_fallbacks_without_backups_returns_the_model_itself():
    model = GenericFakeChatModel(messages=iter([]))

    assert with_fallbacks([model]) is model


def test_ollama_thinking_can_be_turned_off():
    model = create_chat_model("ollama", Settings(_env_file=None, ollama_reasoning=False))

    assert model.reasoning is False


@pytest.mark.parametrize(
    "thinking, extra_body",
    [
        (None, None),
        (True, {"thinking": {"type": "enabled"}}),
        (False, {"thinking": {"type": "disabled"}}),
    ],
)
def test_deepseek_thinking_is_sent_only_when_configured(thinking, extra_body):
    model = create_chat_model("deepseek", settings(deepseek_thinking=thinking))

    assert model.extra_body == extra_body


@pytest.mark.parametrize(
    "provider, thinking, method",
    [
        ("openai", None, "json_schema"),
        ("ollama", None, "json_schema"),
        # Thinking mode (DeepSeek's default) can't force a tool call.
        ("deepseek", None, "json_mode"),
        ("deepseek", True, "json_mode"),
        ("deepseek", False, "function_calling"),
    ],
)
def test_structured_output_method_per_provider(provider, thinking, method):
    assert structured_output_method(provider, settings(deepseek_thinking=thinking)) == method


def test_json_mode_puts_the_schema_in_the_prompt():
    instruction = schema_instruction(TicketClassification)

    assert '"severity_reason"' in instruction.content
    assert '"missing_information"' in instruction.content


def test_instruction_is_prepended_to_text_or_messages():
    instruction = SystemMessage("schema")

    from_text = with_instruction(instruction, "Classify this")
    from_messages = with_instruction(instruction, [("system", "role"), ("user", "Classify this")])

    assert [m.type for m in from_text] == ["system", "human"]
    assert [m.type for m in from_messages] == ["system", "system", "human"]
    assert from_messages[0] is instruction


def test_structured_output_for_deepseek_thinking_adds_the_schema_step():
    config = settings(deepseek_thinking=None)
    runnable = structured_output(
        create_chat_model("deepseek", config), TicketClassification, "deepseek", config
    )

    assert isinstance(runnable.first, RunnableLambda)


def test_deepseek_reasoning_effort_and_ollama_context_are_passed_through():
    deepseek = create_chat_model("deepseek", settings(deepseek_reasoning_effort="low"))
    ollama = create_chat_model("ollama", settings(ollama_num_ctx=8192))

    assert deepseek.reasoning_effort == "low"
    assert ollama.num_ctx == 8192


def test_drop_unknown_keys_at_every_level():
    data = {
        **SAMPLE_CLASSIFICATION,
        "type": "json_object",
        "entities": {**SAMPLE_CLASSIFICATION["entities"], "vendor": "Cisco"},
    }

    cleaned = drop_unknown_keys(data, TicketClassification)

    assert "type" not in cleaned and "vendor" not in cleaned["entities"]
    TicketClassification.model_validate(cleaned)


def deepseek_json_reply(payload: dict) -> list:
    return [AIMessage(content=json.dumps(payload))]


def test_json_mode_tolerates_extra_keys_but_not_missing_ones():
    config = settings(deepseek_thinking=None)
    extra = {**SAMPLE_CLASSIFICATION, "type": "json_object"}
    missing = {k: v for k, v in SAMPLE_CLASSIFICATION.items() if k != "severity"}

    ok = structured_output(
        GenericFakeChatModel(messages=iter(deepseek_json_reply(extra))),
        TicketClassification,
        "deepseek",
        config,
    ).invoke("Clasificá el ticket")
    raw = structured_output(
        GenericFakeChatModel(messages=iter(deepseek_json_reply(missing))),
        TicketClassification,
        "deepseek",
        config,
        include_raw=True,
    ).invoke("Clasificá el ticket")

    assert ok.category.value == "connectivity_loss"
    assert raw["parsed"] is None and raw["parsing_error"] is not None


def test_deepseek_has_its_own_token_cap():
    model = create_chat_model("deepseek", settings(deepseek_max_tokens=9000))

    assert model.max_tokens == 9000
