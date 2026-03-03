# See here for image contents: https://github.com/devcontainers/images/blob/main/src/python/.devcontainer/Dockerfile

# Stage 1: Base
ARG VARIANT="3.13-bookworm"
FROM mcr.microsoft.com/devcontainers/python:1-${VARIANT} AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Stage 2: for development (devcontainer)
FROM base AS development

# Remove Yarn repository that comes with the base image (to avoid GPG key issues)
# Then install native GIS/Postgres dependencies required by django[gis] and PostGIS backend.
RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libproj-dev \
        postgresql-client \
        postgis \
        binutils \
        build-essential && \
    rm -rf /var/lib/apt/lists/*
