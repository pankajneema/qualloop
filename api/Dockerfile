# One image for api / worker / dispatcher / scheduler (ARCHITECTURE section 2).
FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Dev target: includes dev dependencies, code is bind-mounted by compose.
FROM builder AS dev
RUN uv sync --frozen
COPY . .
RUN useradd --system --uid 10001 --no-create-home qualloop
USER qualloop
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM base AS runtime
# Pick up fixed OS security patches on top of the digest-pinned base (Trivy gate).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
ARG GIT_SHA=dev
ENV QL_VERSION=$GIT_SHA
RUN useradd --system --uid 10001 --no-create-home qualloop
COPY --from=builder /app/.venv /app/.venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY seeds ./seeds
USER qualloop
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["gunicorn", "app.main:create_app()", "-k", "uvicorn.workers.UvicornWorker", "-b", "0.0.0.0:8000", "--workers", "2"]
