# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Approval, snapshots and current-only resolution of contract revisions."""

import hashlib
import json
import math
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    DatasetSpecification,
    IndicatorVersion,
    InputFlowVersion,
    ProcessingProfileVersion,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.revision_registry import (
    validate_business_configuration,
)


class ContractRevisionError(ValueError):
    """Raised when a revision cannot be approved, withdrawn or resolved."""


def _canonical_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ContractRevisionError("Canonical JSON forbids NaN and infinity.")
        raise ContractRevisionError(
            "Canonical JSON forbids floats; use a decimal string instead."
        )
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ContractRevisionError("Canonical JSON object keys must be strings.")
        return {key: _canonical_value(value[key]) for key in sorted(value)}
    raise ContractRevisionError(
        f"Canonical JSON does not support {type(value).__name__}."
    )


def canonical_json_bytes(payload: dict) -> bytes:
    """Serialize using the closed `canonical-json-v1` rules."""

    normalized = _canonical_value(payload)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_snapshot_checksum(payload: dict) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(payload)).hexdigest()}"


def _asset_snapshot(specification: DatasetSpecification) -> list[dict]:
    links = specification.asset_links.select_related("configuration_asset").order_by(
        "configuration_asset__what",
        "configuration_asset__version",
        "role",
    )
    return [
        {
            "code": link.configuration_asset.what,
            "version": link.configuration_asset.version,
            "checksum": f"sha256:{link.configuration_asset.checksum_sha256}",
            "role": link.role,
            "required": link.required,
        }
        for link in links
    ]


def _fragment_snapshot(fragment: RequirementFragment) -> dict:
    rules = fragment.validation_rules.order_by("rule_type", "rule_version", "id")
    return {
        "dataset_specification_code": fragment.dataset_specification.code,
        "code": fragment.code,
        "locator_type": fragment.locator_type,
        "result_kind": fragment.result_kind,
        "locator_definition": fragment.locator_definition,
        "rules": [
            {
                "rule_type": rule.rule_type,
                "rule_version": rule.rule_version,
                "parameters": rule.parameters,
                "severity": rule.severity,
            }
            for rule in rules
        ],
    }


def build_revision_snapshot(revision: ContractConfigurationRevision) -> dict:
    """Resolve the draft relations into a complete PK-independent snapshot."""

    profile = revision.processing_profile_version
    orchestration = profile.orchestration_flow_version
    input_selections = (
        revision.input_selections.select_related(
            "processing_profile_input_flow__dataset",
            "processing_profile_input_flow__input_flow_version__dataset_specification",
        )
        .prefetch_related(
            "processing_profile_input_flow__input_flow_version__dataset_specification__asset_links__configuration_asset"
        )
        .order_by(
            "processing_profile_input_flow__dataset__code",
            "processing_profile_input_flow__input_flow_version__code",
        )
    )
    indicator_configurations = (
        revision.indicator_configurations.select_related(
            "contract_indicator__logical_indicator",
            "processing_profile_indicator_version__indicator_version__indicator",
        )
        .prefetch_related(
            "processing_profile_indicator_version__indicator_version__required_fragments__dataset_specification",
            "processing_profile_indicator_version__indicator_version__required_fragments__validation_rules",
        )
        .order_by(
            "contract_indicator__logical_indicator__code",
            "processing_profile_indicator_version__indicator_version__code",
        )
    )

    inputs = []
    for selection in input_selections:
        profile_input = selection.processing_profile_input_flow
        flow = profile_input.input_flow_version
        specification = flow.dataset_specification
        inputs.append(
            {
                "dataset_code": profile_input.dataset.code,
                "dataset_specification": {
                    "code": specification.code,
                    "version": specification.version,
                },
                "input_flow": {
                    "code": flow.code,
                    "version": flow.version,
                    "deployment_name": flow.deployment_name,
                    "artifact_identifier": flow.artifact_identifier,
                },
                "assets": _asset_snapshot(specification),
            }
        )

    indicators = []
    for configuration in indicator_configurations:
        version = configuration.processing_profile_indicator_version.indicator_version
        fragments = (
            version.required_fragments.select_related("dataset_specification")
            .prefetch_related("validation_rules")
            .order_by("dataset_specification__code", "code")
        )
        indicators.append(
            {
                "indicator_code": version.indicator.code,
                "indicator_version": {
                    "code": version.code,
                    "version": version.version,
                    "execution_engine": version.execution_engine,
                    "execution_reference": version.execution_reference,
                    "artifact_identifier": version.artifact_identifier,
                },
                "thresholds": configuration.thresholds,
                "aggregation": configuration.aggregation,
                "penalties": configuration.penalties,
                "parameters": configuration.parameters,
                "fragments": [_fragment_snapshot(fragment) for fragment in fragments],
            }
        )

    return {
        "snapshot_schema_version": revision.SNAPSHOT_SCHEMA_VERSION,
        "contract": {"code": revision.contract.contract_code},
        "revision": {
            "code": revision.code,
            "valid_from": revision.valid_from,
        },
        "processing_profile": {
            "code": profile.code,
            "version": profile.version,
        },
        "orchestration_flow": {
            "code": orchestration.code,
            "version": orchestration.version,
            "deployment_name": orchestration.deployment_name,
            "artifact_identifier": orchestration.artifact_identifier,
        },
        "inputs": inputs,
        "indicators": indicators,
    }


def _validate_draft_composition(revision: ContractConfigurationRevision) -> None:
    profile = revision.processing_profile_version
    if profile.status != ProcessingProfileVersion.Status.PUBLISHED:
        raise ContractRevisionError("The processing profile must be published.")

    inputs = list(
        revision.input_selections.select_related(
            "processing_profile_input_flow__input_flow_version__dataset_specification"
        )
    )
    if not inputs:
        raise ContractRevisionError("The revision must select at least one input.")
    selected_specification_ids = set()
    for selection in inputs:
        profile_input = selection.processing_profile_input_flow
        if profile_input.processing_profile_version_id != profile.pk:
            raise ContractRevisionError(
                f"Input selection {profile_input.pk} does not belong to the profile."
            )
        flow = profile_input.input_flow_version
        if flow.status != InputFlowVersion.Status.PUBLISHED:
            raise ContractRevisionError(f"Input flow {flow.code} is not published.")
        if flow.dataset_specification.status != DatasetSpecification.Status.PUBLISHED:
            raise ContractRevisionError(
                "Dataset specification "
                f"{flow.dataset_specification.code} is not published."
            )
        selected_specification_ids.add(flow.dataset_specification_id)

    configurations = list(
        revision.indicator_configurations.select_related(
            "contract_indicator__logical_indicator",
            "processing_profile_indicator_version__indicator_version",
        )
    )
    if not configurations:
        raise ContractRevisionError(
            "The revision must configure at least one indicator."
        )
    for configuration in configurations:
        contract_indicator = configuration.contract_indicator
        if contract_indicator.contract_id != revision.contract_id:
            raise ContractRevisionError(
                "A configured contract indicator belongs to another contract."
            )
        if contract_indicator.logical_indicator_id is None:
            raise ContractRevisionError(
                "Contract indicators used by revisions need a logical indicator."
            )
        profile_indicator = configuration.processing_profile_indicator_version
        if profile_indicator.processing_profile_version_id != profile.pk:
            raise ContractRevisionError(
                "A configured indicator version does not belong to the profile."
            )
        version = profile_indicator.indicator_version
        if version.status != IndicatorVersion.Status.PUBLISHED:
            raise ContractRevisionError(
                f"Indicator version {version.code} is not published."
            )
        if version.indicator_id != contract_indicator.logical_indicator_id:
            raise ContractRevisionError(
                f"Indicator version {version.code} does not match the "
                "contract indicator."
            )
        for fragment in version.required_fragments.select_related(
            "dataset_specification"
        ):
            if fragment.dataset_specification_id not in selected_specification_ids:
                raise ContractRevisionError(
                    f"Indicator version {version.code} requires fragment "
                    f"{fragment.code} from unselected specification "
                    f"{fragment.dataset_specification.code}."
                )
        for field_name in ("thresholds", "aggregation", "penalties", "parameters"):
            validate_business_configuration(
                getattr(configuration, field_name), field_name=field_name
            )


@transaction.atomic
def approve_contract_revision(
    revision: ContractConfigurationRevision,
    *,
    actor=None,
) -> ContractConfigurationRevision:
    contract = Contract.objects.select_for_update().get(pk=revision.contract_id)
    revisions = ContractConfigurationRevision.objects.select_for_update().filter(
        contract=contract
    )
    locked = revisions.select_related(
        "contract", "processing_profile_version__orchestration_flow_version"
    ).get(pk=revision.pk)
    if locked.status != ContractConfigurationRevision.Status.DRAFT:
        raise ContractRevisionError("Only a draft revision can be approved.")
    if locked.valid_from is None:
        raise ContractRevisionError("valid_from is required before approval.")
    if locked.valid_from < contract.start_date or (
        contract.end_date is not None and locked.valid_from > contract.end_date
    ):
        raise ContractRevisionError("valid_from must be inside the contract period.")

    approved = revisions.filter(
        status=ContractConfigurationRevision.Status.APPROVED
    ).order_by("valid_from", "revision_number")
    latest = approved.last()
    today = timezone.localdate()
    if locked.valid_from < today:
        raise ContractRevisionError("A revision cannot be approved retroactively.")
    if latest is None:
        if locked.valid_from != contract.start_date:
            raise ContractRevisionError(
                "The first revision must start on the contract start date."
            )
    else:
        if locked.valid_from <= latest.valid_from:
            raise ContractRevisionError(
                "A new revision must start after the latest approved revision."
            )

    _validate_draft_composition(locked)
    snapshot = build_revision_snapshot(locked)
    checksum = canonical_snapshot_checksum(snapshot)
    now = timezone.now()
    ContractConfigurationRevision.objects.filter(pk=locked.pk).update(
        status=ContractConfigurationRevision.Status.APPROVED,
        snapshot_schema_version=locked.SNAPSHOT_SCHEMA_VERSION,
        configuration_snapshot=_canonical_value(snapshot),
        snapshot_checksum=checksum,
        approved_by_id=actor.pk if getattr(actor, "pk", None) else None,
        approved_at=now,
        updated_at=now,
    )
    locked.refresh_from_db()
    return locked


@transaction.atomic
def withdraw_contract_revision(
    revision: ContractConfigurationRevision,
    *,
    actor=None,
) -> ContractConfigurationRevision:
    Contract.objects.select_for_update().get(pk=revision.contract_id)
    locked = ContractConfigurationRevision.objects.select_for_update().get(
        pk=revision.pk
    )
    if locked.status == ContractConfigurationRevision.Status.WITHDRAWN:
        raise ContractRevisionError("The revision is already withdrawn.")
    if (
        locked.status == ContractConfigurationRevision.Status.APPROVED
        and locked.valid_from is not None
        and locked.valid_from <= timezone.localdate()
    ):
        raise ContractRevisionError(
            "An already applicable revision cannot be withdrawn retroactively."
        )
    now = timezone.now()
    ContractConfigurationRevision.objects.filter(pk=locked.pk).update(
        status=ContractConfigurationRevision.Status.WITHDRAWN,
        withdrawn_by_id=actor.pk if getattr(actor, "pk", None) else None,
        withdrawn_at=now,
        updated_at=now,
    )
    locked.refresh_from_db()
    return locked


def revision_effective_period(
    revision: ContractConfigurationRevision,
) -> tuple[date, date | None]:
    if revision.status != ContractConfigurationRevision.Status.APPROVED:
        raise ContractRevisionError("Only approved revisions have an effective period.")
    next_revision = (
        ContractConfigurationRevision.objects.filter(
            contract=revision.contract,
            status=ContractConfigurationRevision.Status.APPROVED,
            valid_from__gt=revision.valid_from,
        )
        .order_by("valid_from", "revision_number")
        .first()
    )
    effective_to = (
        next_revision.valid_from - timedelta(days=1)
        if next_revision is not None
        else revision.contract.end_date
    )
    return revision.valid_from, effective_to


def revision_temporal_state(revision: ContractConfigurationRevision) -> str:
    """Derive scheduled, active and expired without persisting those states."""

    if revision.status != ContractConfigurationRevision.Status.APPROVED:
        return revision.status
    today = timezone.localdate()
    effective_from, effective_to = revision_effective_period(revision)
    if effective_from > today:
        return "scheduled"
    if effective_to is not None and effective_to < today:
        return "expired"
    return "active"


def resolve_current_contract_revision(
    contract: Contract,
) -> ContractConfigurationRevision:
    """Resolve only the server-current revision; callers cannot backdate it."""

    today = timezone.localdate()
    if (
        contract.status != Contract.ContractStatus.ACTIVE
        or contract.start_date > today
        or (contract.end_date is not None and contract.end_date < today)
    ):
        raise ContractRevisionError("The contract is not effective today.")
    revision = (
        ContractConfigurationRevision.objects.filter(
            contract=contract,
            status=ContractConfigurationRevision.Status.APPROVED,
            valid_from__lte=today,
        )
        .order_by("-valid_from", "-revision_number")
        .first()
    )
    if revision is None:
        raise ContractRevisionError("The contract has no current approved revision.")
    return revision
