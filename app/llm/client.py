"""Thin layer over the LLM provider.

The rest of the app depends only on `LLMClient` and `LLMResult`, so the provider can be swapped
and tests can inject a fake client without calling the real API.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Generic, Protocol, TypeVar

import openai
from pydantic import BaseModel

from app.config import ReasoningEffort, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Chat-style message: {"role": "system" | "user" | "assistant", "content": "..."}
Message = dict[str, str]


class LLMError(Exception):
    """The model call failed or returned something we can't use."""


class LLMNotConfiguredError(LLMError):
    """API key or model name is missing from the settings."""


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    parsed: T
    model: str
    input_tokens: int
    output_tokens: int  # includes reasoning tokens
    reasoning_tokens: int = 0
    reasoning_effort: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    def parse(self, messages: list[Message], output_model: type[T]) -> LLMResult[T]:
        """Send `messages` and return the reply validated against `output_model`."""
        ...


class OpenAIClient:
    """`LLMClient` backed by the OpenAI Responses API with Structured Outputs."""

    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: ReasoningEffort = "medium",
        timeout: float = 30.0,
        max_retries: int = 2,
    ):
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout, max_retries=max_retries)
        self._model = model
        self._reasoning_effort = reasoning_effort

    def parse(self, messages: list[Message], output_model: type[T]) -> LLMResult[T]:
        try:
            response = self._client.responses.parse(
                model=self._model,
                input=messages,
                text_format=output_model,
                reasoning={"effort": self._reasoning_effort},
                # Tickets may contain customer data: don't keep them on the provider side.
                store=False,
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"LLM request failed: {exc.__class__.__name__}") from exc

        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else None
            raise LLMError(f"LLM response incomplete: {reason}")

        refusal = _find_refusal(response)
        if refusal:
            raise LLMError(f"LLM refused the request: {refusal}")

        parsed = response.output_parsed
        if parsed is None:
            raise LLMError("LLM response had no parsed output")

        usage = response.usage
        details = usage.output_tokens_details if usage else None
        return LLMResult(
            parsed=parsed,
            model=response.model,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            reasoning_tokens=details.reasoning_tokens if details else 0,
            reasoning_effort=self._reasoning_effort,
        )


def _find_refusal(response) -> str | None:
    for item in response.output:
        for content in getattr(item, "content", None) or []:
            if getattr(content, "type", None) == "refusal":
                return content.refusal
    return None


@lru_cache
def _build_openai_client(
    api_key: str, model: str, reasoning_effort: ReasoningEffort
) -> OpenAIClient:
    return OpenAIClient(api_key=api_key, model=model, reasoning_effort=reasoning_effort)


def get_llm_client() -> LLMClient:
    """FastAPI dependency. Tests override it with a fake client."""
    settings = get_settings()
    # An empty OPENAI_API_KEY= line in .env yields an empty secret, not None.
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if not api_key or not settings.openai_model:
        raise LLMNotConfiguredError("Set OPENAI_API_KEY and OPENAI_MODEL to enable analysis")
    return _build_openai_client(api_key, settings.openai_model, settings.openai_reasoning_effort)
