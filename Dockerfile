FROM python:3.13-slim-bookworm

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

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

# Set working directory
WORKDIR /app

# Copy dependency files first (for better layer caching)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies only (cached unless pyproject.toml/uv.lock change)
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code (changes here don't invalidate dependency cache)
COPY src/ ./src/

# Now install the local project (builds webinner with src/ available)
RUN uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Collect static files
RUN uv run manage collectstatic --noinput

# Copy entrypoint script
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Set entrypoint (command comes from docker-compose.yml)
ENTRYPOINT ["./entrypoint.sh"]
