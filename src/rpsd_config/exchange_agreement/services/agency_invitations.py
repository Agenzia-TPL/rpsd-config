# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import hashlib
import re
from dataclasses import dataclass

from allauth.socialaccount.models import SocialAccount
from django.db import IntegrityError, transaction
from django.utils import timezone

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminConfigError,
    KeycloakAdminService,
)

from ..models import Agency, AgencyInvitation, AgencyMembership
from ..rbac import (
    agency_role_to_group_suffix,
    resolve_user_agency_scope,
)


class AgencyInvitationPermissionError(PermissionError):
    """Raised when caller cannot execute agency invitation actions."""


class AgencyInvitationValidationError(ValueError):
    """Raised for invalid payload/state in agency invitation workflows."""


class AgencyInvitationProvisioningError(RuntimeError):
    """Raised when Keycloak provisioning fails for agency invitation workflows."""


@dataclass(frozen=True)
class AgencyInvitationCreateResult:
    invitation: AgencyInvitation
    assigned_group_path: str
    provisioned_user_id: str | None


@dataclass(frozen=True)
class AgencyInvitationAcceptResult:
    invitation: AgencyInvitation
    membership: AgencyMembership
    assigned_group_path: str


def _username_candidate_from_email(email: str) -> str:
    normalized_email = (email or "").strip().lower()
    if normalized_email:
        return normalized_email

    local_part = re.sub(r"[^a-z0-9._-]+", "-", "invited-user")
    local_part = re.sub(r"-+", "-", local_part).strip("-._") or "invited-user"
    digest = hashlib.sha1(b"invited-user").hexdigest()[:8]
    return f"{local_part}-{digest}"


def _resolve_keycloak_user_id_for_logged_user(
    *,
    user,
    keycloak: KeycloakAdminService,
) -> str:
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )
    if social and social.uid:
        return str(social.uid)

    if not user.email:
        raise AgencyInvitationValidationError(
            "Authenticated user has no email, unable to resolve Keycloak identity."
        )

    ensured = keycloak.ensure_user(
        username=(
            getattr(user, "username", "")
            or _username_candidate_from_email(user.email)
        ),
        email=user.email,
    )
    return ensured.id


def create_agency_invitation(
    *,
    actor,
    agency: Agency,
    role_to_assign: str,
    email: str | None,
    keycloak: KeycloakAdminService | None = None,
    provision_user_if_missing: bool = True,
) -> AgencyInvitationCreateResult:
    scope = resolve_user_agency_scope(actor)
    if not scope.can_manage_agency(agency.agency_key):
        raise AgencyInvitationPermissionError(
            "Caller is not allowed to manage invitations for this agency."
        )

    role_choices = {choice[0] for choice in AgencyMembership.Role.choices}
    if role_to_assign not in role_choices:
        raise AgencyInvitationValidationError("Unsupported agency role for invitation.")

    normalized_email = (email or "").strip().lower() or None
    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    try:
        groups = keycloak_service.ensure_agency_groups(agency.agency_key)
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        raise AgencyInvitationProvisioningError(
            f"Unable to ensure agency groups in Keycloak: {exc}"
        ) from exc

    provisioned_user_id: str | None = None
    if normalized_email and provision_user_if_missing:
        try:
            existing = keycloak_service.find_user_by_email(normalized_email)
            if existing is None:
                created = keycloak_service.ensure_user(
                    username=_username_candidate_from_email(normalized_email),
                    email=normalized_email,
                )
                provisioned_user_id = created.id
            else:
                provisioned_user_id = existing.id
        except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
            raise AgencyInvitationProvisioningError(
                f"Unable to provision Keycloak user for invitation: {exc}"
            ) from exc

    try:
        with transaction.atomic():
            invitation = AgencyInvitation.objects.create(
                agency=agency,
                email=normalized_email,
                role_to_assign=role_to_assign,
                invited_by=actor,
                status=AgencyInvitation.Status.PENDING,
            )
    except IntegrityError as exc:
        raise AgencyInvitationValidationError(
            "A pending invitation with the same target already exists for this agency."
        ) from exc

    role_suffix = agency_role_to_group_suffix(role_to_assign)
    assigned_group = groups[role_suffix]
    return AgencyInvitationCreateResult(
        invitation=invitation,
        assigned_group_path=assigned_group.path,
        provisioned_user_id=provisioned_user_id,
    )


@transaction.atomic
def accept_agency_invitation_for_user(
    *,
    token: str,
    user,
    keycloak: KeycloakAdminService | None = None,
) -> AgencyInvitationAcceptResult:
    invitation = (
        AgencyInvitation.objects.select_for_update()
        .select_related("agency")
        .get(token=token)
    )

    if invitation.status != AgencyInvitation.Status.PENDING:
        raise AgencyInvitationValidationError("Invitation is not pending.")

    if invitation.expires_at <= timezone.now():
        invitation.status = AgencyInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise AgencyInvitationValidationError("Invitation has expired.")

    if invitation.email:
        user_email = (user.email or "").lower()
        if user_email != invitation.email.lower():
            raise AgencyInvitationValidationError(
                "Authenticated user email does not match invitation target."
            )

    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    try:
        role_suffix = agency_role_to_group_suffix(invitation.role_to_assign)
        groups = keycloak_service.ensure_agency_groups(invitation.agency.agency_key)
        group_ref = groups[role_suffix]

        keycloak_user_id = _resolve_keycloak_user_id_for_logged_user(
            user=user,
            keycloak=keycloak_service,
        )
        keycloak_service.assign_user_to_group(
            user_id=keycloak_user_id,
            group_id=group_ref.id,
        )
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        raise AgencyInvitationProvisioningError(
            f"Unable to assign agency group in Keycloak: {exc}"
        ) from exc

    membership, _ = AgencyMembership.objects.get_or_create(
        agency=invitation.agency,
        user=user,
        defaults={
            "role": invitation.role_to_assign,
            "created_by": invitation.invited_by,
        },
    )

    invitation_rank = AgencyMembership.role_rank(invitation.role_to_assign)
    current_rank = AgencyMembership.role_rank(membership.role)
    if invitation_rank > current_rank:
        membership.role = invitation.role_to_assign
        membership.save(update_fields=["role", "updated_at"])

    invitation.status = AgencyInvitation.Status.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(
        update_fields=["status", "accepted_by", "accepted_at", "updated_at"]
    )

    return AgencyInvitationAcceptResult(
        invitation=invitation,
        membership=membership,
        assigned_group_path=group_ref.path,
    )
