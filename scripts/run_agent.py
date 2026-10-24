"""Run the LangGraph agent on a ticket and print what it did.

Uses the configured provider (LLM_PROVIDER) and the seeded network database, so it spends
tokens. Scenarios match the incidents in data/network/seed.json:

    python scripts/run_agent.py --scenario customer-no-service
    python scripts/run_agent.py "Texto del ticket" --logs "línea de log"
    python scripts/run_agent.py --scenario slow-site --json
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.graph import build_default_graph, run_agent_analysis  # noqa: E402
from app.config import get_settings  # noqa: E402

SCENARIOS = {
    # The customer doesn't give a circuit: the agent has to find it and the alarm on its port.
    "customer-no-service": "Hola, somos Distribuidora Del Sur. Desde esta mañana no tenemos "
    "internet en el depósito, necesitamos que lo revisen urgente.",
    # A slow site whose real cause is a failed uplink with its pair congested.
    "slow-site": "Varios clientes de SITE-ESTE-04 reportan lentitud y videollamadas que se "
    "cortan desde el mediodía.",
    # A configuration change behind a customer's lost connectivity.
    "config-change": "Banco Austral reporta que desde la madrugada no llega a sus servidores "
    "alojados en el datacenter desde la red de su oficina (VLAN 210).",
    # An internal power alarm: impact depends on battery autonomy.
    "power-alarm": "Monitoreo: alarma de energía en SITE-SUR-02.",
    # Nothing to identify the customer: the agent should not scan the whole network.
    "vague": "No anda nada, por favor llámennos.",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ticket", nargs="?", help="Ticket text (or use --scenario)")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--logs")
    parser.add_argument("--json", action="store_true", help="Print the full result as JSON")
    parser.add_argument(
        "--no-runbooks", action="store_true", help="Run without the runbook search tool"
    )
    args = parser.parse_args()
    ticket = SCENARIOS[args.scenario] if args.scenario else args.ticket
    if not ticket:
        parser.error("give a ticket text or --scenario")

    settings = get_settings()
    graph = build_default_graph(settings, with_runbooks=not args.no_runbooks)
    analysis = run_agent_analysis(graph, ticket, args.logs, settings)

    if args.json:
        print(analysis.model_dump_json(indent=2))
        return 0

    c, d = analysis.classification, analysis.diagnosis
    print(f"Ticket: {ticket}\n")
    print(f"Triage: {c.category.value}/{c.severity.value} - {c.severity_reason}")
    print(
        f"\nInvestigation ({analysis.investigation_model_calls} model calls, "
        f"{len(analysis.tool_calls)} tool calls, limit reached: {analysis.limit_reached}):"
    )
    for call in analysis.tool_calls:
        print(f"  - {call.name}({call.args}) -> {len(call.result)} chars")
    print(f"\nFindings:\n{analysis.findings}\n")
    print("Probable causes:")
    for cause in d.probable_causes:
        print(f"  - [{cause.likelihood.value}] {cause.cause} | {cause.evidence}")
    print("Diagnostic steps:")
    for step in d.diagnostic_steps:
        print(f"  - {step.action}")
    print("Recommended actions:")
    for action in d.recommended_actions:
        print(f"  - {action}")
    print(f"Customer reply: {d.customer_reply!r}")
    print(f"\nLatency: {analysis.latency_seconds}s")
    for model, usage in analysis.usage_by_model.items():
        print(
            f"Tokens [{model}]: in={usage.input_tokens} out={usage.output_tokens} "
            f"reasoning={usage.reasoning_tokens}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
