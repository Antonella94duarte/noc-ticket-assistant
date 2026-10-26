"""Ticket triage with a small local model instead of an LLM: zero-shot classification.

A natural language inference (NLI) model scores how well the ticket supports a hypothesis such
as "Este ticket trata sobre una alarma de energía", once per label, and the best-scoring label
wins. Nothing is trained: the labels are written as short descriptions, in Spanish like the
tickets, and the same descriptions are used for every model so the comparison is about models.

Only available with requirements-hf.txt (transformers and torch). Used by
scripts/evaluate_small_models.py to measure how far a ~100-300M parameter model gets compared to
the LLM triage (classify_v3).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.schemas import IncidentCategory, Severity

LABELS_VERSION = "zero_shot_labels_v1"
HYPOTHESIS_TEMPLATE = "Este ticket trata sobre {}."
SEVERITY_TEMPLATE = "El impacto de este incidente es {}."

# Written once from the rubric in the classify prompts, not tuned on the evaluation set.
CATEGORY_LABELS: dict[IncidentCategory, str] = {
    IncidentCategory.CONNECTIVITY_LOSS: "una pérdida de conectividad o un servicio caído",
    IncidentCategory.LATENCY_PACKET_LOSS: (
        "lentitud, latencia, cortes intermitentes o pérdida de paquetes"
    ),
    IncidentCategory.HARDWARE_FAILURE: "una falla de hardware: fuente, transceptor, placa o equipo",
    IncidentCategory.CONFIGURATION_ERROR: "un error de configuración o un cambio reciente",
    IncidentCategory.POWER_ALARM: "una alarma de energía eléctrica, baterías o rectificadores",
    IncidentCategory.OTHER: "una consulta o un tema que no es una falla de red",
}
SEVERITY_LABELS: dict[Severity, str] = {
    Severity.CRITICAL: "crítico: un sitio entero o muchos clientes sin servicio",
    Severity.MAJOR: "alto: un cliente sin servicio o un equipo sin redundancia",
    Severity.MINOR: "moderado: el servicio funciona pero degradado",
    Severity.WARNING: "bajo: un aviso sin impacto en el servicio",
}


@dataclass(frozen=True)
class SmallTriage:
    category: IncidentCategory
    severity: Severity
    category_score: float
    severity_score: float
    latency_seconds: float


def ticket_text(ticket: str, logs: str | None) -> str:
    return f"{ticket}\n{logs}" if logs else ticket


class ZeroShotTriage:
    """Category and severity from a zero-shot classification pipeline."""

    def __init__(
        self, model_id: str, device: str | int = "cpu", classifier: Callable | None = None
    ) -> None:
        """`classifier` replaces the transformers pipeline (tests use a fake one)."""
        start = time.perf_counter()
        self.model_id = model_id
        if classifier is None:
            from transformers import pipeline  # optional dependency: requirements-hf.txt

            classifier = pipeline("zero-shot-classification", model=model_id, device=device)
        self._classify = classifier
        self.load_seconds = time.perf_counter() - start

    def _best(self, text: str, labels: dict, template: str) -> tuple:
        by_description = {description: value for value, description in labels.items()}
        result = self._classify(
            text, candidate_labels=list(by_description), hypothesis_template=template
        )
        return by_description[result["labels"][0]], result["scores"][0]

    def classify(self, ticket: str, logs: str | None = None) -> SmallTriage:
        text = ticket_text(ticket, logs)
        start = time.perf_counter()
        category, category_score = self._best(text, CATEGORY_LABELS, HYPOTHESIS_TEMPLATE)
        severity, severity_score = self._best(text, SEVERITY_LABELS, SEVERITY_TEMPLATE)
        return SmallTriage(
            category=category,
            severity=severity,
            category_score=round(category_score, 3),
            severity_score=round(severity_score, 3),
            latency_seconds=round(time.perf_counter() - start, 3),
        )
