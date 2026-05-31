# ── base: runtime dependencies only ──────────────────────────────────────────
FROM python:3.10-slim AS base

WORKDIR /app

# Install deps before copying source so the layer is cached on dep-only changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

EXPOSE 8000
CMD ["uvicorn", "protegopay.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


# ── test: base + dev deps + test sources ─────────────────────────────────────
FROM base AS test

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY tests/ tests/
COPY pytest.ini .

# DOCKER_TEST=1 tells conftest.py to use real Postgres + Redis
ENV DOCKER_TEST=1
ENV PYTHONPATH=/app/src

CMD ["python", "-m", "pytest", "tests/", "-v", "--tb=short"]
