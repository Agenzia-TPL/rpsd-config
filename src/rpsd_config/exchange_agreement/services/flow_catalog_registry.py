# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed schemas for flow catalog references and runtime compatibility."""

from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.services.executable_references import (
    validate_artifact_identifier,
)

ENGINE_PREFECT = "prefect"
TRANSPORT_MESSAGE_TYPE = "TransportMessage"


def transport_message_invocation_contract() -> dict:
    return {"schema_version": 1, "message_type": TRANSPORT_MESSAGE_TYPE}


def validate_invocation_contract(value, *, allow_empty: bool = False) -> dict:
    if value in (None, {}):
        if allow_empty:
            return {}
        raise ValidationError("invocation_contract is required.")
    if not isinstance(value, dict):
        raise ValidationError("invocation_contract must be a JSON object.")
    allowed = {"schema_version", "message_type"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(
            f"invocation_contract contains unknown keys: {', '.join(unknown)}."
        )
    if value.get("schema_version") != 1:
        raise ValidationError("Unsupported invocation_contract schema_version.")
    if value.get("message_type") != TRANSPORT_MESSAGE_TYPE:
        raise ValidationError(
            "Only the existing TransportMessage contract is supported."
        )
    return transport_message_invocation_contract()


def validate_input_compatibility(
    value,
    *,
    expected_what: str,
    allow_empty: bool = False,
) -> dict:
    if value in (None, {}):
        if allow_empty:
            return {}
        raise ValidationError("compatibility is required.")
    if not isinstance(value, dict):
        raise ValidationError("compatibility must be a JSON object.")
    allowed = {"schema_version", "what"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValidationError(
            f"compatibility contains unknown keys: {', '.join(unknown)}."
        )
    if value.get("schema_version") != 1:
        raise ValidationError("Unsupported compatibility schema_version.")
    if value.get("what") != expected_what:
        raise ValidationError(
            "compatibility.what must match the DatasetSpecification dataset code."
        )
    return {"schema_version": 1, "what": expected_what}


def validate_flow_executable_references(
    *,
    engine: str,
    deployment_name: str,
    artifact_identifier: str,
    require_complete: bool,
) -> tuple[str, str]:
    deployment = (deployment_name or "").strip()
    artifact = (artifact_identifier or "").strip()
    if engine != ENGINE_PREFECT:
        raise ValidationError("Only the Prefect execution engine is supported.")
    if require_complete and (not deployment or not artifact):
        raise ValidationError(
            "Published flow versions require deployment_name and artifact_identifier."
        )
    if deployment:
        if len(deployment) > 255 or any(
            character.isspace() for character in deployment
        ):
            raise ValidationError(
                "deployment_name must be at most 255 characters without spaces."
            )
    if artifact:
        artifact = validate_artifact_identifier(artifact)
    return deployment, artifact
