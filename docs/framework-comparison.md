# LangGraph vs CrewAI on the same agent

The same ticket analysis built twice: with LangGraph (`app/agents/graph.py`) and with CrewAI
(`app/crew/noc_crew.py`). Both versions use the same prompt files, the same five tools (CrewAI
gets the LangChain tools wrapped without changes: same names, descriptions, argument schemas and
code) and the same output schemas, so the comparison is about orchestration. Measured on
2026-10-25 with the 30-ticket set from [model-comparison.md](model-comparison.md).

| | LangGraph | CrewAI |
|---|---|---|
| Structure | A `StateGraph` with three nodes; the investigator is a `create_agent` tool loop | A sequential `Crew` of three agents, one task each |
| Versions | langgraph 1.2, langchain 1.4 | crewai 1.15.30 |

## Results

Both on the agent with runbook search; one run per configuration.

| Provider | Framework | Errors | Category | Final severity | Root cause | Runbook cited | Reply | Model calls/ticket | Tokens/ticket | Latency mean (p90) | Cost/ticket (upper bound) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| OpenAI `gpt-6-luna` | LangGraph | 0 | 30/30 | 27/30 | 20/23 | 21/24 | 28/30 | 6.1 | 20.3k | 58 s (71 s) | $0.0036 |
| OpenAI `gpt-6-luna` | CrewAI | 0 | 29/30 | 27/30 | 21/23 | 22/24 | 29/30 | 21.1 | 69.3k | 49 s (67 s) | $0.0112 |
| DeepSeek `deepseek-flash` | LangGraph | 1 | 29/30 | 25/30 | 19/23 | 20/24 | 28/30 | 7.0 | 32.0k | 45 s (55 s) | $0.0156 |
| DeepSeek `deepseek-flash` | CrewAI | 0 | 30/30 | 26/30 | 20/23 | 20/24 | 29/30 | 21.2 | 94.7k | 46 s (62 s) | $0.0484 |

**Quality is the same.** Every metric is within one case, which is the noise of a single run on
30 tickets. Both frameworks fail on the same tickets in the same way (blaming the congested
uplink instead of the customer's port with CRC errors; raising the severity because of unrelated
alarms on the site), so those errors come from the model and the prompts, not from the framework.

**CrewAI costs about 3x more.** It makes ~21 model calls per ticket against ~6, and sends 3.4x
the tokens on OpenAI and 3x on DeepSeek. Three things add up: its own reasoning prompt wraps
every agent turn, the outputs of earlier tasks are repeated as context in later ones, and
`output_pydantic` adds calls to convert answers into the schema.

**Latency is similar**, CrewAI even a little faster on OpenAI despite the extra calls. I could
not confirm that the same reasoning effort was applied: CrewAI's usage metrics don't report
reasoning tokens, so this comparison is less reliable than the token counts.

## What was different in practice

| Aspect | LangGraph | CrewAI |
|---|---|---|
| Control over the flow | Explicit graph: nodes, edges and state are code you read and test | Roles, goals and tasks; CrewAI builds the prompts and the loop |
| Prompts | Our prompts are the system prompts; few-shot examples are real user/assistant turns | Our prompts become role backstory and task descriptions inside CrewAI's own prompt; few-shot can only be inlined as text |
| Structured output | Chosen per provider (`structured_output()`: strict schema, JSON mode, function calling) | `output_pydantic` sends a JSON-schema `response_format`. DeepSeek rejects it ("This response_format type is unavailable now"): all 30 runs failed until the tasks asked for JSON in the answer and we parsed it ourselves |
| Limits | Middleware: a tool-call limit (the agent must conclude), a model-call limit, model fallback | `max_iter` per agent; no crew-wide tool-call limit; no built-in provider fallback |
| What the report sees | The investigator's findings plus every raw tool result | Only the investigator's final answer, through task context |
| Providers | Direct integrations for OpenAI, DeepSeek and Ollama | OpenAI native; DeepSeek and Ollama through LiteLLM |
| Observability | Full message list and state; per-model token usage including reasoning; model calls counted with a callback | Task outputs, `token_usage` totals (no reasoning tokens), verbose logs |
| Testing | The whole graph runs end to end with a scripted fake model and the real tools on the test database | Wiring tested (tools, LLM selection, tasks); I didn't find a practical way to run a crew end to end with a fake model |
| Dependencies | Already in the project | ~200 extra packages (chromadb, lancedb, onnxruntime, OpenTelemetry) and `openai<3`, so it lives in a separate image (`requirements-crewai.txt`) |
| Defaults to watch | None found | Sends anonymous telemetry unless `CREWAI_DISABLE_TELEMETRY` / `OTEL_SDK_DISABLED` are set (done in code) |
| Code | 176 lines of orchestration | 196 lines, including the tool adapter and the DeepSeek workaround |

## When to choose which

- **LangGraph** when the flow is known in advance, cost and limits matter, the output must be
  structured on several providers, or the team needs to test and debug every step. That is this
  project, so it stays as the base (ADR 0005).
- **CrewAI** to prototype a multi-role idea quickly or to explain it to non-technical people: the
  role/goal/task vocabulary maps directly onto how a team describes the work, and the first
  version took little code. Budget for about 3x the tokens, check that each provider supports its
  structured-output method, and turn telemetry off.

## Limitations

The same as in [model-comparison.md](model-comparison.md) (30 synthetic tickets, one run,
string-match root cause, upper-bound costs), plus: the CrewAI version follows the LangGraph design
closely; a crew designed from scratch with more autonomy (delegation, a hierarchical process)
could behave differently, most likely with more calls, not fewer.
