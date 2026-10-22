"""Ticket use cases: analyze with caching, and map stored tickets to API responses."""

import hashlib
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import repository
from app.db.models import Ticket
from app.schemas import (
    TicketAnalyzeRequest,
    TicketClassification,
    TicketDetail,
    TicketDiagnosis,
    TokenUsage,
)
from app.services.analyzer import TicketAnalyzer

logger = logging.getLogger(__name__)


def _normalize(text: str | None) -> str:
    """Ignore differences that don't change meaning: line endings and edge whitespace."""
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def content_hash(ticket_text: str, logs: str | None) -> str:
    # The separator keeps "ab" + "c" and "a" + "bc" from hashing the same.
    payload = f"{_normalize(ticket_text)}\x00{_normalize(logs)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def analyze_ticket(
    db: Session, analyzer: TicketAnalyzer, request: TicketAnalyzeRequest
) -> tuple[Ticket, bool]:
    """Return the stored analysis for this ticket, creating it if needed.

    The second value is True when the analysis came from the database instead of the model.
    """
    digest = content_hash(request.ticket_text, request.logs)
    existing = repository.find_by_content(db, digest, analyzer.prompt_version)
    if existing:
        return existing, True

    analysis = analyzer.analyze(request)
    classification = analysis.classification
    ticket = Ticket(
        ticket_text=request.ticket_text,
        logs=request.logs,
        content_hash=digest,
        category=classification.category.value,
        severity=classification.severity.value,
        analysis={
            "classification": classification.model_dump(mode="json"),
            "diagnosis": analysis.diagnosis.model_dump(mode="json"),
        },
        prompt_version=analysis.prompt_version,
        model=analysis.model,
        reasoning_effort=analysis.reasoning_effort,
        input_tokens=analysis.input_tokens,
        output_tokens=analysis.output_tokens,
        reasoning_tokens=analysis.reasoning_tokens,
    )
    db.add(ticket)
    try:
        db.commit()
    except IntegrityError:
        # An identical request finished first and stored its analysis: use that one.
        db.rollback()
        existing = repository.find_by_content(db, digest, analyzer.prompt_version)
        if existing is None:
            raise
        logger.info("Concurrent analysis of the same ticket; returning the stored one")
        return existing, True
    return ticket, False


def to_detail(ticket: Ticket) -> TicketDetail:
    # Tickets analyzed before the diagnosis step have only the classification.
    diagnosis = ticket.analysis.get("diagnosis")
    return TicketDetail(
        id=ticket.id,
        created_at=ticket.created_at,
        ticket_text=ticket.ticket_text,
        logs=ticket.logs,
        classification=TicketClassification.model_validate(ticket.analysis["classification"]),
        diagnosis=TicketDiagnosis.model_validate(diagnosis) if diagnosis else None,
        model=ticket.model,
        reasoning_effort=ticket.reasoning_effort,
        prompt_version=ticket.prompt_version,
        usage=TokenUsage(
            input_tokens=ticket.input_tokens,
            output_tokens=ticket.output_tokens,
            reasoning_tokens=ticket.reasoning_tokens,
            total_tokens=ticket.input_tokens + ticket.output_tokens,
        ),
    )
