# ADR 0001: Evolve the assistant into a multi-agent system in the same repository

- Status: accepted
- Date: 2026-10-23

## Context

The current assistant analyzes a ticket with two chained LLM calls (classify, then diagnose). The
model only sees what the ticket says: it cannot check active alarms, the topology or the
procedures a NOC engineer would use, so its diagnosis stays generic when the ticket is vague.

The next step is an agentic version that investigates before diagnosing, built with the
frameworks this kind of work uses in practice (LangGraph, LlamaIndex, CrewAI), and compared
against cheaper models (DeepSeek, a local model through Ollama).

## Decision

1. **Same repository.** The existing chained pipeline stays as the non-agent baseline. Every
   agentic variant is evaluated against it on the same labeled tickets, so the project can answer
   a concrete question: how much does tool use improve the analysis, and what does it cost?
2. **Network data in the existing PostgreSQL.** Sites, devices, links, circuits and alarms are
   new tables managed with Alembic, next to `tickets`. The tools that agents call are plain Python
   functions over this database, independent of any agent framework, so LangGraph and CrewAI use
   exactly the same tools and the comparison is fair.
3. **Providers.** OpenAI (`gpt-6-luna`) is the reference; DeepSeek and a local model through
   Ollama are compared against it.
4. **Synthetic data only**, and technical documentation in English.

## Alternatives considered

- **A new `noc-agents` repository.** A cleaner start, but it would duplicate the API, persistence,
  CI and eval harness, and lose the baseline that makes the comparison meaningful.
- **SQLite for the network data.** Portable and Docker-free, but it adds a second database while
  PostgreSQL, migrations and database tests are already in place.

## Consequences

- The LLM layer has to support Chat Completions-compatible providers, not only the OpenAI
  Responses API used today (DeepSeek and Ollama don't implement Responses).
- Tests keep running without network or API keys: tools are tested against the seeded test
  database, and agents against a fake model.
