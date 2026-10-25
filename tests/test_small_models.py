import sys
from types import ModuleType
from unittest.mock import MagicMock

from app.config import Settings
from app.rag.runbooks import create_embed_model
from app.schemas import IncidentCategory, Severity
from app.small_models.triage import (
    CATEGORY_LABELS,
    HYPOTHESIS_TEMPLATE,
    SEVERITY_LABELS,
    SEVERITY_TEMPLATE,
    ZeroShotTriage,
)


class FakeZeroShot:
    """Ranks first the label that contains `prefer`, like a pipeline that picked it."""

    def __init__(self, prefer: dict[str, str]):
        self.prefer = prefer
        self.calls = []

    def __call__(self, text, candidate_labels, hypothesis_template):
        self.calls.append((text, candidate_labels, hypothesis_template))
        word = self.prefer[hypothesis_template]
        ranked = sorted(candidate_labels, key=lambda label: word not in label)
        return {"labels": ranked, "scores": [0.9] + [0.1 / len(ranked)] * (len(ranked) - 1)}


def test_every_category_and_severity_has_a_label():
    assert set(CATEGORY_LABELS) == set(IncidentCategory)
    assert set(SEVERITY_LABELS) == set(Severity)
    assert len(set(CATEGORY_LABELS.values())) == len(CATEGORY_LABELS)


def test_best_labels_map_back_to_category_and_severity():
    fake = FakeZeroShot({HYPOTHESIS_TEMPLATE: "energía", SEVERITY_TEMPLATE: "bajo"})
    triage = ZeroShotTriage("fake-model", classifier=fake)

    result = triage.classify("Monitoreo: alarma de energía en SITE-SUR-02.", "AC input failure")

    assert result.category is IncidentCategory.POWER_ALARM
    assert result.severity is Severity.WARNING
    assert result.category_score == 0.9
    text, labels, template = fake.calls[0]
    assert text == "Monitoreo: alarma de energía en SITE-SUR-02.\nAC input failure"
    assert set(labels) == set(CATEGORY_LABELS.values())
    assert [call[2] for call in fake.calls] == [HYPOTHESIS_TEMPLATE, SEVERITY_TEMPLATE]


def test_hf_embeddings_use_e5_prefixes_only_for_e5_models(monkeypatch):
    # A stand-in for the optional package, so the test needs neither torch nor a download.
    embedding = MagicMock()
    module = ModuleType("llama_index.embeddings.huggingface")
    module.HuggingFaceEmbedding = embedding
    monkeypatch.setitem(sys.modules, "llama_index.embeddings.huggingface", module)

    for model in ("intfloat/multilingual-e5-small", "sentence-transformers/LaBSE"):
        create_embed_model("hf", Settings(_env_file=None, hf_embedding_model=model))

    e5, other = (call.kwargs for call in embedding.call_args_list)
    assert e5["model_name"] == "intfloat/multilingual-e5-small"
    assert (e5["query_instruction"], e5["text_instruction"]) == ("query: ", "passage: ")
    assert (other["query_instruction"], other["text_instruction"]) == (None, None)
