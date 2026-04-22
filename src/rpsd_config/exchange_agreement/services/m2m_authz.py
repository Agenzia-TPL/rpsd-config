# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from ..models import Contract, IntegrationGrant, IntegrationPrincipal


@dataclass(frozen=True)
class M2MAuthzDecision:
    allowed: bool
    reason: str


def _is_contract_active_for_ingest(contract: Contract) -> bool:
    """Return True when contract lifecycle allows M2M ingest writes."""
    return contract.is_active_today


def evaluate_m2m_authz(
    *,
    principal_id: str,
    action: str,
    contract_code: str,
    data_category: str | None = None,
) -> M2MAuthzDecision:
    principal = (
        IntegrationPrincipal.objects.select_related("company")
        .filter(keycloak_client_id=principal_id)
        .first()
    )
    if principal is None:
        return M2MAuthzDecision(allowed=False, reason="principal-not-found")

    if principal.status == IntegrationPrincipal.Status.SUSPENDED:
        return M2MAuthzDecision(allowed=False, reason="principal-suspended")
    if principal.status == IntegrationPrincipal.Status.REVOKED:
        return M2MAuthzDecision(allowed=False, reason="principal-revoked")
    if principal.status != IntegrationPrincipal.Status.ACTIVE:
        return M2MAuthzDecision(allowed=False, reason="principal-inactive")

    contract = (
        Contract.objects.select_related("contractor_company")
        .filter(contract_code=contract_code)
        .first()
    )
    if contract is None:
        return M2MAuthzDecision(allowed=False, reason="contract-not-found")

    # Lifecycle gate: no grant can authorize writes on an inactive contract.
    if not _is_contract_active_for_ingest(contract):
        return M2MAuthzDecision(allowed=False, reason="contract-inactive")

    if contract.contractor_company_id != principal.company_id:
        return M2MAuthzDecision(allowed=False, reason="principal-company-mismatch")

    supported_actions = {value for value, _label in IntegrationGrant.Action.choices}
    if action not in supported_actions:
        return M2MAuthzDecision(allowed=False, reason="unsupported-action")

    grant_qs = IntegrationGrant.objects.filter(
        principal=principal,
        contract=contract,
        action=action,
        status=IntegrationGrant.Status.ACTIVE,
    )
    if not grant_qs.exists():
        return M2MAuthzDecision(allowed=False, reason="grant-missing")

    if data_category:
        grant_qs = grant_qs.filter(
            Q(data_category=data_category) | Q(data_category__isnull=True)
        )
        if not grant_qs.exists():
            return M2MAuthzDecision(
                allowed=False, reason="grant-data-category-mismatch"
            )

    now = timezone.now()
    grant_qs = grant_qs.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=now),
        Q(valid_to__isnull=True) | Q(valid_to__gte=now),
    )
    if not grant_qs.exists():
        return M2MAuthzDecision(allowed=False, reason="grant-not-in-validity-window")

    return M2MAuthzDecision(allowed=True, reason="grant-active")
