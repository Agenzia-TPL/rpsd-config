# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed validation rules for versioned indicator metadata."""

import re

from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.services.executable_references import (
    validate_artifact_identifier,
)

EXECUTION_PREFECT = "prefect"
EXECUTION_DBT = "dbt"
EXECUTION_EXTERNAL = "external"
SUPPORTED_EXECUTION_ENGINES = (
    EXECUTION_PREFECT,
    EXECUTION_DBT,
    EXECUTION_EXTERNAL,
)

CONTRACT_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]*$")


def validate_technical_contract(value, *, field_name: str) -> dict:
    """Validate a compact reference to an externally defined data contract."""

    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a JSON object.")
    allowed = {"schema_version", "identifier", "description"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(
            f"{field_name} contains unknown keys: {', '.join(unknown)}."
        )
    schema_version = value.get("schema_version", 1)
    if schema_version != 1:
        raise ValidationError(f"Unsupported {field_name} schema_version.")
    identifier = value.get("identifier")
    if (
        not isinstance(identifier, str)
        or len(identifier.strip()) > 255
        or not CONTRACT_IDENTIFIER_RE.fullmatch(identifier.strip())
    ):
        raise ValidationError(
            f"{field_name}.identifier must be a non-empty stable identifier."
        )
    description = value.get("description", "")
    if not isinstance(description, str):
        raise ValidationError(f"{field_name}.description must be a string.")
    return {
        "schema_version": 1,
        "identifier": identifier.strip(),
        "description": description.strip(),
    }


def validate_execution_reference_fields(
    *,
    engine: str,
    execution_reference: str,
    artifact_identifier: str,
    require_complete: bool,
) -> tuple[str, str]:
    reference = (execution_reference or "").strip()
    artifact = (artifact_identifier or "").strip()
    if not engine:
        if reference or artifact:
            raise ValidationError(
                "Execution reference and artifact identifier require an engine."
            )
        return "", ""
    if engine not in SUPPORTED_EXECUTION_ENGINES:
        raise ValidationError(f"Unsupported execution engine: {engine!r}.")
    if require_complete and (not reference or not artifact):
        raise ValidationError(
            "Published versions with an execution engine require both "
            "execution_reference and artifact_identifier."
        )
    if reference and len(reference) > 255:
        raise ValidationError("execution_reference exceeds 255 characters.")
    if artifact:
        artifact = validate_artifact_identifier(artifact)
    return reference, artifact
