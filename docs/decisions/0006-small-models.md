# ADR 0006: Keep the LLM for triage; allow a local Hugging Face model for runbook search

- Status: accepted
- Date: 2026-10-25

## Context

Every step of the agent uses an LLM. Small open models from Hugging Face run for free on a CPU
and keep data in the process, so it is worth knowing which steps they can take over. Two were
measured on the existing evaluation sets: zero-shot classification for triage (53 labeled
tickets) and sentence embeddings for runbook search (18 labeled queries). Full write-up:
[small-models-comparison.md](../small-models-comparison.md).

## Decision

- **Triage stays on the LLM.** The best zero-shot model got 30/53 categories and 20/53
  severities, against 27/53 and 38/53 for always answering the most common label, and 53/53 and
  46/53 for the LLM. The zero-shot classifier stays in `app/small_models/` with its evaluation, as
  the measured baseline, not as part of the agent.
- **Runbook search gains `RUNBOOK_RETRIEVER=hf`**, a Hugging Face embedding model run in-process
  (default `paraphrase-multilingual-MiniLM-L12-v2`, 118M). It matches OpenAI and `bge-m3` (18/18)
  without an API or an Ollama server. BM25 stays the default, because the agent queries with alarm
  type names, which BM25 already handles, and it needs no extra dependencies.
- The Hugging Face dependencies live in `requirements-hf.txt` and their own image, like CrewAI
  (ADR 0005), with PyTorch's CPU build. The tests use a fake pipeline and a stand-in embedding
  class, so CI needs neither.

## Consequences

- An agent that must not call external APIs can now run fully local: Ollama for the model and a
  local embedding model for the runbooks, either through Ollama (`bge-m3`) or in-process (`hf`).
- In-process embeddings load the model at start-up. That took 80-100 s here because of requests to
  the Hugging Face Hub; a deployment should download the model into the image and run with
  `HF_HUB_OFFLINE=1`.
- Revisit triage with a small model only after there are a few hundred labeled tickets to
  fine-tune on (e.g. SetFit); zero-shot is not enough.
