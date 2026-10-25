"""Compare runbook retrievers on labeled queries: hit@1, hit@3 and MRR, by query language.

    python scripts/evaluate_retrieval.py                  # bm25 only (offline, free)
    python scripts/evaluate_retrieval.py bm25 openai ollama
    python scripts/evaluate_retrieval.py hf:intfloat/multilingual-e5-small    # any HF model

openai and ollama embed the runbooks and the queries (a fraction of a cent with OpenAI; free
and local with Ollama, which needs OLLAMA_EMBEDDING_MODEL pulled). hf runs a Hugging Face model
in-process (requirements-hf.txt): HF_EMBEDDING_MODEL, or the model named after "hf:".
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.evaluation import (  # noqa: E402
    RetrievalResult,
    load_retrieval_cases,
    unique_in_order,
)
from app.rag.runbooks import create_runbook_search  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "data" / "eval" / "runbook_queries.jsonl"
DEPTH = 5  # sections retrieved per query before collapsing them into runbooks


def summarize(label: str, results: list[RetrievalResult]) -> str:
    n = len(results)
    hit1 = sum(r.hit_at(1) for r in results)
    hit3 = sum(r.hit_at(3) for r in results)
    mrr = sum(r.reciprocal_rank for r in results) / n
    return f"{label:<14} n={n:<3} hit@1={hit1}/{n}  hit@3={hit3}/{n}  MRR={mrr:.2f}"


def main() -> int:
    kinds = sys.argv[1:] or ["bm25"]
    cases = load_retrieval_cases(CASES)
    for kind in kinds:
        settings = get_settings()
        if kind.startswith("hf:"):
            settings = settings.model_copy(update={"hf_embedding_model": kind[3:]})
        search = create_runbook_search(kind.split(":", 1)[0], settings)
        results = [
            RetrievalResult(
                case, unique_in_order([h.runbook for h in search.search(case.query, DEPTH)])
            )
            for case in cases
        ]
        print(f"=== {kind}")
        for r in results:
            if not r.hit_at(1):
                expected, got = sorted(r.case.expected), r.ranked_runbooks[:3]
                print(f"   miss@1  {r.case.id:<22} expected {expected} got {got}")
        print("   " + summarize("all", results))
        for lang in ("en", "es"):
            print("   " + summarize(f"lang={lang}", [r for r in results if r.case.lang == lang]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
