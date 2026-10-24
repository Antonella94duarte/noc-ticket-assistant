import itertools
import json
from contextlib import nullcontext

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.agents.graph import AGENT_PROMPT_VERSION, build_agent_graph, run_agent_analysis
from app.config import Settings
from app.db.seed import load_network_seed
from app.schemas import TicketClassification, TicketDiagnosis
from app.tools.langchain_tools import build_network_tools
from tests.conftest import SAMPLE_CLASSIFICATION, SAMPLE_DIAGNOSIS

TICKET = "Desde las 07:45 el cliente Distribuidora Del Sur no tiene internet."


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


class ScriptedModel(GenericFakeChatModel):
    """Plays a fixed sequence of agent turns and returns canned structured outputs.

    `structured_inputs` records what the triage and report steps were sent.
    """

    structured: dict = {}
    structured_inputs: list = []

    def bind_tools(self, tools, **kwargs):
        return self

    def with_structured_output(self, schema, **kwargs):
        def answer(model_input):
            self.structured_inputs.append((schema, model_input))
            return self.structured[schema]

        return RunnableLambda(answer)


class BrokenModel(ScriptedModel):
    """A provider that is down: every call fails."""

    def _generate(self, *args, **kwargs):
        raise ConnectionError("provider unavailable")

    def with_structured_output(self, schema, **kwargs):
        def fail(_):
            raise ConnectionError("provider unavailable")

        return RunnableLambda(fail)


def scripted(turns) -> ScriptedModel:
    return ScriptedModel(
        messages=iter(turns),
        structured={
            TicketClassification: TicketClassification.model_validate(SAMPLE_CLASSIFICATION),
            TicketDiagnosis: TicketDiagnosis.model_validate(SAMPLE_DIAGNOSIS),
        },
        structured_inputs=[],
    )


@pytest.fixture
def tools(db_session):
    load_network_seed(db_session)
    return build_network_tools(lambda: nullcontext(db_session))


def settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def run(models, tools, config=None, providers=None):
    config = config or settings()
    providers = providers or ["openai"] * len(models)
    graph = build_agent_graph(models, providers, tools, config)
    return run_agent_analysis(graph, TICKET, settings=config)


def test_agent_investigates_with_tools_and_reports(tools):
    model = scripted(
        [
            tool_call("find_circuits", {"query": "Distribuidora"}, "c1"),
            tool_call("get_active_alarms", {"site_code": "SITE-SUR-02"}, "c2"),
            AIMessage(content="- SUR-2210 en rtr-sur-02 Gi0/0/3: alarma 11 link_down."),
        ]
    )

    analysis = run([model], tools)

    assert [c.name for c in analysis.tool_calls] == ["find_circuits", "get_active_alarms"]
    circuit = json.loads(analysis.tool_calls[0].result)["circuits"][0]
    assert circuit["circuit_id"] == "SUR-2210"
    assert analysis.findings.startswith("- SUR-2210")
    assert analysis.diagnosis.probable_causes[0].cause == "Fiber cut"
    assert analysis.investigation_model_calls == 3
    assert analysis.limit_reached is False
    assert analysis.prompt_version == AGENT_PROMPT_VERSION


def test_report_receives_findings_and_raw_tool_results(tools):
    model = scripted(
        [
            tool_call("find_circuits", {"query": "Distribuidora"}, "c1"),
            AIMessage(content="Hallazgo: puerto Gi0/0/3 caído."),
        ]
    )

    run([model], tools)

    (schema, report_messages) = model.structured_inputs[-1]
    assert schema is TicketDiagnosis
    request = report_messages[-1]["content"]
    assert "<investigation>\nHallazgo: puerto Gi0/0/3 caído." in request
    assert '"circuit_id":"SUR-2210"' in request


def test_triage_uses_the_few_shot_classification_prompt(tools):
    model = scripted([AIMessage(content="Nada que investigar.")])

    run([model], tools)

    (schema, triage_messages) = model.structured_inputs[0]
    assert schema is TicketClassification
    assert triage_messages[0]["role"] == "system"
    assert TICKET in triage_messages[-1]["content"]


def test_tool_call_limit_blocks_further_tools(tools):
    model = scripted(
        [
            tool_call("get_site", {"site_code": "SITE-SUR-02"}, "c1"),
            tool_call("get_active_alarms", {"site_code": "SITE-SUR-02"}, "c2"),
            AIMessage(content="Concluyo con lo que tengo."),
        ]
    )

    analysis = run([model], tools, settings(agent_max_tool_calls=1))

    first, second = analysis.tool_calls
    assert json.loads(first.result)["found"] is True
    assert "total_active" not in second.result  # blocked: never reached the database
    assert analysis.limit_reached is True
    assert analysis.findings == "Concluyo con lo que tengo."


def test_model_call_limit_stops_a_looping_agent(tools):
    looping = (tool_call("get_active_alarms", {"limit": 1}, f"c{i}") for i in itertools.count())
    model = scripted(looping)

    analysis = run([model], tools, settings(agent_max_model_calls=2))

    assert analysis.investigation_model_calls == 2
    assert analysis.limit_reached is True
    assert analysis.diagnosis is not None  # the report still runs on what was found


def test_fallback_model_takes_over_when_the_primary_fails(tools):
    primary = BrokenModel(messages=iter([]), structured={}, structured_inputs=[])
    backup = scripted(
        [
            tool_call("get_site", {"site_code": "SITE-ESTE-04"}, "c1"),
            AIMessage(content="Hallazgos del modelo de respaldo."),
        ]
    )

    analysis = run([primary, backup], tools, providers=["openai", "ollama"])

    assert analysis.findings == "Hallazgos del modelo de respaldo."
    assert [c.name for c in analysis.tool_calls] == ["get_site"]
    assert analysis.classification.category.value == "connectivity_loss"
