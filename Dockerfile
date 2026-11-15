# Container image for the API (control C31: non-root, minimal contents).
#
# Docker concepts used here, for the owner:
#  * An IMAGE is a frozen filesystem + start command. A CONTAINER is a running copy of it.
#  * A MULTI-STAGE build uses several `FROM` blocks. Early stages ("builder") may contain
#    compilers and caches; the final stage copies only the finished result, so the shipped
#    image is smaller and has less in it to attack.
#  * Each instruction (FROM, RUN, COPY) makes a cached LAYER. Put things that change rarely
#    (dependencies) before things that change often (our code), so rebuilds are fast.
#  * `.dockerignore` lists files that are never sent to the build (secrets, data).
#
# Build:  docker build -t mdr-api:test .
# Run:    docker run --rm -p 8000:8000 -e DATABASE_URL=... -e OPENROUTER_API_KEY=... mdr-api:test
# Config comes from environment variables at run time. No env file is baked into the image.

# ---- Stage 1: builder -------------------------------------------------------------------
# Pinned to an exact patch tag so builds are repeatable; upgrade deliberately.
FROM python:3.12.13-slim-bookworm AS builder

# Copy the uv binary from its official image (pinned; matches the version used in dev).
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# UV_COMPILE_BYTECODE: precompile .pyc for faster start. UV_LINK_MODE=copy: real copies
# (hardlinks across layers don't work). UV_PYTHON_DOWNLOADS=never: use this image's Python.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Layer 1: third-party dependencies only. Reused until pyproject.toml or uv.lock changes.
# --locked fails if the lock is stale; --no-dev skips pytest/ruff/mypy.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-editable

# Layer 2: our package. Only src/ is copied (not tests, scripts, docs, evals, data).
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# ---- Stage 2: runtime -------------------------------------------------------------------
FROM python:3.12.13-slim-bookworm AS runtime

# A dedicated unprivileged user. If the app were ever compromised, the attacker is not
# root inside the container. Fixed numeric UID so hosts can enforce "runAsNonRoot".
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

# Only the finished virtualenv comes across: no uv, no build caches, no source tree.
COPY --from=builder --chown=app:app /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

WORKDIR /app
USER app

# Documentation only (it does not publish the port); `docker run -p` or the host does.
EXPOSE 8000

# Docker runs this inside the container every 30s; three failures mark it "unhealthy".
# Python's stdlib is used so the image needs no curl. Reads $PORT like the server does.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os,sys,urllib.request as u; sys.exit(0 if u.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health', timeout=2).status == 200 else 1)"]

# `sh -c` so $PORT is expanded; `exec` replaces the shell with uvicorn so it receives stop
# signals (SIGTERM) directly and shuts down cleanly. Hosts usually set PORT; locally it
# defaults to 8000. 0.0.0.0 = listen on all interfaces INSIDE the container (required for
# a published port to reach it).
CMD ["sh", "-c", "exec uvicorn multimodal_doc_rag.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
