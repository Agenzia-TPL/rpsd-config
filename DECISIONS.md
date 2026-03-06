# Architectural Decisions

This file records significant architectural decisions made in this project.
Format: Problem → Options considered → Decision → Rationale.

---

## ADR-001: Production ASGI server — Gunicorn + UvicornWorker

**Date:** 2026-03-06

**Problem**

Need a production-grade server for a Django + Django-ninja (async-capable) app
deployed across Docker Compose, Docker Swarm, and Kubernetes.

**Options considered**

- Pure Gunicorn with sync workers (WSGI): loses ASGI/async support needed by Django-ninja
- Pure Uvicorn with `--workers`: works, but less mature process management than Gunicorn
- Gunicorn + UvicornWorker: official recommendation from both Gunicorn and Uvicorn projects

**Decision**

Gunicorn as process manager with `uvicorn.workers.UvicornWorker`.

**Rationale**

- Gunicorn handles process lifecycle, graceful restarts, and SIGTERM correctly
- UvicornWorker provides full ASGI support for async Django-ninja handlers
- Orchestrators (K8s, Swarm) handle horizontal scaling; Gunicorn manages workers per container
- `gunicorn.conf.py` at project root is auto-detected from CWD — no CLI arg clutter
- Config values (`APP_PORT`, `GUNICORN_WORKERS`, etc.) come from `.env` files,
  consistent with how Django reads its own settings via Pydantic Settings
