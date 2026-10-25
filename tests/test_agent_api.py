import json
from contextlib import nullcontext

import pytest
from langchain_core.messages import AIMessage

from app.agents.graph import build_agent_graph
from app.config import Settings
from app.db.seed import load_network_seed
from app.schemas import AgentAnalysis, TokenUsage
from app.services import agent as agent_service
from app.tools.langchain_tools import build_network_tools
from tests.conftest import SAMPLE_AGENT_REPORT, SAMPLE_CLASSIFICATION
from tests.test_agent_graph import BrokenModel, scripted, tool_call

TICKET = {"ticket_text": "Distribuidora Del Sur no tiene internet desde las 07:45."}


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None, openai_api_key="sk-test", openai_model="gpt-6-luna", **overrides
    )


@pytest.fixture
def agent_client(client, db_session):
    load_network_seed(db_session)
    tools = build_network_tools(lambda: nullcontext(db_session))

    def use(model):
        graph = build_agent_graph([model], ["openai"], tools, settings())
        client.app.dependency_overrides[agent_service.get_agent_graph] = lambda: graph
        client.app.dependency_overrides[agent_service.get_settings] = lambda: settings()
        return client

    return use


def events(response) -> list[dict]:
    """The streamed events, checking and then dropping their elapsed time."""
    trace = [json.loads(line) for line in response.text.splitlines()]
    elapsed = [event.pop("elapsed") for event in trace]
    assert elapsed == sorted(elapsed)
    return trace


def test_agent_streams_each_step_then_the_analysis(agent_client):
    model = scripted(
        [
            tool_call("find_circuits", {"query": "Distribuidora"}, "c1"),
            tool_call("get_active_alarms", {"site_code": "SITE-SUR-02"}, "c2"),
            AIMessage(content="SUR-2210: alarma link_down en rtr-sur-02 Gi0/0/3."),
        ]
    )

    response = agent_client(model).post("/api/v1/agent/analyze", json=TICKET)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    trace = events(response)
    assert [e["type"] for e in trace] == [
        "start",
        "triage",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "findings",
        "report",
        "analysis",
    ]
    assert trace[0] == {
        "type": "start",
        "provider": "openai",
        "model": "gpt-6-luna",
        "prompt_version": trace[-1]["analysis"]["prompt_version"],
    }
    assert trace[1]["classification"] == SAMPLE_CLASSIFICATION
    assert trace[2] == {
        "type": "tool_call",
        "id": "c1",
        "name": "find_circuits",
        "args": {"query": "Distribuidora"},
    }
    assert trace[3]["id"] == "c1"
    assert json.loads(trace[3]["result"])["circuits"][0]["circuit_id"] == "SUR-2210"
    assert trace[6]["text"].startswith("SUR-2210")
    assert trace[7]["diagnosis"] == SAMPLE_AGENT_REPORT
    analysis = AgentAnalysis.model_validate(trace[-1]["analysis"])
    assert [c.name for c in analysis.tool_calls] == ["find_circuits", "get_active_alarms"]


def test_a_failure_mid_run_ends_the_stream_with_an_error_event(agent_client):
    response = agent_client(BrokenModel(messages=iter([]))).post(
        "/api/v1/agent/analyze", json=TICKET
    )

    trace = events(response)
    assert response.status_code == 200
    assert trace[-1] == {"type": "error", "detail": "The agent could not analyze the ticket"}
    assert "provider unavailable" not in response.text


def test_agent_needs_a_configured_provider(client, monkeypatch):
    agent_service.get_agent_graph.cache_clear()
    monkeypatch.setattr(
        agent_service, "get_settings", lambda: Settings(_env_file=None, openai_api_key=None)
    )

    response = client.post("/api/v1/agent/analyze", json=TICKET)

    assert response.status_code == 503
    agent_service.get_agent_graph.cache_clear()


def test_agent_validates_the_ticket(client):
    response = client.post("/api/v1/agent/analyze", json={"ticket_text": "short"})

    assert response.status_code == 422


def usage(input_tokens: int, output_tokens: int) -> TokenUsage:
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )


def analysis_with(usage_by_model: dict) -> AgentAnalysis:
    from app.schemas import AgentReport, TicketClassification

    return AgentAnalysis(
        classification=TicketClassification.model_validate(SAMPLE_CLASSIFICATION),
        findings="",
        diagnosis=AgentReport.model_validate(SAMPLE_AGENT_REPORT),
        tool_calls=[],
        investigation_model_calls=1,
        limit_reached=False,
        prompt_version="v",
        usage_by_model=usage_by_model,
        latency_seconds=1.0,
    )


def test_estimated_cost_accepts_dated_model_names():
    analysis = analysis_with({"gpt-6-luna-2026-09-01": usage(1_000_000, 100_000)})

    assert agent_service.estimated_cost(analysis, settings()) == pytest.approx(0.15)


def test_no_cost_estimate_when_a_fallback_model_answered():
    analysis = analysis_with({"gpt-6-luna": usage(10, 10), "deepseek-flash": usage(10, 10)})

    assert agent_service.estimated_cost(analysis, settings()) is None


def test_local_models_cost_nothing():
    analysis = analysis_with({"qwen3:4b": usage(50_000, 2_000)})

    assert agent_service.estimated_cost(analysis, settings(llm_provider="ollama")) == 0.0


@pytest.mark.parametrize("scenario", ["customer-no-service", "slow-site", "config-change"])
def test_recorded_runs_for_the_demo_page_are_complete(client, scenario):
    response = client.get(f"/static/demo/{scenario}.ndjson")

    assert response.status_code == 200
    trace = events(response)
    assert trace[0]["type"] == "start" and trace[-1]["type"] == "analysis"
    AgentAnalysis.model_validate(trace[-1]["analysis"])
