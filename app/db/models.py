import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
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


# --- Network inventory and alarms -------------------------------------------------------------
# Synthetic data the agents query through tools (app/tools). Loaded by app/db/seed.py.

ALARM_SEVERITIES = ("critical", "major", "minor", "warning")


class Site(Base):
    __tablename__ = "sites"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))  # core, aggregation, datacenter, access
    region: Mapped[str] = mapped_column(String(64))
    customers_served: Mapped[int] = mapped_column(Integer)
    backup_power_hours: Mapped[float | None] = mapped_column(Float)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (Index("ix_devices_site_code", "site_code"),)

    hostname: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_code: Mapped[str] = mapped_column(ForeignKey("sites.code"))
    role: Mapped[str] = mapped_column(String(32))
    vendor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    # The other half of a redundant pair, when there is one.
    redundancy_peer: Mapped[str | None] = mapped_column(ForeignKey("devices.hostname"))


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (
        Index("ix_links_a_device", "a_device"),
        Index("ix_links_b_device", "b_device"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24))  # backbone, uplink, bundle_member, transit, ...
    a_device: Mapped[str] = mapped_column(ForeignKey("devices.hostname"))
    a_interface: Mapped[str] = mapped_column(String(48))
    # Null when the far end isn't ours (e.g. a transit provider); described in b_description.
    b_device: Mapped[str | None] = mapped_column(ForeignKey("devices.hostname"))
    b_interface: Mapped[str | None] = mapped_column(String(48))
    b_description: Mapped[str | None] = mapped_column(String(128))
    bundle: Mapped[str | None] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(8))  # up, down


class Circuit(Base):
    __tablename__ = "circuits"
    __table_args__ = (Index("ix_circuits_access_device", "access_device"),)

    circuit_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(128))
    service: Mapped[str] = mapped_column(String(32))  # internet, l2vpn, colocation, voice
    site_code: Mapped[str] = mapped_column(ForeignKey("sites.code"))
    access_device: Mapped[str] = mapped_column(ForeignKey("devices.hostname"))
    access_interface: Mapped[str] = mapped_column(String(48))


class Alarm(Base):
    __tablename__ = "alarms"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('critical', 'major', 'minor', 'warning')", name="ck_alarms_severity"
        ),
        # Agents almost always ask for *active* alarms of a site or a device: partial indexes
        # keep those lookups small no matter how much alarm history accumulates.
        Index(
            "ix_alarms_active_site",
            "site_code",
            "raised_at",
            postgresql_where=text("cleared_at IS NULL"),
        ),
        Index(
            "ix_alarms_active_device",
            "device_hostname",
            postgresql_where=text("cleared_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_code: Mapped[str] = mapped_column(ForeignKey("sites.code"))
    # Null for site-level alarms (commercial power, shelter temperature).
    device_hostname: Mapped[str | None] = mapped_column(ForeignKey("devices.hostname"))
    interface: Mapped[str | None] = mapped_column(String(48))
    alarm_type: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
