# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent multi-format example for the versioned indicator catalog."""

from dataclasses import dataclass

from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    DatasetSpecification,
    FragmentValidationRule,
    Indicator,
    IndicatorVersion,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    ensure_initial_dataset_catalog,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.requirement_fragments import (
    publish_requirement_fragment,
)


@dataclass(frozen=True)
class ExampleFragment:
    specification_code: str
    code: str
    name: str
    path: str
    namespace: str


COMMERCIAL_SPEED_FRAGMENTS = (
    ExampleFragment(
        "netex-ita_v001",
        "service-journey",
        "Service journey",
        "//netex:ServiceJourney",
        "http://www.netex.org.uk/netex",
    ),
    ExampleFragment(
        "netex-ita_v001",
        "line",
        "Line",
        "//netex:Line",
        "http://www.netex.org.uk/netex",
    ),
    ExampleFragment(
        "netex-ita_v001",
        "scheduled-stop-point",
        "Scheduled stop point",
        "//netex:ScheduledStopPoint",
        "http://www.netex.org.uk/netex",
    ),
    ExampleFragment(
        "siri-vm_v001",
        "observed-vehicle-journey",
        "Observed vehicle journey",
        "//siri:VehicleActivity",
        "http://www.siri.org.uk/siri",
    ),
)


@transaction.atomic
def ensure_commercial_speed_example() -> IndicatorVersion:
    """Create a published example needing three NeTEx and one SIRI fragment."""

    ensure_initial_dataset_catalog()
    fragments = []
    for definition in COMMERCIAL_SPEED_FRAGMENTS:
        specification = DatasetSpecification.objects.get(
            code=definition.specification_code
        )
        prefix = "siri" if specification.dataset.code.startswith("siri-") else "netex"
        fragment, _created = RequirementFragment.objects.get_or_create(
            dataset_specification=specification,
            code=definition.code,
            defaults={
                "name": definition.name,
                "description": f"Required input for {definition.name}.",
                "locator_type": RequirementFragment.LocatorType.XPATH,
                "result_kind": RequirementFragment.ResultKind.PRESENCE,
                "locator_definition": {
                    "path": definition.path,
                    "namespaces": {prefix: definition.namespace},
                },
            },
        )
        if fragment.status == RequirementFragment.Status.DRAFT:
            FragmentValidationRule.objects.get_or_create(
                requirement_fragment=fragment,
                rule_type=FragmentValidationRule.RuleType.EXISTS,
                defaults={"parameters": {}},
            )
            fragment = publish_requirement_fragment(fragment)
        fragments.append(fragment)

    indicator, _created = Indicator.objects.update_or_create(
        code="commercial-speed",
        defaults={
            "name": "Commercial speed",
            "description": "Average commercial speed of the monitored service.",
            "status": Indicator.Status.ACTIVE,
        },
    )
    version, _created = IndicatorVersion.objects.get_or_create(
        code="commercial-speed_002",
        defaults={
            "indicator": indicator,
            "version": "002",
            "description": "Commercial speed based on scheduled and observed data.",
            "formula_description": "Travelled distance divided by travel time.",
            "input_contract": {
                "schema_version": 1,
                "identifier": "commercial-speed-input-v2",
                "description": "Normalized scheduled and observed journeys.",
            },
            "output_contract": {
                "schema_version": 1,
                "identifier": "commercial-speed-output-v2",
                "description": "Commercial speed in kilometres per hour.",
            },
            "execution_engine": IndicatorVersion.ExecutionEngine.DBT,
            "execution_reference": "rpsd-monitoring/commercial-speed",
            "artifact_identifier": (
                "dbt:rpsd-monitoring/commercial_speed@sha256:example002"
            ),
        },
    )
    if version.status == IndicatorVersion.Status.DRAFT:
        version.required_fragments.add(*fragments)
        version = publish_indicator_version(version)
    return version
