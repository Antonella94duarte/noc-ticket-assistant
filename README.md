# NOC Ticket Assistant

An API that helps Network Operations Center (NOC) operators triage incident tickets with an LLM.
Given a ticket and optional device logs or alarms, it returns structured JSON with the incident
category, severity, extracted technical entities, missing information to ask the customer,
a step-by-step diagnosis and a draft reply.

> Work in progress. Ticket classification and entity extraction (phase 1) are in place;
> diagnosis, the reply draft and persistence come next.

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
    "missing_information": ["..."]
  },
  "model": "gpt-6-luna",
  "reasoning_effort": "medium",
  "prompt_version": "classify_v1",
  "usage": {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}
}
```

## How the prompt is built

Prompts live in `app/llm/prompts/<version>/`, separate from the code, and every response reports
the `prompt_version` that produced it.

- **Role, tone and context**: the system prompt sets a senior NOC engineer role and describes a
  small fictional network, used to judge impact.
- **Delimiters**: the ticket and logs go inside `<ticket>` and `<logs>` tags and are declared as
  data. Tags written inside the ticket are neutralized so it can't break out of its block
  (prompt-injection defense).
- **Few-shot**: four worked examples, sent as user/assistant turns. One of them contains an
  injection attempt that the expected answer ignores.
- **Conditional output**: when data is missing, the model lists questions for the customer
  instead of guessing values.
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
docker compose up -d db
uvicorn app.main:app --reload
```

Run tests and the linter:

```bash
pytest
ruff check .
```

## Roadmap

- [x] Phase 0: skeleton, Docker Compose, configuration, `/health`
- [x] Phase 1: classification and entity extraction (few-shot, structured output)
- [ ] Phase 2: persistence, migrations, `content_hash` cache, filtered listing
- [ ] Phase 3: chained diagnosis call and customer reply draft
- [ ] Phase 4: tests with a mocked LLM, CI on GitHub Actions
- [ ] Phase 5: documentation, diagram, demo
