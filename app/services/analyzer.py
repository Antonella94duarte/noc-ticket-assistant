"""Orchestrates the LLM calls that analyze a ticket.

Phase 1 runs a single call (classify and extract). Phase 3 chains a second call that uses this
result to diagnose the incident and draft the customer reply.
"""

from app.llm.client import LLMClient
from app.llm.prompt_builder import CLASSIFY_PROMPT_VERSION, build_classify_messages
from app.schemas import (
    TicketAnalysisResponse,
    TicketAnalyzeRequest,
    TicketClassification,
    TokenUsage,
)


class TicketAnalyzer:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def analyze(self, request: TicketAnalyzeRequest) -> TicketAnalysisResponse:
        messages = build_classify_messages(request.ticket_text, request.logs)
        result = self._llm.parse(messages, TicketClassification)
        return TicketAnalysisResponse(
            classification=result.parsed,
            model=result.model,
            reasoning_effort=result.reasoning_effort,
            prompt_version=CLASSIFY_PROMPT_VERSION,
            usage=TokenUsage(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                reasoning_tokens=result.reasoning_tokens,
                total_tokens=result.total_tokens,
            ),
        )
