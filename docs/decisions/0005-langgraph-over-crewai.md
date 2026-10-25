# ADR 0005: Keep LangGraph as the agent framework; CrewAI as a documented comparison

- Status: accepted
- Date: 2026-10-25

## Context

ADR 0001 planned a small CrewAI version of the agent to compare frameworks with real numbers
rather than opinions. It now exists (`app/crew/noc_crew.py`) and has been evaluated on the same
30 tickets, tools, prompts and models as the LangGraph agent. Full write-up:
[framework-comparison.md](../framework-comparison.md).

## Decision

LangGraph stays as the base. The CrewAI version is kept as an optional, tested comparison in its
own image (`requirements-crewai.txt`), with its own CI job.

## Reasons

- **Same quality, a third of the cost.** Root cause, severity, runbook citations and replies are
  within one case of each other on OpenAI and DeepSeek, while CrewAI makes ~21 model calls per
  ticket against ~6 and uses about 3x the tokens.
- **Structured output across providers.** CrewAI's `output_pydantic` relies on a JSON-schema
  `response_format` that DeepSeek rejects; LangGraph lets the project pick the method per provider.
- **Guard rails and fallback** (tool-call limit, model-call limit, provider fallback) come as
  LangChain middleware; CrewAI only caps iterations per agent.
- **Testability**: the LangGraph graph runs end to end in the tests with a fake model.
- **Footprint**: CrewAI adds ~200 packages and needs `openai<3`.

## Consequences

- The API and the evaluation default to LangGraph; `scripts/evaluate_agents.py --systems crew`
  reruns the comparison in the CrewAI image.
- The project's `openai` requirement was widened to `>=2.30` so both images resolve; the API image
  still installs 3.x, and the full test suite passes on both.
