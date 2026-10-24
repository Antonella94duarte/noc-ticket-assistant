"""Check that each LLM provider can do what the agents need, with real calls.

For every provider it checks two capabilities and reports latency and tokens:

1. Tool calling: given the network tools and a question about a site, does the model call the
   right tool with the right argument?
2. Structured output: does it return a ticket classification that matches the Pydantic schema?

It spends a few tokens per provider. Run it by hand:

    python scripts/check_providers.py                 # every provider that is configured
    python scripts/check_providers.py deepseek ollama
"""

import sys
import time
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PROVIDERS, get_settings  # noqa: E402
from app.llm.providers import (  # noqa: E402
    ProviderNotConfiguredError,
    create_chat_model,
    structured_output,
)
from app.schemas import TicketClassification  # noqa: E402
from app.tools.langchain_tools import build_network_tools  # noqa: E402

TOOL_QUESTION = (
    "A customer at SITE-SUR-02 reports problems. Before answering, check which alarms are "
    "active on that site using the available tools."
)
TICKET = "Desde las 07:45 el cliente Distribuidora Del Sur (circuito SUR-2210) no tiene internet."


def check_tool_calling(model, tools) -> tuple[bool, str, dict]:
    start = time.perf_counter()
    reply = model.bind_tools(tools).invoke(TOOL_QUESTION)
    elapsed = time.perf_counter() - start
    calls = [(c["name"], c["args"]) for c in reply.tool_calls]
    ok = any(
        name == "get_active_alarms" and str(args.get("site_code", "")).upper() == "SITE-SUR-02"
        for name, args in calls
    )
    return ok, f"{elapsed:.1f}s calls={calls}", reply.usage_metadata or {}


def check_structured_output(model, provider, settings) -> tuple[bool, str, dict]:
    structured = structured_output(
        model, TicketClassification, provider, settings, include_raw=True
    )
    start = time.perf_counter()
    result = structured.invoke(f"Classify this NOC ticket: {TICKET}")
    elapsed = time.perf_counter() - start
    parsed = result["parsed"]
    if parsed is None:
        return False, f"{elapsed:.1f}s error={result['parsing_error']}", {}
    summary = f"{elapsed:.1f}s {parsed.category.value}/{parsed.severity.value}"
    return True, summary, result["raw"].usage_metadata or {}


def main() -> int:
    settings = get_settings()
    providers = sys.argv[1:] or list(PROVIDERS)
    tools = build_network_tools()  # only their schemas are sent; nothing is executed
    failed = False

    for provider in providers:
        try:
            model = create_chat_model(provider, settings)
        except ProviderNotConfiguredError as exc:
            print(f"== {provider}: skipped ({exc})")
            continue
        name = getattr(model, "model_name", None) or getattr(model, "model", "?")
        print(f"== {provider} ({name})")
        for label, check in (
            ("tool calling", partial(check_tool_calling, model, tools)),
            ("structured output", partial(check_structured_output, model, provider, settings)),
        ):
            try:
                ok, detail, usage = check()
            except Exception as exc:  # report and keep checking the other providers
                ok, detail, usage = False, f"{type(exc).__name__}: {exc}", {}
            failed |= not ok
            tokens = f"in={usage.get('input_tokens')} out={usage.get('output_tokens')}"
            print(f"   {'PASS' if ok else 'FAIL'}  {label:<18} {detail}  [{tokens}]")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
