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
├── tests/              # Test files
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

**Always create test files inside `tests/`, never inside `src/`.**

This project uses a dedicated `tests/` directory at the repo root, mirroring the
`src/rpsd_config/` package structure:

```
tests/
├── exchange_agreement/   # mirrors src/rpsd_config/exchange_agreement/
├── server/               # mirrors src/rpsd_config/server/
└── <app>/                # one subdirectory per Django app
```

- Place new test files in `tests/<app>/test_<module>.py`
- Each subdirectory under `tests/` must have an `__init__.py`
- **Do NOT place test files inside `src/`**, even though Django supports co-located
  tests. `testpaths = ["tests"]` in `pyproject.toml` means pytest will not find them.

> **Warning for users:** If you create a test file inside `src/`, pytest will silently
> ignore it and VS Code's test panel will not show it. Always use the `tests/` tree.

---
*For generic AI assistant guidelines and behavior, see `ai-context.md`.*
