"""Compare the baseline and the agent (with and without runbooks) across providers.

Each system analyzes every ticket in data/eval/agent_cases.jsonl. The results are scored on the
category, the final severity, whether the top probable cause names the evidence that explains
the incident, whether a matching runbook is cited, and whether a customer reply was drafted when
it should be. Latency, tokens and an estimated cost are recorded for each run.

It calls the real models: run it by hand, not in CI.

    python scripts/evaluate_agents.py --providers openai deepseek
    python scripts/evaluate_agents.py --providers ollama --systems baseline agent-runbooks --limit 8
    python scripts/evaluate_agents.py --systems crew   # in the CrewAI image
    python scripts/evaluate_agents.py --summarize data/eval/results/agents-<timestamp>.jsonl

Fallback providers are disabled so each provider is measured on its own.
"""

import argparse
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.baseline import Baseline  # noqa: E402
from app.agents.graph import build_default_graph, run_agent_analysis  # noqa: E402
from app.config import PROVIDERS, Settings, get_settings  # noqa: E402
from app.evaluation import (  # noqa: E402
    AgentCase,
    cited_runbooks,
    load_agent_cases,
    score_agent_run,
    top_cause_text,
)
from app.llm.pricing import estimate_cost  # noqa: E402
from app.llm.providers import create_chat_models  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data" / "eval" / "agent_cases.jsonl"
RESULTS_DIR = ROOT / "data" / "eval" / "results"
SYSTEMS = ("baseline", "agent", "agent-runbooks", "crew")
# Systems that can search the runbooks, so citing one is scored.
WITH_RUNBOOKS = {"agent-runbooks", "crew"}
METRICS = ("category_ok", "severity_ok", "root_cause_ok", "runbook_ok", "reply_ok")


def provider_settings(base: Settings, provider: str) -> Settings:
    return base.model_copy(update={"llm_provider": provider, "llm_fallback_providers": ""})


def model_name(settings: Settings) -> str:
    return {
        "openai": settings.openai_model,
        "deepseek": settings.deepseek_model,
        "ollama": settings.ollama_model,
    }[settings.llm_provider]


def build_runner(system: str, settings: Settings):
    """A function that analyzes one case and returns the fields every system reports."""
    if system == "baseline":
        baseline = Baseline(create_chat_models(settings), [settings.llm_provider], settings)

        def run(case: AgentCase) -> dict:
            result = baseline.run(case.ticket_text, case.logs)
            return {
                "prompt_version": result.prompt_version,
                "classification": result.classification,
                "diagnosis": result.diagnosis,
                # The baseline doesn't revise the severity after diagnosing.
                "final_severity": result.classification.severity.value,
                "tool_calls": [],
                "model_calls": 2,
                "limit_reached": False,
                "usage_by_model": result.usage_by_model,
                "latency_seconds": result.latency_seconds,
            }

        return run

    if system == "crew":
        # Only installed in the CrewAI image (requirements-crewai.txt).
        from app.crew.noc_crew import run_crew_analysis

        def run(case: AgentCase) -> dict:
            result = run_crew_analysis(case.ticket_text, case.logs, settings)
            return {
                **result,
                "final_severity": result["diagnosis"].severity.value,
                "tool_calls": [c.name for c in result["tool_calls"]],
                "limit_reached": False,  # CrewAI doesn't report it
            }

        return run

    graph = build_default_graph(settings, with_runbooks=system == "agent-runbooks")

    def run(case: AgentCase) -> dict:
        result = run_agent_analysis(graph, case.ticket_text, case.logs, settings)
        return {
            "prompt_version": result.prompt_version,
            "classification": result.classification,
            "diagnosis": result.diagnosis,
            "final_severity": result.diagnosis.severity.value,
            "tool_calls": [c.name for c in result.tool_calls],
            "model_calls": result.investigation_model_calls + 2,  # plus triage and report
            "limit_reached": result.limit_reached,
            "usage_by_model": result.usage_by_model,
            "latency_seconds": result.latency_seconds,
        }

    return run


def failed_scores(case: AgentCase, system: str) -> dict:
    """A failed run fails every metric that applies to this case and system, and no other."""
    return {
        "category_ok": False,
        "severity_ok": False,
        "root_cause_ok": False if case.evidence_any else None,
        "runbook_ok": False if case.runbooks and system in WITH_RUNBOOKS else None,
        "reply_ok": False if case.expects_customer_reply is not None else None,
        "questions_ok": False if case.expects_questions is not None else None,
    }


def evaluate_one(run, case: AgentCase, system: str, settings: Settings) -> dict:
    row = {
        "case_id": case.id,
        "system": system,
        "provider": settings.llm_provider,
        "model": model_name(settings),
    }
    start = time.perf_counter()
    try:
        out = run(case)
    except Exception as exc:  # a failed run is a result too: count it, don't stop the eval
        return {
            **row,
            "error": f"{type(exc).__name__}: {str(exc)[:2000]}",
            "latency_seconds": round(time.perf_counter() - start, 2),
            "scores": failed_scores(case, system),
        }

    score = score_agent_run(
        case,
        out["classification"],
        out["diagnosis"],
        out["final_severity"],
        can_search_runbooks=system in WITH_RUNBOOKS,
    )
    input_tokens = sum(u.input_tokens for u in out["usage_by_model"].values())
    output_tokens = sum(u.output_tokens for u in out["usage_by_model"].values())
    return {
        **row,
        "error": None,
        "prompt_version": out["prompt_version"],
        "scores": asdict(score),
        "category": out["classification"].category.value,
        "triage_severity": out["classification"].severity.value,
        "final_severity": out["final_severity"],
        "top_cause": top_cause_text(out["diagnosis"]),
        "cited_runbooks": sorted(cited_runbooks(out["diagnosis"])),
        "tool_calls": out["tool_calls"],
        "model_calls": out["model_calls"],
        "limit_reached": out["limit_reached"],
        "latency_seconds": out["latency_seconds"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": sum(u.reasoning_tokens for u in out["usage_by_model"].values()),
        "cost_usd": estimate_cost(
            settings.llm_provider, model_name(settings), input_tokens, output_tokens
        ),
        "diagnosis": out["diagnosis"].model_dump(mode="json"),
    }


def _rate(rows: list[dict], metric: str) -> str:
    # Failed runs already score False on the metrics that apply; unlabeled ones are None.
    values = [r["scores"][metric] for r in rows if r["scores"][metric] is not None]
    return f"{sum(values)}/{len(values)}" if values else "-"


def summarize(rows: list[dict]) -> str:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        groups[(row["provider"], row["system"])].append(row)

    header = (
        "| Provider | System | n | Errors | Category | Final severity | Root cause | Runbook "
        "| Reply | Tools/ticket | Latency mean (p90) | Tokens/ticket | Cost/ticket |"
    )
    lines = [header, "|" + "---|" * 13]
    order = {s: i for i, s in enumerate(SYSTEMS)}
    for (provider, system), group in sorted(
        groups.items(), key=lambda g: (g[0][0], order[g[0][1]])
    ):
        ok = [r for r in group if not r["error"]]
        latencies = sorted(r["latency_seconds"] for r in ok)
        # Nearest-rank percentile, so a small group reports its slow runs too.
        p90 = latencies[max(0, math.ceil(0.9 * len(latencies)) - 1)] if latencies else 0
        tokens = [r["input_tokens"] + r["output_tokens"] for r in ok]
        costs = [r["cost_usd"] for r in ok if r["cost_usd"] is not None]
        lines.append(
            f"| {provider} | {system} | {len(group)} | {len(group) - len(ok)} "
            f"| {_rate(group, 'category_ok')} | {_rate(group, 'severity_ok')} "
            f"| {_rate(group, 'root_cause_ok')} | {_rate(group, 'runbook_ok')} "
            f"| {_rate(group, 'reply_ok')} "
            f"| {statistics.mean(len(r['tool_calls']) for r in ok) if ok else 0:.1f} "
            f"| {statistics.mean(latencies) if latencies else 0:.0f} s ({p90:.0f} s) "
            f"| {statistics.mean(tokens) if tokens else 0:,.0f} "
            f"| {f'${statistics.mean(costs):.4f}' if costs else '-'} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--providers", nargs="+", choices=PROVIDERS, default=["openai"])
    parser.add_argument(
        "--systems",
        nargs="+",
        choices=SYSTEMS,
        default=list(SYSTEMS[:3]),
        help="crew needs the CrewAI image (requirements-crewai.txt)",
    )
    parser.add_argument("--cases", nargs="+", help="Only these case ids")
    parser.add_argument("--limit", type=int, help="Only the first N cases")
    parser.add_argument("--workers", type=int, default=4, help="Parallel runs (Ollama uses 1)")
    parser.add_argument("--out", type=Path, help="Results file (JSONL)")
    parser.add_argument("--summarize", type=Path, help="Only summarize an existing results file")
    args = parser.parse_args()

    if args.summarize:
        rows = [
            json.loads(line) for line in args.summarize.read_text(encoding="utf-8").splitlines()
        ]
        print(summarize(rows))
        return 0

    cases = load_agent_cases(CASES)
    if args.cases:
        cases = [c for c in cases if c.id in args.cases]
    if args.limit:
        cases = cases[: args.limit]
    out = args.out or RESULTS_DIR / f"agents-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)

    base = get_settings()
    rows: list[dict] = []
    with out.open("a", encoding="utf-8") as sink:
        for provider in args.providers:
            settings = provider_settings(base, provider)
            for system in args.systems:
                run = build_runner(system, settings)
                workers = 1 if provider == "ollama" else args.workers
                print(
                    f"== {provider} / {system}: {len(cases)} cases, {workers} workers", flush=True
                )
                one = partial(evaluate_one, run, system=system, settings=settings)
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for row in pool.map(one, cases):
                        rows.append(row)
                        sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                        sink.flush()
                        status = "ERROR " + row["error"] if row["error"] else row["scores"]
                        print(f"   {row['case_id']:<22} {status}", flush=True)

    print(f"\nResults: {out}\n")
    print(summarize(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
