"""Shortlist Hugging Face models for the small-model comparison, with the Hub API.

Searches the Hub by task and language, sorted by downloads, and prints what matters for running
a model locally next to the API: size, license and how widely it is used. Read-only and free (no
token needed):

    python scripts/find_models.py
    python scripts/find_models.py --limit 15
"""

import argparse

from huggingface_hub import list_models

# (what it is for, Hub task, language tag). The tickets are in Spanish, so models must cover it.
SEARCHES = [
    ("ticket triage", "zero-shot-classification", "es"),
    ("ticket triage", "zero-shot-classification", "multilingual"),
    ("runbook search", "sentence-similarity", "es"),
    ("runbook search", "sentence-similarity", "multilingual"),
]


def parameters(model) -> str:
    total = getattr(model.safetensors, "total", None) if model.safetensors else None
    return f"{total / 1e6:,.0f}M" if total else "?"


def license_of(model) -> str:
    return next((t.split(":", 1)[1] for t in model.tags or [] if t.startswith("license:")), "?")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=8, help="Models per search")
    args = parser.parse_args()

    for purpose, task, language in SEARCHES:
        print(f"\n== {purpose}: {task}, language={language}")
        print(f"{'model':<60} {'downloads':>12} {'likes':>6} {'params':>8}  license")
        models = list_models(
            pipeline_tag=task,
            filter=language,
            sort="downloads",
            limit=args.limit,
            expand=["downloads", "likes", "safetensors", "tags"],
        )
        for m in models:
            print(
                f"{m.id:<60} {m.downloads or 0:>12,} {m.likes or 0:>6} {parameters(m):>8}  "
                f"{license_of(m)}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
