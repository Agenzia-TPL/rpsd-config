FROM python:3.13-slim-bookworm

# Install native GIS dependencies required by django[gis] for CI (lint, test, license check).
# This image avoids reinstalling GDAL from scratch on every CI run.
RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        gdal-bin \
        libgdal-dev \
        libproj-dev \
        git && \
    rm -rf /var/lib/apt/lists/*
