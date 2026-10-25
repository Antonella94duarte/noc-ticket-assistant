import json
from pathlib import Path

import pytest
from llama_index.core.embeddings import MockEmbedding

from app.agents.graph import AGENT_PROMPT_VERSION, agent_prompt_version, build_default_graph
from app.config import Settings
from app.evaluation import RetrievalResult, load_retrieval_cases, unique_in_order
from app.rag.runbooks import (
    build_bm25_search,
    build_embedding_search,
    create_embed_model,
    load_runbook_nodes,
)
from app.tools.langchain_tools import build_runbook_tool

QUERIES = Path(__file__).resolve().parents[1] / "data" / "eval" / "runbook_queries.jsonl"


@pytest.fixture(scope="module")
def nodes():
    return load_runbook_nodes()


@pytest.fixture(scope="module")
def bm25(nodes):
    return build_bm25_search(nodes)


def test_every_runbook_is_split_into_sections(nodes):
    runbooks = {n.metadata["runbook"] for n in nodes}

    assert runbooks == {f"RB-00{i}" for i in range(1, 10)}
    assert len(nodes) > len(runbooks)  # more than one section each


def test_sections_carry_their_runbook_title_and_alarm_types(nodes):
    steps = next(
        n for n in nodes if n.metadata["runbook"] == "RB-002" and n.metadata["section"] == "Steps"
    )

    assert steps.text.startswith("RB-002 Low optical receive power")
    assert "Applies to: optical_rx_los, optical_rx_low, onu_los" in steps.text


def test_bm25_finds_runbooks_by_alarm_type(bm25):
    assert bm25.search("bundle_member_down")[0].runbook == "RB-004"
    assert bm25.search("psu_failure")[0].runbook == "RB-006"


def test_bm25_returns_nothing_instead_of_noise_when_no_word_matches(bm25):
    # Spanish words don't appear in the English runbooks: no match is better than random ones.
    assert bm25.search("el cliente no tiene internet") == []


def test_bm25_regression_on_the_english_eval_queries(bm25):
    """BM25 is deterministic, so its eval score can guard against regressions in CI."""
    cases = [c for c in load_retrieval_cases(QUERIES) if c.lang == "en"]

    results = [
        RetrievalResult(c, unique_in_order([h.runbook for h in bm25.search(c.query, 5)]))
        for c in cases
    ]

    assert sum(r.hit_at(1) for r in results) == len(cases)


def test_long_sections_are_truncated(bm25):
    for hit in bm25.search("link_down interface flap escalation", top_k=3):
        assert len(hit.text) <= 901


def test_embedding_search_works_with_any_embedding_model(nodes):
    search = build_embedding_search(nodes, MockEmbedding(embed_dim=8), "openai", top_k=2)

    hits = search.search("optical power")

    assert len(hits) == 2
    assert search.kind == "openai"


def test_openai_embeddings_need_a_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        create_embed_model("openai", Settings(_env_file=None))


def test_runbook_tool_returns_compact_sections(bm25):
    tool = build_runbook_tool(bm25, top_k=2)

    result = json.loads(tool.invoke({"query": "ac_input_failure"}))

    assert result["found"] is True
    assert [s["runbook"] for s in result["sections"]] == ["RB-005", "RB-005"]
    assert "alarm type names" in tool.description.lower()


def test_retrieval_metrics():
    (case,) = [c for c in load_retrieval_cases(QUERIES) if c.id == "en-alarm-crc"]

    assert RetrievalResult(case, ["RB-003", "RB-001"]).rank == 1
    second = RetrievalResult(case, ["RB-001", "RB-003"])
    assert (second.rank, second.hit_at(1), second.hit_at(3)) == (2, False, True)
    assert second.reciprocal_rank == 0.5
    assert RetrievalResult(case, []).reciprocal_rank == 0.0
    assert unique_in_order(["RB-1", "RB-2", "RB-1"]) == ["RB-1", "RB-2"]


def test_default_graph_with_and_without_runbooks():
    config = Settings(_env_file=None, openai_api_key="sk-test", openai_model="gpt-test")

    with_runbooks = build_default_graph(config)
    without = build_default_graph(config, with_runbooks=False)

    assert with_runbooks.prompt_version == AGENT_PROMPT_VERSION
    assert "investigate_v2" in with_runbooks.prompt_version
    assert without.prompt_version == agent_prompt_version("investigate_v1", "report_v3")
