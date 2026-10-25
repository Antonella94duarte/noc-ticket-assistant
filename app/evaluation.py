"""Score analyses against a labeled set of synthetic tickets.

Used by scripts/evaluate.py to compare prompt versions or settings with numbers instead of a few
hand-checked examples. An expected value may be a list when more than one answer is defensible
under the rubric, so ambiguity in the labels isn't counted as a model error. Optional labels
(questions, customer reply) are only checked on the cases that have them.
"""

import json
import re
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


# --- Agent vs baseline (scripts/evaluate_agents.py) ---------------------------------------------


@dataclass(frozen=True)
class AgentCase:
    """A ticket about the synthetic network snapshot, labeled with what a good analysis finds.

    `evidence_any`: strings of which at least one must appear in the top probable cause, such as
    the interface or alarm that explains the incident; most can only be found with the tools.
    `runbooks`: runbook IDs that apply; checked only for systems that can search runbooks.
    """

    id: str
    ticket_text: str
    logs: str | None
    categories: frozenset[str]
    severities: frozenset[str]
    evidence_any: tuple[str, ...] = ()
    runbooks: frozenset[str] = frozenset()
    expects_questions: bool | None = None
    expects_customer_reply: bool | None = None


@dataclass(frozen=True)
class AgentScore:
    category_ok: bool
    severity_ok: bool  # the system's final severity
    root_cause_ok: bool | None  # None when the case has no evidence label
    runbook_ok: bool | None  # None when no runbook applies or the system can't search them
    reply_ok: bool | None
    questions_ok: bool | None


def load_agent_cases(path: Path) -> list[AgentCase]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        expected = raw["expected"]
        cases.append(
            AgentCase(
                id=raw["id"],
                ticket_text=raw["ticket_text"],
                logs=raw["logs"],
                categories=_as_set(expected["category"], IncidentCategory),
                severities=_as_set(expected["severity"], Severity),
                evidence_any=tuple(expected.get("evidence_any", ())),
                runbooks=frozenset(expected.get("runbooks", ())),
                expects_questions=expected.get("expects_questions"),
                expects_customer_reply=expected.get("customer_reply"),
            )
        )
    return cases


def top_cause_text(diagnosis: TicketDiagnosis) -> str:
    if not diagnosis.probable_causes:
        return ""
    cause = diagnosis.probable_causes[0]
    return f"{cause.cause} {cause.evidence}"


def cited_runbooks(diagnosis: TicketDiagnosis) -> set[str]:
    text = " ".join(
        [s.action for s in diagnosis.diagnostic_steps] + list(diagnosis.recommended_actions)
    )
    return set(re.findall(r"RB-\d{3}", text))


def score_agent_run(
    case: AgentCase,
    classification: TicketClassification,
    diagnosis: TicketDiagnosis,
    final_severity: str,
    can_search_runbooks: bool,
) -> AgentScore:
    cause = top_cause_text(diagnosis).lower()
    root_cause_ok = (
        any(e.lower() in cause for e in case.evidence_any) if case.evidence_any else None
    )
    runbook_ok = (
        bool(cited_runbooks(diagnosis) & case.runbooks)
        if case.runbooks and can_search_runbooks
        else None
    )
    reply_ok = (
        bool(diagnosis.customer_reply) == case.expects_customer_reply
        if case.expects_customer_reply is not None
        else None
    )
    questions_ok = (
        bool(classification.missing_information) == case.expects_questions
        if case.expects_questions is not None
        else None
    )
    return AgentScore(
        category_ok=classification.category.value in case.categories,
        severity_ok=final_severity in case.severities,
        root_cause_ok=root_cause_ok,
        runbook_ok=runbook_ok,
        reply_ok=reply_ok,
        questions_ok=questions_ok,
    )
