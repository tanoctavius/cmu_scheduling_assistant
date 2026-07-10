# Python 3.11 base — matches the backend's target runtime.
# Node 20 is layered on via the devcontainer "node" feature (see devcontainer.json).
FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

# --- uv (Python package/proj manager) ---
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# uv env: create the venv inside the project, don't try to manage Python itself
ENV UV_PROJECT_ENVIRONMENT=/workspaces/cmu-scheduler/backend/.venv \
    UV_LINK_MODE=copy

# --- Preinstall backend deps so the container is ready on first open ---
# Copy only the dependency manifests first for better layer caching.
WORKDIR /tmp/deps
COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/README.md ./backend/README.md
RUN mkdir -p backend/app && touch backend/app/__init__.py \
    && cd backend \
    && uv sync --no-install-project \
    && rm -rf /tmp/deps
