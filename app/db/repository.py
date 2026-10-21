"""Database access for tickets."""

import uuid

from sqlalchemy import ColumnElement, Row, func, select
from sqlalchemy.orm import Session

from app.db.models import Ticket

EXCERPT_LENGTH = 120


def get_ticket(db: Session, ticket_id: uuid.UUID) -> Ticket | None:
    return db.get(Ticket, ticket_id)


def find_by_content(db: Session, content_hash: str, prompt_version: str) -> Ticket | None:
    stmt = select(Ticket).where(
        Ticket.content_hash == content_hash, Ticket.prompt_version == prompt_version
    )
    return db.scalars(stmt).one_or_none()


def _filters(category: str | None, severity: str | None) -> list[ColumnElement[bool]]:
    conditions = []
    if category:
        conditions.append(Ticket.category == category)
    if severity:
        conditions.append(Ticket.severity == severity)
    return conditions


def list_tickets(
    db: Session,
    *,
    category: str | None = None,
    severity: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Row], int]:
    """Return one page of ticket summaries (newest first) and the total matching count.

    Only the columns the listing shows are selected (the analysis JSONB isn't read and the text is
    cut in SQL). The total comes from a window function in the same query instead of a separate
    COUNT.
    """
    conditions = _filters(category, severity)
    stmt = (
        select(
            Ticket.id,
            Ticket.created_at,
            Ticket.category,
            Ticket.severity,
            func.left(Ticket.ticket_text, EXCERPT_LENGTH).label("ticket_excerpt"),
            func.count().over().label("total"),
        )
        .where(*conditions)
        .order_by(Ticket.created_at.desc(), Ticket.id.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = db.execute(stmt).all()
    if rows:
        return rows, rows[0].total
    if offset == 0:
        return [], 0
    # Past the last page there are no rows to carry the window total, so count separately.
    count_stmt = select(func.count()).select_from(Ticket).where(*conditions)
    return [], db.scalar(count_stmt) or 0
