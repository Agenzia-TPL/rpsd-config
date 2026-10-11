# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed, local capability validation; never execute a rule in Config."""

import json
import re
from dataclasses import asdict, dataclass

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class ValidationCapability:
    """Configuration contract of an explicitly supported interpreter."""

    validation_type: str
    file_formats: tuple[str, ...]
    language_versions: tuple[str, ...]
    result_contracts: tuple[str, ...]
    option_keys: tuple[str, ...]


CAPABILITIES = {
    "xpath": ValidationCapability(
        "xpath",
        ("xml",),
        ("1.0", "2.0", "3.1"),
        ("violating_entities",),
        ("namespaces", "empty_context"),
    ),
    "xsd_bundle": ValidationCapability(
        "xsd_bundle",
        ("xml",),
        ("1.0",),
        ("structured_report",),
        (),
    ),
}
CAPABILITIES.update(
    {
        "csv_expression": ValidationCapability(
            "csv_expression",
            ("csv",),
            ("1",),
            ("violating_entities",),
            ("delimiter", "encoding", "header"),
        ),
        "spreadsheet_expression": ValidationCapability(
            "spreadsheet_expression",
            ("xlsx",),
            ("1",),
            ("violating_entities",),
            ("sheet", "header_row"),
        ),
        "text_expression": ValidationCapability(
            "text_expression", ("txt",), ("1",), ("violating_entities",), ("encoding",)
        ),
    }
)
# These are definition contracts for the future external interpreters, not a
# claim that their deployments have been provisioned. application_state is
# intentionally unavailable until its source and approval phase are defined.


def validate_rule_definition(
    *,
    validation_type: str,
    definition: str,
    language_version: str,
    options: dict,
    result_contract: str,
) -> None:
    """Validate supported combinations without opening files or contacting Prefect."""
    capability = (
        CAPABILITIES.get(validation_type) if isinstance(validation_type, str) else None
    )
    if capability is None:
        raise ValidationError(
            "Unsupported validation type.", code="unsupported_validation_type"
        )
    if not isinstance(definition, str) or not definition.strip():
        raise ValidationError(
            "A rule definition is required.", code="invalid_definition_options"
        )
    if language_version not in capability.language_versions:
        raise ValidationError(
            "Unsupported language version.", code="invalid_definition_options"
        )
    if result_contract not in capability.result_contracts:
        raise ValidationError(
            "Unsupported result contract.", code="invalid_definition_options"
        )
    if not isinstance(options, dict) or set(options) - set(capability.option_keys):
        raise ValidationError(
            "Unknown interpreter options.", code="invalid_definition_options"
        )
    if validation_type == "xpath":
        namespaces = options.get("namespaces", {})
        if not isinstance(namespaces, dict) or any(
            not isinstance(k, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", k)
            or not isinstance(v, str)
            or not v.strip()
            for k, v in namespaces.items()
        ):
            raise ValidationError(
                "Invalid XPath namespaces.", code="invalid_definition_options"
            )
        # Only scan outside string literals; a URI/string containing ':' is not a QName.
        without_literals = re.sub(r"'[^']*'|\"[^\"]*\"", "", definition)
        prefixes = set(
            re.findall(
                r"(?<![\w:])([A-Za-z_][\w.-]*):(?!:)[A-Za-z_*]", without_literals
            )
        )
        if prefixes - set(namespaces) - {"fn", "xml"}:
            raise ValidationError(
                "Missing XPath namespace.", code="invalid_definition_options"
            )
        if options.get("empty_context", "pass") not in (
            "pass",
            "violation",
            "not_applicable",
        ):
            raise ValidationError(
                "Invalid empty-context policy.", code="invalid_definition_options"
            )
    elif validation_type == "xsd_bundle":
        try:
            descriptor = json.loads(definition)
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                "Invalid bundle descriptor.", code="invalid_definition_options"
            ) from exc
        required = {"asset_code", "asset_version", "entrypoint", "bundle_sha256"}
        if not isinstance(descriptor, dict) or set(descriptor) != required:
            raise ValidationError(
                "Incomplete bundle descriptor.", code="invalid_definition_options"
            )
        if any(not isinstance(v, str) or not v.strip() for v in descriptor.values()):
            raise ValidationError(
                "Invalid bundle descriptor values.", code="invalid_definition_options"
            )
        from rpsd_config.exchange_agreement.services.schema_bundles import (
            validate_bundle_path,
        )

        validate_bundle_path(descriptor["entrypoint"])
        if (
            not descriptor["entrypoint"].endswith(".xsd")
            or len(descriptor["asset_version"]) > 10
            or not re.fullmatch(r"[1-9][0-9]*", descriptor["asset_version"])
            or int(descriptor["asset_version"]) > 2147483647
            or not re.fullmatch(r"[a-f0-9]{64}", descriptor["bundle_sha256"])
        ):
            raise ValidationError(
                "Invalid bundle digest.", code="invalid_definition_options"
            )

    elif validation_type in {
        "csv_expression",
        "spreadsheet_expression",
        "text_expression",
    }:
        if set(options) != set(capability.option_keys):
            raise ValidationError(
                "Explicit format options are required.",
                code="invalid_definition_options",
            )
        try:
            descriptor = json.loads(definition)
        except (ValueError, TypeError) as exc:
            raise ValidationError(
                "Invalid declarative definition.", code="invalid_definition_options"
            ) from exc
        if not isinstance(descriptor, dict):
            raise ValidationError("Definition must be a JSON object.")
        if validation_type == "text_expression":
            if (
                set(descriptor) != {"predicate", "pattern", "scope"}
                or descriptor["predicate"] != "matches"
                or descriptor["scope"] not in ("line", "file")
                or not isinstance(descriptor["pattern"], str)
            ):
                raise ValidationError("Invalid text predicate definition.")
            try:
                re.compile(descriptor["pattern"])
            except re.error as exc:
                raise ValidationError("Invalid regular expression.") from exc
        else:
            if (
                set(descriptor) != {"predicate", "columns"}
                or descriptor["predicate"] != "required_columns"
                or not isinstance(descriptor["columns"], list)
                or not descriptor["columns"]
                or any(
                    not isinstance(c, str) or not c.strip()
                    for c in descriptor["columns"]
                )
                or len(set(descriptor["columns"])) != len(descriptor["columns"])
            ):
                raise ValidationError("Invalid required-columns definition.")
        if "encoding" in options:
            import codecs

            if not isinstance(options["encoding"], str):
                raise ValidationError("Invalid encoding.")
            try:
                codecs.lookup(options["encoding"])
            except LookupError as exc:
                raise ValidationError("Unsupported encoding.") from exc
        if "delimiter" in options and (
            not isinstance(options["delimiter"], str) or len(options["delimiter"]) != 1
        ):
            raise ValidationError("Delimiter must be one character.")
        if "header" in options and not isinstance(options["header"], bool):
            raise ValidationError("header must be boolean.")
        if "sheet" in options and (
            not isinstance(options["sheet"], str) or not options["sheet"]
        ):
            raise ValidationError("A sheet name is required.")
        if "header_row" in options and (
            not isinstance(options["header_row"], int)
            or isinstance(options["header_row"], bool)
            or options["header_row"] < 1
        ):
            raise ValidationError("header_row must be a positive integer.")


def validate_prefect_reference(value: str) -> None:
    """Require an unambiguous flow/deployment reference, without a network request."""
    if not isinstance(value, str) or not re.fullmatch(r"[^\s/]+/[^\s/]+", value):
        raise ValidationError(
            "Use a flow/deployment Prefect reference.",
            code="missing_execution_reference",
        )


def capability_manifest() -> list[dict]:
    """Return deterministic capability metadata for operational checks."""
    return [
        {
            **{
                name: list(value) if isinstance(value, tuple) else value
                for name, value in asdict(CAPABILITIES[key]).items()
            },
            "definition_contract_version": "1",
            "runtime_status": "external_not_verified",
        }
        for key in sorted(CAPABILITIES)
    ]
