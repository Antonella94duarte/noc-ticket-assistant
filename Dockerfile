FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY data/network ./data/network
COPY data/runbooks ./data/runbooks
COPY app ./app

RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Apply pending migrations, reload the synthetic network data, then start the API. With several
# replicas, run the first two as a separate step instead.
CMD ["sh", "-c", "alembic upgrade head && python -m app.db.seed && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
