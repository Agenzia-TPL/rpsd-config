# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Approval, snapshots and current-only resolution of contract revisions."""

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    ContractConfigurationRevisionStatusEvent,
    ContractIndicator,
    ContractIndicatorConfiguration,
    ContractInputSelection,
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    require_revision_approver,
    require_revision_preparer,
    require_revision_withdrawer,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    ProcessingProfileTransitionError,
    validate_processing_profile_for_publication,
)
from rpsd_config.exchange_agreement.services.revision_registry import (
    validate_business_configuration,
)


class ContractRevisionError(ValueError):
    """Raised when a revision cannot be approved, withdrawn or resolved."""


@dataclass(frozen=True)
class RevisionValidationIssue:
    """Stable machine-readable approval error with operator-friendly context."""

    code: str
    message: str
    details: dict = field(default_factory=dict)


class ContractRevisionValidationError(ContractRevisionError):
    """Raised when one or more complete approval checks fail."""

    def __init__(self, issues: Iterable[RevisionValidationIssue]):
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("At least one validation issue is required.")
        super().__init__("; ".join(issue.message for issue in self.issues))

    @property
    def code(self) -> str:
        return self.issues[0].code


@dataclass(frozen=True)
class RevisionInputResolution:
    """Server-authoritative input selection derived from chosen indicators."""

    mandatory_inputs: tuple[ProcessingProfileInputFlow, ...]
    optional_inputs: tuple[ProcessingProfileInputFlow, ...]
    selected_inputs: tuple[ProcessingProfileInputFlow, ...]
    issues: tuple[RevisionValidationIssue, ...] = ()


def resolve_revision_inputs(
    profile: ProcessingProfileVersion,
    indicator_links: Iterable[ProcessingProfileIndicatorVersion | int],
    selected_optional_inputs: Iterable[ProcessingProfileInputFlow | int] = (),
) -> RevisionInputResolution:
    """Resolve mandatory inputs without trusting browser-provided selections."""

    resolved_indicators = [
        _resolve_profile_indicator(value) for value in indicator_links
    ]
    requested_inputs = [
        _resolve_profile_input(value) for value in selected_optional_inputs
    ]
    issues: list[RevisionValidationIssue] = []

    logical_indicator_ids: set[int] = set()
    required_specification_ids: set[int] = set()
    for link in resolved_indicators:
        version = link.indicator_version
        if link.processing_profile_version_id != profile.pk:
            issues.append(
                RevisionValidationIssue(
                    code="selection_not_in_profile",
                    message=f"Indicator version {version.code} is not in the profile.",
                    details={"indicator_version_code": version.code},
                )
            )
            continue
        if version.indicator_id in logical_indicator_ids:
            issues.append(
                RevisionValidationIssue(
                    code="multiple_versions_for_indicator",
                    message=(
                        "Only one version of indicator "
                        f"{version.indicator.code} can be selected."
                    ),
                    details={"indicator_code": version.indicator.code},
                )
            )
            continue
        logical_indicator_ids.add(version.indicator_id)
        required_specification_ids.update(
            version.required_fragments.values_list(
                "dataset_specification_id", flat=True
            )
        )

    profile_inputs = list(
        profile.input_flow_links.select_related(
            "dataset", "input_flow_version__dataset_specification"
        ).order_by("dataset__code", "input_flow_version__code")
    )
    inputs_by_specification: dict[int, list[ProcessingProfileInputFlow]] = {}
    for profile_input in profile_inputs:
        specification_id = profile_input.input_flow_version.dataset_specification_id
        inputs_by_specification.setdefault(specification_id, []).append(profile_input)

    mandatory: list[ProcessingProfileInputFlow] = []
    for specification_id in sorted(required_specification_ids):
        candidates = inputs_by_specification.get(specification_id, [])
        if not candidates:
            specification = DatasetSpecification.objects.filter(
                pk=specification_id
            ).first()
            issues.append(
                RevisionValidationIssue(
                    code="required_input_not_available_in_profile",
                    message=(
                        "The profile has no input for required specification "
                        f"{getattr(specification, 'code', specification_id)}."
                    ),
                    details={
                        "specification_code": getattr(
                            specification, "code", str(specification_id)
                        )
                    },
                )
            )
        elif len(candidates) > 1:
            issues.append(
                RevisionValidationIssue(
                    code="ambiguous_input_flow",
                    message=(
                        "The profile exposes multiple inputs for specification "
                        f"{candidates[0].input_flow_version.dataset_specification.code}."
                    ),
                    details={"specification_id": specification_id},
                )
            )
        else:
            mandatory.append(candidates[0])

    profile_input_ids = {item.pk for item in profile_inputs}
    mandatory_ids = {item.pk for item in mandatory}
    requested_by_id: dict[int, ProcessingProfileInputFlow] = {}
    for profile_input in requested_inputs:
        if profile_input.pk not in profile_input_ids:
            issues.append(
                RevisionValidationIssue(
                    code="selection_not_in_profile",
                    message=f"Input {profile_input.pk} is not in the profile.",
                    details={"profile_input_id": profile_input.pk},
                )
            )
            continue
        requested_by_id[profile_input.pk] = profile_input

    selected_by_id = {item.pk: item for item in mandatory}
    selected_by_id.update(requested_by_id)
    optional = [item for item in profile_inputs if item.pk not in mandatory_ids]
    selected = sorted(
        selected_by_id.values(),
        key=lambda item: (item.dataset.code, item.input_flow_version.code),
    )
    return RevisionInputResolution(
        mandatory_inputs=tuple(mandatory),
        optional_inputs=tuple(optional),
        selected_inputs=tuple(selected),
        issues=tuple(issues),
    )


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
        "name": fragment.name,
        "description": fragment.description,
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
                "dataset_name": profile_input.dataset.name,
                "dataset_description": profile_input.dataset.description,
                "dataset_specification": {
                    "code": specification.code,
                    "version": specification.version,
                },
                "input_flow": {
                    "code": flow.code,
                    "version": flow.version,
                    "engine": flow.engine,
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
            "name": profile.name,
            "description": profile.description,
        },
        "orchestration_flow": {
            "code": orchestration.code,
            "version": orchestration.version,
            "engine": orchestration.engine,
            "deployment_name": orchestration.deployment_name,
            "artifact_identifier": orchestration.artifact_identifier,
        },
        "inputs": inputs,
        "indicators": indicators,
    }


def validate_revision_for_approval(
    revision: ContractConfigurationRevision,
) -> tuple[RevisionValidationIssue, ...]:
    """Run all composition checks and return every detected problem."""

    issues: list[RevisionValidationIssue] = []
    profile = revision.processing_profile_version
    if profile.status != ProcessingProfileVersion.Status.PUBLISHED:
        issues.append(
            RevisionValidationIssue(
                code="profile_not_published",
                message="The processing profile must be published.",
                details={"profile_code": profile.code, "status": profile.status},
            )
        )

    orchestration = profile.orchestration_flow_version
    if orchestration.status != OrchestrationFlowVersion.Status.PUBLISHED:
        issues.append(
            RevisionValidationIssue(
                code="orchestration_flow_not_published",
                message=(f"Orchestration flow {orchestration.code} is not published."),
                details={
                    "flow_code": orchestration.code,
                    "status": orchestration.status,
                },
            )
        )
    if not orchestration.deployment_name or not orchestration.artifact_identifier:
        issues.append(
            RevisionValidationIssue(
                code="missing_flow_reference",
                message=(
                    f"Orchestration flow {orchestration.code} has incomplete "
                    "executable references."
                ),
                details={"flow_code": orchestration.code},
            )
        )

    inputs = list(
        revision.input_selections.select_related(
            "processing_profile_input_flow__input_flow_version__dataset_specification"
        )
    )
    if not inputs:
        issues.append(
            RevisionValidationIssue(
                code="missing_inputs",
                message="The revision must select at least one input.",
            )
        )
    selected_specification_ids = set()
    for selection in inputs:
        profile_input = selection.processing_profile_input_flow
        if profile_input.processing_profile_version_id != profile.pk:
            issues.append(
                RevisionValidationIssue(
                    code="input_not_in_profile",
                    message=(
                        f"Input selection {profile_input.pk} does not belong to "
                        "the profile."
                    ),
                    details={"profile_input_id": profile_input.pk},
                )
            )
            continue
        flow = profile_input.input_flow_version
        if flow.status != InputFlowVersion.Status.PUBLISHED:
            issues.append(
                RevisionValidationIssue(
                    code="input_flow_not_published",
                    message=f"Input flow {flow.code} is not published.",
                    details={"flow_code": flow.code, "status": flow.status},
                )
            )
        if not flow.deployment_name or not flow.artifact_identifier:
            issues.append(
                RevisionValidationIssue(
                    code="missing_flow_reference",
                    message=(
                        f"Input flow {flow.code} has incomplete executable references."
                    ),
                    details={"flow_code": flow.code},
                )
            )
        if flow.dataset_specification.status != DatasetSpecification.Status.PUBLISHED:
            issues.append(
                RevisionValidationIssue(
                    code="dataset_specification_not_published",
                    message=(
                        "Dataset specification "
                        f"{flow.dataset_specification.code} is not published."
                    ),
                    details={
                        "specification_code": flow.dataset_specification.code,
                        "status": flow.dataset_specification.status,
                    },
                )
            )
        if flow.dataset_specification.dataset.status != Dataset.Status.ACTIVE:
            issues.append(
                RevisionValidationIssue(
                    code="dataset_not_active",
                    message=(
                        f"Dataset {flow.dataset_specification.dataset.code} is not "
                        "active."
                    ),
                    details={
                        "dataset_code": flow.dataset_specification.dataset.code,
                        "status": flow.dataset_specification.dataset.status,
                    },
                )
            )
        selected_specification_ids.add(flow.dataset_specification_id)

    configurations = list(
        revision.indicator_configurations.select_related(
            "contract_indicator__logical_indicator",
            "processing_profile_indicator_version__indicator_version",
        )
    )
    if not configurations:
        issues.append(
            RevisionValidationIssue(
                code="missing_indicators",
                message="The revision must configure at least one indicator.",
            )
        )

    configured_logical_indicator_ids: set[int] = set()
    for configuration in configurations:
        contract_indicator = configuration.contract_indicator
        if contract_indicator.contract_id != revision.contract_id:
            issues.append(
                RevisionValidationIssue(
                    code="contract_indicator_not_in_contract",
                    message=(
                        "A configured contract indicator belongs to another contract."
                    ),
                    details={"contract_indicator_id": contract_indicator.pk},
                )
            )
        profile_indicator = configuration.processing_profile_indicator_version
        if profile_indicator.processing_profile_version_id != profile.pk:
            issues.append(
                RevisionValidationIssue(
                    code="indicator_not_in_profile",
                    message=(
                        "A configured indicator version does not belong to the profile."
                    ),
                    details={"profile_indicator_id": profile_indicator.pk},
                )
            )
            continue
        version = profile_indicator.indicator_version
        if version.indicator_id in configured_logical_indicator_ids:
            issues.append(
                RevisionValidationIssue(
                    code="multiple_versions_for_indicator",
                    message=(
                        "Only one version of indicator "
                        f"{version.indicator.code} can be configured."
                    ),
                    details={"indicator_code": version.indicator.code},
                )
            )
        configured_logical_indicator_ids.add(version.indicator_id)
        if version.status != IndicatorVersion.Status.PUBLISHED:
            issues.append(
                RevisionValidationIssue(
                    code="indicator_not_published",
                    message=f"Indicator version {version.code} is not published.",
                    details={"indicator_version_code": version.code},
                )
            )
        if version.indicator.status != Indicator.Status.ACTIVE:
            issues.append(
                RevisionValidationIssue(
                    code="indicator_not_active",
                    message=f"Indicator {version.indicator.code} is not active.",
                    details={
                        "indicator_code": version.indicator.code,
                        "status": version.indicator.status,
                    },
                )
            )
        if version.execution_engine and (
            not version.execution_reference or not version.artifact_identifier
        ):
            issues.append(
                RevisionValidationIssue(
                    code="missing_indicator_execution_reference",
                    message=(
                        f"Indicator version {version.code} has incomplete executor "
                        "references."
                    ),
                    details={"indicator_version_code": version.code},
                )
            )
        if version.indicator_id != contract_indicator.logical_indicator_id:
            issues.append(
                RevisionValidationIssue(
                    code="indicator_mismatch",
                    message=(
                        f"Indicator version {version.code} does not match the "
                        "contract indicator."
                    ),
                    details={"indicator_version_code": version.code},
                )
            )
        for fragment in version.required_fragments.select_related(
            "dataset_specification"
        ):
            if (
                fragment.status != RequirementFragment.Status.PUBLISHED
                or fragment.dataset_specification_id not in selected_specification_ids
            ):
                issues.append(
                    RevisionValidationIssue(
                        code="missing_fragment",
                        message=(
                            f"Indicator version {version.code} requires fragment "
                            f"{fragment.code} from specification "
                            f"{fragment.dataset_specification.code}."
                        ),
                        details={
                            "indicator_code": version.indicator.code,
                            "indicator_version_code": version.code,
                            "fragment_code": fragment.code,
                            "specification_code": (fragment.dataset_specification.code),
                        },
                    )
                )
        for field_name in ("thresholds", "aggregation", "penalties", "parameters"):
            try:
                validate_business_configuration(
                    getattr(configuration, field_name), field_name=field_name
                )
            except ValidationError as exc:
                issues.append(
                    RevisionValidationIssue(
                        code="invalid_business_configuration",
                        message=f"Invalid {field_name}: {'; '.join(exc.messages)}",
                        details={
                            "indicator_version_code": version.code,
                            "field": field_name,
                        },
                    )
                )

    return tuple(issues)


def _raise_for_approval_issues(revision: ContractConfigurationRevision) -> None:
    issues = validate_revision_for_approval(revision)
    if issues:
        raise ContractRevisionValidationError(issues)


def available_processing_profiles(
    contract: Contract,
    actor,
) -> tuple[ProcessingProfileVersion, ...]:
    """Return technically valid published profiles available to the operator."""

    require_revision_preparer(user=actor, contract=contract)
    profiles = ProcessingProfileVersion.objects.filter(
        status=ProcessingProfileVersion.Status.PUBLISHED
    ).prefetch_related("indicator_version_links__indicator_version")
    applicable = []
    for profile in profiles:
        try:
            validate_processing_profile_for_publication(profile)
        except ProcessingProfileTransitionError:
            continue
        applicable.append(profile)
    return tuple(applicable)


@transaction.atomic
def create_revision_draft(
    contract: Contract,
    profile: ProcessingProfileVersion,
    valid_from: date,
    actor,
    *,
    code: str | None = None,
    change_reason: str | None = None,
    replaces_revision: ContractConfigurationRevision | None = None,
) -> ContractConfigurationRevision:
    """Create a guided draft and prefill the profile's proposed composition."""

    locked_contract = Contract.objects.select_for_update().get(pk=contract.pk)
    require_revision_preparer(user=actor, contract=locked_contract)
    locked_profile = ProcessingProfileVersion.objects.select_related(
        "orchestration_flow_version"
    ).get(pk=profile.pk)
    if locked_profile.status != ProcessingProfileVersion.Status.PUBLISHED:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="profile_not_published",
                    message="The processing profile must be published.",
                    details={"profile_code": locked_profile.code},
                )
            ]
        )
    try:
        validate_processing_profile_for_publication(locked_profile)
    except ProcessingProfileTransitionError as exc:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="profile_not_applicable",
                    message=f"The processing profile is not applicable: {exc}",
                    details={"profile_code": locked_profile.code},
                )
            ]
        ) from exc
    if (
        replaces_revision is not None
        and replaces_revision.contract_id != locked_contract.pk
    ):
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="invalid_revision_sequence",
                    message="The replaced revision must belong to the same contract.",
                )
            ]
        )

    latest_number = (
        ContractConfigurationRevision.objects.filter(
            contract=locked_contract
        ).aggregate(latest=Max("revision_number"))["latest"]
        or 0
    )
    revision_number = latest_number + 1
    revision = ContractConfigurationRevision.objects.create(
        contract=locked_contract,
        revision_number=revision_number,
        code=code or f"{locked_contract.contract_code}-r{revision_number:03d}",
        processing_profile_version=locked_profile,
        valid_from=valid_from,
        change_reason=(
            change_reason
            or f"Draft created from processing profile {locked_profile.code}."
        ),
        replaces_revision=replaces_revision,
        created_by=actor,
    )

    proposed_links = list(
        locked_profile.indicator_version_links.filter(
            proposed_by_default=True
        ).select_related("indicator_version__indicator")
    )
    resolution = resolve_revision_inputs(locked_profile, proposed_links)
    if resolution.issues:
        raise ContractRevisionValidationError(resolution.issues)
    for profile_input in resolution.selected_inputs:
        ContractInputSelection.objects.create(
            revision=revision,
            processing_profile_input_flow=profile_input,
        )

    for profile_indicator in proposed_links:
        logical_indicator_id = profile_indicator.indicator_version.indicator_id
        contract_indicator, _created = ContractIndicator.objects.get_or_create(
            contract=locked_contract,
            logical_indicator_id=logical_indicator_id,
        )
        ContractIndicatorConfiguration.objects.create(
            revision=revision,
            contract_indicator=contract_indicator,
            processing_profile_indicator_version=profile_indicator,
        )

    return revision


def _resolve_profile_input(
    value: ProcessingProfileInputFlow | int,
) -> ProcessingProfileInputFlow:
    if isinstance(value, ProcessingProfileInputFlow):
        return value
    return ProcessingProfileInputFlow.objects.get(pk=value)


def _resolve_profile_indicator(
    value: ProcessingProfileIndicatorVersion | int,
) -> ProcessingProfileIndicatorVersion:
    if isinstance(value, ProcessingProfileIndicatorVersion):
        return value
    return ProcessingProfileIndicatorVersion.objects.get(pk=value)


def _resolve_contract_indicator(value: ContractIndicator | int) -> ContractIndicator:
    if isinstance(value, ContractIndicator):
        return value
    return ContractIndicator.objects.get(pk=value)


@transaction.atomic
def replace_draft_configuration(
    revision: ContractConfigurationRevision,
    selections: Iterable[ProcessingProfileInputFlow | int],
    indicator_configs: Iterable[dict],
    actor,
) -> ContractConfigurationRevision:
    """Atomically replace the editable composition of a draft revision."""

    locked = (
        ContractConfigurationRevision.objects.select_for_update()
        .select_related("contract", "processing_profile_version")
        .get(pk=revision.pk)
    )
    require_revision_preparer(user=actor, contract=locked.contract)
    if locked.status != ContractConfigurationRevision.Status.DRAFT:
        raise ContractRevisionError(
            "Only a draft revision configuration can be replaced."
        )

    requested_inputs = [_resolve_profile_input(value) for value in selections]
    resolved_configurations = []
    selected_profile_indicators = []
    selected_logical_indicator_ids: set[int] = set()
    for item in indicator_configs:
        if not isinstance(item, dict):
            raise ContractRevisionError("Indicator configurations must be objects.")
        try:
            profile_indicator = _resolve_profile_indicator(
                item["processing_profile_indicator_version"]
            )
        except KeyError as exc:
            raise ContractRevisionError(
                f"Missing indicator configuration key: {exc.args[0]}."
            ) from exc
        if profile_indicator.processing_profile_version_id != (
            locked.processing_profile_version_id
        ):
            raise ContractRevisionValidationError(
                [
                    RevisionValidationIssue(
                        code="selection_not_in_profile",
                        message=(
                            "Indicator version "
                            f"{profile_indicator.indicator_version.code} "
                            "is not in the revision profile."
                        ),
                    )
                ]
            )
        logical_indicator_id = profile_indicator.indicator_version.indicator_id
        if logical_indicator_id in selected_logical_indicator_ids:
            raise ContractRevisionValidationError(
                [
                    RevisionValidationIssue(
                        code="multiple_versions_for_indicator",
                        message=(
                            "Only one version per logical indicator can be selected."
                        ),
                    )
                ]
            )
        selected_logical_indicator_ids.add(logical_indicator_id)
        supplied_contract_indicator = item.get("contract_indicator")
        if supplied_contract_indicator is not None:
            contract_indicator = _resolve_contract_indicator(
                supplied_contract_indicator
            )
            if (
                contract_indicator.contract_id != locked.contract_id
                or contract_indicator.logical_indicator_id != logical_indicator_id
            ):
                raise ContractRevisionValidationError(
                    [
                        RevisionValidationIssue(
                            code="indicator_mismatch",
                            message=(
                                "The selected indicator does not match the contract."
                            ),
                        )
                    ]
                )
        else:
            contract_indicator, _created = ContractIndicator.objects.get_or_create(
                contract=locked.contract,
                logical_indicator_id=logical_indicator_id,
            )
        selected_profile_indicators.append(profile_indicator)
        resolved_configurations.append(
            {
                "profile_indicator": profile_indicator,
                "contract_indicator": contract_indicator,
                "thresholds": item.get("thresholds", {}),
                "aggregation": item.get("aggregation", {}),
                "penalties": item.get("penalties", {}),
                "parameters": item.get("parameters", {}),
            }
        )

    resolution = resolve_revision_inputs(
        locked.processing_profile_version,
        selected_profile_indicators,
        requested_inputs,
    )
    if resolution.issues:
        raise ContractRevisionValidationError(resolution.issues)

    locked.input_selections.all().delete()
    locked.indicator_configurations.all().delete()
    for profile_input in resolution.selected_inputs:
        ContractInputSelection.objects.create(
            revision=locked,
            processing_profile_input_flow=profile_input,
        )
    for item in resolved_configurations:
        ContractIndicatorConfiguration.objects.create(
            revision=locked,
            contract_indicator=item["contract_indicator"],
            processing_profile_indicator_version=item["profile_indicator"],
            thresholds=item["thresholds"],
            aggregation=item["aggregation"],
            penalties=item["penalties"],
            parameters=item["parameters"],
        )
    return locked


@transaction.atomic
def approve_contract_revision(
    revision: ContractConfigurationRevision,
    *,
    actor=None,
) -> ContractConfigurationRevision:
    contract = Contract.objects.select_for_update().get(pk=revision.contract_id)
    require_revision_approver(user=actor, contract=contract)
    revisions = ContractConfigurationRevision.objects.select_for_update().filter(
        contract=contract
    )
    locked = revisions.select_related(
        "contract", "processing_profile_version__orchestration_flow_version"
    ).get(pk=revision.pk)
    if locked.status != ContractConfigurationRevision.Status.DRAFT:
        raise ContractRevisionError("Only a draft revision can be approved.")
    if locked.valid_from is None:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="invalid_revision_sequence",
                    message="valid_from is required before approval.",
                )
            ]
        )
    if locked.valid_from < contract.start_date or (
        contract.end_date is not None and locked.valid_from > contract.end_date
    ):
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="invalid_revision_sequence",
                    message="valid_from must be inside the contract period.",
                )
            ]
        )

    approved = revisions.filter(
        status=ContractConfigurationRevision.Status.APPROVED
    ).order_by("valid_from", "revision_number")
    latest = approved.last()
    today = timezone.localdate()
    if locked.valid_from < today:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="retroactive_valid_from",
                    message="A revision cannot be approved retroactively.",
                )
            ]
        )
    if approved.filter(valid_from=locked.valid_from).exists():
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="duplicate_valid_from",
                    message=("An approved revision already uses this valid_from date."),
                )
            ]
        )
    if latest is None:
        if locked.valid_from != contract.start_date:
            raise ContractRevisionValidationError(
                [
                    RevisionValidationIssue(
                        code="invalid_revision_sequence",
                        message=(
                            "The first revision must start on the contract start date."
                        ),
                    )
                ]
            )
    else:
        if locked.valid_from <= latest.valid_from:
            raise ContractRevisionValidationError(
                [
                    RevisionValidationIssue(
                        code="invalid_revision_sequence",
                        message=(
                            "A new revision must start after the latest approved "
                            "revision."
                        ),
                    )
                ]
            )

    _raise_for_approval_issues(locked)
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
    ContractConfigurationRevisionStatusEvent.objects.create(
        revision=locked,
        from_status=ContractConfigurationRevision.Status.DRAFT,
        to_status=ContractConfigurationRevision.Status.APPROVED,
        changed_by=actor,
        reason=locked.change_reason,
        snapshot_checksum=checksum,
    )
    locked.refresh_from_db()
    return locked


@transaction.atomic
def withdraw_contract_revision(
    revision: ContractConfigurationRevision,
    *,
    reason: str | None = None,
    actor=None,
) -> ContractConfigurationRevision:
    contract = Contract.objects.select_for_update().get(pk=revision.contract_id)
    require_revision_withdrawer(user=actor, contract=contract)
    reason = (reason or "").strip()
    if not reason:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="withdrawal_reason_required",
                    message="A withdrawal reason is required.",
                )
            ]
        )
    locked = ContractConfigurationRevision.objects.select_for_update().get(
        pk=revision.pk
    )
    if locked.status == ContractConfigurationRevision.Status.WITHDRAWN:
        raise ContractRevisionError("The revision is already withdrawn.")
    if locked.valid_from is None or locked.valid_from <= timezone.localdate():
        raise ContractRevisionError(
            "A revision that is not future cannot be withdrawn."
        )
    now = timezone.now()
    ContractConfigurationRevision.objects.filter(pk=locked.pk).update(
        status=ContractConfigurationRevision.Status.WITHDRAWN,
        withdrawal_reason=reason,
        withdrawn_by_id=actor.pk if getattr(actor, "pk", None) else None,
        withdrawn_at=now,
        updated_at=now,
    )
    ContractConfigurationRevisionStatusEvent.objects.create(
        revision=locked,
        from_status=locked.status,
        to_status=ContractConfigurationRevision.Status.WITHDRAWN,
        changed_by=actor,
        reason=reason,
        snapshot_checksum=locked.snapshot_checksum,
    )
    locked.refresh_from_db()
    return locked


def approve_revision(
    revision: ContractConfigurationRevision,
    actor,
) -> ContractConfigurationRevision:
    """Feature-facing alias with an explicit authorized actor."""

    return approve_contract_revision(revision, actor=actor)


def withdraw_revision(
    revision: ContractConfigurationRevision,
    reason: str,
    actor,
) -> ContractConfigurationRevision:
    """Feature-facing alias with mandatory reason and authorized actor."""

    return withdraw_contract_revision(revision, reason=reason, actor=actor)


def create_replacement_revision(
    current_revision: ContractConfigurationRevision,
    profile: ProcessingProfileVersion,
    actor,
    *,
    change_reason: str,
) -> ContractConfigurationRevision:
    """Prepare a draft that closes the current revision logically from today."""

    if current_revision.status != ContractConfigurationRevision.Status.APPROVED:
        raise ContractRevisionValidationError(
            [
                RevisionValidationIssue(
                    code="invalid_revision_sequence",
                    message="Only an approved revision can be replaced.",
                )
            ]
        )
    return create_revision_draft(
        current_revision.contract,
        profile,
        timezone.localdate(),
        actor,
        change_reason=change_reason,
        replaces_revision=current_revision,
    )


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
