# Application Overview

The `exchange_agreement` application models the service-contract ecosystem for local public transport. It connects stakeholders, dataset definitions, indicator definitions, and contract-level configurations used to monitor service performance.

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

## Local Development (Devcontainer + Keycloak)

- Use the `rpsd` repository ror running a local instance of Keycloak.
- Django/OIDC settings are read from environment variables and, if present, from `.env` at the project root.
- Start by copying `.env.example` to `.env` and adjusting the required values.

### Local URLs

- Browser (host) -> Django: `http://client.localhost:12080`
- Browser (host) -> Keycloak: `http://keycloak.localhost:19300`
- Django (container) -> Keycloak: `http://keycloak.localhost:19300` (recommended local default)

Example `/etc/hosts` entries:

```txt
127.0.0.1 client.localhost
127.0.0.1 keycloak.localhost
```

### Recommended OIDC variables in `.env`

- `KEYCLOAK_DISCOVERY_URL`: discovery/token/userinfo endpoint used by Django
- `OIDC_AUTHORIZATION_ENDPOINT_URL`: public browser redirect endpoint for Keycloak login
- `OIDC_ISSUER_URL`: public issuer expected during `id_token` validation
- `OIDC_FETCH_USERINFO`: if `false`, Django uses `id_token` claims instead of calling `userinfo` (useful in local mixed-host setups)

If you use custom hostnames in `/etc/hosts`, add them to `DJANGO_ALLOWED_HOSTS` (and, if required, `DJANGO_CSRF_TRUSTED_ORIGINS`) in `.env`.

## OIDC Callback Troubleshooting (401)

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
