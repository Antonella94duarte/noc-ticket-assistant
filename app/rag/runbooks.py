"""Retrieval over the NOC runbooks with LlamaIndex.

Each runbook is split into its sections (When to use, Steps, Escalation...), and every section
is prefixed with its runbook's title and the alarm types it applies to, so a retrieved section
makes sense on its own and keyword search can match alarm type names.

Three retrievers, chosen with RUNBOOK_RETRIEVER:

- bm25 (default): keyword ranking. Free, offline and deterministic, so it also runs in CI; it
  can't match a Spanish query to an English runbook.
- openai: OpenAI embeddings (semantic, multilingual). Indexing the runbooks costs a fraction of
  a cent; queries leave the machine.
- ollama: local embeddings through Ollama (semantic, multilingual with a model like bge-m3).

The index is small (dozens of sections), so it is built in memory when first needed.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from llama_index.core import SimpleDirectoryReader, VectorStoreIndex
from llama_index.core.base.base_retriever import BaseRetriever
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import TextNode

from app.config import Settings, get_settings

RUNBOOKS_DIR = Path(__file__).resolve().parents[2] / "data" / "runbooks"
MAX_SECTION_CHARS = 900

RetrieverKind = Literal["bm25", "openai", "ollama", "hf"]


@dataclass(frozen=True)
class RunbookHit:
    runbook: str  # e.g. "RB-002"
    title: str
    section: str
    score: float
    text: str


def _header(document_text: str) -> tuple[str, str, str]:
    """(runbook id, title, applies-to line) from the top of a runbook."""
    title_line = document_text.splitlines()[0].lstrip("# ").strip()
    runbook_id = title_line.split()[0]
    applies = re.search(r"^- Applies to[^:]*:\s*(.+)$", document_text, re.MULTILINE)
    return runbook_id, title_line, applies.group(1).replace("`", "") if applies else ""


def load_runbook_nodes(directory: Path = RUNBOOKS_DIR) -> list[TextNode]:
    """One node per runbook section, self-contained thanks to a short header."""
    documents = SimpleDirectoryReader(str(directory), required_exts=[".md"]).load_data()
    nodes: list[TextNode] = []
    for document in sorted(documents, key=lambda d: d.metadata["file_name"]):
        runbook_id, title, applies_to = _header(document.text)
        for section in MarkdownNodeParser().get_nodes_from_documents([document]):
            heading = section.text.splitlines()[0].lstrip("# ").strip()
            nodes.append(
                TextNode(
                    id_=f"{runbook_id}:{len(nodes)}",
                    text=f"{title}\nApplies to: {applies_to}\n\n{section.text}",
                    metadata={"runbook": runbook_id, "title": title, "section": heading},
                    excluded_embed_metadata_keys=["runbook", "title", "section"],
                    excluded_llm_metadata_keys=["runbook", "title", "section"],
                )
            )
    return nodes


class RunbookSearch:
    def __init__(self, retriever: BaseRetriever, kind: RetrieverKind):
        self._retriever = retriever
        self.kind = kind

    def search(self, query: str, top_k: int = 3) -> list[RunbookHit]:
        hits = []
        for result in self._retriever.retrieve(query)[:top_k]:
            # BM25 scores 0 when no query word appears in a section: that's no match, not a
            # weak one, and handing it to the agent would only add noise.
            if not result.score:
                continue
            meta = result.node.metadata
            text = result.node.get_content()
            hits.append(
                RunbookHit(
                    runbook=meta["runbook"],
                    title=meta["title"],
                    section=meta["section"],
                    score=round(float(result.score or 0.0), 4),
                    text=text if len(text) <= MAX_SECTION_CHARS else text[:MAX_SECTION_CHARS] + "…",
                )
            )
        return hits


def build_bm25_search(nodes: list[TextNode], top_k: int = 3) -> RunbookSearch:
    from llama_index.retrievers.bm25 import BM25Retriever

    retriever = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=top_k, language="en")
    return RunbookSearch(retriever, "bm25")


def build_embedding_search(
    nodes: list[TextNode], embed_model: BaseEmbedding, kind: RetrieverKind, top_k: int = 3
) -> RunbookSearch:
    index = VectorStoreIndex(nodes, embed_model=embed_model)
    return RunbookSearch(index.as_retriever(similarity_top_k=top_k), kind)


def create_embed_model(kind: RetrieverKind, settings: Settings) -> BaseEmbedding:
    if kind == "openai":
        from llama_index.embeddings.openai import OpenAIEmbedding

        if not settings.openai_api_key:
            raise ValueError("Set OPENAI_API_KEY to use OpenAI embeddings for runbook search")
        return OpenAIEmbedding(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key.get_secret_value(),
        )
    if kind == "ollama":
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            model_name=settings.ollama_embedding_model, base_url=settings.ollama_base_url
        )
    if kind == "hf":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding  # requirements-hf.txt

        model = settings.hf_embedding_model
        # E5 models were trained with these prefixes and retrieve worse without them.
        e5 = "e5" in model.lower()
        return HuggingFaceEmbedding(
            model_name=model,
            query_instruction="query: " if e5 else None,
            text_instruction="passage: " if e5 else None,
            device="cpu",
        )
    raise ValueError(f"No embedding model for retriever {kind!r}")


def create_runbook_search(
    kind: RetrieverKind | None = None, settings: Settings | None = None
) -> RunbookSearch:
    settings = settings or get_settings()
    kind = kind or settings.runbook_retriever
    nodes = load_runbook_nodes()
    if kind == "bm25":
        return build_bm25_search(nodes, settings.runbook_top_k)
    return build_embedding_search(
        nodes, create_embed_model(kind, settings), kind, settings.runbook_top_k
    )


@lru_cache
def get_runbook_search() -> RunbookSearch:
    """Shared search for the configured retriever, built once per process."""
    return create_runbook_search()
