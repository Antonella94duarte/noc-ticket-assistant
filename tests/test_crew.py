"""Tests for the CrewAI version. They need requirements-crewai.txt (the CrewAI image) and are
skipped elsewhere."""

import json
import os

import pytest
from langchain_core.tools import tool

pytest.importorskip("crewai")

from app.config import Settings  # noqa: E402
from app.crew.noc_crew import (  # noqa: E402
    CREW_PROMPT_VERSION,
    LangChainToolAdapter,
    ToolRecorder,
    build_crew,
    create_crew_llm,
    parse_task_output,
)
from app.schemas import AgentReport, TicketClassification  # noqa: E402


@tool(parse_docstring=True)
def get_site(site_code: str) -> str:
    """A site's role and alarms.

    Args:
        site_code: Site code such as "SITE-SUR-02".
    """
    return f'{{"code":"{site_code}","found":true}}'


def settings(**overrides) -> Settings:
    base = {"openai_api_key": "sk-test", "openai_model": "gpt-test", "deepseek_api_key": "ds"}
    return Settings(_env_file=None, **{**base, **overrides})


def test_telemetry_is_disabled():
    assert os.environ["CREWAI_DISABLE_TELEMETRY"] == "true"
    assert os.environ["OTEL_SDK_DISABLED"] == "true"


def test_adapter_keeps_the_langchain_tool_unchanged_and_records_calls():
    recorder = ToolRecorder()
    adapted = LangChainToolAdapter(get_site, recorder)

    result = adapted.run(site_code="SITE-SUR-02")

    assert adapted.name == "get_site"
    assert adapted.description == get_site.description
    assert adapted.args_schema is get_site.args_schema
    assert result == '{"code":"SITE-SUR-02","found":true}'
    assert [(c.name, c.args) for c in recorder.calls] == [
        ("get_site", {"site_code": "SITE-SUR-02"})
    ]


@pytest.mark.parametrize(
    "provider, model",
    [
        ("openai", "openai/gpt-test"),
        ("deepseek", "deepseek/deepseek-flash"),
        ("ollama", "ollama/qwen3:4b"),
    ],
)
def test_llm_per_provider(provider, model):
    llm = create_crew_llm(settings(llm_provider=provider))

    assert llm.model.endswith(model.split("/", 1)[1])


def test_crew_mirrors_the_langgraph_steps():
    config = settings(agent_max_model_calls=4)
    llm = create_crew_llm(config)

    crew, triage, investigate, report = build_crew(
        "Distribuidora Del Sur sin internet.", None, llm, [get_site], ToolRecorder(), config
    )

    assert [t.agent.role for t in crew.tasks] == [
        "NOC triage engineer",
        "NOC investigation engineer",
        "NOC incident reporter",
    ]
    assert triage.output_pydantic is TicketClassification
    assert report.output_pydantic is AgentReport
    assert investigate.context == [triage]
    assert report.context == [triage, investigate]
    assert [t.name for t in investigate.agent.tools] == ["get_site"]
    assert investigate.agent.max_iter == 4
    assert "<ticket>\nDistribuidora Del Sur sin internet.\n</ticket>" in investigate.description
    assert CREW_PROMPT_VERSION.startswith("crew:classify_v3")


def test_deepseek_tasks_ask_for_json_in_the_answer_instead_of_response_format():
    config = settings(llm_provider="deepseek")

    _, triage, _, report = build_crew(
        "Ticket", None, create_crew_llm(config), [get_site], ToolRecorder(), config
    )

    assert triage.output_pydantic is None and report.output_pydantic is None
    assert '"severity_reason"' in report.expected_output


def test_raw_json_answers_are_parsed_with_extra_keys_dropped():
    from types import SimpleNamespace

    from tests.conftest import SAMPLE_CLASSIFICATION

    payload = json.dumps({**SAMPLE_CLASSIFICATION, "type": "json_object"})
    raw = f"```json\n{payload}\n```"

    parsed = parse_task_output(SimpleNamespace(pydantic=None, raw=raw), TicketClassification)

    assert parsed.category.value == "connectivity_loss"
