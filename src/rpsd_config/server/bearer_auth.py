# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""JWT Bearer token authentication for service-to-service calls.

Follows Django's ``RemoteUserMiddleware`` + ``RemoteUserBackend`` pattern:

* ``JWTBearerBackend`` validates the JWT and resolves a Django User via
  allauth's ``SocialAccount``.
* ``JWTBearerMiddleware`` extracts the Bearer token from the
  ``Authorization`` header and delegates to the backend.
* ``BearerTokenAuth`` is a thin Django-Ninja security class that
  documents Bearer auth in the OpenAPI schema.
"""

import logging

import jwt
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.conf import settings
from django.contrib import auth
from ninja.security import HttpBearer

LOGGER = logging.getLogger(__name__)


def _keycloak_urls() -> tuple[str, str]:
    """Return the token issuer and the server-reachable JWKS URL.

    The *issuer* must match the ``iss`` claim in Keycloak JWTs, which
    uses ``KC_HOSTNAME`` (typically ``http://localhost:19300``).  We read
    it from ``OIDC_ISSUER_URL``.

    The *JWKS URL* is a server-to-server call, so it must use the
    container-reachable address from ``KEYCLOAK_DISCOVERY_URL``
    (e.g. ``http://host.docker.internal:19300``).
    """
    issuer = getattr(settings, "OIDC_ISSUER_URL", "")
    discovery = getattr(settings, "KEYCLOAK_DISCOVERY_URL", "")
    server_base = discovery.removesuffix("/.well-known/openid-configuration")
    jwks_url = server_base + "/protocol/openid-connect/certs"
    return issuer, jwks_url


# ---------------------------------------------------------------------------
# Django authentication backend
# ---------------------------------------------------------------------------


class JWTBearerBackend:
    """Authenticate a request by validating a Keycloak JWT Bearer token."""

    def authenticate(self, request, jwt_token=None):
        if jwt_token is None:
            return None

        issuer, jwks_url = _keycloak_urls()
        if not issuer:
            return None

        try:
            alg, key = jwtkit.fetch_key(
                jwt_token, jwks_url, jwtkit.lookup_kid_jwk
            )
            claims = jwt.decode(
                jwt_token,
                key=key,
                algorithms=[alg],
                issuer=issuer,
                options={
                    "verify_signature": True,
                    "verify_iss": True,
                    "verify_aud": False,
                    "verify_exp": True,
                },
            )
        except (OAuth2Error, jwt.PyJWTError) as exc:
            LOGGER.info("JWT Bearer validation failed: %s", exc)
            return None

        sub = claims.get("sub")
        if not sub:
            LOGGER.info("JWT Bearer token has no 'sub' claim")
            return None

        provider_id = getattr(settings, "OIDC_PROVIDER_ID", "keycloak")
        try:
            social_account = SocialAccount.objects.select_related("user").get(
                provider=provider_id,
                uid=sub,
            )
        except SocialAccount.DoesNotExist:
            LOGGER.info(
                "No SocialAccount for provider=%s uid=%s", provider_id, sub
            )
            return None

        return social_account.user

    def get_user(self, user_id):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None


# ---------------------------------------------------------------------------
# Django middleware
# ---------------------------------------------------------------------------


class JWTBearerMiddleware:
    """Extract Bearer token from the Authorization header and authenticate."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer "):
            token = header[7:]
            user = auth.authenticate(request, jwt_token=token)
            if user is not None:
                request.user = user
        return self.get_response(request)


# ---------------------------------------------------------------------------
# Django-Ninja security class (OpenAPI documentation only)
# ---------------------------------------------------------------------------


class BearerTokenAuth(HttpBearer):
    """Declare Bearer auth in the OpenAPI schema.

    Actual JWT validation is performed by ``JWTBearerMiddleware`` +
    ``JWTBearerBackend`` before the view is called.  This class simply
    checks whether ``request.user`` was already authenticated.
    """

    def authenticate(self, request, token):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            return user
        return None
