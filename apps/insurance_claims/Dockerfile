# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY claims_agent ./claims_agent
COPY evals ./evals
RUN pip install --upgrade pip && pip install . && python -m spacy download en_core_web_sm

COPY fixtures ./fixtures
COPY web ./web

RUN useradd --create-home --uid 10001 appuser && mkdir -p /data && chown appuser /data
USER appuser

# Demo defaults (override with -e or .env). No API key -> deterministic rules mode.
ENV FIXTURES_DIR=/app/fixtures APP_TODAY=2026-09-28 DEBUG_PANEL=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status == 200 else 1)"
CMD ["uvicorn", "--factory", "claims_agent.api:create_app", "--host", "0.0.0.0", "--port", "8000"]
