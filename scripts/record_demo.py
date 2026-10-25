"""Record real agent runs for the demo page to replay without an API key.

Runs the agent on the scenarios in scripts/run_agent.py with the configured provider and the
seeded network database, and saves the streamed events, exactly as POST /api/v1/agent/analyze
sends them, to app/static/demo/<scenario>.ndjson. It spends tokens: run it by hand.

    python scripts/record_demo.py customer-no-service slow-site config-change
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_agent import SCENARIOS  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.agent import get_agent_graph, trace_lines  # noqa: E402

DEMO_DIR = Path(__file__).resolve().parents[1] / "app" / "static" / "demo"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenarios", nargs="+", choices=sorted(SCENARIOS))
    args = parser.parse_args()

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    graph = get_agent_graph()
    for scenario in args.scenarios:
        lines = list(trace_lines(graph, SCENARIOS[scenario], None, settings))
        if '"type": "error"' in lines[-1]:
            print(f"{scenario}: the run failed, nothing saved (see the log)")
            continue
        path = DEMO_DIR / f"{scenario}.ndjson"
        path.write_text("".join(lines), encoding="utf-8")
        print(f"{scenario}: {len(lines)} events -> {path.relative_to(DEMO_DIR.parents[2])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
