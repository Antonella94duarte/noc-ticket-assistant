"""Orchestrates the chained LLM calls that analyze a ticket.

1. Classify: category, severity, entities and open questions (few-shot, cheap and focused).
2. Diagnose: takes the classification as input and reasons step by step to probable causes,
   checks, actions and a draft customer reply.

Splitting the work keeps each prompt short and focused, lets each step be tested and versioned on
its own, and gives the diagnosis a structured starting point instead of raw text.
"""

from dataclasses import dataclass

from app.llm.client import LLMClient, LLMResult
from app.llm.prompt_builder import (
    CLASSIFY_PROMPT_VERSION,
    DIAGNOSE_PROMPT_VERSION,
    build_classify_messages,
    build_diagnose_messages,
)
from app.schemas import TicketAnalyzeRequest, TicketClassification, TicketDiagnosis


@dataclass(frozen=True)
class Analysis:
    classification: TicketClassification
    diagnosis: TicketDiagnosis
    prompt_version: str
    model: str
    reasoning_effort: str | None
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int


class TicketAnalyzer:
    # Stored with each analysis and part of the cache key: changing either prompt yields a new
    # analysis instead of a stale cached one.
    prompt_version = f"{CLASSIFY_PROMPT_VERSION}+{DIAGNOSE_PROMPT_VERSION}"

    def __init__(self, llm: LLMClient):
        self._llm = llm

    def analyze(self, request: TicketAnalyzeRequest) -> Analysis:
        classified = self._llm.parse(
            build_classify_messages(request.ticket_text, request.logs), TicketClassification
        )
        diagnosed = self._llm.parse(
            build_diagnose_messages(request.ticket_text, request.logs, classified.parsed),
            TicketDiagnosis,
        )
        return Analysis(
            classification=classified.parsed,
            diagnosis=diagnosed.parsed,
            prompt_version=self.prompt_version,
            model=classified.model,
            reasoning_effort=classified.reasoning_effort,
            **_sum_usage(classified, diagnosed),
        )


def _sum_usage(*results: LLMResult) -> dict[str, int]:
    return {
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "reasoning_tokens": sum(r.reasoning_tokens for r in results),
    }
