# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractIndicator,
    ContractMembership,
    ContractPublication,
    IndicatorDef,
    Structure,
)

SNAPSHOT_SCHEMA_VERSION = "1.0"


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


def _file_sha256(file_field) -> str | None:
    if not file_field:
        return None
    try:
        hasher = hashlib.sha256()
        with file_field.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        # Snapshot generation should be resilient if the storage
        # backend/file is missing.
        return None


def _file_metadata(file_field) -> dict[str, Any] | None:
    if not file_field:
        return None

    size_bytes = None
    try:
        size_bytes = file_field.size
    except Exception:
        size_bytes = None

    return {
        "file_name": file_field.name.split("/")[-1]
        if getattr(file_field, "name", "")
        else "",
        "storage_path": getattr(file_field, "name", ""),
        "size_bytes": size_bytes,
        "sha256": _file_sha256(file_field),
    }


def _structure_snapshot(structure: Structure) -> dict[str, Any]:
    definition = structure.definition if isinstance(structure.definition, dict) else {}
    return {
        "dataset": {
            "slug": structure.dataset.slug,
            "name": structure.dataset.name,
            "description": structure.dataset.description,
        },
        "name": structure.name,
        "description": structure.description,
        "definition": definition,
        "xpath": structure.get_xpath_selector(),
        "fields": structure.get_mandatory_fields(),
    }


def _indicator_snapshot(link: ContractIndicator) -> dict[str, Any]:
    indicator: IndicatorDef = link.indicator
    structures = list(indicator.structures.all())
    structures.sort(key=lambda s: (s.dataset.slug, s.name))
    return {
        "code": indicator.code,
        "type": indicator.type,
        "type_label": str(
            indicator.get_type_display()
            if hasattr(indicator, "get_type_display")
            else indicator.type
        ),
        "name": indicator.name,
        "description": indicator.description,
        "formula": indicator.formula,
        "notes": indicator.notes,
        "sql_procedure_name": indicator.sql_procedure_name,
        "sql_snippet": indicator.sql_snippet,
        "contract_params": link.params
        if isinstance(link.params, dict)
        else link.params,
        "structures": [_structure_snapshot(s) for s in structures],
    }


def _published_by_snapshot(user) -> dict[str, Any] | None:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    display = getattr(user, "get_full_name", lambda: "")() or getattr(
        user, "username", ""
    )
    return {
        "username": getattr(user, "username", ""),
        "email": getattr(user, "email", ""),
        "display_name": display,
    }


def build_contract_snapshot(
    contract: Contract,
    *,
    publication_version: int,
    published_at,
    published_by=None,
    snapshot_schema_version: str = SNAPSHOT_SCHEMA_VERSION,
) -> dict[str, Any]:
    """
    Build a frozen aggregate payload for a contract publication.

    The payload intentionally includes business fields and labels, while avoiding
    internal relational ids/FKs.
    """
    documents = list(contract.documents.all().order_by("-created_at", "id"))
    indicator_links = list(
        ContractIndicator.objects.select_related("indicator")
        .prefetch_related("indicator__structures__dataset")
        .filter(contract=contract)
        .order_by("indicator__code")
    )

    flow_profile_payload = None
    if contract.flow_profile:
        flow_profile_payload = {
            "code": contract.flow_profile.code,
            "name": contract.flow_profile.name,
            "description": contract.flow_profile.description,
            "schema_version": contract.flow_profile.schema_version,
            "is_active": contract.flow_profile.is_active,
            "options": contract.flow_profile.options
            if isinstance(contract.flow_profile.options, dict)
            else {},
        }

    snapshot = {
        "metadata": {
            "snapshot_schema_version": snapshot_schema_version,
            "publication_version": publication_version,
            "published_at": published_at.isoformat(),
            "published_by": _published_by_snapshot(published_by),
        },
        "contract": {
            "contract_code": contract.contract_code,
            "status": contract.status,
            "status_label": str(contract.get_status_display()),
            "contract_type": contract.contract_type,
            "contract_type_label": str(contract.contract_type_label),
            "version": contract.version,
            "tender_id": contract.tender_id,
            "start_date": contract.start_date.isoformat(),
            "end_date": contract.end_date.isoformat() if contract.end_date else None,
            "closed_at": contract.closed_at.isoformat() if contract.closed_at else None,
            "closed_reason": contract.closed_reason,
            "replaced_by_contract_code": contract.replaced_by.contract_code
            if contract.replaced_by
            else None,
            "program_file": _file_metadata(contract.contract_program_file),
        },
        "client_agency": {
            "name": contract.client_agency.name,
            "description": contract.client_agency.description,
        },
        "contractor_company": {
            "name": contract.contractor_company.name,
            "description": contract.contractor_company.description,
        },
        "lot": {
            "short_description": contract.lot.short_description,
            "description": contract.lot.description,
        },
        "flow_profile": flow_profile_payload,
        "documents": [
            {
                "name": doc.name,
                "created_at": doc.created_at.isoformat(),
                "file": _file_metadata(doc.file),
            }
            for doc in documents
        ],
        "indicators": [_indicator_snapshot(link) for link in indicator_links],
    }

    snapshot["computed_summary"] = {
        "documents_count": len(snapshot["documents"]),
        "indicators_count": len(snapshot["indicators"]),
        "structures_count": sum(
            len(item["structures"]) for item in snapshot["indicators"]
        ),
        "has_program_file": bool(snapshot["contract"]["program_file"]),
    }
    return snapshot


def compute_snapshot_checksum(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@transaction.atomic
def publish_contract(*, contract: Contract, user) -> ContractPublication:
    """
    Publish (or republish) a contract by creating a versioned immutable snapshot.

    - first publish moves status draft -> active
    - subsequent publishes on active create a new publication version
    """
    locked_contract = Contract.objects.select_for_update().get(pk=contract.pk)

    _require_publish_permission(user, locked_contract)

    if locked_contract.status == Contract.ContractStatus.CLOSED:
        raise PublishContractError(400, "Closed contracts cannot be published.")
    if locked_contract.flow_profile_id is None:
        raise PublishContractError(400, "A flow profile is required before publishing.")
    if not ContractIndicator.objects.filter(contract=locked_contract).exists():
        raise PublishContractError(
            400, "At least one contract indicator is required before publishing."
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

    published_at = timezone.now()
    snapshot = build_contract_snapshot(
        locked_contract,
        publication_version=next_version,
        published_at=published_at,
        published_by=user,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
    )
    checksum = compute_snapshot_checksum(snapshot)

    publication = ContractPublication.objects.create(
        contract=locked_contract,
        publication_version=next_version,
        published_at=published_at,
        published_by=user if getattr(user, "is_authenticated", False) else None,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_checksum=checksum,
    )

    if status_changed:
        locked_contract.save(update_fields=["status", "updated_at"])

    return publication
