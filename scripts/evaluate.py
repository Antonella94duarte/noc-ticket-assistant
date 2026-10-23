"""Run the analysis over the labeled eval set with the real model.

It calls the OpenAI API, so it spends tokens: run it by hand, not in CI.

    python scripts/evaluate.py
    python scripts/evaluate.py --prompt-version classify_v1 --effort low
    python scripts/evaluate.py --with-diagnosis --diagnose-version diagnose_v1 --runs 2

Settings (API key, model, default effort) come from the environment / .env like the API.
"""

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.evaluation import CaseResult, EvalCase, load_cases, score  # noqa: E402
from app.llm.client import OpenAIClient  # noqa: E402
from app.llm.prompt_builder import (  # noqa: E402
    CLASSIFY_PROMPT_VERSION,
    DIAGNOSE_PROMPT_VERSION,
    build_classify_messages,
    build_diagnose_messages,
)
from app.schemas import TicketClassification, TicketDiagnosis  # noqa: E402

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "data" / "eval" / "classification.jsonl"


def failure_notes(result: CaseResult) -> list[str]:
    case = result.case
    notes = []
    if not result.category_ok:
        notes.append(f"category: expected {sorted(case.categories)}")
    if not result.severity_ok:
        notes.append(f"severity: expected {sorted(case.severities)}")
    if result.questions_ok is False:
        notes.append(f"questions: expected {'some' if case.expects_questions else 'none'}")
    if result.reply_ok is False:
        notes.append(f"customer reply: expected {'one' if case.expects_customer_reply else 'none'}")
    return notes


def run_once(
    llm: OpenAIClient, cases: list[EvalCase], args: argparse.Namespace
) -> tuple[list[CaseResult], list[int]]:
    results, diagnosis_output_tokens = [], []
    for case in cases:
        classify_messages = build_classify_messages(
            case.ticket_text, case.logs, args.prompt_version
        )
        classification = llm.parse(classify_messages, TicketClassification).parsed
        diagnosis = None
        if args.with_diagnosis:
            diagnose_messages = build_diagnose_messages(
                case.ticket_text, case.logs, classification, args.diagnose_version
            )
            diagnosed = llm.parse(diagnose_messages, TicketDiagnosis)
            diagnosis = diagnosed.parsed
            # Visible output only: output_tokens also counts the hidden reasoning tokens.
            diagnosis_output_tokens.append(diagnosed.output_tokens - diagnosed.reasoning_tokens)

        result = score(case, classification, diagnosis)
        results.append(result)
        c = result.classification
        notes = failure_notes(result)
        detail = f"  <- {'; '.join(notes)}" if notes else ""
        mark = "PASS" if result.passed else "FAIL"
        print(f"{mark}  {case.id:<30} {c.category.value}/{c.severity.value}{detail}")
    return results, diagnosis_output_tokens


def summarize(results: list[CaseResult], diagnosis_output_tokens: list[int]) -> None:
    total = len(results)
    print(f"category accuracy: {sum(r.category_ok for r in results)}/{total}")
    print(f"severity accuracy: {sum(r.severity_ok for r in results)}/{total}")
    questions = [r.questions_ok for r in results if r.questions_ok is not None]
    if questions:
        print(f"questions ok:      {sum(questions)}/{len(questions)}")
    replies = [r.reply_ok for r in results if r.reply_ok is not None]
    if replies:
        print(f"customer reply ok: {sum(replies)}/{len(replies)}")
    print(f"cases passed:      {sum(r.passed for r in results)}/{total}")
    if diagnosis_output_tokens:
        mean = statistics.mean(diagnosis_output_tokens)
        top = max(diagnosis_output_tokens)
        print(f"diagnosis visible output tokens: mean {mean:.0f}, max {top}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--prompt-version", default=CLASSIFY_PROMPT_VERSION)
    parser.add_argument("--with-diagnosis", action="store_true", help="Also run the diagnosis")
    parser.add_argument("--diagnose-version", default=DIAGNOSE_PROMPT_VERSION)
    parser.add_argument("--effort", help="Reasoning effort (defaults to OPENAI_REASONING_EFFORT)")
    parser.add_argument("--runs", type=int, default=1, help="Repeat to see run-to-run variation")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_api_key or not settings.openai_model:
        print("Set OPENAI_API_KEY and OPENAI_MODEL first.", file=sys.stderr)
        return 2
    effort = args.effort or settings.openai_reasoning_effort
    llm = OpenAIClient(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.openai_model,
        reasoning_effort=effort,
        timeout=settings.openai_timeout_seconds,
    )

    cases = load_cases(args.cases)
    all_results, all_tokens = [], []
    for run in range(1, args.runs + 1):
        print(f"--- run {run}/{args.runs}")
        results, tokens = run_once(llm, cases, args)
        all_results += results
        all_tokens += tokens
        print()

    diagnose = f" diagnose={args.diagnose_version}" if args.with_diagnosis else ""
    print(f"prompt={args.prompt_version}{diagnose} model={settings.openai_model} effort={effort}")
    print(f"runs={args.runs}, totals over all runs:")
    summarize(all_results, all_tokens)
    return 0


if __name__ == "__main__":
    sys.exit(main())
