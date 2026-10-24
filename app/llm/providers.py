"""Chat models for the agents, from any supported provider.

Agent code depends only on LangChain's `BaseChatModel`, so switching provider is a `.env` change
(`LLM_PROVIDER`), and `LLM_FALLBACK_PROVIDERS` lists the providers to try when the primary one
fails. Each provider keeps its quirks here:

- OpenAI reasoning models take a reasoning effort instead of a temperature, and enforce JSON
  schemas strictly.
- DeepSeek thinks by default. In thinking mode it ignores temperature and can't be forced to
  call a function, which is how LangChain usually gets structured output; so structured output
  uses JSON mode with the schema in the prompt, validated by Pydantic on our side.
- Ollama runs locally: no API key, nothing leaves the machine.

Use `structured_output()` instead of calling `with_structured_output` directly, so these
differences stay here. The baseline pipeline (app/llm/client.py) still uses the OpenAI Responses
API directly.
"""

import json
import typing
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, ValidationError

from app.config import Provider, Settings, get_settings
from app.llm.client import LLMNotConfiguredError

StructuredOutputMethod = Literal["json_schema", "function_calling", "json_mode"]

MAX_RETRIES = 2


class ProviderNotConfiguredError(LLMNotConfiguredError):
    """The provider was selected but its key or model is missing."""


def _secret(value) -> str:
    return value.get_secret_value() if value else ""


def create_chat_model(
    provider: Provider | None = None, settings: Settings | None = None
) -> BaseChatModel:
    """Chat model for `provider` (default: LLM_PROVIDER), configured from the settings."""
    settings = settings or get_settings()
    provider = provider or settings.llm_provider

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        if not _secret(settings.openai_api_key) or not settings.openai_model:
            raise ProviderNotConfiguredError("Set OPENAI_API_KEY and OPENAI_MODEL to use OpenAI")
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key.get_secret_value(),
            reasoning_effort=settings.openai_reasoning_effort,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.openai_timeout_seconds,
            max_retries=MAX_RETRIES,
        )

    if provider == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        if not _secret(settings.deepseek_api_key):
            raise ProviderNotConfiguredError("Set DEEPSEEK_API_KEY to use DeepSeek")
        thinking = settings.deepseek_thinking
        return ChatDeepSeek(
            model=settings.deepseek_model,
            api_key=settings.deepseek_api_key.get_secret_value(),
            api_base=settings.deepseek_base_url,
            temperature=settings.llm_temperature,
            max_tokens=settings.deepseek_max_tokens,
            timeout=settings.openai_timeout_seconds,
            max_retries=MAX_RETRIES,
            reasoning_effort=settings.deepseek_reasoning_effort,
            extra_body=(
                None
                if thinking is None
                else {"thinking": {"type": "enabled" if thinking else "disabled"}}
            ),
        )

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=settings.llm_temperature,
            num_predict=settings.llm_max_tokens,
            num_ctx=settings.ollama_num_ctx,
            reasoning=settings.ollama_reasoning,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")


def create_chat_models(settings: Settings | None = None) -> list[BaseChatModel]:
    """The primary model followed by the fallbacks, in the order they should be tried.

    Every listed provider must be configured: a fallback that can't start would only fail
    later, in the middle of an incident.
    """
    settings = settings or get_settings()
    providers = [settings.llm_provider, *settings.fallback_providers]
    return [create_chat_model(provider, settings) for provider in providers]


def with_fallbacks(models: list[BaseChatModel]) -> Runnable:
    """One runnable that tries each model in turn, for single calls outside an agent loop.

    Agents get the same behavior from LangChain's ModelFallbackMiddleware instead, because a
    fallback wrapper can't bind tools.
    """
    primary, *fallbacks = models
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


# --- Structured output ----------------------------------------------------------------------


def structured_output_method(provider: Provider, settings: Settings) -> StructuredOutputMethod:
    """How `provider` can be asked for output that matches a Pydantic schema."""
    if provider == "deepseek":
        # Forcing a function call only works with thinking explicitly turned off.
        return "function_calling" if settings.deepseek_thinking is False else "json_mode"
    return "json_schema"


def schema_instruction(schema: type[BaseModel]) -> SystemMessage:
    """JSON mode only guarantees valid JSON, not its shape: the schema goes in the prompt."""
    return SystemMessage(
        "Answer only with a JSON object that matches this JSON schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


def with_instruction(instruction: BaseMessage, model_input) -> list[BaseMessage]:
    messages = (
        [HumanMessage(model_input)]
        if isinstance(model_input, str)
        else convert_to_messages(model_input)
    )
    return [instruction, *messages]


def _nested_model(annotation) -> type[BaseModel] | None:
    """The Pydantic model inside `Model`, `Model | None` or `list[Model]`, if any."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    for arg in typing.get_args(annotation):
        found = _nested_model(arg)
        if found:
            return found
    return None


def drop_unknown_keys(data, schema: type[BaseModel]):
    """Remove keys the schema doesn't define, at every level.

    JSON mode guarantees valid JSON but not its shape, and models sometimes add a key of their
    own (DeepSeek once added "type": "json_object"). Required keys are still enforced by the
    schema afterwards; only the extras are dropped.
    """
    if isinstance(data, list):
        return [drop_unknown_keys(item, schema) for item in data]
    if not isinstance(data, dict):
        return data
    cleaned = {}
    for key, value in data.items():
        field = schema.model_fields.get(key)
        if field is None:
            continue
        nested = _nested_model(field.annotation)
        cleaned[key] = drop_unknown_keys(value, nested) if nested else value
    return cleaned


def _json_mode(model: BaseChatModel, schema: type[BaseModel], include_raw: bool) -> Runnable:
    instruction = schema_instruction(schema)
    bound = model.bind(response_format={"type": "json_object"})

    def parse(message: AIMessage):
        try:
            parsed = schema.model_validate(drop_unknown_keys(json.loads(message.text), schema))
        except (ValueError, ValidationError) as exc:
            if not include_raw:
                raise
            return {"raw": message, "parsed": None, "parsing_error": exc}
        return {"raw": message, "parsed": parsed, "parsing_error": None} if include_raw else parsed

    return (
        RunnableLambda(lambda model_input: with_instruction(instruction, model_input))
        | bound
        | RunnableLambda(parse)
    )


def structured_output(
    model: BaseChatModel,
    schema: type[BaseModel],
    provider: Provider | None = None,
    settings: Settings | None = None,
    include_raw: bool = False,
) -> Runnable:
    """`model` returning instances of `schema`, using the method its provider supports."""
    settings = settings or get_settings()
    provider = provider or settings.llm_provider
    method = structured_output_method(provider, settings)
    if method == "json_mode":
        return _json_mode(model, schema, include_raw)
    # OpenAI enforces the schema server-side when asked to; others are validated by Pydantic.
    strict = {"strict": True} if provider == "openai" else {}
    return model.with_structured_output(schema, method=method, include_raw=include_raw, **strict)


def structured_with_fallbacks(
    models: list[BaseChatModel],
    providers: list[Provider],
    schema: type[BaseModel],
    settings: Settings,
) -> Runnable:
    """One structured-output runnable per model (each with its provider's method), in order."""
    primary, *fallbacks = [
        structured_output(model, schema, provider, settings)
        for model, provider in zip(models, providers, strict=True)
    ]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary
