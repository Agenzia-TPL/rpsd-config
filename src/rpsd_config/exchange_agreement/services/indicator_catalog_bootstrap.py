# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent multi-format example for the versioned indicator catalog."""

from dataclasses import dataclass

from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    ensure_initial_dataset_catalog,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
)


@dataclass(frozen=True)
class ExampleRequirement:
    specification_code: str
    code: str
    name: str
    path: str
    namespace: str


COMMERCIAL_SPEED_REQUIREMENTS = (
    ExampleRequirement(
        "netex-ita_v001",
        "service-journey",
        "Service journey",
        "//netex:ServiceJourney",
        "http://www.netex.org.uk/netex",
    ),
    ExampleRequirement(
        "netex-ita_v001",
        "line",
        "Line",
        "//netex:Line",
        "http://www.netex.org.uk/netex",
    ),
    ExampleRequirement(
        "netex-ita_v001",
        "scheduled-stop-point",
        "Scheduled stop point",
        "//netex:ScheduledStopPoint",
        "http://www.netex.org.uk/netex",
    ),
    ExampleRequirement(
        "siri-vm_v001",
        "observed-vehicle-journey",
        "Observed vehicle journey",
        "//siri:VehicleActivity",
        "http://www.siri.org.uk/siri",
    ),
)


@transaction.atomic
def ensure_commercial_speed_example(*, actor) -> IndicatorVersion:
    """Create an indicator with three NeTEx and one SIRI validation rule."""

    ensure_initial_dataset_catalog()
    from rpsd_config.exchange_agreement.services.validation_bindings import (
        bind_indicator_rule,
    )
    from rpsd_config.exchange_agreement.services.validation_catalog import (
        require_catalog_admin,
        transition_validation_rule,
    )
    from rpsd_config.exchange_agreement.services.validation_seed import (
        ensure_seed_version,
    )

    require_catalog_admin(actor)
    bindings = []
    for definition in COMMERCIAL_SPEED_REQUIREMENTS:
        specification = DatasetSpecification.objects.get(
            code=definition.specification_code
        )
        prefix = "siri" if specification.dataset.code.startswith("siri-") else "netex"
        rule, _ = ValidationRule.objects.get_or_create(
            code="commercial-speed-" + definition.code,
            defaults={"name": definition.name},
        )
        rule_version, _ = ensure_seed_version(
            ValidationRuleVersion,
            rule=rule,
            version="001",
            defaults={
                "name": definition.name,
                "validation_type_version": get_validation_type_version("xpath", "1.0"),
                "definition": "/*[not(" + definition.path + ")]",
                "options": {"namespaces": {prefix: definition.namespace}},
                "execution_reference": "fixture-validators/"
                + specification.dataset.code,
            },
        )
        if rule_version.status == "draft":
            rule_version = transition_validation_rule(
                rule_version, target_status="published", actor=actor
            )
        bindings.append((specification, rule_version))

    indicator, _created = Indicator.objects.update_or_create(
        code="commercial-speed",
        defaults={
            "name": "Commercial speed",
            "description": "Average commercial speed of the monitored service.",
            "status": Indicator.Status.ACTIVE,
        },
    )
    version, _created = ensure_seed_version(
        IndicatorVersion,
        code="commercial-speed_002",
        defaults={
            "indicator": indicator,
            "version": "002",
            "description": "Commercial speed based on scheduled and observed data.",
            "formula_description": "Travelled distance divided by travel time.",
            "input_schema": {
                "schema_version": 1,
                "identifier": "commercial-speed-input-v2",
                "description": "Normalized scheduled and observed journeys.",
            },
            "output_schema": {
                "schema_version": 1,
                "identifier": "commercial-speed-output-v2",
                "description": "Commercial speed in kilometres per hour.",
            },
            "execution_engine": IndicatorVersion.ExecutionEngine.PREFECT,
            "execution_reference": "rpsd-monitoring/commercial-speed",
            "artifact_identifier": (
                "dbt:rpsd-monitoring/commercial_speed@sha256:example002"
            ),
        },
    )
    if version.status == IndicatorVersion.Status.DRAFT:
        for specification, rule_version in bindings:
            if not version.rule_bindings.filter(
                dataset_specification=specification, rule_version=rule_version
            ).exists():
                bind_indicator_rule(
                    indicator_version=version,
                    specification=specification,
                    rule_version=rule_version,
                    impact="calculation",
                    dimensions=[],
                    actor=actor,
                )
        version = publish_indicator_version(version, actor=actor)
    return version
