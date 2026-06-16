# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /src/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ML_COPILOT_WORKSPACE_ROOT=/app \
    ML_COPILOT_DB_PATH=/data/ml-copilot.db

WORKDIR /app

RUN groupadd --system mlcopilot \
    && useradd --system --gid mlcopilot --home-dir /app --shell /usr/sbin/nologin mlcopilot \
    && mkdir -p /data \
    && chown -R mlcopilot:mlcopilot /data

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir .

COPY --from=frontend-builder /src/frontend/dist ./frontend/dist

RUN chown -R mlcopilot:mlcopilot /app

USER mlcopilot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/sessions', timeout=3).read()" || exit 1

CMD ["python", "-m", "uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
