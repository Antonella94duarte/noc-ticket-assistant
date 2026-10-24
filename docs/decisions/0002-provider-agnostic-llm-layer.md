# ADR 0002: Provider-agnostic LLM layer for the agents, built on LangChain chat models

- Status: accepted
- Date: 2026-10-23

## Context

The baseline pipeline calls the OpenAI Responses API directly (`app/llm/client.py`). The agents
must run on several providers so they can be compared on accuracy, cost and latency: OpenAI,
DeepSeek and a local model through Ollama. These providers differ in ways that matter:

| | OpenAI (`gpt-6-luna`) | DeepSeek (`deepseek-flash`) | Ollama (`qwen3`) |
|---|---|---|---|
| API | Responses and Chat Completions | Chat Completions-compatible (no Responses) | Native and OpenAI-compatible |
| Tool calling | Yes | Yes | Yes (model dependent) |
| Strict JSON schema | Yes | Beta endpoint only | `format` with a JSON schema |
| Temperature | Not for reasoning models | Ignored in thinking mode | Yes |
| Thinks by default | Yes (reasoning effort) | Yes (`thinking`) | `qwen3`: yes |
| Forced tool call | Yes | Not in thinking mode | Yes |
| Data leaves the machine | Yes | Yes (servers in China) | No |

DeepSeek's model names changed: the current models are `deepseek-flash` and `deepseek-v4-pro`,
while some integration docs still show `deepseek-chat` and `deepseek-reasoner`. Checked against
the official docs on 2026-10-23.

## Decision

- Agents depend only on LangChain's `BaseChatModel`. `app/llm/providers.py` builds one from the
  settings: `LLM_PROVIDER` picks it, so switching provider is a `.env` change.
- Each provider's quirks stay inside the factory (reasoning effort vs temperature, base URLs,
  thinking on or off). `structured_output()` picks the method each provider supports: a strict
  JSON schema for OpenAI and Ollama; for DeepSeek, JSON mode with the schema in the prompt while
  it thinks (its default, which can't force a function call), or function calling with
  `DEEPSEEK_THINKING=false`. Pydantic validates every result.
- `LLM_FALLBACK_PROVIDERS` lists the providers to try when the primary one fails. Single calls use
  `with_fallbacks`; agents will use LangChain's `ModelFallbackMiddleware`, because a fallback
  wrapper can't bind tools.
- Every fallback must be configured at startup: a backup that can't start would only fail in the
  middle of an incident.
- The network tools are wrapped as LangChain tools in `app/tools/langchain_tools.py`, with
  docstrings written for the model and compact JSON results.
- `scripts/check_providers.py` verifies with real calls that each provider can call the right
  tool and return a valid structured classification, and reports latency and tokens.

## First checks (`scripts/check_providers.py`, 2026-10-23)

The ticket is "customer SUR-2210 without internet"; the expected answer is a major
connectivity loss (one customer down).

| Provider | Tool calling | Structured output | Notes |
|---|---|---|---|
| OpenAI `gpt-6-luna` | pass, 2.6-4.0 s | pass, 4.8-6.7 s, `connectivity_loss/major` | |
| DeepSeek `deepseek-flash`, thinking on (default) | pass, 1.4 s | pass, 4.9 s, `connectivity_loss/major` | Called two tools in parallel (alarms and site). First attempt failed: thinking mode rejects a forced function call |
| DeepSeek `deepseek-flash`, thinking off | pass, 1.7 s | pass, 2.4 s, `connectivity_loss/critical` | `DEEPSEEK_THINKING=false` |
| Ollama `qwen3:4b`, thinking on (default) | pass, 5.1-11.8 s | pass, 22-23 s, `connectivity_loss/critical` | 1,700 output tokens of thinking; first call 105 s while the model loads into the GPU |
| Ollama `qwen3:4b`, thinking off | pass, 5.2 s | pass, 3.0 s, `hardware_failure/critical` | `OLLAMA_REASONING=false` |

These are smoke tests of one question each, not an evaluation: they show that every provider
can drive the agents. They already hint at the trade-off to measure later: without thinking,
both cheaper models answer faster but overrate the severity or pick the wrong category.

## Alternatives considered

- **One OpenAI client with a different `base_url` per provider.** Simple, and DeepSeek and Ollama
  accept it, but it gives up the Responses API for OpenAI, gives no fallback or tool-binding
  support, and LangGraph and CrewAI would need adapters anyway.
- **LiteLLM as the abstraction.** Good provider coverage, but one more layer between LangGraph and
  the models, and LangChain's integrations already cover the three providers.

## Consequences

- The baseline keeps its own OpenAI client; both paths coexist until the evaluation shows whether
  the agents are worth their cost.
- Privacy: tickets sent to OpenAI or DeepSeek leave the machine. All data in this repository is
  synthetic; with real customer data, the local model or a provider under a data processing
  agreement would be required.
