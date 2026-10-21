import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.db import repository
from app.db.session import get_db
from app.llm.client import LLMClient, get_llm_client
from app.schemas import (
    HealthResponse,
    IncidentCategory,
    Severity,
    TicketAnalyzeRequest,
    TicketAnalyzeResponse,
    TicketDetail,
    TicketPage,
    TicketSummary,
)
from app.services import tickets as ticket_service
from app.services.analyzer import TicketAnalyzer

logger = logging.getLogger(__name__)

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1", tags=["tickets"])


@health_router.get("/health", response_model=HealthResponse)
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Report API status and whether the database answers a trivial query."""
    try:
        db.execute(text("SELECT 1"))
        database = "ok"
    except SQLAlchemyError:
        logger.exception("Database health check failed")
        database = "unavailable"

    if database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database=database, version=__version__)
    return HealthResponse(status="ok", database=database, version=__version__)


def get_analyzer(llm: LLMClient = Depends(get_llm_client)) -> TicketAnalyzer:
    return TicketAnalyzer(llm)


@api_router.post(
    "/tickets/analyze",
    response_model=TicketAnalyzeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Identical ticket already analyzed; stored analysis."}},
)
def analyze_ticket(
    request: TicketAnalyzeRequest,
    response: Response,
    db: Session = Depends(get_db),
    analyzer: TicketAnalyzer = Depends(get_analyzer),
) -> TicketAnalyzeResponse:
    """Classify a ticket, extract its entities and list what to ask the customer.

    An identical ticket (same text and logs, same prompt version) returns the stored analysis
    with 200 instead of calling the model again. LLM errors are turned into 502/503 responses
    by the handlers registered in app.main.
    """
    ticket, cached = ticket_service.analyze_ticket(db, analyzer, request)
    if cached:
        response.status_code = status.HTTP_200_OK
    detail = ticket_service.to_detail(ticket)
    return TicketAnalyzeResponse(**detail.model_dump(), cached=cached)


@api_router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: uuid.UUID, db: Session = Depends(get_db)) -> TicketDetail:
    ticket = repository.get_ticket(db, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket_service.to_detail(ticket)


@api_router.get("/tickets", response_model=TicketPage)
def list_tickets(
    category: IncidentCategory | None = None,
    severity: Severity | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> TicketPage:
    """List tickets newest first, optionally filtered by category and severity."""
    rows, total = repository.list_tickets(
        db,
        category=category.value if category else None,
        severity=severity.value if severity else None,
        limit=limit,
        offset=offset,
    )
    items = [TicketSummary.model_validate(row, from_attributes=True) for row in rows]
    return TicketPage(items=items, total=total, limit=limit, offset=offset)
