# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.utils import timezone

from ..models import IntegrationPrincipal


class M2MSecretStoreError(ValueError):
    """Raised when M2M client secret storage/reveal fails."""


def _fernet() -> Fernet:
    raw_key = (
        getattr(settings, "M2M_CLIENT_SECRET_ENCRYPTION_KEY", "")
        or settings.SECRET_KEY
    )
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def store_client_secret(
    principal: IntegrationPrincipal,
    *,
    client_secret: str,
    key_id: str | None = None,
) -> IntegrationPrincipal:
    if not client_secret:
        raise M2MSecretStoreError("client_secret is required.")

    principal.client_secret_ciphertext = _fernet().encrypt(
        client_secret.encode("utf-8")
    ).decode("ascii")
    principal.client_secret_key_id = key_id or getattr(
        settings, "M2M_CLIENT_SECRET_KEY_ID", "local"
    )
    principal.client_secret_updated_at = timezone.now()
    principal.save(
        update_fields=[
            "client_secret_ciphertext",
            "client_secret_key_id",
            "client_secret_updated_at",
            "updated_at",
        ]
    )
    return principal


def reveal_client_secret(principal: IntegrationPrincipal) -> str:
    if not principal.client_secret_ciphertext:
        raise M2MSecretStoreError("No client secret is stored for this principal.")
    try:
        return _fernet().decrypt(
            principal.client_secret_ciphertext.encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise M2MSecretStoreError("Unable to decrypt client secret.") from exc


def clear_client_secret(principal: IntegrationPrincipal) -> IntegrationPrincipal:
    principal.client_secret_ciphertext = ""
    principal.client_secret_key_id = ""
    principal.client_secret_updated_at = None
    principal.save(
        update_fields=[
            "client_secret_ciphertext",
            "client_secret_key_id",
            "client_secret_updated_at",
            "updated_at",
        ]
    )
    return principal
