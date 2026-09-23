# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent registration of standard input and orchestration flows."""

from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    InputFlowVersion,
    OrchestrationFlowVersion,
)
from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    ensure_initial_dataset_catalog,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)


@transaction.atomic
def ensure_standard_flow_catalog() -> tuple[
    list[InputFlowVersion], OrchestrationFlowVersion
]:
    specifications = ensure_initial_dataset_catalog()
    input_flows = []
    for specification in specifications:
        dataset_code = specification.dataset.code
        code = f"{dataset_code}-import_001"
        flow, _created = InputFlowVersion.objects.get_or_create(
            code=code,
            defaults={
                "version": "001",
                "name": f"{specification.dataset.name} import",
                "description": (f"Import and validation for {specification.code}."),
                "dataset_specification": specification,
                "engine": InputFlowVersion.Engine.PREFECT,
                "deployment_name": f"validators/{dataset_code}-default",
                "artifact_identifier": f"git:rpsd-flows@{dataset_code}-import-001",
            },
        )
        if flow.status == InputFlowVersion.Status.DRAFT:
            flow = publish_input_flow_version(flow)
        input_flows.append(flow)

    orchestration, _created = OrchestrationFlowVersion.objects.get_or_create(
        code="contract-processing_001",
        defaults={
            "version": "001",
            "name": "Contract processing",
            "description": "General orchestration for a configured contract.",
            "engine": OrchestrationFlowVersion.Engine.PREFECT,
            "deployment_name": "rpsd-contract-processing/default",
            "artifact_identifier": "git:rpsd-flows@contract-processing-001",
        },
    )
    if orchestration.status == OrchestrationFlowVersion.Status.DRAFT:
        orchestration = publish_orchestration_flow_version(orchestration)
    return input_flows, orchestration
