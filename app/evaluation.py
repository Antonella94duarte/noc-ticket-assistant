"""Score analyses against a labeled set of synthetic tickets.

Used by scripts/evaluate.py to compare prompt versions or settings with numbers instead of a few
hand-checked examples. An expected value may be a list when more than one answer is defensible
under the rubric, so ambiguity in the labels isn't counted as a model error. Optional labels
(questions, customer reply) are only checked on the cases that have them.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.schemas import IncidentCategory, Severity, TicketClassification, TicketDiagnosis


@dataclass(frozen=True)
class EvalCase:
    id: str
    ticket_text: str
    logs: str | None
    categories: frozenset[str]
    severities: frozenset[str]
    expects_questions: bool | None = None
    expects_customer_reply: bool | None = None


@dataclass(frozen=True)
class CaseResult:
    case: EvalCase
    classification: TicketClassification
    category_ok: bool
    severity_ok: bool
    questions_ok: bool | None  # None when the case has no expectation about questions
    reply_ok: bool | None = None  # None when unlabeled or the diagnosis wasn't run

    @property
    def passed(self) -> bool:
        return (
            self.category_ok
            and self.severity_ok
            and self.questions_ok is not False
            and self.reply_ok is not False
        )


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
                expects_customer_reply=expected.get("customer_reply"),
            )
        )
    return cases


def score(
    case: EvalCase,
    classification: TicketClassification,
    diagnosis: TicketDiagnosis | None = None,
) -> CaseResult:
    questions_ok = None
    if case.expects_questions is not None:
        questions_ok = bool(classification.missing_information) == case.expects_questions
    reply_ok = None
    if diagnosis is not None and case.expects_customer_reply is not None:
        reply_ok = bool(diagnosis.customer_reply) == case.expects_customer_reply
    return CaseResult(
        case=case,
        classification=classification,
        category_ok=classification.category.value in case.categories,
        severity_ok=classification.severity.value in case.severities,
        questions_ok=questions_ok,
        reply_ok=reply_ok,
    )


# --- Runbook retrieval ------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    lang: str
    style: str
    query: str
    expected: frozenset[str]


@dataclass(frozen=True)
class RetrievalResult:
    case: RetrievalCase
    ranked_runbooks: list[str]  # unique runbook ids, best first

    @property
    def rank(self) -> int | None:
        """1-based position of the first expected runbook, or None if it wasn't retrieved."""
        for position, runbook in enumerate(self.ranked_runbooks, start=1):
            if runbook in self.case.expected:
                return position
        return None

    def hit_at(self, k: int) -> bool:
        return self.rank is not None and self.rank <= k

    @property
    def reciprocal_rank(self) -> float:
        return 1 / self.rank if self.rank else 0.0


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            cases.append(
                RetrievalCase(
                    id=raw["id"],
                    lang=raw["lang"],
                    style=raw["style"],
                    query=raw["query"],
                    expected=frozenset(raw["expected"]),
                )
            )
    return cases


def unique_in_order(runbooks: list[str]) -> list[str]:
    """Several sections of one runbook count as one result at its best position."""
    return list(dict.fromkeys(runbooks))
