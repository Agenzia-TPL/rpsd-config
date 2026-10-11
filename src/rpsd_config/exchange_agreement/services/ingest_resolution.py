# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Current-only ingest configuration resolution from approved snapshots."""

from dataclasses import dataclass

from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionError,
    canonical_snapshot_checksum,
)


class IngestResolutionError(RuntimeError):
    """Stable domain error raised while resolving runtime configuration."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.public_message = message
        super().__init__(message)


@dataclass(frozen=True)
class CurrentContractConfiguration:
    contract: Contract
    revision: ContractConfigurationRevision
    snapshot_schema_version: str
    snapshot_checksum: str
    snapshot: dict


@dataclass(frozen=True)
class CurrentIngestConfiguration(CurrentContractConfiguration):
    data_category: str
    dataset_specification: dict
    input_flow_version: dict
    orchestration_flow_version: dict


def _require_mapping(value, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            f"Current configuration has an invalid {label}",
        )
    return value


def _require_text_fields(value: dict, *, fields: tuple[str, ...], label: str) -> None:
    if any(
        not isinstance(value.get(name), str) or not value[name].strip()
        for name in fields
    ):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            f"Current configuration has incomplete {label}",
        )


def resolve_current_contract_configuration(
    contract: Contract,
) -> CurrentContractConfiguration:
    """Resolve and integrity-check today's approved contract snapshot."""

    today = timezone.localdate()
    if (
        contract.status != Contract.ContractStatus.ACTIVE
        or contract.start_date > today
        or (contract.end_date is not None and contract.end_date < today)
    ):
        raise IngestResolutionError(
            "contract_not_effective",
            "Contract is not effective today",
        )

    revisions = ContractConfigurationRevision.objects.filter(
        contract=contract,
        status=ContractConfigurationRevision.Status.APPROVED,
        valid_from__lte=today,
    ).order_by("-valid_from", "-revision_number")
    revision = revisions.first()
    if revision is None:
        raise IngestResolutionError(
            "configuration_not_ready",
            "Current contract configuration is not available",
        )
    if revisions.filter(valid_from=revision.valid_from).count() != 1:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current contract configuration is ambiguous",
        )

    snapshot = _require_mapping(
        revision.configuration_snapshot,
        label="snapshot",
    )
    try:
        digest = canonical_snapshot_checksum(snapshot)
    except ContractRevisionError as exc:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current configuration cannot be serialized",
        ) from exc
    if (
        revision.snapshot_schema_version
        not in {"canonical-json-v1", "canonical-json-v2"}
        or snapshot.get("snapshot_schema_version") != revision.snapshot_schema_version
        or not revision.snapshot_checksum
        or digest != revision.snapshot_checksum
    ):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current contract configuration failed integrity checks",
        )

    contract_snapshot = _require_mapping(
        snapshot.get("contract"), label="contract metadata"
    )
    if contract_snapshot.get("code") != contract.contract_code:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "The snapshot belongs to a different contract",
        )
    revision_snapshot = _require_mapping(
        snapshot.get("revision"),
        label="revision metadata",
    )
    if revision_snapshot.get("code") != revision.code:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current contract configuration revision does not match its snapshot",
        )

    return CurrentContractConfiguration(
        contract=contract,
        revision=revision,
        snapshot_schema_version=revision.snapshot_schema_version,
        snapshot_checksum=revision.snapshot_checksum,
        snapshot=snapshot,
    )


def resolve_current_ingest_configuration(
    contract: Contract,
    data_category: str,
) -> CurrentIngestConfiguration:
    """Resolve today's approved input without accepting a client-supplied date."""

    category = (data_category or "").strip().lower()
    current = resolve_current_contract_configuration(contract)
    snapshot = current.snapshot

    inputs = snapshot.get("inputs")
    if not isinstance(inputs, list):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current contract configuration has invalid inputs",
        )
    if any(not isinstance(item, dict) for item in inputs):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current configuration has invalid input entries",
        )
    matches = [item for item in inputs if item.get("dataset_code") == category]
    if not matches:
        raise IngestResolutionError(
            "data_category_not_configured",
            "The requested data category is not configured",
        )
    if len(matches) != 1:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "Current contract configuration has ambiguous inputs",
        )

    selected = _require_mapping(matches[0], label="selected input")
    specification = _require_mapping(
        selected.get("dataset_specification"),
        label="dataset specification",
    )
    input_flow = _require_mapping(
        selected.get("input_flow"),
        label="input flow",
    )
    orchestration = _require_mapping(
        snapshot.get("orchestration_flow"),
        label="orchestration flow",
    )
    _require_text_fields(
        specification,
        fields=("code", "version"),
        label="dataset specification",
    )
    flow_fields = (
        "code",
        "version",
        "engine",
        "deployment_name",
        "artifact_identifier",
    )
    _require_text_fields(input_flow, fields=flow_fields, label="input flow")
    _require_text_fields(
        orchestration,
        fields=flow_fields,
        label="orchestration flow",
    )

    return CurrentIngestConfiguration(
        contract=contract,
        revision=current.revision,
        snapshot_schema_version=current.snapshot_schema_version,
        snapshot_checksum=current.snapshot_checksum,
        snapshot=snapshot,
        data_category=category,
        dataset_specification=specification,
        input_flow_version=input_flow,
        orchestration_flow_version=orchestration,
    )
