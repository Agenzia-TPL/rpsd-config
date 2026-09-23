# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    ContractMembership,
    ContractPublication,
)


@dataclass
class PublishContractError(Exception):
    status_code: int
    message: str

    def __str__(self) -> str:
        return self.message


def _require_publish_permission(user, contract: Contract):
    if not user or not getattr(user, "is_authenticated", False):
        raise PublishContractError(401, "Authentication required.")
    if user.is_superuser:
        return
    if not ContractMembership.objects.filter(
        contract=contract,
        user=user,
        role=ContractMembership.Role.CONTRACT_ADMIN,
    ).exists():
        raise PublishContractError(403, "Contract admin role required to publish.")


@transaction.atomic
def publish_contract(*, contract: Contract, user) -> ContractPublication:
    """
    Publish (or republish) a contract by creating a versioned immutable snapshot.

    The publication is a verbatim, immutable copy of the current approved
    configuration revision. The first publication moves a draft contract to
    active; subsequent publications keep their own progressive audit version.
    """
    locked_contract = Contract.objects.select_for_update().get(pk=contract.pk)

    _require_publish_permission(user, locked_contract)

    if locked_contract.status == Contract.ContractStatus.CLOSED:
        raise PublishContractError(400, "Closed contracts cannot be published.")

    today = timezone.localdate()
    if locked_contract.start_date > today or (
        locked_contract.end_date is not None and locked_contract.end_date < today
    ):
        raise PublishContractError(
            400,
            "The contract is not effective today.",
        )
    revision = (
        ContractConfigurationRevision.objects.select_for_update()
        .filter(
            contract=locked_contract,
            status=ContractConfigurationRevision.Status.APPROVED,
            valid_from__lte=today,
        )
        .order_by("-valid_from", "-revision_number")
        .first()
    )
    if revision is None:
        raise PublishContractError(
            400,
            "The contract has no current approved configuration revision.",
        )

    next_version = (
        ContractPublication.objects.filter(contract=locked_contract).aggregate(
            max_version=Max("publication_version")
        )["max_version"]
        or 0
    ) + 1

    status_changed = False
    if locked_contract.status == Contract.ContractStatus.DRAFT:
        locked_contract.status = Contract.ContractStatus.ACTIVE
        status_changed = True

    publication = ContractPublication.objects.create(
        contract=locked_contract,
        configuration_revision=revision,
        publication_version=next_version,
        published_at=timezone.now(),
        published_by=user if getattr(user, "is_authenticated", False) else None,
        snapshot_schema_version=revision.snapshot_schema_version,
        snapshot=revision.configuration_snapshot,
        snapshot_checksum=revision.snapshot_checksum,
    )

    if status_changed:
        locked_contract.save(update_fields=["status", "updated_at"])

    return publication
