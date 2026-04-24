# Project Context

This file provides project-specific context for AI coding assistants.

## Project Overview

This is the **Config service** of the **Rapsodia platform** (`rpsd-config`).
It is a Django-based REST API that manages configuration data for other
Rapsodia services.

## Project Structure

```
project-root/
├── pyproject.toml      # Project configuration
├── uv.lock             # Lock file
├── src/                # Project source files
│   └── rpsd_config/    # Django application package
├── tests/              # Unit tests (no external services)
├── tests_integration/  # Integration tests (require DB, Keycloak, etc.)
└── README.md           # Project documentation
```

## Project-Specific Guidelines

- This service is part of the larger Rapsodia platform; changes may affect
  other services that depend on configuration data
- Follow the existing Django application structure under `src/rpsd_config/`
- Use `--package rpsd-config` when targeting this package in uv workspace
  commands, if applicable

---

## Technology Stack

- **Language:** Python 3.13+
- **Framework:** Django (REST API) + Django-ninja (async API support)
- **Package Manager:** uv (not pip/poetry/conda)
- **Production server:** Gunicorn (process manager) + UvicornWorker (ASGI)
- **Testing:** pytest
- **Linting/Formatting:** ruff

## Development Environment

- **Containerization:** Docker + devcontainers

## Common Development Commands

- `uv sync` - Install/update all dependencies
- `uv add <package>` - Add a dependency
- `uv run pytest` - Run tests
- `uv run ruff format` - Format code
- `uv run ruff check --fix` - Auto-fix linting issues
- `uv run python` - Execute Python code on the fly
- `uv run devserver` - Run Django dev server with configured host/port (devcontainer)

See `USAGE.md` for running with Docker (integration tests, staging, production).

## Development Guidelines

- **IMPORTANT:** Always use `uv` commands, never `pip`, `poetry`, or `conda`
- Run `uv sync` after adding/removing dependencies
- Use `uv run pytest` to run tests after making changes
- Use `uv run ruff format` and `uv run ruff check --fix` for code quality
- For workspace projects, use `--package <member>` when targeting specific packages

## Coding Standards

- Follow PEP 8 for Python code style
- Use type hints where applicable
- Use ruff for formatting and linting
- Write docstrings for all public functions and classes
- Always prefer absolute imports over relative ones
- Do not use workarounds such as `# type: ignore[arg-type]`
- Do not use workarounds such as `cast()`
- Use Pydantic Settings (not python-decouple or python-dotenv) for full type inference

## Code Quality Requirements

- Generate code that passes the configured Ruff rules
- Use modern Python type hints: `dict` not `Dict`, `list` not `List`, `str | None` not `Optional[str]`
- Keep lines under 88 characters (project's line length limit)
- Sort and format imports properly (standard library, third-party, local imports in separate groups)
- Remove unused imports
- Add trailing newlines to all filesode
- Avoid f-strings without placeholders — use regular strings instead
- Break long lines using parentheses, multi-line strings, or temporary variables

## Test File Placement

**Always create test files inside `tests/` or `tests_integration/`, never inside `src/`.**

Tests are split into two root-level directories based on their external service requirements:

```
tests/                        # Unit tests — no external services required
├── server/                   # mirrors src/rpsd_config/server/
└── <app>/                    # one subdirectory per Django app

tests_integration/            # Integration tests — require PostgreSQL, Keycloak, etc.
├── server/
└── exchange_agreement/       # mirrors src/rpsd_config/exchange_agreement/
```

### Which directory to use

| Test type | Directory | Criterion |
|-----------|-----------|-----------|
| Unit test | `tests/` | Uses `SimpleTestCase`; all external calls mocked |
| Integration test | `tests_integration/` | Uses `TestCase`; touches real DB, Keycloak, or other services |

### Rules

- Place new test files in `<dir>/<app>/test_<module>.py`
- Each subdirectory must have an `__init__.py`
- **Do NOT place test files inside `src/`** — `testpaths = ["tests"]` in `pyproject.toml`
  means pytest will not find them

### Running tests

```bash
# CI / default — unit tests only (always pass, no services needed)
pytest

# Integration tests — requires services running (see USAGE.md)
pytest tests_integration/ --reuse-db

# Everything
pytest tests/ tests_integration/ --reuse-db
```

`--reuse-db` is already in `addopts` so it applies automatically when running
`tests_integration/` from VS Code as well.

> **Warning:** If you create a test that requires the database (inherits from `TestCase`
> or uses `@pytest.mark.django_db`) inside `tests/`, it will cause CI to fail. Put it
> in `tests_integration/` instead.

### VS Code test discovery

`.vscode/settings.json` passes both directories to pytest explicitly:

```json
"python.testing.pytestArgs": ["tests", "tests_integration"]
```

This makes all 70 tests visible in the Test Explorer. Integration tests will appear
as failed/errored when services are not running — which is intentional and honest.
Do not remove `tests_integration` from this list.

---
*For generic AI assistant guidelines and behavior, see `ai-context.md`.*
