# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from rpsd_config.server.keycloak_admin import KeycloakAdminService

from ..models import Agency, AgencyInvitation, AgencyMembership
from ..rbac import resolve_user_agency_scope
from .agency_invitations import (
    AgencyInvitationCreateResult,
    AgencyInvitationPermissionError,
    AgencyInvitationProvisioningError,
    AgencyInvitationValidationError,
    create_agency_invitation,
)


class AgencyBootstrapPermissionError(PermissionError):
    """Raised when caller cannot bootstrap a new agency."""


class AgencyBootstrapValidationError(ValueError):
    """Raised for invalid payload/state in agency bootstrap workflow."""


class AgencyBootstrapProvisioningError(RuntimeError):
    """Raised when Keycloak provisioning fails for agency bootstrap workflow."""


@dataclass(frozen=True)
class AgencyBootstrapResult:
    agency: Agency
    invitation: AgencyInvitation
    assigned_group_path: str
    provisioned_user_id: str | None


def _ensure_platform_admin_actor(actor) -> None:
    scope = resolve_user_agency_scope(actor)
    if getattr(actor, "is_superuser", False) or scope.is_platform_admin:
        return
    raise AgencyBootstrapPermissionError(
        "Caller is not allowed to bootstrap a new agency."
    )


def _normalize_bootstrap_payload(
    *,
    agency_name: str,
    initial_admin_email: str,
    agency_key: str | None,
) -> tuple[str, str, str]:
    normalized_name = (agency_name or "").strip()
    if not normalized_name:
        raise AgencyBootstrapValidationError("Agency name is required.")

    normalized_email = (initial_admin_email or "").strip().lower()
    if not normalized_email:
        raise AgencyBootstrapValidationError("Initial admin email is required.")

    normalized_key = Agency.normalize_agency_key(agency_key or normalized_name)
    if Agency.objects.filter(agency_key=normalized_key).exists():
        raise AgencyBootstrapValidationError(
            f"Agency key '{normalized_key}' already exists."
        )
    if Agency.objects.filter(name__iexact=normalized_name).exists():
        raise AgencyBootstrapValidationError(
            f"Agency name '{normalized_name}' already exists."
        )

    return normalized_name, normalized_email, normalized_key


def _build_bootstrap_result(
    *,
    agency: Agency,
    invitation_result: AgencyInvitationCreateResult,
) -> AgencyBootstrapResult:
    return AgencyBootstrapResult(
        agency=agency,
        invitation=invitation_result.invitation,
        assigned_group_path=invitation_result.assigned_group_path,
        provisioned_user_id=invitation_result.provisioned_user_id,
    )


def bootstrap_agency_with_admin_invitation(
    *,
    actor,
    agency_name: str,
    initial_admin_email: str,
    agency_key: str | None = None,
    keycloak: KeycloakAdminService | None = None,
    provision_user_if_missing: bool = True,
) -> AgencyBootstrapResult:
    _ensure_platform_admin_actor(actor)

    normalized_name, normalized_email, normalized_key = _normalize_bootstrap_payload(
        agency_name=agency_name,
        initial_admin_email=initial_admin_email,
        agency_key=agency_key,
    )

    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    try:
        with transaction.atomic():
            agency = Agency.objects.create(
                name=normalized_name,
                agency_key=normalized_key,
            )
            invitation_result = create_agency_invitation(
                actor=actor,
                agency=agency,
                role_to_assign=AgencyMembership.Role.AGENCY_ADMIN,
                email=normalized_email,
                keycloak=keycloak_service,
                provision_user_if_missing=provision_user_if_missing,
            )
            return _build_bootstrap_result(
                agency=agency,
                invitation_result=invitation_result,
            )
    except AgencyInvitationPermissionError as exc:
        raise AgencyBootstrapPermissionError(str(exc)) from exc
    except AgencyInvitationValidationError as exc:
        raise AgencyBootstrapValidationError(str(exc)) from exc
    except AgencyInvitationProvisioningError as exc:
        raise AgencyBootstrapProvisioningError(str(exc)) from exc
    except ValidationError as exc:
        raise AgencyBootstrapValidationError(f"Agency validation failed: {exc}") from exc
    except IntegrityError as exc:
        raise AgencyBootstrapValidationError(
            "Unable to bootstrap agency due to a constraint violation."
        ) from exc
