# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Reusable target-model fixtures for M2M runtime API tests."""

from dataclasses import dataclass
from unittest.mock import patch

from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    ContractIndicator,
    ContractIndicatorConfiguration,
    ContractInputSelection,
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    IndicatorVersionInput,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_contract_revision,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)


@dataclass(frozen=True)
class RuntimeInputFixture:
    category: str
    dataset_name: str
    dataset_description: str
    specification_code: str
    specification_version: str
    flow_code: str
    flow_version: str
    deployment_name: str
    flow_description: str
    selected: bool = False
    required: bool = False


def install_approved_runtime_configuration(
    *,
    contract,
    actor,
    profile_code: str,
    profile_version: str,
    profile_name: str,
    profile_description: str,
    orchestration_deployment_name: str,
    inputs: tuple[RuntimeInputFixture, ...],
):
    """Install a published profile and its first approved contract revision."""

    profile_inputs = []
    required_specifications = []
    for item in inputs:
        dataset = Dataset.objects.create(
            code=item.category,
            name=item.dataset_name,
            description=item.dataset_description,
        )
        specification = publish_dataset_specification(
            DatasetSpecification.objects.create(
                dataset=dataset,
                code=item.specification_code,
                version=item.specification_version,
                description=f"{item.dataset_name} specification",
            ),
            actor=actor,
        )
        if item.required:
            required_specifications.append(specification)
        input_flow = publish_input_flow_version(
            InputFlowVersion.objects.create(
                dataset_specification=specification,
                code=item.flow_code,
                version=item.flow_version,
                name=f"{item.dataset_name} import",
                description=item.flow_description,
                deployment_name=item.deployment_name,
                artifact_identifier=f"git:rpsd-flows@{item.flow_code}",
            ),
            actor=actor,
        )
        profile_inputs.append((item, dataset, input_flow))

    logical_indicator_code = f"{profile_code.replace('_', '-')}-indicator"
    logical_indicator = Indicator.objects.create(
        code=logical_indicator_code,
        name="Runtime contract indicator",
        description="Indicator used by the runtime API contract fixture.",
    )
    indicator_version = IndicatorVersion.objects.create(
        indicator=logical_indicator,
        code=f"{logical_indicator_code}_001",
        version="001",
        description="Runtime contract indicator version.",
        formula_description="Fixture formula.",
        execution_engine="prefect",
        execution_reference="fixture-indicators/runtime",
        artifact_identifier="git:fixture@runtime",
    )
    for required_specification in required_specifications:
        IndicatorVersionInput.objects.get_or_create(
            indicator_version=indicator_version,
            dataset_specification=required_specification,
        )
    from rpsd_config.exchange_agreement.services.indicator_catalog import (
        publish_indicator_version,
    )

    indicator_version = publish_indicator_version(indicator_version, actor=actor)

    orchestration = publish_orchestration_flow_version(
        OrchestrationFlowVersion.objects.create(
            code=f"{profile_code}-orchestration_001",
            version="001",
            name=f"{profile_name} orchestration",
            description="Coordinate the contract processing pipeline.",
            deployment_name=orchestration_deployment_name,
            artifact_identifier=f"git:rpsd-flows@{profile_code}-orchestration-001",
        ),
        actor=actor,
    )
    profile = ProcessingProfileVersion.objects.create(
        code=profile_code,
        version=profile_version,
        name=profile_name,
        description=profile_description,
        orchestration_flow_version=orchestration,
    )
    selected_profile_inputs = []
    for item, dataset, input_flow in profile_inputs:
        link = ProcessingProfileInputFlow.objects.create(
            processing_profile_version=profile,
            dataset=dataset,
            input_flow_version=input_flow,
        )
        if item.selected:
            selected_profile_inputs.append(link)
    profile_indicator = ProcessingProfileIndicatorVersion.objects.create(
        processing_profile_version=profile,
        indicator_version=indicator_version,
        proposed_by_default=True,
    )
    profile = publish_processing_profile(profile, actor=actor)

    contract_indicator = ContractIndicator.objects.create(
        contract=contract,
        logical_indicator=logical_indicator,
    )
    revision = ContractConfigurationRevision.objects.create(
        contract=contract,
        revision_number=1,
        code=f"{contract.contract_code.lower()}-r001",
        processing_profile_version=profile,
        valid_from=contract.start_date,
        change_reason="Initial runtime configuration.",
        created_by=actor,
    )
    for profile_input in selected_profile_inputs:
        ContractInputSelection.objects.create(
            revision=revision,
            processing_profile_input_flow=profile_input,
        )
    ContractIndicatorConfiguration.objects.create(
        revision=revision,
        contract_indicator=contract_indicator,
        processing_profile_indicator_version=profile_indicator,
    )
    with patch(
        "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
        return_value=contract.start_date,
    ):
        revision = approve_contract_revision(revision, actor=actor)

    return profile, revision
