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
    - "${APP_EXTERNAL_PORT:-20100}:${APP_PORT:-8000}"
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
| `APP_PORT` | `8000` | gunicorn, Django devserver | **Internal** bind port — where Gunicorn/Django listens inside the container. Rarely needs changing. |
| `APP_EXTERNAL_SCHEME` | `http` | Django | Scheme for CSRF trusted origins |
| `APP_EXTERNAL_HOST` | `localhost` | Django | External hostname |
| `APP_EXTERNAL_PORT` | `20100` | Django | **External** port users access in their browser. Drives CSRF trusted origins. Set this per deployment (e.g. `80`, `443`). |

> **NOTE — do not confuse `APP_PORT` and `APP_EXTERNAL_PORT`:**
> - `APP_PORT` is the port Gunicorn/Django binds to *inside the container*. The default (`8000`) is almost always correct — leave it alone unless you have a specific reason to change it.
> - `APP_EXTERNAL_PORT` is the port that appears in the URL users type in their browser. This is the one to customise per deployment scenario (e.g. `80` for intranet HTTP, `443` for HTTPS via an external gateway).
> - In the Docker Compose port mapping `HOST:CONTAINER`, `APP_EXTERNAL_PORT` goes on the **host side** and `APP_PORT` goes on the **container side**.
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

## Authentication

### Human users (OIDC / Keycloak)

Human users log in via OpenID Connect through Keycloak. This is handled by
`django-allauth` and requires no manual setup beyond the environment variables
described below.

| Variable | Default | Description |
|---|---|---|
| `OIDC_PROVIDER_ID` | `keycloak` | Provider identifier — must match the allauth provider record |
| `KEYCLOAK_DISCOVERY_URL` | `http://keycloak:8080/realms/rpsd/.well-known/openid-configuration` | OIDC discovery endpoint (server-to-server, must be container-reachable) |
| `OIDC_AUTHORIZATION_ENDPOINT_URL` | *(empty)* | Override the browser-facing authorization URL (must use `localhost`) |
| `OIDC_ISSUER_URL` | *(empty)* | Override the expected token issuer (must match Keycloak's `KC_HOSTNAME`) |
| `OIDC_CLIENT_ID` | `django` | OAuth2 client ID (must match Keycloak client config) |
| `OIDC_CLIENT_SECRET` | `django-secret` | OAuth2 client secret |
| `OIDC_FETCH_USERINFO` | `false` | Fetch userinfo endpoint after authentication |

### Service-to-service (JWT Bearer)

Other services authenticate by passing a Keycloak JWT as a Bearer token in the
`Authorization` header. The token is validated by `JWTBearerMiddleware` +
`JWTBearerBackend`, which maps the JWT's `sub` claim to a Django User via
allauth's `SocialAccount` model.

No additional settings are needed — the JWKS URL and issuer are derived from
`KEYCLOAK_DISCOVERY_URL` and `OIDC_ISSUER_URL`.

#### Keycloak setup (one-time per service)

1. In Keycloak Admin, go to the `rpsd` realm → **Clients** → **Create client**
2. Set **Client ID** (e.g., `rpsd-ingest`), **Client authentication** = On
3. Under **Capability config**: enable **Service accounts roles**, disable **Standard flow**
4. Save, then go to the **Credentials** tab and note the client secret
5. To find the service account's `sub` (UUID): go to the **Service accounts roles** tab
   and click the service account user link at the top — the **ID** field is the `sub`

#### Django setup (one-time per service)

1. In Django Admin, create a **User** for the service (e.g., username `service-rpsd-ingest`).
   Assign permissions and group memberships as needed.
2. Create a **Social Account** linked to that user:
   - **Provider**: `keycloak` (must match `OIDC_PROVIDER_ID`)
   - **Uid**: the UUID from Keycloak (the `sub` claim)

#### Usage

```bash
# Get a token
TOKEN=$(curl -s -X POST \
  http://localhost:19300/realms/rpsd/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=rpsd-ingest&client_secret=YOUR_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Call the API
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:20100/exchange_agreement/api/v1/contracts
```

> **Tip:** During development, the default access token lifetime is 5 minutes.
> To increase it, go to Keycloak Admin → **Realm Settings** → **Tokens** →
> **Access Token Lifespan**. You can also override it per-client under
> **Clients** → select client → **Advanced** → **Access Token Lifespan**.

---

## Static Files

Static files are collected at build time (`RUN uv run manage collectstatic --noinput`
in the Dockerfile) and served from `/app/staticfiles/`.

For production, configure a reverse proxy (nginx, Traefik) to serve `/static/` directly
from that directory.
