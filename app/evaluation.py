"""Score classifications against a labeled set of synthetic tickets.

Used by scripts/evaluate.py to compare prompt versions or settings with numbers instead of a few
hand-checked examples. An expected value may be a list when more than one answer is defensible
under the rubric, so ambiguity in the labels isn't counted as a model error.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas import IncidentCategory, Severity, TicketClassification


@dataclass(frozen=True)
class EvalCase:
    id: str
    ticket_text: str
    logs: str | None
    categories: frozenset[str]
    severities: frozenset[str]
    expects_questions: bool | None = None


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    classification: TicketClassification
    category_ok: bool
    severity_ok: bool
    questions_ok: bool | None  # None when the case has no expectation about questions

    @property
    def passed(self) -> bool:
        return self.category_ok and self.severity_ok and self.questions_ok is not False


def _as_set(value: str | list[str], allowed: type) -> frozenset[str]:
    values = [value] if isinstance(value, str) else value
    for v in values:
        allowed(v)  # raises ValueError on a typo in the labels
    return frozenset(values)


def load_cases(path: Path) -> list[EvalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        expected = raw["expected"]
        cases.append(
            EvalCase(
                id=raw["id"],
                ticket_text=raw["ticket_text"],
                logs=raw["logs"],
                categories=_as_set(expected["category"], IncidentCategory),
                severities=_as_set(expected["severity"], Severity),
                expects_questions=expected.get("expects_questions"),
            )
        )
    return cases


def score(case: EvalCase, classification: TicketClassification) -> CaseResult:
    questions_ok = None
    if case.expects_questions is not None:
        questions_ok = bool(classification.missing_information) == case.expects_questions
    return CaseResult(
        case=case,
        classification=classification,
        category_ok=classification.category.value in case.categories,
        severity_ok=classification.severity.value in case.severities,
        questions_ok=questions_ok,
    )
