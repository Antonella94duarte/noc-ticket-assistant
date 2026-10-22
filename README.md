# NOC Ticket Assistant

[![CI](https://github.com/Antonella94duarte/noc-ticket-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Antonella94duarte/noc-ticket-assistant/actions/workflows/ci.yml)

An API that helps Network Operations Center (NOC) operators triage incident tickets with an LLM.
Given a ticket and optional device logs or alarms, it returns structured JSON with the incident
category, severity, extracted technical entities, missing information to ask the customer,
a step-by-step diagnosis and a draft reply.

> Work in progress. The analysis pipeline, persistence, tests and CI (phases 1-4) are in place;
> the final documentation and demo come next.

All tickets and logs in this repository are synthetic.

## Stack

FastAPI · Pydantic v2 · PostgreSQL · SQLAlchemy 2.0 · Alembic · pytest · Docker Compose · ruff

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

Interactive API docs: http://localhost:8000/docs

`POST /api/v1/tickets/analyze` needs `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`
(it answers 503 until they are set). `OPENAI_REASONING_EFFORT` (default `medium`) controls how
much the model reasons before answering; reasoning tokens are billed as output.

## Usage

```bash
curl -X POST http://localhost:8000/api/v1/tickets/analyze   -H "Content-Type: application/json"   --data-binary @data/samples/interface_errors.json
```

```json
{
  "id": "3d490895-…",
  "created_at": "2026-10-21T23:13:20Z",
  "ticket_text": "Cliente de SITE-ESTE-04 reporta cortes intermitentes…",
  "logs": "sw-este-04 Gi1/0/12 is up, line protocol is up…",
  "cached": false,
  "classification": {
    "category": "latency_packet_loss",
    "severity": "minor",
    "severity_reason": "...",
    "entities": {
      "sites": ["SITE-ESTE-04"],
      "devices": ["sw-este-04"],
      "interfaces": ["Gi1/0/12"],
      "ip_addresses": [],
      "event_time": "09:15"
    },
    "missing_information": ["¿Cuál es el circuito o servicio afectado?", "..."]
  },
  "diagnosis": {
    "reasoning": [
      "El contador muestra 1873 errores de entrada, incluidos 1650 CRC...",
      "..."
    ],
    "probable_causes": [
      {"cause": "Problema físico en el enlace de Gi1/0/12...", "likelihood": "medium", "evidence": "..."}
    ],
    "diagnostic_steps": [
      {"action": "...", "command": "show interfaces Gi1/0/12", "expected_result": "..."}
    ],
    "recommended_actions": ["..."],
    "customer_reply": "Lamentamos los inconvenientes que están teniendo con las videollamadas..."
  },
  "model": "gpt-6-luna",
  "reasoning_effort": "medium",
  "prompt_version": "classify_v2+diagnose_v1",
  "usage": {"input_tokens": 3785, "output_tokens": 1804, "reasoning_tokens": 273, "total_tokens": 5589}
}
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/tickets/analyze` | Analyze a ticket (text + optional logs). `201` when new, `200` with `"cached": true` when an identical ticket was already analyzed |
| `GET` | `/api/v1/tickets/{id}` | A ticket with its stored classification and diagnosis |
| `GET` | `/api/v1/tickets` | Newest first, filters `category` and `severity`, pagination `limit` (max 100) and `offset` |
| `GET` | `/health` | API and database status (`503` when the database is down) |

## Data model

One `tickets` table keeps the ticket, its analysis and how it was produced:

- The full analysis is a **JSONB** column, so reading a ticket with its analysis is one query, no joins.
- `category` and `severity` are plain indexed columns (composite indexes with `created_at`), because
  the listing filters and sorts by them.
- `content_hash` is a SHA-256 of the ticket text and logs, ignoring line endings and edge
  whitespace. It is unique together with `prompt_version`: an identical ticket is served from the
  database without calling the model, and a new prompt version gets a fresh analysis. Two identical
  requests racing each other end up with one row.
- The listing selects only summary columns (the text is cut to 120 characters in SQL) and gets the
  total from a window function in the same query.
- `prompt_version`, `model`, `reasoning_effort` and token counts are stored with every analysis.

Migrations are managed with Alembic and run automatically when the API container starts.

## How the analysis works

Each ticket goes through two chained model calls (`app/services/analyzer.py`):

1. **Classify** (`classify_v2`): category, severity, entities and the questions still open for the
   customer. Few-shot, short output.
2. **Diagnose** (`diagnose_v1`): receives the ticket plus the classification as JSON and returns
   step-by-step reasoning, probable causes with their evidence, diagnostic steps with CLI commands,
   immediate actions and a draft reply to the customer.

Splitting the work keeps each prompt focused, lets each step be versioned and tested on its own,
and gives the diagnosis a structured starting point. If either call fails nothing is stored, so a
half analysis is never served from the cache.

With `gpt-6-luna` at `medium` effort, an analysis takes about 13-18 s and ~5,500 tokens
(about US$0.0013) on the sample tickets.

## How the prompts are built

Prompts live in `app/llm/prompts/<version>/`, separate from the code, and every response reports
the `prompt_version` that produced it. Older versions are kept so stored analyses stay traceable.

- **Role, tone and context**: the system prompt sets a senior NOC engineer role and describes a
  small fictional network, used to judge impact.
- **Delimiters**: the ticket and logs go inside `<ticket>` and `<logs>` tags and are declared as
  data. Tags written inside the ticket are neutralized so it can't break out of its block
  (prompt-injection defense). The classification passed to the second call gets the same
  treatment, since it was generated from customer text.
- **Few-shot**: five worked classification examples, sent as user/assistant turns. One contains an
  injection attempt that the expected answer ignores; another teaches that lost redundancy is
  `major` even before customers notice.
- **Conditional output**: when data is missing, the classification lists questions instead of
  guessing values, and the diagnosis marks itself as provisional and puts those questions in the
  customer reply.
- **Chain of thought**: `reasoning` is the first field of the diagnosis schema. The model writes
  JSON in schema order, so it lays out the evidence before reaching conclusions, and the operator
  can audit how it got there.
- **Structured output**: the OpenAI Responses API with Structured Outputs enforces the Pydantic
  schema, and the reply is validated again on our side. Refusals and truncated replies become a
  502 instead of bad data.

The OpenAI client sits behind `app/llm/client.py`, so the rest of the app depends on a small
interface and tests inject a fake client.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
docker compose up -d db         # published on host port 5433
alembic upgrade head
uvicorn app.main:app --reload
```

Run tests and the linter:

```bash
pytest
ruff check .
```

Tests never call OpenAI: the LLM client is a FastAPI dependency that the tests replace with a fake,
so they are free, fast and deterministic.

Database tests run against a real PostgreSQL in a separate `noc_tickets_test` database (created and
migrated with Alembic, each test rolled back). Point `TEST_DATABASE_URL` elsewhere if needed. If
PostgreSQL isn't reachable those tests are skipped locally, but they fail in CI so a broken setup
can't produce a green build.

## Continuous integration

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull request:

- **lint**: `ruff check` and `ruff format --check`.
- **test**: `pytest` against a PostgreSQL 16 service container, so the migrations and every
  database test run in CI.

## Evaluating prompts

`data/eval/classification.jsonl` holds 12 labeled synthetic tickets, separate from the few-shot
examples and the samples. When a case has more than one defensible answer under the rubric, its
label lists all of them, so label ambiguity isn't counted as a model error.

`scripts/evaluate.py` runs the classification step over them with the real model and reports
accuracy and tokens. It spends tokens, so it runs by hand, not in CI:

```bash
python scripts/evaluate.py                                   # current prompt and settings
python scripts/evaluate.py --prompt-version classify_v1 --effort low
```

Results with `gpt-6-luna` (one run each):

| Prompt | Effort | Category | Severity | Output tokens |
|---|---|---|---|---|
| classify_v2 | medium | 12/12 | 12/12 | 4,171 |
| classify_v1 | medium | 12/12 | 12/12 | 3,597 |
| classify_v2 | low | 11/12 | 11/12 | 1,240 |

What this shows:
- At `medium` effort both prompts get every case right, so this set no longer separates them. It
  works as a regression guard; telling prompt versions apart needs harder cases.
- At `low` effort, `classify_v2` labeled "Tenemos problemas con el servicio" as a major
  connectivity loss: the new rule for vague total outages ("no anda nada") was applied to a ticket
  that never says the service is down. A prompt fix can introduce its own error, which is why the
  set exists.
- A single run per configuration doesn't capture the model's run-to-run variation.

## Roadmap

- [x] Phase 0: skeleton, Docker Compose, configuration, `/health`
- [x] Phase 1: classification and entity extraction (few-shot, structured output)
- [x] Phase 2: persistence, migrations, `content_hash` cache, filtered listing
- [x] Phase 3: chained diagnosis call and customer reply draft
- [x] Phase 4: tests with a mocked LLM, CI on GitHub Actions, prompt evaluation set
- [ ] Phase 5: documentation, diagram, demo
