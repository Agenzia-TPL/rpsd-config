# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Validation of executable references stored in the flow catalog."""

from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.services.executable_references import (
    validate_artifact_identifier,
)

ENGINE_PREFECT = "prefect"


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
