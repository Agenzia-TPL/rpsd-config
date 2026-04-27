# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""M2M Bearer token authentication for company integration clients."""

import logging
from dataclasses import dataclass
from typing import Any

import jwt
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.conf import settings
from ninja.security import HttpBearer

from rpsd_config.exchange_agreement.models import IntegrationPrincipal
from rpsd_config.exchange_agreement.services.m2m_audit import audit_m2m_event

from .bearer_auth import _keycloak_urls

LOGGER = logging.getLogger(__name__)


class M2MTokenValidationError(RuntimeError):
    """Raised when a M2M token cannot be accepted."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class M2MAuthContext:
    principal: IntegrationPrincipal
    client_id: str
    claims: dict[str, Any]


def _client_id_claim_names() -> list[str]:
    configured = getattr(settings, "M2M_API_CLIENT_ID_CLAIM", "azp")
    names = [item.strip() for item in configured.split(",") if item.strip()]
    for fallback in ("azp", "client_id"):
        if fallback not in names:
            names.append(fallback)
    return names


def extract_m2m_client_id(claims: dict[str, Any]) -> str:
    for claim_name in _client_id_claim_names():
        value = claims.get(claim_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise M2MTokenValidationError("client-id-missing")


def validate_m2m_token(token: str) -> dict[str, Any]:
    issuer, jwks_url = _keycloak_urls()
    if not issuer:
        raise M2MTokenValidationError("issuer-not-configured")

    expected_audience = getattr(settings, "M2M_API_EXPECTED_AUDIENCE", "").strip()
    clock_skew = int(getattr(settings, "M2M_API_CLOCK_SKEW_SECONDS", 30) or 0)
    try:
        alg, key = jwtkit.fetch_key(token, jwks_url, jwtkit.lookup_kid_jwk)
        kwargs: dict[str, Any] = {
            "key": key,
            "algorithms": [alg],
            "issuer": issuer,
            "leeway": clock_skew,
            "options": {
                "verify_signature": True,
                "verify_iss": True,
                "verify_aud": bool(expected_audience),
                "verify_exp": True,
            },
        }
        if expected_audience:
            kwargs["audience"] = expected_audience
        claims = jwt.decode(token, **kwargs)
    except (OAuth2Error, jwt.PyJWTError) as exc:
        LOGGER.info("M2M token validation failed: %s", exc)
        raise M2MTokenValidationError("token-invalid") from exc

    if not isinstance(claims, dict):
        raise M2MTokenValidationError("token-claims-invalid")
    return claims


def authenticate_m2m_token(token: str) -> M2MAuthContext:
    if not getattr(settings, "M2M_API_ENABLED", True):
        raise M2MTokenValidationError("m2m-api-disabled")

    claims = validate_m2m_token(token)
    client_id = extract_m2m_client_id(claims)
    principal = (
        IntegrationPrincipal.objects.select_related("company")
        .filter(keycloak_client_id=client_id)
        .first()
    )
    if principal is None:
        audit_m2m_event(
            "api.auth_denied",
            keycloak_client_id=client_id,
            reason="principal-not-found",
        )
        raise M2MTokenValidationError("principal-not-found")
    if principal.status != IntegrationPrincipal.Status.ACTIVE:
        audit_m2m_event(
            "api.auth_denied",
            principal_id=principal.pk,
            company_id=principal.company_id,
            keycloak_client_id=client_id,
            reason=f"principal-{principal.status}",
        )
        raise M2MTokenValidationError(f"principal-{principal.status}")

    return M2MAuthContext(principal=principal, client_id=client_id, claims=claims)


class M2MClientTokenAuth(HttpBearer):
    """Django-Ninja auth class for company M2M clients."""

    def authenticate(self, request, token):
        try:
            context = authenticate_m2m_token(token)
        except M2MTokenValidationError as exc:
            setattr(request, "m2m_auth_reason", exc.reason)
            return None

        request.integration_principal = context.principal
        request.integration_client_id = context.client_id
        request.integration_claims = context.claims
        return context.principal
