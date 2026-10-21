# NOC Ticket Assistant

An API that helps Network Operations Center (NOC) operators triage incident tickets with an LLM.
Given a ticket and optional device logs or alarms, it returns structured JSON with the incident
category, severity, extracted technical entities, missing information to ask the customer,
a step-by-step diagnosis and a draft reply.

> Work in progress. Phase 0 (project skeleton, Docker Compose, configuration and `/health`) is done.

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
- [ ] Phase 1: classification and entity extraction (few-shot, structured output)
- [ ] Phase 2: persistence, migrations, `content_hash` cache, filtered listing
- [ ] Phase 3: chained diagnosis call and customer reply draft
- [ ] Phase 4: tests with a mocked LLM, CI on GitHub Actions
- [ ] Phase 5: documentation, diagram, demo
