# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed, versioned configuration schema for scalar indicator parameters."""

import math

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
        or schema.get("schema_version") != 1
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
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(spec, dict)
            or set(spec) - {"type", "enum", "minimum", "maximum", "description"}
            or not isinstance(spec.get("type"), str)
            or spec.get("type") not in TYPES
        ):
            raise ValidationError("Invalid parameter property definition.")
        if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
            raise ValidationError("Parameter enum must be a non-empty list.")
        if "description" in spec and not isinstance(spec["description"], str):
            raise ValidationError("Parameter description must be a string.")
        for value in spec.get("enum", []):
            if not isinstance(value, TYPES[spec["type"]]) or (
                isinstance(value, bool) and spec["type"] in {"integer", "number"}
            ):
                raise ValidationError("Parameter enum has an invalid type.")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValidationError("Parameter enum must contain finite values.")
        for bound in ("minimum", "maximum"):
            if bound in spec and (
                spec["type"] not in {"number", "integer"}
                or not isinstance(spec[bound], (int, float))
                or isinstance(spec[bound], bool)
                or not math.isfinite(spec[bound])
            ):
                raise ValidationError("Invalid numeric parameter bound.")
        if (
            "minimum" in spec
            and "maximum" in spec
            and spec["minimum"] > spec["maximum"]
        ):
            raise ValidationError("Parameter bounds are inverted.")


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
        expected = TYPES[spec["type"]]
        if not isinstance(value, expected) or (
            isinstance(value, bool) and spec["type"] in {"integer", "number"}
        ):
            raise ValidationError(f"Invalid type for parameter {name}.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError(f"Parameter {name} must be finite.")
        if "enum" in spec and value not in spec["enum"]:
            raise ValidationError(f"Invalid value for parameter {name}.")
        if (
            "minimum" in spec
            and value < spec["minimum"]
            or "maximum" in spec
            and value > spec["maximum"]
        ):
            raise ValidationError(f"Parameter {name} is outside its bounds.")
