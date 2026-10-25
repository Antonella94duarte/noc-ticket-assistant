"""Run the LangGraph agent for the API and stream its trace as NDJSON."""

import json
import logging
import queue
import threading
import time
from collections.abc import Iterator
from functools import lru_cache

from fastapi.encoders import jsonable_encoder
from langgraph.graph.state import CompiledStateGraph

from app.agents.graph import build_default_graph, stream_agent_analysis
from app.config import Settings, get_settings
from app.llm.pricing import estimate_cost
from app.schemas import AgentAnalysis

logger = logging.getLogger(__name__)

_DONE = object()


@lru_cache(maxsize=1)
def get_agent_graph() -> CompiledStateGraph:
    """The graph for the configured providers, built on first use. Raises
    ProviderNotConfiguredError (a 503) while the provider has no key."""
    return build_default_graph(get_settings())


def configured_model(settings: Settings) -> str:
    return {
        "openai": settings.openai_model,
        "deepseek": settings.deepseek_model,
        "ollama": settings.ollama_model,
    }[settings.llm_provider]


def estimated_cost(analysis: AgentAnalysis, settings: Settings) -> float | None:
    """Upper-bound US$ for the run (see app/llm/pricing.py), priced as the configured provider.

    None when a fallback provider answered or the model's price is unknown.
    """
    model = configured_model(settings)
    total = 0.0
    for name, usage in analysis.usage_by_model.items():
        # Providers may report a dated name such as "gpt-6-luna-2026-09-01".
        if not name.startswith(model):
            return None
        cost = estimate_cost(settings.llm_provider, model, usage.input_tokens, usage.output_tokens)
        if cost is None:
            return None
        total += cost
    return total


def _events(
    graph: CompiledStateGraph, ticket_text: str, logs: str | None, settings: Settings
) -> Iterator[dict]:
    start = time.perf_counter()

    def timed(event: dict) -> dict:
        # Seconds since the request started, so a client can show where the time goes.
        return {**event, "elapsed": round(time.perf_counter() - start, 1)}

    yield timed(
        {
            "type": "start",
            "provider": settings.llm_provider,
            "model": configured_model(settings),
            "prompt_version": getattr(graph, "prompt_version", None),
        }
    )
    try:
        for event in stream_agent_analysis(graph, ticket_text, logs, settings):
            if event["type"] == "analysis":
                event["estimated_cost_usd"] = estimated_cost(event["analysis"], settings)
            yield timed(event)
    except Exception:
        # The response has already started with 200: report the failure as the last event, and
        # keep provider details in the log.
        logger.exception("Agent run failed")
        yield timed({"type": "error", "detail": "The agent could not analyze the ticket"})


def trace_lines(
    graph: CompiledStateGraph, ticket_text: str, logs: str | None, settings: Settings
) -> Iterator[str]:
    """One JSON object per line, written as each step of the agent finishes.

    The run happens in its own thread: a streaming response would otherwise resume the
    generator in a different context each time, and token usage is tracked in a context
    variable.
    """
    events: queue.Queue = queue.Queue()

    def run() -> None:
        for event in _events(graph, ticket_text, logs, settings):
            events.put(event)
        events.put(_DONE)

    threading.Thread(target=run, name="agent-run", daemon=True).start()
    while (event := events.get()) is not _DONE:
        yield json.dumps(jsonable_encoder(event), ensure_ascii=False) + "\n"
