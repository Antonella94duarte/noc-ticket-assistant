from pathlib import Path

import pytest

from app.evaluation import EvalCase, load_cases, score
from app.schemas import TicketClassification
from tests.conftest import SAMPLE_CLASSIFICATION

EVAL_SET = Path(__file__).resolve().parents[1] / "data" / "eval" / "classification.jsonl"


def make_case(**overrides) -> EvalCase:
    fields = {
        "id": "case",
        "ticket_text": "El enlace está caído.",
        "logs": None,
        "categories": frozenset({"connectivity_loss"}),
        "severities": frozenset({"critical", "major"}),
    }
    return EvalCase(**{**fields, **overrides})


def classify(**overrides) -> TicketClassification:
    return TicketClassification.model_validate({**SAMPLE_CLASSIFICATION, **overrides})


def test_eval_set_loads_with_valid_labels_and_unique_ids():
    cases = load_cases(EVAL_SET)

    assert len(cases) >= 10
    assert len({c.id for c in cases}) == len(cases)


def test_label_typos_are_rejected(tmp_path):
    bad = tmp_path / "cases.jsonl"
    bad.write_text(
        '{"id": "x", "ticket_text": "t", "logs": null, '
        '"expected": {"category": "conectivity_loss", "severity": "major"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_cases(bad)


def test_any_accepted_value_counts_as_correct():
    result = score(make_case(), classify(severity="major"))

    assert result.category_ok and result.severity_ok and result.passed


def test_wrong_severity_fails_the_case():
    result = score(make_case(), classify(severity="minor"))

    assert result.category_ok
    assert not result.severity_ok
    assert not result.passed


def test_questions_expectation_is_checked_only_when_labeled():
    unlabeled = score(make_case(), classify(missing_information=[]))
    expects = score(make_case(expects_questions=True), classify(missing_information=[]))

    assert unlabeled.questions_ok is None and unlabeled.passed
    assert expects.questions_ok is False and not expects.passed
