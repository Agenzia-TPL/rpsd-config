# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed output contracts for configurable contractual evaluations."""

import re

from django.core.exceptions import ValidationError

AGGREGATIONS = {
    "sum",
    "average",
    "minimum",
    "maximum",
    "count_distinct",
    "already_aggregated",
}
CODE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,95}$")


def validate_metrics(metrics: list) -> None:
    """Validate metric metadata without reading or calculating operational data."""
    if not isinstance(metrics, list) or not metrics:
        raise ValidationError("Output metrics must be a non-empty list.")
    seen = set()
    for metric in metrics:
        if not isinstance(metric, dict) or set(metric) - {
            "code",
            "type",
            "unit",
            "grain",
            "dimensions",
            "aggregations",
            "distinct_key",
        }:
            raise ValidationError("Invalid output metric definition.")
        code = metric.get("code")
        if not isinstance(code, str) or not CODE.fullmatch(code) or code in seen:
            raise ValidationError("Metric codes must be valid and unique.")
        seen.add(code)
        if metric.get("type") not in {"integer", "number"}:
            raise ValidationError("Evaluation metrics must be numeric.")
        for key in ("unit", "grain"):
            if not isinstance(metric.get(key), str) or not metric[key].strip():
                raise ValidationError(f"Metric {key} is required.")
        dimensions = metric.get("dimensions")
        aggregations = metric.get("aggregations")
        if (
            not isinstance(dimensions, list)
            or any(not isinstance(d, str) or not CODE.fullmatch(d) for d in dimensions)
            or len(dimensions) != len(set(dimensions))
            or not isinstance(aggregations, list)
            or not aggregations
            or any(
                not isinstance(a, str) or a not in AGGREGATIONS for a in aggregations
            )
            or len(aggregations) != len(set(aggregations))
        ):
            raise ValidationError("Invalid metric dimensions or aggregations.")
        if "count_distinct" in aggregations:
            if not isinstance(metric.get("distinct_key"), str) or not CODE.fullmatch(
                metric["distinct_key"]
            ):
                raise ValidationError(
                    "Distinct counts require a declared distinct key."
                )
        elif "distinct_key" in metric:
            raise ValidationError("A distinct key requires count_distinct.")


def metric_catalog(version) -> dict:
    """Return only explicitly declared metrics of the exact technical version."""
    schema = version.output_schema
    if schema.get("schema_version") != 2:
        return {}
    validate_metrics(schema.get("metrics"))
    return {metric["code"]: metric for metric in schema["metrics"]}


def validate_metric(version, code: str, aggregation: str) -> dict:
    """Require an advertised metric and a semantically permitted aggregation."""
    metric = metric_catalog(version).get(code)
    if metric is None or aggregation not in metric["aggregations"]:
        raise ValidationError("Select a declared metric and supported aggregation.")
    return metric
