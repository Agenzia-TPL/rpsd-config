# Usage Guide

Operational guide for running and configuring `rpsd-config`.

---

## Running the Service

### Devcontainer (development)

Inside the VS Code devcontainer:

```bash
uv run devserver
```

Uses Django's built-in `runserver`. Reads `APP_HOST` and `APP_PORT` from settings.
Hot-reload is enabled. Not for production use.

### Docker (integration tests, staging, production)

The Docker image is built from `Dockerfile` (project root) and does not embed a default
command — each deployment config provides it.

**Required command in your compose / Swarm / K8s config:**

```yaml
command: ["gunicorn", "rpsd_config.server.asgi:application"]
```

Gunicorn auto-detects `gunicorn.conf.py` from the container's working directory (`/app/`).
No `-c` flag is needed.

**Example Docker Compose service:**

```yaml
rpsd-config:
  image: rpsd-config:local
  build:
    context: ./rpsd-config
    dockerfile: ./Dockerfile      # use project root Dockerfile, NOT .devcontainer/Dockerfile
  command: ["gunicorn", "rpsd_config.server.asgi:application"]
  ports:
    - "${APP_PORT:-8989}:8989"
  volumes:
    - ./rpsd-config/.env.base:/app/.env.base:ro
    - ./rpsd-config/.env:/app/.env:ro
```

---

## Configuration

Settings are managed via `.env.base` and `.env` files at the project root.

- `.env.base` — scenario defaults (checked in or per-deployment baseline)
- `.env` — local overrides (git-ignored)

`.env` takes precedence over `.env.base`. Both files are mounted into the container
as read-only volumes and are also read directly by Pydantic Settings.

### Available environment variables

| Variable | Default | Used by | Description |
|---|---|---|---|
| `APP_HOST` | `0.0.0.0` | Django devserver | Bind host for devserver |
| `APP_PORT` | `8989` | gunicorn, Django devserver | Bind port |
| `APP_EXTERNAL_SCHEME` | `http` | Django | Scheme for CSRF trusted origins |
| `APP_EXTERNAL_HOST` | `localhost` | Django | External hostname |
| `APP_EXTERNAL_PORT` | `8989` | Django | External port |
| `GUNICORN_WORKERS` | `2` | gunicorn | Number of worker processes per container |
| `GUNICORN_TIMEOUT` | `30` | gunicorn | Worker timeout in seconds |
| `DJANGO_SECRET_KEY` | insecure default | Django | **Set this in production** |
| `DEBUG` | `True` | Django | Set to `False` in production |

### Configuration flow

```
.env / .env.base
      │
      ├─→ Docker Compose (volumes) → Pydantic Settings → Django
      └─→ Docker Compose (env_file:) → container env vars → gunicorn.conf.py (os.getenv)
```

Both Gunicorn and Django read from the same source. No duplication of values.

---

## Database

Configure via environment variables using double-underscore nesting:

```
DATABASES__default__HOST=postgis
DATABASES__default__NAME=rpsd
DATABASES__default__USER=rpsd
DATABASES__default__PASSWORD=rpsd
DATABASES__default__PORT=5432
```

---

## Static Files

Static files are collected at build time (`RUN uv run manage collectstatic --noinput`
in the Dockerfile) and served from `/app/staticfiles/`.

For production, configure a reverse proxy (nginx, Traefik) to serve `/static/` directly
from that directory.
