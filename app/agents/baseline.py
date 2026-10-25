"""The non-agent baseline on any provider: classify_v3, then diagnose_v2, no tools.

The same prompts as the API pipeline (app/services/analyzer.py), but through LangChain chat
models, so the evaluation can compare it with the agent on every provider.
"""

import time

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.language_models import BaseChatModel

from app.agents.graph import token_usage
from app.config import Provider, Settings, get_settings
from app.llm.prompt_builder import (
    CLASSIFY_PROMPT_VERSION,
    DIAGNOSE_PROMPT_VERSION,
    build_classify_messages,
    build_diagnose_messages,
)
from app.llm.providers import create_chat_models, structured_with_fallbacks
from app.schemas import BaselineAnalysis, TicketClassification, TicketDiagnosis

BASELINE_PROMPT_VERSION = f"baseline:{CLASSIFY_PROMPT_VERSION}+{DIAGNOSE_PROMPT_VERSION}"


class Baseline:
    prompt_version = BASELINE_PROMPT_VERSION

    def __init__(self, models: list[BaseChatModel], providers: list[Provider], settings: Settings):
        self._classify = structured_with_fallbacks(
            models, providers, TicketClassification, settings
        )
        self._diagnose = structured_with_fallbacks(models, providers, TicketDiagnosis, settings)

    def run(self, ticket_text: str, logs: str | None = None) -> BaselineAnalysis:
        with get_usage_metadata_callback() as usage:
            start = time.perf_counter()
            classification = self._classify.invoke(build_classify_messages(ticket_text, logs))
            diagnosis = self._diagnose.invoke(
                build_diagnose_messages(ticket_text, logs, classification)
            )
            latency = time.perf_counter() - start
        return BaselineAnalysis(
            classification=classification,
            diagnosis=diagnosis,
            prompt_version=self.prompt_version,
            usage_by_model={m: token_usage(raw) for m, raw in usage.usage_metadata.items()},
            latency_seconds=round(latency, 2),
        )


def build_default_baseline(settings: Settings | None = None) -> Baseline:
    settings = settings or get_settings()
    providers = [settings.llm_provider, *settings.fallback_providers]
    return Baseline(create_chat_models(settings), providers, settings)
