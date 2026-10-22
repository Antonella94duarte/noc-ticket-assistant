"""Run the classification step over the labeled eval set with the real model.

It calls the OpenAI API, so it spends tokens: run it by hand, not in CI.

    python scripts/evaluate.py
    python scripts/evaluate.py --prompt-version classify_v1 --effort low

Settings (API key, model, default effort) come from the environment / .env like the API.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.evaluation import load_cases, score  # noqa: E402
from app.llm.client import OpenAIClient  # noqa: E402
from app.llm.prompt_builder import CLASSIFY_PROMPT_VERSION, build_classify_messages  # noqa: E402
from app.schemas import TicketClassification  # noqa: E402

DEFAULT_CASES = Path(__file__).resolve().parents[1] / "data" / "eval" / "classification.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--prompt-version", default=CLASSIFY_PROMPT_VERSION)
    parser.add_argument("--effort", help="Reasoning effort (defaults to OPENAI_REASONING_EFFORT)")
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
    results, input_tokens, output_tokens = [], 0, 0
    for case in cases:
        messages = build_classify_messages(case.ticket_text, case.logs, args.prompt_version)
        llm_result = llm.parse(messages, TicketClassification)
        input_tokens += llm_result.input_tokens
        output_tokens += llm_result.output_tokens
        result = score(case, llm_result.parsed)
        results.append(result)

        c = result.classification
        mark = "PASS" if result.passed else "FAIL"
        notes = []
        if not result.category_ok:
            notes.append(f"category: expected {sorted(case.categories)}")
        if not result.severity_ok:
            notes.append(f"severity: expected {sorted(case.severities)}")
        if result.questions_ok is False:
            expected = "some" if case.expects_questions else "none"
            notes.append(f"questions: expected {expected}")
        detail = f"  <- {'; '.join(notes)}" if notes else ""
        print(f"{mark}  {case.id:<30} {c.category.value}/{c.severity.value}{detail}")

    total = len(results)
    print()
    print(f"prompt={args.prompt_version} model={settings.openai_model} effort={effort}")
    print(f"category accuracy: {sum(r.category_ok for r in results)}/{total}")
    print(f"severity accuracy: {sum(r.severity_ok for r in results)}/{total}")
    print(f"cases passed:      {sum(r.passed for r in results)}/{total}")
    print(f"tokens: {input_tokens} input, {output_tokens} output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
