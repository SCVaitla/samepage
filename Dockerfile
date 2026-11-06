# SamePage Engine. Small, non-root, locked dependencies.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY samepage ./samepage
COPY corpus ./corpus
COPY eval ./eval
RUN uv sync --frozen --no-dev && useradd --create-home --uid 10001 samepage && mkdir -p /data && chown samepage /data
USER samepage
ENV SAMEPAGE_DB_PATH=/data/samepage.sqlite SAMEPAGE_REPORTS_DIR=/data/reports PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["samepage", "serve", "--port", "8080"]
