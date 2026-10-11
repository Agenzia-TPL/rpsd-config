# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Declarative CSV demo; execution remains in the external validator."""

import json

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    DatasetVersionRule,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    bind_dataset_rule,
    bind_indicator_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.services.validation_seed import ensure_seed_version


@transaction.atomic
def ensure_csv_validation_demo(*, actor) -> ProcessingProfileVersion:
    """Seed all three policies and a dimension requirement on a separate CSV profile."""
    require_catalog_admin(actor)
    dataset, _ = Dataset.objects.get_or_create(
        code="demo-csv", defaults={"name": "CSV journeys"}
    )
    spec, created = ensure_seed_version(
        DatasetSpecification,
        code="demo-csv_001",
        defaults={
            "dataset": dataset,
            "version": "001",
            "description": "Declarative CSV fixture",
            "metadata": {"format": "csv"},
        },
    )
    bindings = {}
    for suffix, columns, policy in (
        ("identity", ["journey_id"], "reject_import"),
        ("timestamp", ["source_timestamp"], "warn"),
        ("line", ["line"], "indicator_only"),
    ):
        rule, _ = ValidationRule.objects.get_or_create(
            code="demo-csv-" + suffix, defaults={"name": "CSV " + suffix}
        )
        version, _ = ensure_seed_version(
            ValidationRuleVersion,
            rule=rule,
            version="001",
            defaults={
                "name": rule.name,
                "validation_type": "csv_expression",
                "language_version": "1",
                "definition": json.dumps(
                    {"predicate": "required_columns", "columns": columns},
                    sort_keys=True,
                ),
                "options": {"delimiter": ";", "encoding": "utf-8", "header": True},
                "execution_reference": "fixture-validators/csv",
            },
        )
        if version.status == "draft":
            version = transition_validation_rule(
                version, target_status="published", actor=actor
            )
        binding = DatasetVersionRule.objects.filter(
            dataset_specification=spec, rule_version=version
        ).first()
        if binding is None:
            if spec.status != "draft" and not created:
                raise ValidationError(
                    "Published CSV demo is incomplete; create a new version."
                )
            binding = bind_dataset_rule(
                specification=spec,
                rule_version=version,
                import_policy=policy,
                actor=actor,
            )
        elif binding.import_policy != policy:
            raise ValidationError("CSV demo policy conflict.")
        bindings[suffix] = binding
    if spec.status == "draft":
        spec = publish_dataset_specification(spec, actor=actor)
    dimension, _ = IndicatorDimension.objects.get_or_create(
        code="line", defaults={"name": "Linea"}
    )
    logical, _ = Indicator.objects.get_or_create(
        code="demo-csv-journey-count",
        defaults={"name": "CSV journey count", "description": "CSV fixture indicator"},
    )
    indicator, _ = ensure_seed_version(
        IndicatorVersion,
        code="demo-csv-journey-count_001",
        defaults={
            "indicator": logical,
            "version": "001",
            "description": "CSV count with optional disaggregation",
            "formula_description": "External journey count",
            "execution_engine": "prefect",
            "execution_reference": "fixture-indicators/csv-count",
            "artifact_identifier": "git:fixture@csv-count-001",
        },
    )
    if indicator.status == "draft":
        if not indicator.rule_bindings.exists():
            bind_indicator_rule(
                indicator_version=indicator,
                dataset_rule=bindings["line"],
                impact="dimension",
                dimensions=[dimension],
                actor=actor,
            )
        indicator = publish_indicator_version(indicator, actor=actor)
    flow, _ = ensure_seed_version(
        InputFlowVersion,
        code="demo-csv-import_001",
        defaults={
            "dataset_specification": spec,
            "version": "001",
            "name": "CSV fixture input",
            "description": "Fixture reference; external runtime not provisioned",
            "engine": "prefect",
            "deployment_name": "fixture-validators/csv",
            "artifact_identifier": "git:fixture@csv-import-001",
        },
    )
    if flow.status == "draft":
        flow = publish_input_flow_version(flow, actor=actor)
    orchestration, _ = ensure_seed_version(
        OrchestrationFlowVersion,
        code="demo-csv-processing_001",
        defaults={
            "version": "001",
            "name": "CSV fixture orchestration",
            "description": "External fixture reference",
            "engine": "prefect",
            "deployment_name": "fixture-contracts/csv-demo",
            "artifact_identifier": "git:fixture@csv-processing-001",
        },
    )
    if orchestration.status == "draft":
        orchestration = publish_orchestration_flow_version(orchestration, actor=actor)
    profile, _ = ensure_seed_version(
        ProcessingProfileVersion,
        code="validation-csv-demo_001",
        defaults={
            "version": "001",
            "name": "CSV validation demo",
            "description": "Required columns, warnings and line compatibility",
            "orchestration_flow_version": orchestration,
        },
    )
    if profile.status == "draft":
        ProcessingProfileInputFlow.objects.get_or_create(
            processing_profile_version=profile,
            dataset=dataset,
            defaults={"input_flow_version": flow},
        )
        ProcessingProfileIndicatorVersion.objects.get_or_create(
            processing_profile_version=profile,
            indicator_version=indicator,
            defaults={"proposed_by_default": True},
        )
        profile = publish_processing_profile(profile, actor=actor)
    return profile
