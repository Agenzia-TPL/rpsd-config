# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from ..models import IntegrationPrincipal

logger = logging.getLogger(__name__)


class M2MSecretStorageError(RuntimeError):
    """Raised when M2M secret encryption/decryption fails."""


def _resolve_key_material() -> str:
    configured = str(getattr(settings, "M2M_SECRET_ENCRYPTION_KEY", "") or "").strip()
    if configured:
        return configured

    fallback = str(getattr(settings, "SECRET_KEY", "") or "").strip()
    if fallback:
        return fallback

    raise M2MSecretStorageError(
        "Missing encryption key material for M2M secret storage."
    )


def _resolve_key_id() -> str:
    configured = str(getattr(settings, "M2M_SECRET_ENCRYPTION_KEY_ID", "") or "").strip()
    if configured:
        return configured
    return "derived-from-django-secret-key"


def _build_cipher() -> Fernet:
    key_material = _resolve_key_material().encode("utf-8")
    digest = hashlib.sha256(key_material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def store_principal_secret(
    *,
    principal: IntegrationPrincipal,
    raw_secret: str,
    mark_rotation: bool = False,
) -> IntegrationPrincipal:
    """Encrypt and persist a principal secret.

    The plaintext secret is never written to logs or model fields.
    """

    if not isinstance(raw_secret, str) or not raw_secret:
        raise M2MSecretStorageError("Cannot store an empty M2M secret.")

    cipher = _build_cipher()
    ciphertext = cipher.encrypt(raw_secret.encode("utf-8")).decode("utf-8")
    now = timezone.now()

    principal.client_secret_ciphertext = ciphertext
    principal.client_secret_key_id = _resolve_key_id()
    principal.client_secret_updated_at = now

    update_fields = [
        "client_secret_ciphertext",
        "client_secret_key_id",
        "client_secret_updated_at",
        "updated_at",
    ]
    if mark_rotation:
        principal.last_secret_rotation_at = now
        update_fields.append("last_secret_rotation_at")

    principal.save(update_fields=update_fields)
    return principal


def reveal_principal_secret(*, principal: IntegrationPrincipal) -> str | None:
    """Decrypt and return the secret for the provided principal."""

    ciphertext = (principal.client_secret_ciphertext or "").strip()
    if not ciphertext:
        return None

    try:
        secret = _build_cipher().decrypt(ciphertext.encode("utf-8"))
    except InvalidToken as exc:
        logger.error(
            "m2m.secret.decrypt_failed",
            extra={
                "integration_principal_id": principal.id,
                "company_id": principal.company_id,
                "keycloak_client_id": principal.keycloak_client_id,
                "secret_key_id": principal.client_secret_key_id,
            },
        )
        raise M2MSecretStorageError(
            "Stored M2M secret cannot be decrypted with current key."
        ) from exc

    return secret.decode("utf-8")
