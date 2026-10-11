# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent target catalog with shared checks and a composed indicator."""

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    DatasetVersionRule,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionInput,
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
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    add_indicator_dependency,
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


def ensure_seed_version(model, *, defaults: dict, **lookup):
    """Reject semantic drift instead of silently reusing a different seed version."""
    instance, created = model.objects.get_or_create(defaults=defaults, **lookup)
    if not created:
        mismatches = [
            field
            for field, expected in defaults.items()
            if getattr(instance, field) != expected
        ]
        if mismatches:
            raise ValidationError(
                f"Seed conflict for {model.__name__}: {', '.join(mismatches)}. "
                "Create an explicitly reviewed new version.",
                code="seed_definition_conflict",
            )
    return instance, created


@transaction.atomic
def ensure_validation_demo(*, actor) -> ProcessingProfileVersion:
    """Seed separate versions; never alter already published compositions."""
    require_catalog_admin(actor)
    specs = []
    new_spec_ids = set()
    definitions = [
        ("netex", "//n:ServiceJourney", "http://www.netex.org.uk/netex"),
        ("siri-vm", "//n:VehicleActivity", "http://www.siri.org.uk/siri"),
    ]
    for code, path, namespace in definitions:
        dataset, _ = Dataset.objects.get_or_create(code=code, defaults={"name": code})
        spec, created = ensure_seed_version(
            DatasetSpecification,
            code=code + "-validation-demo_001",
            defaults={
                "dataset": dataset,
                "version": "validation-demo-001",
                "description": "Target validation demo",
                "metadata": {"format": "xml"},
            },
        )
        if created:
            new_spec_ids.add(spec.pk)
        rule, _ = ValidationRule.objects.get_or_create(
            code=code + "-demo-presence",
            defaults={"name": "Required " + code + " entities"},
        )
        version, _ = ensure_seed_version(
            ValidationRuleVersion,
            rule=rule,
            version="001",
            defaults={
                "name": rule.name,
                "validation_type": "xpath",
                "definition": "/*[not(" + path + ")]",
                "language_version": "1.0",
                "options": {"namespaces": {"n": namespace}},
                "execution_reference": "validators/" + code + "-demo",
            },
        )
        if version.status == "draft":
            version = transition_validation_rule(
                version, target_status="published", actor=actor
            )
        binding = DatasetVersionRule.objects.filter(
            dataset_specification=spec, rule_version=version
        ).first()
        if binding is not None and binding.import_policy != "reject_import":
            raise ValidationError("Demo base rule policy differs from the seed.")
        if binding is None:
            if spec.status != "draft":
                raise ValidationError(
                    "Published demo dataset composition is incomplete; "
                    "create a new version."
                )
            bind_dataset_rule(
                specification=spec,
                rule_version=version,
                import_policy="reject_import",
                actor=actor,
            )
        if spec.status == "draft":
            spec = publish_dataset_specification(spec, actor=actor)
        specs.append(spec)
    dimension, _ = IndicatorDimension.objects.get_or_create(
        code="line", defaults={"name": "Linea"}
    )
    rule, _ = ValidationRule.objects.get_or_create(
        code="netex-demo-line", defaults={"name": "Line dimension"}
    )
    line_rule, _ = ensure_seed_version(
        ValidationRuleVersion,
        rule=rule,
        version="001",
        defaults={
            "name": rule.name,
            "validation_type": "xpath",
            "definition": "//n:ServiceJourney[not(n:LineRef)]",
            "language_version": "1.0",
            "options": {"namespaces": {"n": definitions[0][2]}},
            "execution_reference": "validators/netex-demo",
        },
    )
    if line_rule.status == "draft":
        line_rule = transition_validation_rule(
            line_rule, target_status="published", actor=actor
        )
    line_binding = DatasetVersionRule.objects.filter(
        dataset_specification=specs[0], rule_version=line_rule
    ).first()
    if line_binding is not None and line_binding.import_policy != "indicator_only":
        raise ValidationError("Demo indicator rule policy differs from the seed.")
    if line_binding is None:
        if specs[0].status != "draft" and specs[0].pk not in new_spec_ids:
            raise ValidationError(
                "Published demo dataset is missing its indicator rule; "
                "create a new version instead of changing the seed composition."
            )
        line_binding = bind_dataset_rule(
            specification=specs[0],
            rule_version=line_rule,
            import_policy="indicator_only",
            actor=actor,
        )
    versions = []
    for code in ("demo-journey-count", "demo-composed-performance"):
        logical, _ = Indicator.objects.get_or_create(
            code=code,
            defaults={"name": code, "description": "Validation demo indicator"},
        )
        version, _ = ensure_seed_version(
            IndicatorVersion,
            code=code + "_001",
            defaults={
                "indicator": logical,
                "version": "001",
                "description": "Target validation demo",
                "formula_description": "External Prefect calculation",
                "execution_engine": "prefect",
                "execution_reference": "indicators/" + code,
                "artifact_identifier": "git:rpsd-flows@validation-demo",
            },
        )
        if version.status == "draft":
            if not version.dataset_inputs.exists():
                for spec in [specs[0]] if not versions else [specs[1]]:
                    IndicatorVersionInput.objects.create(
                        indicator_version=version, dataset_specification=spec
                    )
            if not versions:
                if not version.rule_bindings.exists():
                    bind_indicator_rule(
                        indicator_version=version,
                        dataset_rule=line_binding,
                        impact="dimension",
                        dimensions=[dimension],
                        actor=actor,
                    )
            elif not version.dependency_links.exists():
                add_indicator_dependency(
                    dependent=version, prerequisite=versions[0], actor=actor
                )
            version = publish_indicator_version(version, actor=actor)
        versions.append(version)
    flows = []
    for spec in specs:
        flow, _ = ensure_seed_version(
            InputFlowVersion,
            code="validation-demo-" + spec.dataset.code + "_001",
            defaults={
                "dataset_specification": spec,
                "version": "001",
                "name": "Validation demo input",
                "description": "Demo integration reference; runtime not provisioned",
                "engine": "prefect",
                "deployment_name": "validators/" + spec.dataset.code + "-demo",
                "artifact_identifier": "git:rpsd-flows@validation-demo",
            },
        )
        if flow.status == "draft":
            flow = publish_input_flow_version(flow, actor=actor)
        flows.append(flow)
    orchestration, _ = ensure_seed_version(
        OrchestrationFlowVersion,
        code="validation-demo-processing_001",
        defaults={
            "version": "001",
            "name": "Validation demo orchestration",
            "description": "Demo integration reference",
            "engine": "prefect",
            "deployment_name": "contracts/validation-demo",
            "artifact_identifier": "git:rpsd-flows@validation-demo",
        },
    )
    if orchestration.status == "draft":
        orchestration = publish_orchestration_flow_version(orchestration, actor=actor)
    profile, _ = ensure_seed_version(
        ProcessingProfileVersion,
        code="validation-demo_001",
        defaults={
            "version": "001",
            "name": "Target validation demo",
            "description": "Two async inputs; root inherits a shared prerequisite",
            "orchestration_flow_version": orchestration,
        },
    )
    if profile.status == "draft":
        for flow in flows:
            ProcessingProfileInputFlow.objects.get_or_create(
                processing_profile_version=profile,
                dataset=flow.dataset_specification.dataset,
                defaults={"input_flow_version": flow},
            )
        ProcessingProfileIndicatorVersion.objects.get_or_create(
            processing_profile_version=profile,
            indicator_version=versions[-1],
            defaults={"proposed_by_default": True},
        )
        profile = publish_processing_profile(profile, actor=actor)
    return profile
