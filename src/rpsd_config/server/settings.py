# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""
Django settings for rpsd_config project.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/5.2/ref/settings/
"""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_project_root() -> Path:
    """Get the project root directory.

    Assumes structure: project_root/src/rpsd_config/server/settings.py
    Returns: project_root as an absolute Path
    """
    return Path(__file__).parent.parent.parent.parent.resolve()


PROJECT_ROOT = _get_project_root()


def resolve_path(v: Any) -> str:
    """Resolve path fields relative to PROJECT_ROOT if not absolute.

    This validator:
    - Accepts absolute paths as-is
    - Resolves relative paths against PROJECT_ROOT
    - Returns string representation for storage
    - Enables portable configuration across environments

    Note: check_fields=False allows this validator to exist even when
    the fields are not yet defined. Remove check_fields=False when you
    add the actual path fields above.
    """
    if not v:
        return v
    path = Path(v)
    if path.is_absolute():
        return str(path)
    resolved = (PROJECT_ROOT / path).resolve()
    return str(resolved)


class DatabaseModel(BaseModel):
    ENGINE: str = "django.contrib.gis.db.backends.postgis"
    HOST: str = Field(default="postgis")
    NAME: str = Field(default="rpsd")
    PASSWORD: str = Field(default="rpsd")
    PORT: int = Field(default=5432)
    USER: str = Field(default="rpsd")
    OPTIONS: dict = Field(default_factory=dict)
    CONN_MAX_AGE: int = Field(default=0)


class GeneralSettings(BaseSettings):
    # https://docs.djangoproject.com/en/5.2/ref/settings/

    # SECURITY WARNING: keep the secret key used in production secret!
    SECRET_KEY: str = Field(
        default="django-insecure-gc*7f_p9)xhm6itzdtb(cpkt_pjpl0e-pp7kjn0(u=6+n+i1lp",
        validation_alias="DJANGO_SECRET_KEY",
    )
    # SECURITY WARNING: don't run with debug turned on in production!
    DEBUG: bool = Field(default=True)
    DATABASES: dict[str, DatabaseModel] = Field(default={"default": DatabaseModel()})

    # Default primary key field type
    # https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field
    DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

    # Custom user model (TBD?)
    # AUTH_USER_MODEL: str = "custom_user.User"

    ALLOWED_HOSTS: list[str] = []
    CSRF_TRUSTED_ORIGINS: list[str] = []

    # Proxy header support for SSL termination
    # SECURITY: Only enable when behind a trusted proxy/gateway!
    # When enabled, Django trusts X-Forwarded-* headers to determine:
    # - Original scheme (http/https)
    # - Original hostname
    # - Original port
    SECURE_PROXY_SSL_HEADER: tuple[str, str] | None = Field(default=None)
    USE_X_FORWARDED_HOST: bool = Field(default=False)
    USE_X_FORWARDED_PORT: bool = Field(default=False)

    ROOT_URLCONF: str = "rpsd_config.server.urls"
    WSGI_APPLICATION: str = "rpsd_config.server.wsgi.application"

    # Application definition
    INSTALLED_APPS: list[str] = [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.sessions",
        "django.contrib.messages",
        "django.contrib.staticfiles",
        "django.contrib.sites",
        "allauth",
        "allauth.account",
        "allauth.socialaccount",
        "allauth.socialaccount.providers.openid_connect",
        "leaflet",
        "django.contrib.gis",
        "rpsd_config.app1",
        "rpsd_config.exchange_agreement.apps.ExchangeAgreementConfig",
        "rpsd_config.admin_stakeholders",
        "rpsd_config.admin_agreements",
        "rpsd_config.admin_dataset_exchange",
        #        "rpsd_config.admin_service_net",
    ]

    MIDDLEWARE: list[str] = [
        "django.middleware.security.SecurityMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "rpsd_config.server.bearer_auth.JWTBearerMiddleware",
        "allauth.account.middleware.AccountMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]

    # Password validation
    # https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators
    AUTH_PASSWORD_VALIDATORS: list[dict] = [
        {
            "NAME": (
                "django.contrib.auth.password_validation"
                ".UserAttributeSimilarityValidator"
            ),
        },
        {
            "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        },
        {
            "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
        },
        {
            "NAME": (
                "django.contrib.auth.password_validation.NumericPasswordValidator"
            ),
        },
    ]

    SITE_ID: int = Field(default=1)

    AUTHENTICATION_BACKENDS: list[str] = [
        "django.contrib.auth.backends.ModelBackend",
        "allauth.account.auth_backends.AuthenticationBackend",
        "rpsd_config.server.bearer_auth.JWTBearerBackend",
    ]

    LOGIN_REDIRECT_URL: str = "/"
    # LOGIN_URL: str = "/"
    LOGOUT_REDIRECT_URL: str | None = "/"
    ACCOUNT_EMAIL_VERIFICATION: str = "none"
    ACCOUNT_SIGNUP_FIELDS: list[str] = ["username*", "password1*", "password2*"]
    ACCOUNT_ADAPTER: str = "rpsd_config.server.account_adapter.RpsdAccountAdapter"
    SOCIALACCOUNT_LOGIN_ON_GET: bool = True

    SOCIALACCOUNT_ADAPTER: str = (
        "rpsd_config.server.socialaccount_adapter.RpsdSocialAccountAdapter"
    )


class I18NSettings(BaseSettings):
    # Internationalization
    # https://docs.djangoproject.com/en/5.2/topics/i18n/
    LANGUAGE_CODE: str = "it"
    TIME_ZONE: str = "Europe/Rome"
    USE_I18N: bool = True
    USE_L10N: bool = True
    USE_TZ: bool = True

    # Italian date/time formats
    DATE_FORMAT: str = "j F Y"
    DATETIME_FORMAT: str = "j F Y, H:i"
    SHORT_DATE_FORMAT: str = "d/m/Y"
    SHORT_DATETIME_FORMAT: str = "d/m/Y H:i"


class StaticSettings(BaseSettings):
    # Static files (CSS, JavaScript, Images)
    # https://docs.djangoproject.com/en/5.2/howto/static-files/

    STATIC_URL: str = "static/"
    STATIC_ROOT: str = Field(default=resolve_path("staticfiles"))
    STATICFILES_DIRS: list[str] = Field(
        default_factory=lambda: [resolve_path("src/rpsd_config/static")]
    )

    MEDIA_URL: str = "media/"
    MEDIA_ROOT: str = Field(default=resolve_path("media"))

    TEMPLATES: list[dict] = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [resolve_path("src/rpsd_config/templates")],
            "APP_DIRS": True,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                    "rpsd_config.server.context_processors.navigation_context",
                ],
            },
        },
    ]


class LeafletSettings(BaseSettings):
    LEAFLET_CONFIG: dict = Field(
        default={
            "DEFAULT_CENTER": (45.4642637, 9.1896343),
            "DEFAULT_ZOOM": 13,
            "MIN_ZOOM": 2,
            "MAX_ZOOM": 19,  # Do not exceed 19 with standard OSM tiles
            "SCALE": "metric",
            "RESET_VIEW": True,
            "TILES": [
                (
                    "OSM",
                    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
                    {
                        "attribution": "&copy; OpenStreetMap contributors",
                        "maxZoom": 19,
                        "maxNativeZoom": 19,
                    },
                )
            ],
        }
    )


class OIDCSettings(BaseSettings):
    OIDC_PROVIDER_ID: str = Field(default="keycloak")
    KEYCLOAK_DISCOVERY_URL: str = Field(
        default=("http://keycloak:8080/realms/rpsd/.well-known/openid-configuration")
    )
    OIDC_AUTHORIZATION_ENDPOINT_URL: str = Field(default="")
    OIDC_ISSUER_URL: str = Field(default="")
    OIDC_CLIENT_ID: str = Field(default="django")
    OIDC_CLIENT_SECRET: str = Field(default="django-secret")
    OIDC_FETCH_USERINFO: bool = Field(default=False)
    OIDC_ALLOW_PLATFORM_ADMIN_SIGNUP_WITHOUT_INVITATION: bool = Field(default=False)

    SOCIALACCOUNT_PROVIDERS: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def compute_socialaccount_providers(self) -> "OIDCSettings":
        oidc_apps = []
        if (
            self.KEYCLOAK_DISCOVERY_URL
            and self.OIDC_CLIENT_ID
            and self.OIDC_CLIENT_SECRET
        ):
            app_settings: dict = {
                "server_url": self.KEYCLOAK_DISCOVERY_URL,
                "fetch_userinfo": self.OIDC_FETCH_USERINFO,
            }
            if self.OIDC_AUTHORIZATION_ENDPOINT_URL:
                app_settings["authorization_endpoint"] = (
                    self.OIDC_AUTHORIZATION_ENDPOINT_URL
                )
            if self.OIDC_ISSUER_URL:
                app_settings["issuer"] = self.OIDC_ISSUER_URL

            oidc_apps = [
                {
                    "provider_id": self.OIDC_PROVIDER_ID,
                    "name": "Keycloak",
                    "client_id": self.OIDC_CLIENT_ID,
                    "secret": self.OIDC_CLIENT_SECRET,
                    "settings": app_settings,
                }
            ]

        self.SOCIALACCOUNT_PROVIDERS = {
            "openid_connect": {
                "APPS": oidc_apps,
            }
        }
        return self


class KeycloakAdminSettings(BaseSettings):
    KEYCLOAK_ADMIN_BASE_URL: str = Field(default="")
    KEYCLOAK_ADMIN_REALM: str = Field(default="")
    KEYCLOAK_ADMIN_CLIENT_ID: str = Field(default="rpsd-config-admin-api")
    KEYCLOAK_ADMIN_CLIENT_SECRET: str = Field(default="")
    KEYCLOAK_ADMIN_REQUEST_TIMEOUT_SECONDS: float = Field(default=10.0)
    KEYCLOAK_ADMIN_VERIFY_TLS: bool = Field(default=True)
    KEYCLOAK_ADMIN_GROUP_ROOT: str = Field(default="/rpsd")

    @model_validator(mode="after")
    def compute_keycloak_admin_defaults(self) -> "KeycloakAdminSettings":
        discovery = getattr(self, "KEYCLOAK_DISCOVERY_URL", "") or ""
        parsed = urlparse(discovery)
        if parsed.scheme and parsed.hostname:
            if not self.KEYCLOAK_ADMIN_BASE_URL:
                base_url = f"{parsed.scheme}://{parsed.hostname}"
                if parsed.port:
                    base_url = f"{base_url}:{parsed.port}"
                self.KEYCLOAK_ADMIN_BASE_URL = base_url

            if not self.KEYCLOAK_ADMIN_REALM:
                segments = [part for part in parsed.path.split("/") if part]
                for index, part in enumerate(segments):
                    if part == "realms" and index + 1 < len(segments):
                        self.KEYCLOAK_ADMIN_REALM = segments[index + 1]
                        break

        normalized_root = "/" + "/".join(
            [
                segment
                for segment in self.KEYCLOAK_ADMIN_GROUP_ROOT.split("/")
                if segment
            ]
        )
        self.KEYCLOAK_ADMIN_GROUP_ROOT = normalized_root or "/rpsd"
        return self


class AppSettings(BaseSettings):
    """Application-specific settings (non-Django framework settings).

    See: https://docs.djangoproject.com/en/5.2/ref/settings/
    """

    # External access configuration (how users access the application)
    EXTERNAL_SCHEME: str = Field(default="http")
    EXTERNAL_HOST: str = Field(default="localhost")
    EXTERNAL_PORT: int = Field(default=20100)

    # Gunicorn process settings (read by gunicorn.conf.py via os.getenv, not by Django)
    GUNICORN_WORKERS: int = Field(default=2)
    GUNICORN_TIMEOUT: int = Field(default=30)

    # M2M company client defaults (rpsd-config only).
    M2M_DEFAULT_ENVIRONMENT: str = Field(default="prod")
    M2M_DEFAULT_CLIENT_SUFFIX: str = Field(default="default-prod")
    M2M_CLIENT_SECRET_KEY_ID: str = Field(default="local")
    M2M_CLIENT_SECRET_ENCRYPTION_KEY: str = Field(default="")

    # M2M API authentication (rpsd-config only).
    M2M_API_ENABLED: bool = Field(default=True)
    M2M_API_EXPECTED_AUDIENCE: str = Field(default="")
    M2M_API_CLIENT_ID_CLAIM: str = Field(default="azp")
    M2M_API_CLOCK_SKEW_SECONDS: int = Field(default=30)


class ProjectSettings(
    GeneralSettings,
    I18NSettings,
    StaticSettings,
    LeafletSettings,
    OIDCSettings,
    KeycloakAdminSettings,
    AppSettings,
):
    model_config = SettingsConfigDict(
        env_file=resolve_path(".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        env_nested_delimiter="__",
    )

    @model_validator(mode="after")
    def compute_external_urls(self) -> "ProjectSettings":
        """Auto-compute CSRF_TRUSTED_ORIGINS.

        Builds these values from EXTERNAL_SCHEME, EXTERNAL_HOST,
        and EXTERNAL_PORT to create a single source of truth for
        external access configuration.
        """
        # Build base URL from EXTERNAL_*
        # Omit port for standard HTTP (80) and HTTPS (443) ports
        port_str = ""
        if (self.EXTERNAL_SCHEME == "http" and self.EXTERNAL_PORT != 80) or (
            self.EXTERNAL_SCHEME == "https" and self.EXTERNAL_PORT != 443
        ):
            port_str = f":{self.EXTERNAL_PORT}"

        base_url = f"{self.EXTERNAL_SCHEME}://{self.EXTERNAL_HOST}{port_str}"

        # Add base_url to CSRF_TRUSTED_ORIGINS if not already present
        if base_url not in self.CSRF_TRUSTED_ORIGINS:
            self.CSRF_TRUSTED_ORIGINS.append(base_url)

        return self


from rpsd_config.server.pydjantic import to_django  # noqa: E402

to_django(ProjectSettings())
