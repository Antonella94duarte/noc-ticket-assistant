import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    """A ticket and its analysis in one row, so reading both is a single query with no joins."""

    __tablename__ = "tickets"
    __table_args__ = (
        # The same input analyzed with the same prompt is served from this row instead of calling
        # the model again. A new prompt version produces a new row.
        UniqueConstraint("content_hash", "prompt_version", name="uq_tickets_content_hash_prompt"),
        # The listing filters by category/severity and always sorts newest first.
        Index("ix_tickets_category_created_at", "category", "created_at"),
        Index("ix_tickets_severity_created_at", "severity", "created_at"),
        Index("ix_tickets_created_at", "created_at"),
    )
    # Fetch server-generated values (created_at) with RETURNING in the INSERT itself, instead of
    # a second SELECT after commit.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    ticket_text: Mapped[str] = mapped_column(Text)
    logs: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))

    category: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    # Full LLM output: {"classification": ..., "diagnosis": ...}.
    analysis: Mapped[dict] = mapped_column(JSONB)

    # What produced the analysis and what it cost.
    prompt_version: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    reasoning_tokens: Mapped[int] = mapped_column(Integer)
