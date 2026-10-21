"""Orchestrates the LLM calls that analyze a ticket.

Phase 1 runs a single call (classify and extract). Phase 3 chains a second call that uses this
result to diagnose the incident and draft the customer reply.
"""

from dataclasses import dataclass

from app.llm.client import LLMClient, LLMResult
from app.llm.prompt_builder import CLASSIFY_PROMPT_VERSION, build_classify_messages
from app.schemas import TicketAnalyzeRequest, TicketClassification


@dataclass(frozen=True)
class Analysis:
    classification: TicketClassification
    prompt_version: str
    llm: LLMResult  # model, reasoning effort and token usage of the call


class TicketAnalyzer:
    prompt_version = CLASSIFY_PROMPT_VERSION

    def __init__(self, llm: LLMClient):
        self._llm = llm

    def analyze(self, request: TicketAnalyzeRequest) -> Analysis:
        messages = build_classify_messages(request.ticket_text, request.logs)
        result = self._llm.parse(messages, TicketClassification)
        return Analysis(
            classification=result.parsed, prompt_version=self.prompt_version, llm=result
        )
