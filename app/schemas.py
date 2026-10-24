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
        description="Questions about data still missing to diagnose: for the customer, or for the "
        "NOC team when the ticket is an internal alarm."
    )


class Likelihood(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProbableCause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cause: str
    likelihood: Likelihood
    evidence: str = Field(description="What in the ticket or logs supports it, or what is assumed.")


class DiagnosticStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str = Field(description="What the engineer should check or do.")
    command: str | None = Field(description="CLI command to run, or null if not applicable.")
    expected_result: str = Field(description="What result confirms or rules out a cause.")


class TicketDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Field order matters: the model writes the JSON in schema order, so the reasoning is produced
    # before the conclusions that depend on it.
    reasoning: list[str] = Field(
        description="Step-by-step reasoning from the evidence to the probable causes."
    )
    probable_causes: list[ProbableCause] = Field(description="Most likely first.")
    diagnostic_steps: list[DiagnosticStep] = Field(description="In the order to run them.")
    recommended_actions: list[str] = Field(
        description="Immediate actions: mitigation, escalation, field dispatch."
    )
    customer_reply: str | None = Field(
        description="Draft reply to the customer, or null when no customer reported the incident "
        "(internal monitoring alarm)."
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
    diagnosis: TicketDiagnosis | None = Field(
        description="Null for tickets analyzed before the diagnosis step existed."
    )
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


# --- Agent analysis (app/agents) ---


class AgentReport(TicketDiagnosis):
    """The agent's diagnosis plus a severity re-assessed with the investigation's evidence."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity = Field(description="Severity re-assessed with the evidence.")
    severity_reason: str = Field(description="One sentence citing the evidence for the severity.")


class ToolCallRecord(BaseModel):
    name: str
    args: dict
    result: str = Field(description="What the tool returned to the model (compact JSON).")


class AgentAnalysis(BaseModel):
    classification: TicketClassification
    findings: str = Field(description="The investigator's summary of what it checked and found.")
    diagnosis: AgentReport
    tool_calls: list[ToolCallRecord]
    investigation_model_calls: int
    limit_reached: bool = Field(
        description="True when the investigator hit its tool or model call limit."
    )
    prompt_version: str
    usage_by_model: dict[str, TokenUsage]
    latency_seconds: float


class BaselineAnalysis(BaseModel):
    """The chained baseline (classify, then diagnose; no tools) run through LangChain models."""

    classification: TicketClassification
    diagnosis: TicketDiagnosis
    prompt_version: str
    usage_by_model: dict[str, TokenUsage]
    latency_seconds: float
