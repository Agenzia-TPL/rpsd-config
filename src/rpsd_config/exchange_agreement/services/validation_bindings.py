# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Authorized rule binding creation and publication consistency."""

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    DatasetVersionRule,
    IndicatorVersionInput,
    IndicatorVersionRule,
    IndicatorVersionRuleDimension,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
    serialize_validation_rule,
)


@transaction.atomic
def save_dataset_rule(binding: DatasetVersionRule, *, actor) -> DatasetVersionRule:
    """Save a permitted applicability and preserve the original creation actor."""
    require_catalog_admin(actor)
    if binding._state.adding:
        binding.created_by = actor
    binding.save()
    return binding


@transaction.atomic
def bind_dataset_rule(
    *, specification, rule_version, import_policy: str, actor
) -> DatasetVersionRule:
    """Associate a published rule and keep append-only provenance."""
    require_catalog_admin(actor)
    return save_dataset_rule(
        DatasetVersionRule(
            dataset_specification=specification,
            rule_version=rule_version,
            import_policy=import_policy,
        ),
        actor=actor,
    )


@transaction.atomic
def bind_indicator_rule(
    *, indicator_version, dataset_rule, impact: str, dimensions, actor
) -> IndicatorVersionRule:
    """Create a complete impact plus its dimensions atomically."""
    require_catalog_admin(actor)
    binding = IndicatorVersionRule.objects.create(
        indicator_version=indicator_version,
        dataset_version_rule=dataset_rule,
        impact=impact,
    )
    for dimension in dimensions:
        IndicatorVersionRuleDimension.objects.create(
            binding=binding, dimension=dimension
        )
    binding.validate_complete()
    return binding


@transaction.atomic
def update_indicator_rule(binding, *, impact: str, dimensions, actor):
    """Replace a draft's impact and dimensions as one validated operation."""
    require_catalog_admin(actor)
    binding.check_editable()
    binding = IndicatorVersionRule.objects.get(pk=binding.pk)
    binding.dimension_links.all().delete()
    binding.impact = impact
    binding.save()
    for dimension in dimensions:
        IndicatorVersionRuleDimension.objects.create(
            binding=binding, dimension=dimension
        )
    binding.validate_complete()
    return binding


@transaction.atomic
def declare_indicator_input(*, indicator_version, specification, actor):
    """Declare a required dataset even when no validation rule exists."""
    require_catalog_admin(actor)
    return IndicatorVersionInput.objects.create(
        indicator_version=indicator_version, dataset_specification=specification
    )


def resolve_dataset_rules(
    specification, indicator_versions, *, paths=None
) -> list[dict]:
    """Resolve import policies and distinct consumers without executing checks."""
    paths = paths or {}
    versions = {version.pk: version for version in indicator_versions}
    consumers = {}
    for version in sorted(versions.values(), key=lambda version: version.code):
        for binding in version.rule_bindings.filter(
            dataset_version_rule__dataset_specification=specification
        ).select_related("dataset_version_rule"):
            binding.validate_complete()
            consumers.setdefault(binding.dataset_version_rule_id, []).append(
                {
                    "indicator_version_code": version.code,
                    "impact": binding.impact,
                    "affected_dimensions": sorted(
                        binding.affected_dimensions.values_list("code", flat=True)
                    ),
                    "dependency_paths": sorted(paths.get(version.pk, [[version.code]])),
                }
            )
    result = []
    for binding in specification.rule_bindings.select_related("rule_version__rule"):
        relevant = consumers.get(binding.pk, [])
        if binding.import_policy == "indicator_only" and not relevant:
            continue
        binding.full_clean()
        result.append(
            {
                "rule": serialize_validation_rule(binding.rule_version),
                "import_policy": binding.import_policy,
                "consumers": relevant,
            }
        )
    return sorted(
        result,
        key=lambda entry: (entry["rule"]["rule_code"], entry["rule"]["rule_version"]),
    )


def validate_profile_input_coverage(profile, indicator_versions) -> None:
    """Require the exact declared specifications, including rule-free inputs."""
    supplied = {}
    for link in profile.input_flow_links.select_related(
        "input_flow_version__dataset_specification"
    ):
        supplied.setdefault(link.dataset_id, []).append(
            link.input_flow_version.dataset_specification_id
        )
    required = {}
    for version in indicator_versions:
        for spec in required_dataset_specifications(version):
            if spec.dataset_id in required and required[spec.dataset_id].pk != spec.pk:
                raise ValidationError(
                    "Conflicting dataset versions.", code="conflicting_dataset_versions"
                )
            required[spec.dataset_id] = spec
    for spec in required.values():
        if supplied.get(spec.dataset_id) != [spec.pk]:
            raise ValidationError(
                f"Missing exact profile input: {spec.code}.",
                code="missing_profile_input",
            )


def validate_indicator_bindings(version) -> None:
    """Check all binding completeness at publication, not only in forms."""
    for binding in version.rule_bindings.select_related(
        "dataset_version_rule__rule_version",
        "dataset_version_rule__dataset_specification",
    ):
        binding.validate_complete()
    for link in version.dataset_inputs.select_related("dataset_specification"):
        link.full_clean()


def required_dataset_specifications(version) -> list:
    """Keep rule-free input declarations alongside inputs derived from rules."""
    specs = {
        link.dataset_specification.pk: link.dataset_specification
        for link in version.dataset_inputs.select_related(
            "dataset_specification__dataset"
        )
    }
    for binding in version.rule_bindings.select_related(
        "dataset_version_rule__dataset_specification__dataset"
    ):
        spec = binding.dataset_version_rule.dataset_specification
        specs[spec.pk] = spec
    # Retain historical requirements until the explicit migration removes them.
    for fragment in version.required_fragments.select_related(
        "dataset_specification__dataset"
    ):
        specs[fragment.dataset_specification_id] = fragment.dataset_specification
    by_category = {}
    for spec in specs.values():
        if (
            spec.dataset.code in by_category
            and by_category[spec.dataset.code].pk != spec.pk
        ):
            raise ValidationError(
                "Conflicting dataset versions.", code="conflicting_dataset_versions"
            )
        by_category[spec.dataset.code] = spec
    return sorted(specs.values(), key=lambda spec: spec.code)
