# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminService,
)

from ..models import Company, IntegrationPrincipal
from .m2m_client_naming import (
    DEFAULT_M2M_ENVIRONMENT,
    DEFAULT_M2M_INTEGRATION_NAME,
    resolve_default_m2m_client_id,
)
from .m2m_audit import audit_m2m_event
from .m2m_secret_store import M2MSecretStorageError, store_principal_secret

logger = logging.getLogger(__name__)


class M2MProvisioningError(RuntimeError):
    """Raised when M2M principal provisioning fails."""

    def __init__(
        self,
        message: str,
        *,
        client_id: str,
        client_uuid: str,
        compensation_action: str,
    ) -> None:
        super().__init__(message)
        self.client_id = client_id
        self.client_uuid = client_uuid
        self.compensation_action = compensation_action


@dataclass(frozen=True)
class M2MProvisionResult:
    principal: IntegrationPrincipal
    keycloak_client_id: str
    keycloak_client_uuid: str
    keycloak_client_created: bool
    principal_created: bool
    client_secret: str | None


def _find_default_principal(company: Company) -> IntegrationPrincipal | None:
    return (
        IntegrationPrincipal.objects.filter(
            company=company,
            name=DEFAULT_M2M_INTEGRATION_NAME,
            environment=DEFAULT_M2M_ENVIRONMENT,
        )
        .order_by("id")
        .first()
    )


def _compensate_new_keycloak_client(
    *,
    keycloak_service: KeycloakAdminService,
    client_uuid: str,
    client_id: str,
    company_id: int,
) -> str:
    try:
        deleted = keycloak_service.delete_client(client_uuid=client_uuid)
        action = "deleted" if deleted else "already-missing"
        logger.warning(
            "m2m.provisioning.compensation.delete",
            extra={
                "company_id": company_id,
                "keycloak_client_id": client_id,
                "keycloak_client_uuid": client_uuid,
                "compensation_action": action,
            },
        )
        return action
    except KeycloakAdminAPIError:
        logger.exception(
            "m2m.provisioning.compensation.delete_failed",
            extra={
                "company_id": company_id,
                "keycloak_client_id": client_id,
                "keycloak_client_uuid": client_uuid,
            },
        )
        try:
            keycloak_service.disable_client(client_uuid=client_uuid)
            logger.error(
                "m2m.provisioning.compensation.disable",
                extra={
                    "company_id": company_id,
                    "keycloak_client_id": client_id,
                    "keycloak_client_uuid": client_uuid,
                    "compensation_action": "disabled",
                },
            )
            return "disabled"
        except KeycloakAdminAPIError:
            logger.exception(
                "m2m.provisioning.compensation.disable_failed",
                extra={
                    "company_id": company_id,
                    "keycloak_client_id": client_id,
                    "keycloak_client_uuid": client_uuid,
                    "compensation_action": "failed",
                },
            )
            return "failed"


def provision_default_m2m_principal_for_company(
    *,
    company: Company,
    actor=None,
    request_id: str | None = None,
    keycloak: KeycloakAdminService | None = None,
) -> M2MProvisionResult:
    """Create or reuse the default M2M principal with Keycloak compensation.

    Flow:
    1. If default principal already exists, return it (idempotent retry).
    2. Resolve deterministic client_id.
    3. Create/reuse confidential client in Keycloak.
    4. Persist IntegrationPrincipal in Django.
    5. If Django persistence fails after Keycloak create, compensate by
       delete -> disable.
    """

    existing_principal = _find_default_principal(company)
    if existing_principal is not None:
        audit_m2m_event(
            "principal.create",
            request_id=request_id,
            outcome="success",
            actor=actor,
            company=company,
            principal=existing_principal,
            reason="already-existing",
        )
        return M2MProvisionResult(
            principal=existing_principal,
            keycloak_client_id=existing_principal.keycloak_client_id,
            keycloak_client_uuid=existing_principal.keycloak_client_uuid,
            keycloak_client_created=False,
            principal_created=False,
            client_secret=None,
        )

    keycloak_service = keycloak or KeycloakAdminService.from_settings()
    client_id = resolve_default_m2m_client_id(company=company)
    keycloak_client = keycloak_service.create_confidential_m2m_client(
        client_id=client_id,
        name=f"{company.name} M2M",
        description=f"Default M2M integration for company {company.name}",
    )

    try:
        with transaction.atomic():
            principal = IntegrationPrincipal.objects.create(
                company=company,
                name=DEFAULT_M2M_INTEGRATION_NAME,
                environment=DEFAULT_M2M_ENVIRONMENT,
                keycloak_client_id=keycloak_client.client.client_id,
                keycloak_client_uuid=keycloak_client.client.id,
                status=IntegrationPrincipal.Status.ACTIVE,
                created_by=actor,
            )
            store_principal_secret(
                principal=principal,
                raw_secret=keycloak_client.secret,
                mark_rotation=False,
            )
    except (IntegrityError, M2MSecretStorageError) as exc:
        if isinstance(exc, IntegrityError):
            concurrent = _find_default_principal(company)
            if (
                concurrent is not None
                and concurrent.keycloak_client_id == keycloak_client.client.client_id
            ):
                logger.info(
                    "m2m.provisioning.concurrent_reuse",
                    extra={
                        "company_id": company.id,
                        "keycloak_client_id": concurrent.keycloak_client_id,
                        "keycloak_client_uuid": concurrent.keycloak_client_uuid,
                    },
                )
                audit_m2m_event(
                    "principal.create",
                    request_id=request_id,
                    outcome="success",
                    actor=actor,
                    company=company,
                    principal=concurrent,
                    reason="concurrent-reuse",
                )
                return M2MProvisionResult(
                    principal=concurrent,
                    keycloak_client_id=concurrent.keycloak_client_id,
                    keycloak_client_uuid=concurrent.keycloak_client_uuid,
                    keycloak_client_created=False,
                    principal_created=False,
                    client_secret=None,
                )

        compensation_action = "not-required"
        if keycloak_client.created:
            compensation_action = _compensate_new_keycloak_client(
                keycloak_service=keycloak_service,
                client_uuid=keycloak_client.client.id,
                client_id=keycloak_client.client.client_id,
                company_id=company.id,
            )

        audit_m2m_event(
            "principal.create",
            request_id=request_id,
            outcome="error",
            actor=actor,
            company=company,
            reason=f"persistence-failed:{compensation_action}",
            extra={
                "keycloak_client_id": keycloak_client.client.client_id,
                "keycloak_client_uuid": keycloak_client.client.id,
            },
        )

        raise M2MProvisioningError(
            (
                "Unable to persist IntegrationPrincipal after Keycloak client "
                "provisioning."
            ),
            client_id=keycloak_client.client.client_id,
            client_uuid=keycloak_client.client.id,
            compensation_action=compensation_action,
        ) from exc

    audit_m2m_event(
        "principal.create",
        request_id=request_id,
        outcome="success",
        actor=actor,
        company=company,
        principal=principal,
        reason="created" if keycloak_client.created else "reused-keycloak-client",
    )

    return M2MProvisionResult(
        principal=principal,
        keycloak_client_id=keycloak_client.client.client_id,
        keycloak_client_uuid=keycloak_client.client.id,
        keycloak_client_created=keycloak_client.created,
        principal_created=True,
        client_secret=keycloak_client.secret if keycloak_client.created else None,
    )
