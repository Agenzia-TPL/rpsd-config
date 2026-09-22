# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Reusable role policies for contract configuration revisions."""

from rpsd_config.exchange_agreement.models import (
    AgencyMembership,
    Contract,
    ContractMembership,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope


class ContractRevisionPermissionError(PermissionError):
    """Raised when an actor cannot perform a revision operation."""


def can_prepare_contract_revision(*, user, contract: Contract) -> bool:
    """Return whether a user may create or edit a draft for the contract."""

    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True

    scope = resolve_user_agency_scope(user)
    agency_key = contract.client_agency.agency_key
    if scope.is_platform_admin or agency_key in (
        set(scope.admin_agency_keys) | set(scope.editor_agency_keys)
    ):
        return True

    if AgencyMembership.objects.filter(
        agency_id=contract.client_agency_id,
        user=user,
        status=AgencyMembership.Status.ACTIVE,
        role__in={
            AgencyMembership.Role.AGENCY_ADMIN,
            AgencyMembership.Role.AGENCY_EDITOR,
        },
    ).exists():
        return True

    return ContractMembership.objects.filter(
        contract=contract,
        user=user,
        role__in={
            ContractMembership.Role.CONTRACT_ADMIN,
            ContractMembership.Role.CONTRACT_EDITOR,
        },
    ).exists()


def can_approve_contract_revision(*, user) -> bool:
    """Return whether a user may approve or withdraw a revision."""

    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return resolve_user_agency_scope(user).is_platform_admin


def require_revision_preparer(*, user, contract: Contract) -> None:
    if not can_prepare_contract_revision(user=user, contract=contract):
        raise ContractRevisionPermissionError(
            "The actor cannot prepare revisions for this contract."
        )


def require_revision_approver(*, user) -> None:
    if not can_approve_contract_revision(user=user):
        raise ContractRevisionPermissionError(
            "Only a platform administrator can approve or withdraw revisions."
        )
