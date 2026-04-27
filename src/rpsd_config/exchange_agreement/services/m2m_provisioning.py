# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminConfigError,
    KeycloakAdminService,
)

from ..models import Company, IntegrationPrincipal
from .m2m_audit import audit_m2m_event
from .m2m_client_naming import resolve_default_m2m_client_id
from .m2m_secret_store import store_client_secret


class M2MProvisioningError(RuntimeError):
    """Raised when default company M2M provisioning fails."""


@dataclass(frozen=True)
class M2MProvisionResult:
    principal: IntegrationPrincipal
    created: bool


def provision_default_m2m_principal_for_company(
    *,
    company: Company,
    actor=None,
    keycloak: KeycloakAdminService | None = None,
) -> M2MProvisionResult:
    environment = getattr(settings, "M2M_DEFAULT_ENVIRONMENT", "prod")
    existing = (
        IntegrationPrincipal.objects.filter(company=company, environment=environment)
        .order_by("id")
        .first()
    )
    if existing is not None:
        audit_m2m_event(
            "principal.reused",
            company_id=company.pk,
            principal_id=existing.pk,
            keycloak_client_id=existing.keycloak_client_id,
        )
        return M2MProvisionResult(principal=existing, created=False)

    client_id = resolve_default_m2m_client_id(company, environment=environment)
    service = keycloak or KeycloakAdminService.from_settings()
    try:
        client = service.create_confidential_m2m_client(
            client_id=client_id,
            name=f"{company.name} default {environment}",
        )
        client_secret = service.get_client_secret(client_uuid=client.id)
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        audit_m2m_event(
            "principal.provision_error",
            company_id=company.pk,
            error=str(exc),
        )
        raise M2MProvisioningError(f"Unable to provision M2M client: {exc}") from exc

    try:
        with transaction.atomic():
            principal = IntegrationPrincipal.objects.create(
                company=company,
                name="default",
                environment=environment,
                keycloak_client_id=client.client_id,
                keycloak_client_uuid=client.id,
                status=IntegrationPrincipal.Status.ACTIVE,
                created_by=actor if getattr(actor, "is_authenticated", False) else None,
            )
            store_client_secret(principal, client_secret=client_secret)
            audit_m2m_event(
                "principal.created",
                company_id=company.pk,
                principal_id=principal.pk,
                keycloak_client_id=principal.keycloak_client_id,
            )
            return M2MProvisionResult(principal=principal, created=True)
    except Exception as exc:
        try:
            service.delete_client(client_uuid=client.id)
            compensation = "delete"
        except Exception:
            try:
                service.disable_client(client_uuid=client.id)
                compensation = "disable"
            except Exception:
                compensation = "failed"
        audit_m2m_event(
            "principal.compensated",
            company_id=company.pk,
            keycloak_client_id=client.client_id,
            compensation=compensation,
            error=str(exc),
        )
        raise M2MProvisioningError(
            "Unable to persist M2M principal after Keycloak client creation."
        ) from exc


def rotate_m2m_principal_secret(
    *,
    principal: IntegrationPrincipal,
    actor=None,
    keycloak: KeycloakAdminService | None = None,
) -> str:
    service = keycloak or KeycloakAdminService.from_settings()
    secret = service.rotate_client_secret(client_uuid=principal.keycloak_client_uuid)
    principal.last_secret_rotation_at = timezone.now()
    principal.save(update_fields=["last_secret_rotation_at", "updated_at"])
    store_client_secret(principal, client_secret=secret)
    audit_m2m_event(
        "secret.rotated",
        principal_id=principal.pk,
        company_id=principal.company_id,
        keycloak_client_id=principal.keycloak_client_id,
        actor_id=getattr(actor, "pk", None),
    )
    return secret


def revoke_m2m_principal(
    *,
    principal: IntegrationPrincipal,
    actor=None,
    keycloak: KeycloakAdminService | None = None,
) -> None:
    from .m2m_secret_store import clear_client_secret

    service = keycloak or KeycloakAdminService.from_settings()
    if principal.keycloak_client_uuid:
        service.disable_client(client_uuid=principal.keycloak_client_uuid)
    clear_client_secret(principal)
    principal.status = IntegrationPrincipal.Status.REVOKED
    principal.save(update_fields=["status", "updated_at"])
    audit_m2m_event(
        "principal.revoked",
        principal_id=principal.pk,
        company_id=principal.company_id,
        keycloak_client_id=principal.keycloak_client_id,
        actor_id=getattr(actor, "pk", None),
    )
