# syntax=docker/dockerfile:1.7

# UV_VERSION is required; supplied by docker-compose / Makefile from the
# repo-root .tool-versions file so the workflow, Dockerfile, and local
# tooling stay in lockstep on a single source of truth.
ARG UV_VERSION

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv-bin

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY app ./app

EXPOSE 8080

HEALTHCHECK --interval=5s --timeout=3s --start-period=3s --retries=10 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
