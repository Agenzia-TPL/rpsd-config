# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Deterministic additive evaluation examples; no runtime or live database reset."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    Indicator,
    IndicatorDimension,
    IndicatorEvaluationThreshold,
    IndicatorPenalty,
    IndicatorVersion,
    IndicatorVersionInput,
    Lot,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.indicator_evaluations import (
    save_evaluation,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.exchange_agreement.services.validation_seed import (
    ensure_seed_version,
    ensure_validation_demo,
)


@transaction.atomic
def ensure_evaluation_demo(*, actor):
    """Create two draft contracts, leaving contract approval explicit."""
    base = ensure_validation_demo(actor=actor)
    logical, _ = Indicator.objects.get_or_create(
        code="evaluation-demo-missed",
        defaults={
            "name": "Corse mancanti e guasti (demo)",
            "description": "Configuration examples; runtime not provisioned.",
        },
    )
    output = {
        "schema_version": 2,
        "identifier": "evaluation-demo-output-v1",
        "description": "",
        "metrics": [
            {
                "code": "missed",
                "type": "integer",
                "unit": "journeys",
                "grain": "line-day",
                "dimensions": ["line"],
                "aggregations": ["sum"],
            },
            {
                "code": "line_day_fault",
                "type": "integer",
                "unit": "line-day",
                "grain": "one flag (0/1) per line per day",
                "dimensions": ["line"],
                "aggregations": ["sum"],
            },
        ],
    }
    parameters = {
        "schema_version": 2,
        "properties": {
            "linee_incluse": {
                "type": "array",
                "items": {"type": "string"},
                "min_items": 1,
                "unique_items": True,
                "description": (
                    "Exact technical Line/@id values in the NeTEx input, "
                    "not public labels."
                ),
                "reference_namespace": "netex:http://www.netex.org.uk/netex:Line/@id",
            }
        },
        "required": ["linee_incluse"],
    }
    version, _ = ensure_seed_version(
        IndicatorVersion,
        code="evaluation-demo-missed_001",
        defaults={
            "indicator": logical,
            "version": "001",
            "description": "Typed contractual evaluation examples",
            "formula_description": (
                "External calculation; indicator returns line-day metrics."
            ),
            "parameter_schema": parameters,
            "output_schema": output,
            "execution_engine": "prefect",
            "execution_reference": "indicators/evaluation-demo",
            "artifact_identifier": "git:rpsd-flows@evaluation-demo-001",
        },
    )
    source_links = list(base.input_flow_links.all())
    if version.status == "draft":
        for link in source_links:
            IndicatorVersionInput.objects.get_or_create(
                indicator_version=version,
                dataset_specification=link.input_flow_version.dataset_specification,
            )
        version = publish_indicator_version(version, actor=actor)
    profile, _ = ensure_seed_version(
        ProcessingProfileVersion,
        code="evaluation-demo_001",
        defaults={
            "version": "001",
            "name": "Soglie e penali demo",
            "description": "Configuration only; external runtime not provisioned.",
            "orchestration_flow_version": base.orchestration_flow_version,
        },
    )
    if profile.status == "draft":
        for link in source_links:
            ProcessingProfileInputFlow.objects.get_or_create(
                processing_profile_version=profile,
                dataset=link.dataset,
                defaults={"input_flow_version": link.input_flow_version},
            )
        ProcessingProfileIndicatorVersion.objects.get_or_create(
            processing_profile_version=profile,
            indicator_version=version,
            defaults={"proposed_by_default": True},
        )
        profile = publish_processing_profile(profile, actor=actor)
    IndicatorDimension.objects.get_or_create(code="line", defaults={"name": "Linea"})
    agency, _ = Agency.objects.get_or_create(
        agency_key="evaluation-demo", defaults={"name": "Evaluation demo agency"}
    )
    company, _ = Company.objects.get_or_create(name="Evaluation demo TPL")
    revisions = []
    for suffix, lines in (("A", ["2", "3", "4"]), ("B", ["7", "8"])):
        lot, _ = Lot.objects.get_or_create(
            agency=agency,
            short_description="EVAL-" + suffix,
            defaults={"description": "Deterministic evaluation demo lot"},
        )
        contract, _ = Contract.objects.get_or_create(
            contract_code="EVALUATION-DEMO-" + suffix,
            defaults={
                "client_agency": agency,
                "contractor_company": company,
                "lot": lot,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "draft",
            },
        )
        if (
            contract.start_date != date(2026, 1, 1)
            or contract.end_date != date(2026, 12, 31)
            or contract.client_agency_id != agency.pk
            or contract.lot_id != lot.pk
            or contract.contractor_company_id != company.pk
        ):
            raise ValidationError(
                "Evaluation seed contract conflicts with its declared definition."
            )
        revision = contract.configuration_revisions.filter(
            code=contract.contract_code + "-r001"
        ).first()
        if revision is None:
            revision = create_revision_draft(contract, profile, date(2026, 1, 1), actor)
        if revision.processing_profile_version_id != profile.pk:
            raise ValidationError(
                "Evaluation seed revision uses a conflicting profile."
            )
        owner = revision.indicator_configurations.get()
        expected_parameters = {"linee_incluse": lines}
        if revision.status != "draft" and owner.parameters != expected_parameters:
            raise ValidationError(
                "An approved evaluation demo conflicts; create a new version."
            )
        if owner.parameters and owner.parameters != expected_parameters:
            raise ValidationError("Evaluation demo parameter conflict.")
        if revision.status == "draft":
            owner.parameters = expected_parameters
            owner.save()
        definitions = [
            ("daily-faults", "daily", "line_day_fault", "gt", "3", {}),
            ("monthly-faults", "monthly", "line_day_fault", "gt", "10", {}),
            ("daily-missed", "daily", "missed", "gte", "10", {}),
            (
                "custom-range",
                "custom_range",
                "missed",
                "gt",
                "3",
                {
                    "period_start_date": date(2026, 10, 10),
                    "period_end_date": date(2026, 10, 12),
                },
            ),
            (
                "until-end",
                "custom_to_contract_end",
                "missed",
                "gt",
                "10",
                {"period_start_date": date(2026, 11, 1)},
            ),
            (
                "three-days",
                "custom_duration_days",
                "missed",
                "gt",
                "3",
                {"period_start_date": date(2026, 10, 10), "period_days": 3},
            ),
        ]
        for code, period, metric, operator, limit, extra in definitions:
            threshold, created = ensure_seed_version(
                IndicatorEvaluationThreshold,
                contract_revision_indicator=owner,
                code=code,
                defaults={
                    "name": code,
                    "metric_code": metric,
                    "aggregation_method": "sum",
                    "period_type": period,
                    "violation_operator": operator,
                    "limit_value": Decimal(limit),
                    "severity": "alert",
                    "missing_data_policy": "not_evaluable",
                    "evaluation_timezone": "Europe/Rome",
                    "partial_period_policy": "complete_only",
                    **extra,
                },
            )
            if revision.status != "draft" and created:
                raise ValidationError(
                    "An approved demo is missing its declared threshold."
                )
            if created:
                save_evaluation(threshold, dimensions=[], actor=actor)
        # Fixed and per-unit examples are separate; all penalties are cumulative.
        common = {
            "activation_threshold": owner.evaluation_thresholds.get(
                code="daily-missed"
            ),
            "name": "Daily missed journeys",
            "currency": "EUR",
            "amount_rounding_mode": "half_up",
        }
        economic = (
            {"calculation_method": "fixed_amount", "fixed_amount": Decimal("500")}
            if suffix == "A"
            else {
                "calculation_method": "per_unit",
                "quantity_metric_code": "missed",
                "quantity_aggregation_method": "sum",
                "allowance_quantity": Decimal("10"),
                "unit_amount": Decimal("50"),
            }
        )
        penalty, created = ensure_seed_version(
            IndicatorPenalty,
            contract_revision_indicator=owner,
            code="daily-missed",
            defaults={**common, **economic},
        )
        if revision.status != "draft" and created:
            raise ValidationError("An approved demo is missing its declared penalty.")
        if created:
            save_evaluation(penalty, dimensions=[], actor=actor)
        revisions.append(revision)
    return profile, revisions
