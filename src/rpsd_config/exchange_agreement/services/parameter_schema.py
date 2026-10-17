# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Versioned scalar and homogeneous-list parameter contracts."""

import math
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

TYPES = {"string": str, "boolean": bool, "integer": int, "number": (int, float)}


def validate_parameter_schema(schema: dict) -> None:
    """Validate the supported schema; it describes values, never executes code."""
    if schema == {}:
        return
    if (
        not isinstance(schema, dict)
        or set(schema) - {"schema_version", "properties", "required", "allow_extra"}
        or type(schema.get("schema_version")) is not int
        or schema.get("schema_version") not in {1, 2}
    ):
        raise ValidationError("Unsupported parameter schema.")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if (
        not isinstance(properties, dict)
        or not isinstance(required, list)
        or any(not isinstance(k, str) for k in required)
        or len(set(required)) != len(required)
        or set(required) - set(properties)
    ):
        raise ValidationError("Invalid parameter schema properties/required.")
    if not isinstance(schema.get("allow_extra", False), bool):
        raise ValidationError("allow_extra must be boolean.")
    for name, spec in properties.items():
        if not isinstance(name, str) or not name:
            raise ValidationError("Parameter names must be non-empty strings.")
        _validate_property(
            spec,
            arrays=schema["schema_version"] == 2,
            decimal_strings=schema["schema_version"] == 2,
        )


def _validate_property(
    spec: dict, *, arrays: bool, decimal_strings: bool = False
) -> None:
    if not isinstance(spec, dict):
        raise ValidationError("Invalid parameter property definition.")
    if arrays and spec.get("type") == "array":
        if set(spec) - {
            "type",
            "items",
            "min_items",
            "max_items",
            "unique_items",
            "description",
            "reference_namespace",
        }:
            raise ValidationError("Unsupported array schema fields.")
        _validate_property(
            spec.get("items"), arrays=False, decimal_strings=decimal_strings
        )
        for key in ("min_items", "max_items"):
            if key in spec and (type(spec[key]) is not int or spec[key] < 0):
                raise ValidationError("Array bounds must be non-negative integers.")
        if spec.get("min_items", 0) > spec.get("max_items", 2**63 - 1):
            raise ValidationError("Array bounds are inverted.")
        if not isinstance(spec.get("unique_items", False), bool):
            raise ValidationError("unique_items must be boolean.")
        for key in ("description", "reference_namespace"):
            if key in spec and (
                not isinstance(spec[key], str) or not spec[key].strip()
            ):
                raise ValidationError(f"{key} must be a non-empty string.")
        return
    if (
        set(spec) - {"type", "enum", "minimum", "maximum", "description"}
        or not isinstance(spec.get("type"), str)
        or spec.get("type") not in TYPES
    ):
        raise ValidationError("Invalid parameter property definition.")
    if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
        raise ValidationError("Parameter enum must be a non-empty list.")
    if "description" in spec and not isinstance(spec["description"], str):
        raise ValidationError("Parameter description must be a string.")
    for value in spec.get("enum", []):
        _validate_scalar(
            {"type": spec["type"]}, value, "enum", decimal_strings=decimal_strings
        )
    for bound in ("minimum", "maximum"):
        if bound in spec and (
            spec["type"] not in {"number", "integer"}
            or not _finite_bound(spec[bound], decimal_strings=decimal_strings)
        ):
            raise ValidationError("Invalid numeric parameter bound.")
    if (
        "minimum" in spec
        and "maximum" in spec
        and Decimal(str(spec["minimum"])) > Decimal(str(spec["maximum"]))
    ):
        raise ValidationError("Parameter bounds are inverted.")


def _finite_bound(value, *, decimal_strings=False):
    if type(value) not in ({int, float, str} if decimal_strings else {int, float}):
        return False
    try:
        return Decimal(str(value)).is_finite()
    except InvalidOperation:
        return False


def _validate_scalar(spec: dict, value, name: str, *, decimal_strings=False) -> None:
    if spec["type"] == "number" and decimal_strings and isinstance(value, str):
        if not _finite_bound(value, decimal_strings=True):
            raise ValidationError(f"Parameter {name} must be a finite decimal string.")
        value = Decimal(value)
    if not isinstance(
        value,
        TYPES[spec["type"]] + (Decimal,)
        if spec["type"] == "number" and decimal_strings
        else TYPES[spec["type"]],
    ) or (isinstance(value, bool) and spec["type"] in {"integer", "number"}):
        raise ValidationError(f"Invalid type for parameter {name}.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValidationError(f"Parameter {name} must be finite.")
    if "enum" in spec and value not in (
        [Decimal(str(v)) for v in spec["enum"]]
        if spec["type"] == "number" and decimal_strings
        else spec["enum"]
    ):
        raise ValidationError(f"Invalid value for parameter {name}.")
    if (
        "minimum" in spec
        and value < Decimal(str(spec["minimum"]))
        or "maximum" in spec
        and value > Decimal(str(spec["maximum"]))
    ):
        raise ValidationError(f"Parameter {name} is outside its bounds.")


def validate_indicator_parameters(schema: dict, values: dict) -> None:
    """Check a revision's own values against its indicator's declared schema."""
    validate_parameter_schema(schema)
    if not isinstance(values, dict):
        raise ValidationError("Parameters must be an object.")
    if not schema:
        return
    props = schema.get("properties", {})
    if set(schema.get("required", [])) - set(values):
        raise ValidationError(
            "Required indicator parameters are missing.",
            code="missing_dependency_parameters",
        )
    if not schema.get("allow_extra", False) and set(values) - set(props):
        raise ValidationError("Unknown indicator parameters.")
    for name, value in values.items():
        if name not in props:
            continue
        spec = props[name]
        if spec["type"] == "array":
            if not isinstance(value, list):
                raise ValidationError(f"Parameter {name} must be a list.")
            if len(value) < spec.get("min_items", 0) or len(value) > spec.get(
                "max_items", 2**63 - 1
            ):
                raise ValidationError(f"Parameter {name} has an invalid list length.")
            for item in value:
                _validate_scalar(
                    spec["items"],
                    item,
                    name,
                    decimal_strings=schema["schema_version"] == 2,
                )
            if spec.get("unique_items") and len(set(value)) != len(value):
                raise ValidationError(f"Parameter {name} contains duplicates.")
        else:
            _validate_scalar(
                spec, value, name, decimal_strings=schema["schema_version"] == 2
            )
