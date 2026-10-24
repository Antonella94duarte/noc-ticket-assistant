"""Multi-step ticket analysis orchestrated with LangGraph.

    START -> triage -> investigate -> report -> END

- triage: classify_v3 (few-shot, structured output), the same prompt as the baseline.
- investigate: a tool-calling agent (LangChain `create_agent`) that queries alarms, topology and
  circuits. Middleware limits its tool and model calls and switches to the fallback models when
  the primary provider fails.
- report: a structured diagnosis (same TicketDiagnosis schema as the baseline, so both can be
  compared) grounded on the investigation's findings and raw tool results.

The graph only depends on LangChain chat models and tools, so any provider and the fake models
used in tests plug in the same way.
"""

import time
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.callbacks import BaseCallbackHandler, get_usage_metadata_callback
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from app.config import Provider, Settings, get_settings
from app.llm.prompt_builder import (
    CLASSIFY_PROMPT_VERSION,
    INVESTIGATE_PROMPT_VERSION,
    REPORT_PROMPT_VERSION,
    build_classify_messages,
    build_report_messages,
    format_investigation_request,
    load_system_prompt,
)
from app.llm.providers import create_chat_models, structured_output
from app.schemas import (
    AgentAnalysis,
    TicketClassification,
    TicketDiagnosis,
    TokenUsage,
    ToolCallRecord,
)
from app.tools.langchain_tools import build_network_tools

AGENT_PROMPT_VERSION = (
    f"agent:{CLASSIFY_PROMPT_VERSION}+{INVESTIGATE_PROMPT_VERSION}+{REPORT_PROMPT_VERSION}"
)


class AgentState(TypedDict, total=False):
    ticket_text: str
    logs: str | None
    classification: TicketClassification
    investigation_messages: list[BaseMessage]
    investigation_model_calls: int
    findings: str
    diagnosis: TicketDiagnosis


class _ModelCallCounter(BaseCallbackHandler):
    """Counts chat model calls. Counting AI messages would also count the notice that the
    call-limit middleware adds when it stops the agent."""

    def __init__(self) -> None:
        self.calls = 0

    def on_chat_model_start(self, *args, **kwargs) -> None:
        self.calls += 1


def _structured_with_fallbacks(
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


def _tool_results(messages: list[BaseMessage]) -> list[ToolCallRecord]:
    """Each tool call the investigator made, with the result it got back."""
    results = {m.tool_call_id: m.text for m in messages if isinstance(m, ToolMessage)}
    return [
        ToolCallRecord(name=call["name"], args=call["args"], result=results.get(call["id"], ""))
        for m in messages
        if isinstance(m, AIMessage)
        for call in m.tool_calls
    ]


def _investigation_text(findings: str, tool_calls: list[ToolCallRecord]) -> str:
    lines = [findings.strip() or "(The investigator returned no summary.)", "", "Tool results:"]
    if not tool_calls:
        lines.append("(no tools were called)")
    for call in tool_calls:
        lines.append(f"- {call.name}({call.args}) -> {call.result}")
    return "\n".join(lines)


def build_agent_graph(
    models: list[BaseChatModel],
    providers: list[Provider],
    tools: list[BaseTool],
    settings: Settings | None = None,
) -> CompiledStateGraph:
    """`models[0]` is the primary model; the rest are fallbacks, tried in order on errors."""
    settings = settings or get_settings()
    triage_chain = _structured_with_fallbacks(models, providers, TicketClassification, settings)
    report_chain = _structured_with_fallbacks(models, providers, TicketDiagnosis, settings)

    middleware = [
        # Past the tool limit the agent can't call tools anymore and has to conclude.
        ToolCallLimitMiddleware(run_limit=settings.agent_max_tool_calls, exit_behavior="continue"),
        # Hard stop on model calls: an agent stuck in a loop can't keep spending.
        ModelCallLimitMiddleware(run_limit=settings.agent_max_model_calls, exit_behavior="end"),
    ]
    if len(models) > 1:
        middleware.insert(0, ModelFallbackMiddleware(*models[1:]))
    investigator = create_agent(
        models[0],
        tools,
        system_prompt=load_system_prompt(INVESTIGATE_PROMPT_VERSION),
        middleware=middleware,
        name="investigator",
    )

    def triage(state: AgentState) -> AgentState:
        messages = build_classify_messages(state["ticket_text"], state.get("logs"))
        return {"classification": triage_chain.invoke(messages)}

    def investigate(state: AgentState) -> AgentState:
        request = format_investigation_request(
            state["ticket_text"], state.get("logs"), state["classification"]
        )
        counter = _ModelCallCounter()
        result = investigator.invoke(
            {"messages": [HumanMessage(request)]}, config={"callbacks": [counter]}
        )
        messages = result["messages"]
        # When a limit stops the agent, its notice is the last message: kept on purpose, so the
        # report knows the investigation was cut short.
        final = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        return {
            "investigation_messages": messages,
            "investigation_model_calls": counter.calls,
            "findings": final.text if final else "",
        }

    def report(state: AgentState) -> AgentState:
        tool_calls = _tool_results(state["investigation_messages"])
        messages = build_report_messages(
            state["ticket_text"],
            state.get("logs"),
            state["classification"],
            _investigation_text(state["findings"], tool_calls),
        )
        return {"diagnosis": report_chain.invoke(messages)}

    graph = StateGraph(AgentState)
    graph.add_node("triage", triage)
    graph.add_node("investigate", investigate)
    graph.add_node("report", report)
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "investigate")
    graph.add_edge("investigate", "report")
    graph.add_edge("report", END)
    return graph.compile(name="noc_agent")


def build_default_graph(settings: Settings | None = None) -> CompiledStateGraph:
    """The graph wired to the configured providers and the real network tools."""
    settings = settings or get_settings()
    providers = [settings.llm_provider, *settings.fallback_providers]
    return build_agent_graph(
        create_chat_models(settings), providers, build_network_tools(), settings
    )


def _usage(raw: dict) -> TokenUsage:
    details = raw.get("output_token_details") or {}
    return TokenUsage(
        input_tokens=raw.get("input_tokens", 0),
        output_tokens=raw.get("output_tokens", 0),
        reasoning_tokens=details.get("reasoning", 0),
        total_tokens=raw.get("total_tokens", 0),
    )


def run_agent_analysis(
    graph: CompiledStateGraph,
    ticket_text: str,
    logs: str | None = None,
    settings: Settings | None = None,
) -> AgentAnalysis:
    settings = settings or get_settings()
    with get_usage_metadata_callback() as usage:
        start = time.perf_counter()
        state = graph.invoke({"ticket_text": ticket_text, "logs": logs})
        latency = time.perf_counter() - start

    tool_calls = _tool_results(state["investigation_messages"])
    model_calls = state["investigation_model_calls"]
    return AgentAnalysis(
        classification=state["classification"],
        findings=state["findings"],
        diagnosis=state["diagnosis"],
        tool_calls=tool_calls,
        investigation_model_calls=model_calls,
        limit_reached=(
            len(tool_calls) > settings.agent_max_tool_calls
            or model_calls >= settings.agent_max_model_calls
        ),
        prompt_version=AGENT_PROMPT_VERSION,
        usage_by_model={model: _usage(raw) for model, raw in usage.usage_metadata.items()},
        latency_seconds=round(latency, 2),
    )
