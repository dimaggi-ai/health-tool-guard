# DIMAGGI Tool Guard — single-container runner.
# Stage 1 builds the Angular dashboard, Stage 2 serves it together with the
# FastAPI backend. The repo root is the build context (docker/compose.yml
# sets `context: ..`). Pair with docker/compose.yml, which also brings up
# Ollama and pulls gemma4:e4b on first start.

# ── 1. Build the Angular dashboard ────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /web
COPY web/package*.json ./
RUN npm install --no-audit --no-fund
COPY web/ ./
RUN npx ng build --configuration=production --base-href=/

# ── 2. Python runtime + bundled frontend ──────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# System deps for healthchecks and policy tests.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python deps first so layer caches across code edits.
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt pytest

# App code.
COPY backend/ /app/backend/
COPY tests/   /app/tests/
COPY verifier/ /app/verifier/
COPY policies/ /app/policies/
COPY sdk/      /app/sdk/

# Pre-built frontend (served by FastAPI when TOOLGUARD_SERVE_FRONTEND=1).
COPY --from=frontend /web/dist/tool-guard/browser /app/web

ENV TOOLGUARD_SERVE_FRONTEND=1 \
    TOOLGUARD_FRONTEND_DIR=/app/web \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
EXPOSE 8080

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
