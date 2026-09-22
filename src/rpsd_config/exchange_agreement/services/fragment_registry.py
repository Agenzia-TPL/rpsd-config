# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed registries for declarative fragment locators and validation rules."""

from django.core.exceptions import ValidationError

LOCATOR_XPATH = "xpath"
LOCATOR_TABLE = "table"
RESULT_PRESENCE = "presence"
RESULT_SCALAR_VALUES = "scalar_values"

RULE_EXISTS = "exists"
RULE_NON_EMPTY = "non_empty"
RULE_ALL_VALUES_IN_SET = "all_values_in_set"
RULE_CONTAINS_ALL_VALUES = "contains_all_values"
RULE_SET_EQUALS = "set_equals"

SUPPORTED_LOCATOR_TYPES = (LOCATOR_XPATH, LOCATOR_TABLE)
SUPPORTED_RESULT_KINDS = (RESULT_PRESENCE, RESULT_SCALAR_VALUES)
SUPPORTED_RULE_TYPES = (
    RULE_EXISTS,
    RULE_NON_EMPTY,
    RULE_ALL_VALUES_IN_SET,
    RULE_CONTAINS_ALL_VALUES,
    RULE_SET_EQUALS,
)


def _require_object(value, *, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object.")
    return value


def _reject_unknown_keys(value: dict, *, allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(f"{label} contains unknown keys: {', '.join(unknown)}.")


def _required_text(value: dict, key: str, *, label: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValidationError(f"{label}.{key} must be a non-empty string.")
    return item.strip()


def _unique_text_list(value, *, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label} must be a non-empty list of strings.")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"{label} must contain non-empty strings.")
        normalized.append(item.strip())
    if len(set(normalized)) != len(normalized):
        raise ValidationError(f"{label} must not contain duplicate values.")
    return normalized


def validate_locator_definition(
    locator_type: str,
    result_kind: str,
    definition,
) -> dict:
    """Validate and normalize one locator using the closed v1 registry."""

    value = _require_object(definition, label="locator_definition")
    if locator_type == LOCATOR_XPATH:
        _reject_unknown_keys(
            value,
            allowed={"path", "namespaces"},
            label="locator_definition",
        )
        path = _required_text(value, "path", label="locator_definition")
        namespaces = value.get("namespaces")
        if not isinstance(namespaces, dict) or not namespaces:
            raise ValidationError(
                "locator_definition.namespaces must be a non-empty object."
            )
        normalized_namespaces = {}
        for prefix, uri in namespaces.items():
            if not isinstance(prefix, str) or not prefix.strip():
                raise ValidationError("XPath namespace prefixes must be non-empty.")
            if not isinstance(uri, str) or not uri.strip():
                raise ValidationError("XPath namespace URIs must be non-empty.")
            normalized_namespaces[prefix.strip()] = uri.strip()
        return {"path": path, "namespaces": normalized_namespaces}

    if locator_type == LOCATOR_TABLE:
        allowed = {"resource", "columns"}
        if result_kind == RESULT_SCALAR_VALUES:
            allowed = {"resource", "column"}
        _reject_unknown_keys(value, allowed=allowed, label="locator_definition")
        normalized = {
            "resource": _required_text(value, "resource", label="locator_definition")
        }
        if result_kind == RESULT_SCALAR_VALUES:
            normalized["column"] = _required_text(
                value,
                "column",
                label="locator_definition",
            )
        elif "columns" in value:
            normalized["columns"] = _unique_text_list(
                value["columns"],
                label="locator_definition.columns",
            )
        return normalized

    raise ValidationError(f"Unsupported locator type: {locator_type!r}.")


def _boolean_parameter(parameters: dict, key: str, *, default: bool) -> bool:
    value = parameters.get(key, default)
    if not isinstance(value, bool):
        raise ValidationError(f"parameters.{key} must be a boolean.")
    return value


def _normalize_comparison_values(
    values: list[str],
    *,
    case_sensitive: bool,
    trim: bool,
) -> list[str]:
    normalized = []
    for value in values:
        item = value.strip() if trim else value
        item = item if case_sensitive else item.casefold()
        normalized.append(item)
    return normalized


def validate_rule_parameters(
    rule_type: str,
    rule_version: int,
    result_kind: str,
    parameters,
) -> dict:
    """Validate and normalize parameters for one registered rule version."""

    if rule_version != 1 or rule_type not in SUPPORTED_RULE_TYPES:
        raise ValidationError(
            f"Unsupported validation rule: {rule_type}/v{rule_version}."
        )
    value = _require_object(parameters, label="parameters")

    if rule_type == RULE_EXISTS:
        _reject_unknown_keys(value, allowed=set(), label="parameters")
        return {}

    if result_kind != RESULT_SCALAR_VALUES:
        raise ValidationError(
            f"Rule {rule_type}/v{rule_version} requires scalar_values."
        )

    if rule_type == RULE_NON_EMPTY:
        _reject_unknown_keys(value, allowed={"trim"}, label="parameters")
        return {"trim": _boolean_parameter(value, "trim", default=True)}

    values_key = {
        RULE_ALL_VALUES_IN_SET: "allowed_values",
        RULE_CONTAINS_ALL_VALUES: "required_values",
        RULE_SET_EQUALS: "expected_values",
    }[rule_type]
    _reject_unknown_keys(
        value,
        allowed={values_key, "case_sensitive", "trim"},
        label="parameters",
    )
    values = _unique_text_list(value.get(values_key), label=f"parameters.{values_key}")
    case_sensitive = _boolean_parameter(value, "case_sensitive", default=True)
    trim = _boolean_parameter(value, "trim", default=True)
    comparison_values = _normalize_comparison_values(
        values,
        case_sensitive=case_sensitive,
        trim=trim,
    )
    if len(set(comparison_values)) != len(comparison_values):
        raise ValidationError(
            f"parameters.{values_key} contains duplicates after normalization."
        )
    return {
        values_key: values,
        "case_sensitive": case_sensitive,
        "trim": trim,
    }
