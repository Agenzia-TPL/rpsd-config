# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q
from django.utils import timezone
from ninja.errors import HttpError

from ..models import Contract, IntegrationGrant, IntegrationPrincipal


@dataclass(frozen=True)
class IntegrationGrantDecision:
    allowed: bool
    reason: str
    principal: IntegrationPrincipal | None = None
    grant: IntegrationGrant | None = None


def active_grants_filter(at: datetime | None = None, *, prefix: str = "") -> Q:
    checked_at = at or timezone.now()
    return (
        Q(**{f"{prefix}status": IntegrationGrant.Status.ACTIVE})
        & (
            Q(**{f"{prefix}valid_from__isnull": True})
            | Q(**{f"{prefix}valid_from__lte": checked_at})
        )
        & (
            Q(**{f"{prefix}valid_to__isnull": True})
            | Q(**{f"{prefix}valid_to__gte": checked_at})
        )
    )


def accessible_contracts_for_principal(
    principal: IntegrationPrincipal,
    *,
    action: str = IntegrationGrant.Action.INGEST_WRITE,
    at: datetime | None = None,
):
    checked_at = at or timezone.now()
    return (
        Contract.objects.select_related(
            "lot",
            "client_agency",
            "contractor_company",
            "replaced_by",
            "flow_profile",
        )
        .filter(
            status=Contract.ContractStatus.ACTIVE,
            start_date__lte=checked_at.date(),
            contractor_company=principal.company,
            integration_grants__principal=principal,
            integration_grants__action=action,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=checked_at.date()))
        .filter(active_grants_filter(checked_at, prefix="integration_grants__"))
        .distinct()
    )


def require_m2m_principal(request) -> IntegrationPrincipal:
    principal = getattr(request, "integration_principal", None)
    if principal is None:
        raise HttpError(401, "M2M authentication required.")
    return principal


def default_active_principal_for_company(
    company_id: int,
    *,
    environment: str = "prod",
) -> IntegrationPrincipal | None:
    return (
        IntegrationPrincipal.objects.filter(
            company_id=company_id,
            environment=(environment or "prod").strip().lower(),
            status=IntegrationPrincipal.Status.ACTIVE,
        )
        .order_by("id")
        .first()
    )


def ensure_default_contract_ingest_grant(
    *,
    contract: Contract,
    actor=None,
    environment: str = "prod",
) -> IntegrationGrant | None:
    """Ensure the contractor company's default M2M client can ingest for contract.

    The grant is intentionally category-neutral: the contract flow profile
    remains responsible for selecting the admissible data categories.
    """

    principal = default_active_principal_for_company(
        contract.contractor_company_id,
        environment=environment,
    )
    if principal is None:
        return None

    grant, _created = IntegrationGrant.objects.get_or_create(
        principal=principal,
        contract=contract,
        action=IntegrationGrant.Action.INGEST_WRITE,
        data_category=None,
        defaults={
            "status": IntegrationGrant.Status.ACTIVE,
            "created_by": actor if getattr(actor, "pk", None) else None,
        },
    )
    return grant


def require_m2m_contract_access(
    request,
    *,
    contract_code: str,
    action: str = IntegrationGrant.Action.INGEST_WRITE,
    data_category: str | None = None,
    at: datetime | None = None,
) -> tuple[IntegrationPrincipal, Contract, IntegrationGrant | None]:
    principal = require_m2m_principal(request)
    decision = can_client_ingest_for_contract(
        keycloak_client_id=principal.keycloak_client_id,
        contract_code=contract_code,
        data_category=data_category,
        environment=principal.environment,
        action=action,
        at=at,
    )
    if not decision.allowed:
        if decision.reason in {"contract-not-found", "principal-company-mismatch"}:
            raise HttpError(404, "Contract not found.")
        raise HttpError(403, f"M2M contract access denied: {decision.reason}.")

    contract = (
        Contract.objects.select_related(
            "lot",
            "client_agency",
            "contractor_company",
            "replaced_by",
            "flow_profile",
        )
        .filter(contract_code=contract_code)
        .get()
    )
    return principal, contract, decision.grant


def can_client_ingest_for_contract(
    *,
    keycloak_client_id: str,
    contract_code: str,
    data_category: str | None = None,
    environment: str = "prod",
    action: str = IntegrationGrant.Action.INGEST_WRITE,
    at: datetime | None = None,
) -> IntegrationGrantDecision:
    checked_at = at or timezone.now()
    principal = (
        IntegrationPrincipal.objects.select_related("company")
        .filter(
            keycloak_client_id=keycloak_client_id,
            environment=(environment or "prod").strip().lower(),
        )
        .first()
    )
    if principal is None:
        return IntegrationGrantDecision(False, "principal-not-found")
    if principal.status == IntegrationPrincipal.Status.SUSPENDED:
        return IntegrationGrantDecision(False, "principal-suspended", principal)
    if principal.status == IntegrationPrincipal.Status.REVOKED:
        return IntegrationGrantDecision(False, "principal-revoked", principal)
    if principal.status != IntegrationPrincipal.Status.ACTIVE:
        return IntegrationGrantDecision(False, "principal-not-active", principal)

    contract = Contract.objects.filter(contract_code=contract_code).first()
    if contract is None:
        return IntegrationGrantDecision(False, "contract-not-found", principal)
    if contract.contractor_company_id != principal.company_id:
        return IntegrationGrantDecision(False, "principal-company-mismatch", principal)
    if not contract.is_active_today:
        return IntegrationGrantDecision(False, "contract-inactive", principal)
    if action not in {choice[0] for choice in IntegrationGrant.Action.choices}:
        return IntegrationGrantDecision(False, "unsupported-action", principal)

    category = (data_category or "").strip().lower()
    category_filter = Q(data_category__isnull=True)
    if category:
        category_filter |= Q(data_category=category)

    qs = (
        IntegrationGrant.objects.filter(
            principal=principal,
            contract=contract,
            action=action,
            status=IntegrationGrant.Status.ACTIVE,
        )
        .filter(category_filter)
        .order_by("-data_category", "id")
    )
    grant = qs.filter(
        Q(valid_from__isnull=True) | Q(valid_from__lte=checked_at),
        Q(valid_to__isnull=True) | Q(valid_to__gte=checked_at),
    ).first()
    if grant is not None:
        return IntegrationGrantDecision(True, "grant-active", principal, grant)

    if qs.exists():
        return IntegrationGrantDecision(
            False,
            "grant-not-in-validity-window",
            principal,
        )
    return IntegrationGrantDecision(False, "grant-missing", principal)
