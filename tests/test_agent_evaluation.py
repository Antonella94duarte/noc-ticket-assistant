import importlib.util
from pathlib import Path

import pytest

from app.agents.baseline import BASELINE_PROMPT_VERSION, Baseline
from app.config import Settings
from app.evaluation import AgentCase, cited_runbooks, load_agent_cases, score_agent_run
from app.llm.pricing import estimate_cost
from app.schemas import TicketClassification, TicketDiagnosis
from tests.conftest import SAMPLE_CLASSIFICATION, SAMPLE_DIAGNOSIS
from tests.test_agent_graph import scripted

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "eval" / "agent_cases.jsonl"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "evaluate_agents", ROOT / "scripts" / "evaluate_agents.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_case(**overrides) -> AgentCase:
    fields = {
        "id": "case",
        "ticket_text": "Distribuidora Del Sur sin internet.",
        "logs": None,
        "categories": frozenset({"connectivity_loss"}),
        "severities": frozenset({"major"}),
        "evidence_any": ("Gi0/0/3",),
        "runbooks": frozenset({"RB-008"}),
        "expects_customer_reply": True,
    }
    return AgentCase(**{**fields, **overrides})


def diagnosis(
    cause: str, evidence: str = "", actions=("Revisar el puerto [RB-008]",), reply="Hola"
):
    return TicketDiagnosis.model_validate(
        {
            **SAMPLE_DIAGNOSIS,
            "probable_causes": [{"cause": cause, "likelihood": "high", "evidence": evidence}],
            "recommended_actions": list(actions),
            "customer_reply": reply,
        }
    )


CLASSIFICATION = TicketClassification.model_validate(SAMPLE_CLASSIFICATION)


# --- The labeled cases ---


def test_cases_load_with_unique_ids():
    cases = load_agent_cases(CASES)

    assert len(cases) == 30
    assert len({c.id for c in cases}) == 30


def test_expected_runbooks_exist():
    existing = {p.name[:6] for p in (ROOT / "data" / "runbooks").glob("RB-*.md")}

    for case in load_agent_cases(CASES):
        assert case.runbooks <= existing, case.id


def test_every_evidence_label_can_be_found_by_the_tools():
    """A label typo would silently make the root-cause metric fail for every system."""
    findable = (ROOT / "data" / "network" / "seed.json").read_text(encoding="utf-8").lower()

    for case in load_agent_cases(CASES):
        if case.evidence_any:
            assert any(e.lower() in findable for e in case.evidence_any), case.id


# --- Scoring ---


def test_root_cause_must_name_the_evidence_in_the_top_cause():
    found = score_agent_run(
        make_case(), CLASSIFICATION, diagnosis("Puerto gi0/0/3 caído"), "major", True
    )
    vague = score_agent_run(
        make_case(), CLASSIFICATION, diagnosis("Falla del acceso"), "major", True
    )

    assert found.root_cause_ok is True  # case-insensitive
    assert vague.root_cause_ok is False


def test_runbooks_are_only_scored_for_systems_that_can_search_them():
    with_search = score_agent_run(make_case(), CLASSIFICATION, diagnosis("x"), "major", True)
    without = score_agent_run(make_case(), CLASSIFICATION, diagnosis("x"), "major", False)
    wrong = score_agent_run(
        make_case(), CLASSIFICATION, diagnosis("x", actions=["Seguir [RB-003]"]), "major", True
    )

    assert with_search.runbook_ok is True
    assert without.runbook_ok is None
    assert wrong.runbook_ok is False


def test_unlabeled_metrics_are_not_scored():
    case = make_case(evidence_any=(), runbooks=frozenset(), expects_customer_reply=None)

    score = score_agent_run(case, CLASSIFICATION, diagnosis("x"), "major", True)

    assert (score.root_cause_ok, score.runbook_ok, score.reply_ok) == (None, None, None)


def test_final_severity_is_what_counts():
    score = score_agent_run(make_case(), CLASSIFICATION, diagnosis("x"), "minor", True)

    assert score.severity_ok is False
    assert score.category_ok is True


def test_cited_runbooks_reads_steps_and_actions():
    d = diagnosis("x", actions=["A [RB-001]", "B [RB-009] y RB-001"])

    assert cited_runbooks(d) == {"RB-001", "RB-009"}


def test_cost_estimates():
    assert estimate_cost("openai", "gpt-6-luna", 1_000_000, 100_000) == pytest.approx(0.15)
    assert estimate_cost("ollama", "qwen3:4b", 50_000, 50_000) == 0.0
    assert estimate_cost("openai", "unknown-model", 1, 1) is None


# --- Baseline and summary ---


def test_baseline_classifies_then_diagnoses_without_tools():
    model = scripted([])
    model.structured[TicketDiagnosis] = TicketDiagnosis.model_validate(SAMPLE_DIAGNOSIS)

    result = Baseline([model], ["openai"], Settings(_env_file=None)).run("Cliente sin internet.")

    assert [schema for schema, _ in model.structured_inputs] == [
        TicketClassification,
        TicketDiagnosis,
    ]
    assert result.prompt_version == BASELINE_PROMPT_VERSION
    assert result.classification.category.value == "connectivity_loss"


def test_summary_counts_errors_as_failures():
    script = load_script()
    ok = {
        "provider": "openai",
        "system": "agent",
        "error": None,
        "scores": {
            "category_ok": True,
            "severity_ok": True,
            "root_cause_ok": None,
            "runbook_ok": None,
            "reply_ok": True,
        },
        "tool_calls": ["get_site"],
        "latency_seconds": 10.0,
        "input_tokens": 1000,
        "output_tokens": 200,
        "cost_usd": 0.0002,
    }
    failed = {
        "provider": "openai",
        "system": "agent",
        "error": "Timeout",
        "scores": {
            "category_ok": False,
            "severity_ok": False,
            "root_cause_ok": False,
            "runbook_ok": None,
            "reply_ok": False,
        },
        "latency_seconds": 60.0,
    }

    table = script.summarize([ok, failed])

    row = table.splitlines()[2]
    assert "| openai | agent | 2 | 1 | 1/2 | 1/2 | 0/1 |" in row
    assert "$0.0002" in row


def test_a_failed_run_only_fails_the_metrics_that_apply():
    script = load_script()
    case = make_case(evidence_any=(), runbooks=frozenset({"RB-008"}))

    baseline = script.failed_scores(case, "baseline")
    with_runbooks = script.failed_scores(case, "agent-runbooks")

    assert baseline["root_cause_ok"] is None  # no evidence label
    assert baseline["runbook_ok"] is None  # the baseline can't search runbooks
    assert with_runbooks["runbook_ok"] is False
