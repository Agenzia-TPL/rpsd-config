# rpsd-config — Configuration Service for the Rapsodia Platform

`rpsd-config` is the configuration and contract-management service of the
**Rapsodia** platform, developed by Agenzia TPL Bacino Città Metropolitana
Milano, Monza e Brianza, Lodi, Pavia.

## Description

The Rapsodia platform supports local public transport authorities in monitoring
the quality of service delivered by transport operators under contractual
agreements. `rpsd-config` is the component that stores and manages all the
configuration needed for this monitoring:

- **Who is involved** — transport agencies (contracting authorities),
  companies (operators), and territorial authorities (Regions, Municipalities).
- **What is being monitored** — datasets, data structures, and indicator
  definitions that describe how service performance is measured.
- **How it is configured** — contracts link agencies and operators to a set
  of indicators, thresholds, and data-ingestion profiles.
- **Versioned publications** — once a contract is configured, it can be
  published as an immutable, checksum-verified snapshot used downstream by
  other platform components.

The service is intended for use by technical staff of transport authorities and
operators who manage the monitoring configuration. It exposes a REST API (based
on Django Ninja / OpenAPI) and an administration back-office.

## Domain Model (High Level)

The domain starts from stakeholders:

- `Agency`: client / contracting authority
- `Company`: operator / contractor
- `Authority`: territorial authority (Region, Municipality, etc.), optionally with GIS geometry

Service network modeling is intentionally split:

- Django currently keeps `Lot` as contractual context
- operational network details (routes/stops/trips) are delegated to an external PostgreSQL database

Note: the former Django runtime models for service-network details (`Route`, `Stop`, `Trip`, `TripStop`) have been removed from the Django runtime and are now expected to be managed in an external PostgreSQL database.

This keeps the Django codebase focused on contracts and monitoring configuration while reducing coupling with detailed network operations.

### Datasets and Structures

- `Dataset` identifies data families (for example NetEx, SIRI PT, SIRI VM)
- `Structure` describes logical sections/segments of a dataset (with JSON definition, selectors, required fields)
- `IndicatorDef` defines monitoring indicators and the dataset structures required to compute them

### Contracts and Monitoring Configuration

- `Contract` represents a service contract between one client agency and one contractor company, bound to one `Lot`
- `ContractDocument` stores supporting contract documents
- `ContractIndicator` associates indicators to a contract with contract-specific JSON parameters (thresholds, weights, etc.)
- `FlowProfile` stores reusable operational ingestion/retention configuration that can be assigned to contracts

### Access and Onboarding

- `ContractMembership` handles contract-scoped access roles
- `ContractInvitation` handles invitation-token based onboarding

### Contract Publications

`ContractPublication` stores immutable, versioned publication snapshots of a contract aggregate:

- per-contract progressive `publication_version`
- publication metadata (`published_at`, `published_by`)
- frozen JSON snapshot (`snapshot`)
- checksum (`snapshot_checksum`)

Republishing creates a new publication version and preserves history.

## Repository Structure

```
rpsd-config/
├── src/
│   └── rpsd_config/
│       ├── server/              # Django project: settings, ASGI/WSGI entry-points, URLs, OIDC
│       ├── exchange_agreement/  # Core domain: models, API, admin, services, migrations
│       ├── admin_agreements/    # Admin proxy app for contract views
│       ├── admin_stakeholders/  # Admin proxy app for agency/company/authority views
│       ├── admin_service_net/   # Admin proxy app for service-network views
│       ├── admin_dataset_exchange/ # Admin proxy app for dataset/indicator views
│       ├── app1/                # Placeholder / sandbox app
│       ├── static/              # Static assets
│       └── templates/           # Django templates
├── tests/                       # pytest test suite (mirrors src/ structure)
├── ai-skills/                   # AI coding-agent skill definitions
├── .github/workflows/           # CI/CD pipelines (test, lint, SPDX check, build)
├── pyproject.toml               # Project metadata and dependency declarations
├── uv.lock                      # Locked dependency tree (uv)
├── Dockerfile                   # Production container image
├── docker-compose.yml           # Local development compose stack
├── gunicorn.conf.py             # Gunicorn process configuration
├── LICENSE                      # EUPL-1.2 licence text
└── README.md                    # This file
```

## Prerequisites

**Runtime:**
- Python ≥ 3.13
- PostgreSQL with PostGIS extension (≥ 15 recommended)
- A Keycloak instance (or compatible OIDC provider) for authentication

**Build / development:**
- [uv](https://docs.astral.sh/uv/) ≥ 0.5 (dependency and virtual-environment manager)
- Docker and Docker Compose (for the local devcontainer stack)

**Key Python dependencies** (see `pyproject.toml` for pinned versions):
- `django[gis]` ≥ 5.2
- `django-ninja` ≥ 1.5.3 (async REST API framework)
- `psycopg[binary]` ≥ 3.1
- `pydantic-settings` ≥ 2.12
- `django-allauth` ≥ 0.56 (OIDC authentication)
- `gunicorn` ≥ 21.0 + `uvicorn` ≥ 0.23 (ASGI server)

## Installation

### Local development (Devcontainer + Keycloak)

1. Clone the repository and open it in VS Code with the Dev Containers extension,
   or start the compose stack manually:

   ```bash
   docker compose up -d
   ```

2. Copy the example environment file and adjust the values:

   ```bash
   cp .env.local.example .env.base
   # edit .env.base and .env as needed
   ```

3. Install Python dependencies:

   ```bash
   uv sync
   ```

4. Apply database migrations:

   ```bash
   uv run python src/rpsd_config/manage.py migrate
   ```

5. (Optional) Seed dummy data:

   ```bash
   uv run python src/rpsd_config/manage.py seed_dummy_data --reset --publish-contracts
   ```

6. Start the development server:

   ```bash
   uv run devserver
   ```

The application will be available at `http://client.localhost:12080`.

A local Keycloak instance is expected at `http://keycloak.localhost:19300`
(see the `rpsd` repository for Keycloak setup).

Add the following entries to `/etc/hosts` if not already present:

```
127.0.0.1 client.localhost
127.0.0.1 keycloak.localhost
```

### Docker / production

Build the container image:

```bash
docker build -t rpsd-config .
```

Run with the required environment variables set (see Configuration below):

```bash
docker run --env-file .env.production rpsd-config
```

## Configuration

All settings are loaded from environment variables (and optionally from
`.env.base` / `.env` files in the project root in non-production environments).

| Variable | Required | Default | Description |
|---|---|---|---|
| `DJANGO_SECRET_KEY` | Yes (prod) | insecure dev key | Django secret key. Set a strong random value in production. |
| `DEBUG` | No | `True` | Set to `False` in production. |
| `DJANGO_ALLOWED_HOSTS` | Yes (prod) | `*` (dev) | Comma-separated list of allowed hostnames. |
| `DATABASES` | No | PostGIS on `postgis:5432` | JSON dict with Django `DATABASES` format. |
| `KEYCLOAK_DISCOVERY_URL` | Yes | — | OIDC discovery endpoint of the Keycloak realm. |
| `OIDC_AUTHORIZATION_ENDPOINT_URL` | No | — | Public browser-facing Keycloak login URL (use when container-to-Keycloak hostname differs from browser-to-Keycloak hostname). |
| `OIDC_ISSUER_URL` | No | — | Expected `iss` claim in the ID token. |
| `OIDC_CLIENT_ID` | No | `django` | OIDC client ID registered in Keycloak. |
| `OIDC_CLIENT_SECRET` | No | `django-secret` | OIDC client secret. Set in production. |
| `OIDC_FETCH_USERINFO` | No | `False` | If `True`, Django calls the userinfo endpoint instead of reading claims from the ID token. |
| `EXTERNAL_SCHEME` | No | `http` | Public-facing URL scheme (`http` or `https`). Used for building absolute URLs. |
| `EXTERNAL_HOST` | No | `localhost` | Public-facing hostname. |
| `EXTERNAL_PORT` | No | `20100` | Public-facing port. |
| `GUNICORN_WORKERS` | No | `2` | Number of Gunicorn worker processes. |
| `GUNICORN_TIMEOUT` | No | `30` | Gunicorn worker timeout in seconds. |
| `SECURE_PROXY_SSL_HEADER` | No | — | Set to `HTTP_X_FORWARDED_PROTO,https` when behind an SSL-terminating proxy. |
| `USE_X_FORWARDED_HOST` | No | `False` | Trust the `X-Forwarded-Host` header. |
| `USE_X_FORWARDED_PORT` | No | `False` | Trust the `X-Forwarded-Port` header. |

## Local Development: OIDC Callback Troubleshooting (401)

If `/accounts/oidc/keycloak/login/callback/` returns `401`, check:

1. Runtime values loaded by Django

```bash
python src/rpsd_config/manage.py shell -c "from django.conf import settings; print(settings.SOCIALACCOUNT_PROVIDERS)"
```

2. Keycloak token endpoint acceptance of `client_id` / `client_secret`

```bash
curl -X POST "http://keycloak.localhost:19300/realms/rapsodia/protocol/openid-connect/token" \
  -H "content-type: application/x-www-form-urlencoded" \
  --data "grant_type=client_credentials&client_id=django&client_secret=django-secret"
```

3. Django logs during login/callback (OIDC callback diagnostics are enabled in local development)

Example invite URL (local):

```txt
http://client.localhost:12080/invite/6bf9bc71-45ca-4218-93bb-f4293a6f99b2/
```

## API (Django Ninja)

API base path:

- `/exchange_agreement/api/`

API docs:

- Swagger UI: `/exchange_agreement/api/docs`
- OpenAPI JSON: `/exchange_agreement/api/openapi.json`

Key endpoints (v1):

- Contracts
  - `GET /exchange_agreement/api/v1/contracts`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/flow-profile`
  - `PUT /exchange_agreement/api/v1/contracts/{contract_code}/flow-profile`
- Contract indicators / required inputs
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/indicators`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/indicators/{indicator_code}`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/required-inputs`
- Contract publications
  - `POST /exchange_agreement/api/v1/contracts/{contract_code}/publish`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/publications`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/publications/{publication_version}`
  - `GET /exchange_agreement/api/v1/publications/{publication_id}`
- Catalogs
  - `GET /exchange_agreement/api/v1/indicators`
  - `GET /exchange_agreement/api/v1/structures`
  - `GET /exchange_agreement/api/v1/flow-profiles`
- Onboarding invite helpers
  - `GET /exchange_agreement/api/invitations/{token}/check`
  - `POST /exchange_agreement/api/invitations/{token}/start`

## Admin Backoffice Notes

### Contract publish action (Django admin)

In `Admin > Contracts`, a bulk action is available:

- `Publish selected contracts`

Behavior:

- publishes selected `active` contracts
- skips `draft` contracts (by design)
- skips `closed` contracts
- creates `ContractPublication` snapshots (append-only history)

`ContractPublication` is also exposed in the admin as a technical, read-only view for snapshot inspection.

## Dummy Data Seed Command

Management command:

- `src/rpsd_config/exchange_agreement/management/commands/seed_dummy_data.py`

What it seeds:

- stakeholders: `Agency`, `Company`, `Authority`, `Lot`
- dataset catalog: `Dataset`, `Structure`
- indicators: `IndicatorDef` + `structures` relation
- flow profiles: `FlowProfile`
- contracts: `Contract` + program file + `ContractDocument`
- mappings: `ContractIndicator`
- access: `ContractMembership`
- onboarding: `ContractInvitation`
- optional publications: `ContractPublication`

Usage:

```bash
uv run python src/rpsd_config/manage.py seed_dummy_data
```

Reset before seed:

```bash
uv run python src/rpsd_config/manage.py seed_dummy_data --reset
```

Seed and publish dummy contracts:

```bash
uv run python src/rpsd_config/manage.py seed_dummy_data --reset --publish-contracts
```

Useful parameters:

```bash
uv run python src/rpsd_config/manage.py seed_dummy_data --lots 5 --indicators 10 --seed 123
```

## Project Status

**Alpha** — the service is under active development and not yet recommended for
production use without validation by Agenzia TPL staff.

Known limitations:

- The onboarding flow for the first agency admin when no contracts exist is not
  yet fully defined.
- GTFS shared-area storage integration is under evaluation.
- The publication lifecycle (range semantics, revocation) may be refined.

See the Open Notes / Backlog section below for the full list of pending items.

## Open Notes / Backlog (Translated)

The following notes are kept as a lightweight project backlog and need refinement before implementation:

- Define onboarding flow for the first agency admin when no contracts exist yet
- Reassess the initial invitation mechanism for an agency admin who can create new contracts
- Evaluate GTFS shared-area storage integration (copy/export files after contract save via a custom action or dedicated workflow)
- Re-evaluate naming in the DB around `dataset` vs `dataset type`
- Indicator immutability policy: after creation, prefer create-new / clone-new-version rather than in-place edits
- Contract constraints are already enforced on unique code and version tuple; keep documentation aligned with actual model constraints
- Publication lifecycle refinements (if needed): publication range semantics, status simplification, and future revocation strategy

## Language Policy (Suggested)

To keep the repository maintainable:

- code, comments, docstrings, logs: English
- user-facing UI text: can remain Italian for now (or migrate later via Django i18n)
- legacy/reference files: keep them clearly marked as archive/reference unless actively maintained

## Copyright

Copyright 2025–2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA.

## Licence

This software is released under the **European Union Public Licence v. 1.2
(EUPL-1.2)**. See the [LICENSE](LICENSE) file for the full licence text.

SPDX-License-Identifier: `EUPL-1.2`

## Maintainer

**Agenzia TPL Bacino Città Metropolitana Milano, Monza e Brianza, Lodi, Pavia**

For bug reports, questions, and feature requests, please open an issue on the
[GitHub issue tracker](https://github.com/Agenzia-TPL/rpsd-config/issues).
