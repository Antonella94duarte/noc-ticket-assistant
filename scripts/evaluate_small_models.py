"""Small local models vs the LLM for ticket triage, on every labeled ticket.

Runs zero-shot classification models from Hugging Face (app/small_models/triage.py) and,
optionally, the LLM triage (classify_v3) over the 53 labeled tickets in data/eval
(classification.jsonl and agent_cases.jsonl), and reports category and severity accuracy,
latency per ticket and cost. Needs requirements-hf.txt; the models are downloaded on first use.

    python scripts/evaluate_small_models.py
    python scripts/evaluate_small_models.py --llm openai deepseek
    python scripts/evaluate_small_models.py --summarize data/eval/results/small-models-<ts>.jsonl

--llm calls the real provider (53 short calls, about $0.02 with gpt-6-luna).
"""

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PROVIDERS, get_settings  # noqa: E402
from app.evaluation import load_agent_cases, load_cases  # noqa: E402
from app.llm.pricing import estimate_cost  # noqa: E402
from app.llm.prompt_builder import CLASSIFY_PROMPT_VERSION, build_classify_messages  # noqa: E402
from app.llm.providers import create_chat_model, structured_output  # noqa: E402
from app.schemas import TicketClassification  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "eval"
RESULTS_DIR = EVAL / "results"
ZERO_SHOT_MODELS = [
    "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
]


def all_cases() -> list:
    return load_cases(EVAL / "classification.jsonl") + load_agent_cases(EVAL / "agent_cases.jsonl")


def row(system: str, case, category: str, severity: str, latency: float, **extra) -> dict:
    return {
        "system": system,
        "case_id": case.id,
        "category": category,
        "severity": severity,
        "category_ok": category in case.categories,
        "severity_ok": severity in case.severities,
        "latency_seconds": latency,
        **extra,
    }


def run_zero_shot(model_id: str, cases: list) -> list[dict]:
    from app.small_models.triage import LABELS_VERSION, ZeroShotTriage

    triage = ZeroShotTriage(model_id)
    print(f"== {model_id}: loaded in {triage.load_seconds:.1f} s", flush=True)
    triage.classify(cases[0].ticket_text, cases[0].logs)  # warm-up, not timed
    rows = []
    for case in cases:
        result = triage.classify(case.ticket_text, case.logs)
        rows.append(
            row(
                model_id,
                case,
                result.category.value,
                result.severity.value,
                result.latency_seconds,
                cost_usd=0.0,
                labels_version=LABELS_VERSION,
                scores=[result.category_score, result.severity_score],
            )
        )
    return rows


def run_llm(provider: str, cases: list) -> list[dict]:
    settings = get_settings().model_copy(update={"llm_provider": provider})
    model = create_chat_model(provider, settings)
    name = getattr(model, "model_name", None) or getattr(model, "model", provider)
    chain = structured_output(model, TicketClassification, provider, settings, include_raw=True)
    print(f"== {provider} {name}: {CLASSIFY_PROMPT_VERSION}", flush=True)
    rows = []
    for case in cases:
        start = time.perf_counter()
        try:
            out = chain.invoke(build_classify_messages(case.ticket_text, case.logs))
        except Exception as exc:  # a failed call is a result: count it, keep going
            out = {"parsed": None, "parsing_error": exc, "raw": None}
        latency = round(time.perf_counter() - start, 3)
        parsed = out["parsed"]
        usage = (out["raw"].usage_metadata or {}) if out["raw"] is not None else {}
        cost = estimate_cost(
            provider, name, usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        )
        if parsed is None:
            rows.append(row(f"llm:{provider}", case, "error", "error", latency, cost_usd=cost))
            continue
        rows.append(
            row(
                f"llm:{provider}",
                case,
                parsed.category.value,
                parsed.severity.value,
                latency,
                cost_usd=cost,
                model=name,
            )
        )
    return rows


def summarize(rows: list[dict]) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["system"]].append(r)
    lines = [
        "| System | n | Category | Severity | Latency mean (p90) | Cost/ticket |",
        "|---|---|---|---|---|---|",
    ]
    for system, group in groups.items():
        n = len(group)
        latencies = sorted(r["latency_seconds"] for r in group)
        p90 = latencies[max(0, math.ceil(0.9 * n) - 1)]
        costs = [r["cost_usd"] for r in group if r["cost_usd"] is not None]
        lines.append(
            f"| {system} | {n} | {sum(r['category_ok'] for r in group)}/{n} "
            f"| {sum(r['severity_ok'] for r in group)}/{n} "
            f"| {statistics.mean(latencies):.2f} s ({p90:.2f} s) "
            f"| {f'${statistics.mean(costs):.5f}' if costs else '-'} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="*", default=ZERO_SHOT_MODELS, help="Zero-shot models")
    parser.add_argument("--llm", nargs="*", choices=PROVIDERS, default=[], help="LLM providers")
    parser.add_argument("--out", type=Path, help="Results file (JSONL)")
    parser.add_argument("--summarize", type=Path, help="Only summarize an existing results file")
    args = parser.parse_args()

    if args.summarize:
        lines = args.summarize.read_text(encoding="utf-8").splitlines()
        print(summarize([json.loads(line) for line in lines]))
        return 0

    cases = all_cases()
    out = args.out or RESULTS_DIR / f"small-models-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for model_id in args.models:
        rows += run_zero_shot(model_id, cases)
    for provider in args.llm:
        rows += run_llm(provider, cases)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")

    for r in rows:
        if not (r["category_ok"] and r["severity_ok"]):
            print(
                f"   miss {r['system'][-28:]:<28} {r['case_id']:<28} "
                f"{r['category']}/{r['severity']}"
            )
    print(f"\nResults: {out}\n")
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
