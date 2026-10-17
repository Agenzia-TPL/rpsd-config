# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared validation and serialization of contractual evaluation conditions."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.services.evaluation_schema import (
    metric_catalog,
    validate_metric,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)

PERIOD_FIELDS = (
    "period_type",
    "period_start_date",
    "period_end_date",
    "period_days",
    "evaluation_timezone",
    "partial_period_policy",
)


def indicator_version(target):
    """Resolve the owner's exact technical version, never the latest catalog row."""
    from rpsd_config.exchange_agreement.models import ContractRevisionIndicator

    owner = ContractRevisionIndicator.objects.select_related(
        "processing_profile_indicator_version__indicator_version", "revision__contract"
    ).get(pk=target.owner_id())
    return owner, owner.processing_profile_indicator_version.indicator_version


def period_context(target, *, complete: bool) -> dict:
    """Validate inclusive calendar dates and resolve finite, immutable boundaries."""
    owner, _ = indicator_version(target)
    if getattr(target, "activation_threshold_id", None):
        from rpsd_config.exchange_agreement.models import IndicatorEvaluationThreshold

        threshold = IndicatorEvaluationThreshold.objects.get(
            pk=target.activation_threshold_id
        )
        if threshold.contract_revision_indicator_id != owner.pk:
            raise ValidationError(
                {"activation_threshold": "Use this revision indicator’s threshold."}
            )
        if any(getattr(target, name) not in (None, "") for name in PERIOD_FIELDS):
            raise ValidationError(
                "A linked penalty must inherit its threshold's entire period context."
            )
        return period_context(threshold, complete=complete)
    kind = target.period_type
    start, end, days = (
        target.period_start_date,
        target.period_end_date,
        target.period_days,
    )
    custom = {"custom_range", "custom_to_contract_end", "custom_duration_days"}
    if kind not in custom and any(v is not None for v in (start, end, days)):
        raise ValidationError("Calendar periods cannot have custom date fields.")
    if kind != "custom_range" and end is not None:
        raise ValidationError(
            {"period_end_date": "Only custom_range accepts an explicit end date."}
        )
    if kind != "custom_duration_days" and days is not None:
        raise ValidationError(
            {"period_days": "Only custom_duration_days accepts a duration."}
        )
    if days is not None and (type(days) is not int or days < 1):
        raise ValidationError(
            {"period_days": "Provide a positive integer number of calendar days."}
        )
    if target.evaluation_timezone:
        try:
            ZoneInfo(target.evaluation_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(
                {"evaluation_timezone": "Use a valid IANA timezone."}
            ) from None
    if start and end and end < start:
        raise ValidationError(
            {"period_end_date": "The inclusive end cannot precede the start."}
        )
    contract = owner.revision.contract
    if kind == "custom_duration_days" and start and days:
        try:
            end = start + timedelta(days=days - 1)
        except (OverflowError, ValueError):
            raise ValidationError(
                {"period_days": "The duration exceeds representable dates."}
            ) from None
    if kind == "contract":
        start = contract.start_date
    if kind in {"custom_to_contract_end", "contract"}:
        end = contract.end_date
    if (
        start
        and start < contract.start_date
        or end
        and contract.end_date
        and end > contract.end_date
    ):
        raise ValidationError(
            "The declared window must be inside the contract's dates."
        )
    if (
        start
        and contract.end_date
        and start > contract.end_date
        or start
        and end
        and end < start
    ):
        raise ValidationError("The declared window falls outside the contract.")
    if complete:
        for name in ("period_type", "evaluation_timezone", "partial_period_policy"):
            if not getattr(target, name):
                raise ValidationError(
                    {name: "An explicit choice is required before approval."}
                )
        if kind in custom | {"contract"} and (start is None or end is None):
            raise ValidationError(
                "A finite start and end are required for this period before approval."
            )
    return {
        "period_type": kind,
        "declared_start": target.period_start_date.isoformat()
        if target.period_start_date
        else None,
        "declared_end": target.period_end_date.isoformat()
        if target.period_end_date
        else None,
        "period_days": days,
        "resolved_start": start.isoformat() if start else None,
        "resolved_end": end.isoformat() if end else None,
        "end_source": "contract"
        if kind in {"contract", "custom_to_contract_end"}
        else "configuration",
        "contract_start": contract.start_date.isoformat(),
        "contract_end": contract.end_date.isoformat() if contract.end_date else None,
        "applicable_from": owner.revision.valid_from.isoformat(),
        "revision_boundary_policy": "stop_at_next_effective_revision",
        "evaluation_timezone": target.evaluation_timezone,
        "partial_period_policy": target.partial_period_policy,
        "date_boundaries": "inclusive",
        "week_start": "monday",
    }


def validate_dimensions(target, codes) -> None:
    """Validate native and direct-through M:N changes against frozen output metadata."""
    _, version = indicator_version(target)
    if getattr(target, "activation_threshold_id", None):
        if codes:
            raise ValidationError(
                "A linked penalty inherits its threshold's dimensions."
            )
        return
    metric_code = getattr(target, "metric_code", "") or getattr(
        target, "quantity_metric_code", ""
    )
    metrics = metric_catalog(version)
    allowed = (
        set(metrics.get(metric_code, {}).get("dimensions", []))
        if metric_code
        else set().union(*(set(m["dimensions"]) for m in metrics.values()))
    )
    if set(codes) - allowed:
        raise ValidationError(
            "Select only dimensions advertised by the indicator metric."
        )


def validate_evaluation(target, *, complete: bool) -> None:
    """Validate draft consistency or the stronger approval contract."""
    owner, version = indicator_version(target)
    period_context(target, complete=complete)
    penalty = hasattr(target, "calculation_method")
    metric_code = target.quantity_metric_code if penalty else target.metric_code
    aggregation = (
        target.quantity_aggregation_method if penalty else target.aggregation_method
    )
    if metric_code and aggregation:
        validate_metric(version, metric_code, aggregation)
    elif metric_code and metric_code not in metric_catalog(version):
        raise ValidationError("Unknown output metric.")
    if target.pk:
        validate_dimensions(
            target,
            getattr(
                target,
                "_pending_dimensions",
                list(target.group_by_dimensions.values_list("code", flat=True)),
            ),
        )
    if not penalty:
        if complete:
            for name in (
                "metric_code",
                "aggregation_method",
                "violation_operator",
                "severity",
                "missing_data_policy",
            ):
                if not getattr(target, name):
                    raise ValidationError(
                        {name: "Complete the threshold before approval."}
                    )
            if target.limit_value is None:
                raise ValidationError(
                    {"limit_value": "A limit is required before approval."}
                )
        return
    method = target.calculation_method
    for name in ("fixed_amount", "unit_amount", "allowance_quantity", "maximum_amount"):
        value = getattr(target, name)
        if value is not None and (not value.is_finite() or value < 0):
            raise ValidationError({name: "Provide a non-negative finite decimal."})
    present = {
        name
        for name in (
            "quantity_metric_code",
            "quantity_aggregation_method",
            "allowance_quantity",
            "fixed_amount",
            "unit_amount",
            "external_execution_reference",
            "external_artifact_identifier",
            "external_parameter_schema",
            "external_parameters",
        )
        if getattr(target, name) not in (None, "", {})
    }
    required = {
        "fixed_amount": {"fixed_amount"},
        "per_unit": {
            "quantity_metric_code",
            "quantity_aggregation_method",
            "allowance_quantity",
            "unit_amount",
        },
        "external": {
            "external_execution_reference",
            "external_artifact_identifier",
            "external_parameter_schema",
        },
    }.get(method, set())
    allowed = required | ({"external_parameters"} if method == "external" else set())
    if present - allowed:
        raise ValidationError(
            "Remove fields incompatible with the selected penalty method."
        )
    if complete and (
        not method
        or required - present
        or not target.currency
        or not target.amount_rounding_mode
    ):
        raise ValidationError(
            "Complete the penalty method, currency, rounding and required coefficients."
        )
    if method == "external":
        executor = version.output_schema.get("penalty_executor", {})
        if (
            target.external_execution_reference != executor.get("execution_reference")
            or target.external_artifact_identifier
            != executor.get("artifact_identifier")
            or target.external_parameter_schema != executor.get("parameter_schema")
        ):
            raise ValidationError(
                "Select the executor advertised by the published "
                "indicator output contract."
            )
        validate_indicator_parameters(
            target.external_parameter_schema, target.external_parameters
        )
    if target.activation_threshold_id:
        threshold = target.activation_threshold
        validate_evaluation(threshold, complete=complete)
        if target.pk and metric_code:
            dimensions = set(
                threshold.group_by_dimensions.values_list("code", flat=True)
            )
            if dimensions - set(
                metric_catalog(version).get(metric_code, {}).get("dimensions", [])
            ):
                raise ValidationError(
                    "The economic quantity does not support the threshold's grouping."
                )


def serialize_evaluation(target) -> dict:
    """Produce a canonical, local-code-based record without mutable lookups later."""
    validate_evaluation(target, complete=True)
    _, version = indicator_version(target)
    result = {}
    for field in target._meta.fields:
        if (
            field.name
            in {
                "id",
                "contract_revision_indicator",
                "created_at",
                "updated_at",
                "activation_threshold",
            }
            or field.name in PERIOD_FIELDS
        ):
            continue
        value = getattr(target, field.name)
        result[field.name] = str(value) if isinstance(value, Decimal) else value
    threshold = getattr(target, "activation_threshold", None)
    result["activation_threshold_code"] = threshold.code if threshold else None
    context_target = threshold or target
    result["context"] = period_context(target, complete=True)
    result["group_by_dimensions"] = sorted(
        context_target.group_by_dimensions.values_list("code", flat=True)
    )
    code = getattr(target, "metric_code", "") or getattr(
        target, "quantity_metric_code", ""
    )
    result["metric"] = metric_catalog(version).get(code) if code else None
    return result


def evaluation_snapshot(revision) -> list[dict]:
    """Freeze complete declarative policies and never compute monetary results."""
    rows = []
    for owner in revision.indicator_configurations.select_related(
        "processing_profile_indicator_version__indicator_version"
    ).order_by("processing_profile_indicator_version__indicator_version__code"):
        thresholds = list(owner.evaluation_thresholds.all())
        penalties = list(owner.evaluation_penalties.all())
        if not thresholds and not penalties:
            continue
        if owner.thresholds or owner.penalties:
            raise ValidationError(
                "Resolve legacy economic JSON before adding relational evaluations."
            )
        rows.append(
            {
                "indicator_version_code": (
                    owner.processing_profile_indicator_version.indicator_version.code
                ),
                "penalty_combination_policy": "cumulative",
                "thresholds": [serialize_evaluation(t) for t in thresholds],
                "penalties": [serialize_evaluation(p) for p in penalties],
            }
        )
    return rows


@transaction.atomic
def save_evaluation(target, *, dimensions, actor):
    """Shared authorized write boundary for web and admin."""
    from rpsd_config.exchange_agreement.models import (
        EvaluationPenaltyDimension,
        EvaluationThresholdDimension,
    )
    from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
        require_revision_preparer,
    )

    owner = target.lock_owner()
    require_revision_preparer(user=actor, contract=owner.revision.contract)
    created = target.pk is None
    dimensions = list(dimensions)
    target._pending_dimensions = [d.code for d in dimensions]
    target.save()
    validate_dimensions(target, target._pending_dimensions)
    target.group_by_dimensions.clear()
    link_model = (
        EvaluationPenaltyDimension
        if hasattr(target, "calculation_method")
        else EvaluationThresholdDimension
    )
    key = "penalty" if hasattr(target, "calculation_method") else "threshold"
    for dimension in dimensions:
        link_model.objects.create(**{key: target, "dimension": dimension})
    target.full_clean()
    del target._pending_dimensions
    log_evaluation_change(target, actor, created=created)
    return target


@transaction.atomic
def delete_evaluation(target, *, actor):
    """Authorized removal; PROTECT retains a threshold referenced by a penalty."""
    from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
        require_revision_preparer,
    )

    owner = target.lock_owner()
    require_revision_preparer(user=actor, contract=owner.revision.contract)
    log_evaluation_change(target, actor, deleted=True)
    target.delete()


def validate_frozen_evaluations(snapshot: dict) -> None:
    """Validate references from immutable data only, without ORM or live dates."""
    from rpsd_config.exchange_agreement.services.ingest_resolution import (
        IngestResolutionError,
    )

    try:
        rows = snapshot["evaluation_configurations"]
        if not isinstance(rows, list):
            raise ValueError
        selected = set(snapshot["selected_indicators"])
        seen = set()
        for row in rows:
            code = row["indicator_version_code"]
            if code in seen or code not in selected:
                raise ValueError
            seen.add(code)
            thresholds, penalties = row["thresholds"], row["penalties"]
            if not isinstance(thresholds, list) or not isinstance(penalties, list):
                raise ValueError
            for entries in (thresholds, penalties):
                codes = [entry["code"] for entry in entries]
                if len(codes) != len(set(codes)) or not all(
                    isinstance(c, str) and c for c in codes
                ):
                    raise ValueError
                for entry in entries:
                    context = entry["context"]
                    if context["date_boundaries"] != "inclusive" or context[
                        "partial_period_policy"
                    ] not in {"complete_only", "evaluate_partial"}:
                        raise ValueError
                    ZoneInfo(context["evaluation_timezone"])
                    for key in (
                        "limit_value",
                        "fixed_amount",
                        "unit_amount",
                        "allowance_quantity",
                        "maximum_amount",
                    ):
                        if entry.get(key) is not None and (
                            not isinstance(entry[key], str)
                            or not Decimal(entry[key]).is_finite()
                        ):
                            raise ValueError
            if penalties and row["penalty_combination_policy"] != "cumulative":
                raise ValueError
            threshold_codes = {t["code"] for t in thresholds}
            if any(
                p["activation_threshold_code"] is not None
                and p["activation_threshold_code"] not in threshold_codes
                for p in penalties
            ):
                raise ValueError
    except (KeyError, ValueError, TypeError, ArithmeticError, ZoneInfoNotFoundError):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "The frozen evaluation configuration is inconsistent",
        ) from None


@transaction.atomic
def clone_evaluations(source, target, *, actor):
    """Copy local rows and dimensions, remapping threshold references in the draft."""
    from rpsd_config.exchange_agreement.models import (
        ContractConfigurationRevision,
        IndicatorEvaluationThreshold,
        IndicatorPenalty,
    )
    from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
        require_revision_preparer,
    )

    revision = ContractConfigurationRevision.objects.select_for_update().get(
        pk=target.revision_id
    )
    require_revision_preparer(user=actor, contract=revision.contract)
    if (
        revision.status != "draft"
        or source.processing_profile_indicator_version.indicator_version_id
        != target.processing_profile_indicator_version.indicator_version_id
    ):
        raise ValidationError("Clone only matching technical versions into a draft.")
    if target.evaluation_thresholds.exists() or target.evaluation_penalties.exists():
        raise ValidationError("The target already has evaluation conditions.")
    mapping = {}
    for model, manager in (
        (IndicatorEvaluationThreshold, source.evaluation_thresholds),
        (IndicatorPenalty, source.evaluation_penalties),
    ):
        for original in manager.all():
            values = {
                f.attname: getattr(original, f.attname)
                for f in model._meta.fields
                if f.name
                not in {
                    "id",
                    "created_at",
                    "updated_at",
                    "contract_revision_indicator",
                    "activation_threshold",
                }
            }
            copied = model(contract_revision_indicator=target, **values)
            if model is IndicatorPenalty and original.activation_threshold_id:
                copied.activation_threshold = mapping[original.activation_threshold_id]
            save_evaluation(
                copied, dimensions=list(original.group_by_dimensions.all()), actor=actor
            )
            if model is IndicatorEvaluationThreshold:
                mapping[original.pk] = copied


def log_evaluation_change(target, actor, *, deleted=False, created=False):
    """Reuse Django's persistent administration audit without storing parameters."""
    from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
    from django.contrib.contenttypes.models import ContentType

    LogEntry.objects.create(
        user_id=actor.pk,
        content_type=ContentType.objects.get_for_model(
            target, for_concrete_model=False
        ),
        object_id=str(target.pk),
        object_repr=str(target)[:200],
        action_flag=DELETION if deleted else ADDITION if created else CHANGE,
        change_message=(
            "Contractual evaluation configuration changed through the shared service."
        ),
    )
