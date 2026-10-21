import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    version: str


# --- Ticket analysis: request ---


class TicketAnalyzeRequest(BaseModel):
    ticket_text: str = Field(min_length=10, max_length=5000, description="Ticket as written.")
    logs: str | None = Field(
        default=None, max_length=20000, description="Optional device logs or alarms."
    )


# --- Ticket analysis: LLM output ---
# These models are sent to the model as a JSON schema (Structured Outputs), so every field is
# required and has no default: optional values are expressed as nullable or as empty lists.


class IncidentCategory(str, Enum):
    CONNECTIVITY_LOSS = "connectivity_loss"
    LATENCY_PACKET_LOSS = "latency_packet_loss"
    HARDWARE_FAILURE = "hardware_failure"
    CONFIGURATION_ERROR = "configuration_error"
    POWER_ALARM = "power_alarm"
    OTHER = "other"


class Severity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"


class ExtractedEntities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sites: list[str] = Field(description="Site names or codes mentioned.")
    devices: list[str] = Field(description="Device hostnames or models mentioned.")
    interfaces: list[str] = Field(description="Interfaces or ports, e.g. ge-0/0/1.")
    ip_addresses: list[str] = Field(description="IPv4 or IPv6 addresses mentioned.")
    event_time: str | None = Field(description="When the event started, as written, or null.")


class TicketClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: IncidentCategory
    severity: Severity
    severity_reason: str = Field(description="One sentence justifying the severity.")
    entities: ExtractedEntities
    missing_information: list[str] = Field(
        description="Questions to ask the customer when data needed to diagnose is missing."
    )


# --- Ticket analysis: API response ---


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int = Field(description="Includes reasoning_tokens.")
    reasoning_tokens: int
    total_tokens: int


class TicketDetail(BaseModel):
    id: uuid.UUID
    created_at: datetime
    ticket_text: str
    logs: str | None
    classification: TicketClassification
    model: str
    reasoning_effort: str | None
    prompt_version: str
    usage: TokenUsage


class TicketAnalyzeResponse(TicketDetail):
    cached: bool = Field(
        description="True when an identical ticket was already analyzed with this prompt version "
        "and the stored analysis was returned without calling the model."
    )


class TicketSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    category: IncidentCategory
    severity: Severity
    ticket_excerpt: str


class TicketPage(BaseModel):
    items: list[TicketSummary]
    total: int
    limit: int
    offset: int
