# See here for image contents: https://github.com/devcontainers/images/blob/main/src/python/.devcontainer/Dockerfile

# [Choice] Python version (use -bookworm or -bullseye variants on local arm64/Apple Silicon): 3, 3.13, 3.12, 3.11, 3.10, 3.9, 3-bookworm, 3.13-bookworm, 3.12-bookworm, 3.11-bookworm, 3.10-bookworm, 3.9-bookworm, 3-bullseye, 3.13-bullseye, 3.12-bullseye, 3.11-bullseye, 3.10-bullseye, 3.9-bullseye, 3-buster, 3.12-buster, 3.11-buster, 3.10-buster, 3.9-buster

# Stage 1: Base
ARG VARIANT="3.13-bookworm"
FROM mcr.microsoft.com/devcontainers/python:1-${VARIANT} AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Stage 2: for development (devcontainer)
FROM base AS development

# Copy everything at once - no layer separation needed for development
COPY pyproject.toml uv.lock ./

# Remove empty placeholder lockfile, then generate real one
# (notice the "--dev" and "--no-install-project" flags)
RUN if [ ! -s uv.lock ]; then rm uv.lock; fi && \
    uv lock && \
    uv sync --dev --no-install-project

# Stage 3: production
FROM base AS production

WORKDIR /app  # Only set WORKDIR for production

# Copy and install production dependencies
COPY pyproject.toml uv.lock ./

# Remove empty placeholder lockfile, then generate real one
# (notice the "--no-dev" flag)
RUN if [ ! -s uv.lock ]; then rm uv.lock; fi && \
    uv lock && \
    uv sync --no-dev
