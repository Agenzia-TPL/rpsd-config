# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass

from allauth.socialaccount.models import SocialAccount
from django.db import transaction
from django.utils import timezone

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminConfigError,
    KeycloakAdminService,
)

from ..models import Agency, AgencyMembership
from ..rbac import (
    agency_role_to_group_path,
    agency_role_to_group_suffix,
    iter_agency_group_assignments,
    resolve_user_agency_scope,
)


class AgencyMembershipPermissionError(PermissionError):
    """Raised when caller cannot manage agency memberships."""


class AgencyMembershipValidationError(ValueError):
    """Raised for invalid agency membership state or payload."""


class AgencyMembershipProvisioningError(RuntimeError):
    """Raised when Keycloak membership provisioning fails."""


@dataclass(frozen=True)
class AgencyMembershipSyncResult:
    touched: int
    revoked: int


def _keycloak_user_id_for_user(*, user, keycloak: KeycloakAdminService) -> str:
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )
    if social and social.uid:
        return str(social.uid)

    if not user.email:
        raise AgencyMembershipValidationError(
            "User has no email, unable to resolve Keycloak identity."
        )

    ensured = keycloak.ensure_user(
        username=getattr(user, "username", "") or user.email,
        email=user.email,
    )
    return ensured.id


def _ensure_actor_can_manage_agency(*, actor, agency: Agency) -> None:
    scope = resolve_user_agency_scope(actor)
    if not scope.can_manage_agency(agency.agency_key):
        raise AgencyMembershipPermissionError(
            "Caller is not allowed to manage memberships for this agency."
        )


def _validate_role(role: str) -> None:
    if role not in {choice[0] for choice in AgencyMembership.Role.choices}:
        raise AgencyMembershipValidationError("Unsupported agency membership role.")


def _group_path_for_membership(*, agency: Agency, role: str) -> str:
    return agency_role_to_group_path(agency_key=agency.agency_key, role=role)


def _group_ref_for_membership(
    *,
    keycloak: KeycloakAdminService,
    agency: Agency,
    role: str,
):
    role_suffix = agency_role_to_group_suffix(role)
    groups = keycloak.ensure_agency_groups(agency.agency_key)
    return groups[role_suffix]


def sync_agency_memberships_from_groups(
    *,
    user,
    groups,
    source: str = AgencyMembership.Source.KEYCLOAK_SYNC,
    authoritative: bool = False,
) -> AgencyMembershipSyncResult:
    """Mirror agency groups already available in OIDC claims/session into Django.

    The default mode is conservative: it creates/updates confirmed memberships
    and does not revoke local rows merely because a claim set may be incomplete.
    """

    now = timezone.now()
    grouped_by_agency: dict[str, dict] = {}
    for assignment in iter_agency_group_assignments(groups):
        current = grouped_by_agency.get(assignment["agency_key"])
        if current is None or AgencyMembership.role_rank(
            assignment["role"]
        ) > AgencyMembership.role_rank(current["role"]):
            grouped_by_agency[assignment["agency_key"]] = assignment

    agencies = {
        agency.agency_key: agency
        for agency in Agency.objects.filter(agency_key__in=grouped_by_agency)
    }
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )
    keycloak_user_id = str(social.uid) if social and social.uid else ""

    touched = 0
    seen_agency_ids: set[int] = set()
    with transaction.atomic():
        for agency_key, assignment in grouped_by_agency.items():
            agency = agencies.get(agency_key)
            if agency is None:
                continue
            membership, created = AgencyMembership.objects.get_or_create(
                agency=agency,
                user=user,
                defaults={
                    "role": assignment["role"],
                    "status": AgencyMembership.Status.ACTIVE,
                    "source": source,
                    "keycloak_group_path": assignment["group_path"],
                    "keycloak_user_id": keycloak_user_id,
                    "last_synced_at": now,
                },
            )
            seen_agency_ids.add(agency.id)

            fields: list[str] = []
            if not created:
                updates = {
                    "role": assignment["role"],
                    "status": AgencyMembership.Status.ACTIVE,
                    "source": source,
                    "keycloak_group_path": assignment["group_path"],
                    "keycloak_user_id": keycloak_user_id,
                    "last_synced_at": now,
                    "last_sync_error": "",
                    "revoked_by": None,
                    "revoked_at": None,
                }
                for field, value in updates.items():
                    if getattr(membership, field) != value:
                        setattr(membership, field, value)
                        fields.append(field)
                if fields:
                    fields.append("updated_at")
                    membership.save(update_fields=fields)
            touched += 1

        revoked = 0
        if authoritative:
            stale_memberships = AgencyMembership.objects.filter(
                user=user,
                status=AgencyMembership.Status.ACTIVE,
            ).exclude(agency_id__in=seen_agency_ids)
            revoked = stale_memberships.update(
                status=AgencyMembership.Status.REVOKED,
                source=source,
                revoked_at=now,
                last_synced_at=now,
                updated_at=now,
            )

    return AgencyMembershipSyncResult(touched=touched, revoked=revoked)


def assign_agency_membership(
    *,
    actor,
    agency: Agency,
    user,
    role: str,
    keycloak: KeycloakAdminService | None = None,
    source: str = AgencyMembership.Source.ADMIN_ACTION,
    enforce_actor_permission: bool = True,
    preserve_higher_local_role: bool = False,
) -> AgencyMembership:
    if enforce_actor_permission:
        _ensure_actor_can_manage_agency(actor=actor, agency=agency)
    _validate_role(role)
    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    effective_role = role
    existing_membership = AgencyMembership.objects.filter(
        agency=agency,
        user=user,
    ).first()
    if (
        preserve_higher_local_role
        and existing_membership is not None
        and AgencyMembership.role_rank(existing_membership.role)
        > AgencyMembership.role_rank(role)
    ):
        effective_role = existing_membership.role

    try:
        group_ref = _group_ref_for_membership(
            keycloak=keycloak_service,
            agency=agency,
            role=effective_role,
        )
        keycloak_user_id = _keycloak_user_id_for_user(
            user=user,
            keycloak=keycloak_service,
        )
        keycloak_service.assign_user_to_group(
            user_id=keycloak_user_id,
            group_id=group_ref.id,
        )
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        raise AgencyMembershipProvisioningError(
            f"Unable to assign agency group in Keycloak: {exc}"
        ) from exc

    now = timezone.now()
    membership, _ = AgencyMembership.objects.update_or_create(
        agency=agency,
        user=user,
        defaults={
            "role": effective_role,
            "status": AgencyMembership.Status.ACTIVE,
            "source": source,
            "keycloak_group_path": group_ref.path,
            "keycloak_user_id": keycloak_user_id,
            "last_synced_at": now,
            "last_sync_error": "",
            "updated_by": actor,
            "revoked_by": None,
            "revoked_at": None,
        },
    )
    if membership.created_by_id is None:
        membership.created_by = actor
        membership.save(update_fields=["created_by", "updated_at"])
    return membership


def change_agency_membership_role(
    *,
    actor,
    membership: AgencyMembership,
    new_role: str,
    keycloak: KeycloakAdminService | None = None,
) -> AgencyMembership:
    _ensure_actor_can_manage_agency(actor=actor, agency=membership.agency)
    _validate_role(new_role)

    old_role = membership.role
    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    try:
        new_group_ref = _group_ref_for_membership(
            keycloak=keycloak_service,
            agency=membership.agency,
            role=new_role,
        )
        keycloak_user_id = _keycloak_user_id_for_user(
            user=membership.user,
            keycloak=keycloak_service,
        )
        keycloak_service.assign_user_to_group(
            user_id=keycloak_user_id,
            group_id=new_group_ref.id,
        )
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        raise AgencyMembershipProvisioningError(
            f"Unable to assign new agency group in Keycloak: {exc}"
        ) from exc

    old_group_path = _group_path_for_membership(agency=membership.agency, role=old_role)
    try:
        old_group_ref = keycloak_service.get_group_by_path(old_group_path)
        if old_group_ref is not None and old_group_ref.id != new_group_ref.id:
            keycloak_service.remove_user_from_group(
                user_id=keycloak_user_id,
                group_id=old_group_ref.id,
            )
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        membership.status = AgencyMembership.Status.SYNC_ERROR
        membership.source = AgencyMembership.Source.ADMIN_ACTION
        membership.keycloak_group_path = new_group_ref.path
        membership.keycloak_user_id = keycloak_user_id
        membership.last_sync_error = str(exc)
        membership.updated_by = actor
        membership.save(
            update_fields=[
                "status",
                "source",
                "keycloak_group_path",
                "keycloak_user_id",
                "last_sync_error",
                "updated_by",
                "updated_at",
            ]
        )
        raise AgencyMembershipProvisioningError(
            f"New Keycloak group assigned, but old group removal failed: {exc}"
        ) from exc

    membership.role = new_role
    membership.status = AgencyMembership.Status.ACTIVE
    membership.source = AgencyMembership.Source.ADMIN_ACTION
    membership.keycloak_group_path = new_group_ref.path
    membership.keycloak_user_id = keycloak_user_id
    membership.last_synced_at = timezone.now()
    membership.last_sync_error = ""
    membership.updated_by = actor
    membership.revoked_by = None
    membership.revoked_at = None
    membership.save(
        update_fields=[
            "role",
            "status",
            "source",
            "keycloak_group_path",
            "keycloak_user_id",
            "last_synced_at",
            "last_sync_error",
            "updated_by",
            "revoked_by",
            "revoked_at",
            "updated_at",
        ]
    )
    return membership


def revoke_agency_membership(
    *,
    actor,
    membership: AgencyMembership,
    keycloak: KeycloakAdminService | None = None,
) -> AgencyMembership:
    _ensure_actor_can_manage_agency(actor=actor, agency=membership.agency)
    keycloak_service = keycloak or KeycloakAdminService.from_settings()

    group_path = membership.keycloak_group_path or _group_path_for_membership(
        agency=membership.agency,
        role=membership.role,
    )
    try:
        group_ref = keycloak_service.get_group_by_path(group_path)
        keycloak_user_id = membership.keycloak_user_id or _keycloak_user_id_for_user(
            user=membership.user,
            keycloak=keycloak_service,
        )
        if group_ref is not None:
            keycloak_service.remove_user_from_group(
                user_id=keycloak_user_id,
                group_id=group_ref.id,
            )
    except (KeycloakAdminConfigError, KeycloakAdminAPIError) as exc:
        raise AgencyMembershipProvisioningError(
            f"Unable to revoke agency group in Keycloak: {exc}"
        ) from exc

    now = timezone.now()
    membership.status = AgencyMembership.Status.REVOKED
    membership.source = AgencyMembership.Source.ADMIN_ACTION
    membership.keycloak_user_id = keycloak_user_id
    membership.last_synced_at = now
    membership.last_sync_error = ""
    membership.updated_by = actor
    membership.revoked_by = actor
    membership.revoked_at = now
    membership.save(
        update_fields=[
            "status",
            "source",
            "keycloak_user_id",
            "last_synced_at",
            "last_sync_error",
            "updated_by",
            "revoked_by",
            "revoked_at",
            "updated_at",
        ]
    )
    return membership
