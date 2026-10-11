# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle and deterministic serialization for versioned indicators."""

import json

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Indicator,
    IndicatorVersion,
    IndicatorVersionStatusEvent,
)
from rpsd_config.exchange_agreement.services.indicator_registry import (
    validate_execution_reference_fields,
)


class IndicatorVersionTransitionError(ValueError):
    """Raised when an indicator-version transition is invalid."""


ALLOWED_TRANSITIONS = {
    IndicatorVersion.Status.DRAFT: {
        IndicatorVersion.Status.PUBLISHED,
        IndicatorVersion.Status.WITHDRAWN,
    },
    IndicatorVersion.Status.PUBLISHED: {
        IndicatorVersion.Status.DEPRECATED,
        IndicatorVersion.Status.WITHDRAWN,
    },
    IndicatorVersion.Status.DEPRECATED: {IndicatorVersion.Status.WITHDRAWN},
    IndicatorVersion.Status.WITHDRAWN: set(),
}


def _validate_for_publication(version: IndicatorVersion) -> None:
    if version.indicator.status != Indicator.Status.ACTIVE:
        raise IndicatorVersionTransitionError("The logical indicator is not active.")
    if version.execution_engine != "prefect":
        raise ValidationError(
            "Published indicators require a Prefect calculation flow.",
            code="missing_calculation_reference",
        )
    from rpsd_config.exchange_agreement.services.validation_registry import (
        validate_prefect_reference,
    )

    try:
        validate_prefect_reference(version.execution_reference)
    except ValidationError as exc:
        raise ValidationError(
            "A Prefect calculation reference is required.",
            code="missing_calculation_reference",
        ) from exc
    validate_execution_reference_fields(
        engine=version.execution_engine,
        execution_reference=version.execution_reference,
        artifact_identifier=version.artifact_identifier,
        require_complete=True,
    )
    from rpsd_config.exchange_agreement.services.indicator_dependencies import (
        resolve_indicator_closure,
    )

    resolve_indicator_closure([version])


@transaction.atomic
def transition_indicator_version(
    version: IndicatorVersion,
    *,
    target_status: str,
    actor=None,
) -> IndicatorVersion:
    from rpsd_config.exchange_agreement.services.indicator_dependencies import (
        lock_indicator_graph,
    )

    lock_indicator_graph()
    locked = (
        IndicatorVersion.objects.select_for_update()
        .select_related("indicator")
        .get(pk=version.pk)
    )
    source_status = locked.status
    if target_status not in ALLOWED_TRANSITIONS[source_status]:
        raise IndicatorVersionTransitionError(
            f"Transition {source_status} -> {target_status} is not allowed."
        )

    update_fields = {"status": target_status, "updated_at": timezone.now()}
    if target_status == IndicatorVersion.Status.PUBLISHED:
        locked.full_clean()
        _validate_for_publication(locked)
        update_fields.update(
            {
                "published_at": timezone.now(),
                "published_by_id": actor.pk if getattr(actor, "pk", None) else None,
            }
        )

    models.QuerySet.update(
        IndicatorVersion.objects.filter(pk=locked.pk), **update_fields
    )
    IndicatorVersionStatusEvent.objects.create(
        indicator_version=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


def publish_indicator_version(
    version: IndicatorVersion, *, actor=None
) -> IndicatorVersion:
    return transition_indicator_version(
        version,
        target_status=IndicatorVersion.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_indicator_version(
    version: IndicatorVersion, *, actor=None
) -> IndicatorVersion:
    return transition_indicator_version(
        version,
        target_status=IndicatorVersion.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_indicator_version(
    version: IndicatorVersion, *, actor=None
) -> IndicatorVersion:
    return transition_indicator_version(
        version,
        target_status=IndicatorVersion.Status.WITHDRAWN,
        actor=actor,
    )


def serialize_indicator_version(version: IndicatorVersion) -> dict:
    return {
        "code": version.code,
        "version": version.version,
        "description": version.description,
        "formula_description": version.formula_description,
        "input_schema": version.input_schema,
        "input_contract": version.input_schema,
        "output_schema": version.output_schema,
        "output_contract": version.output_schema,
        "parameter_schema": version.parameter_schema,
        "execution_engine": version.execution_engine,
        "execution_reference": version.execution_reference,
        "artifact_identifier": version.artifact_identifier,
        "status": version.status,
        "published_at": (
            version.published_at.isoformat() if version.published_at else None
        ),
        "required_fragments": [],
    }


def serialize_indicator_catalog_entry(indicator: Indicator) -> dict:
    versions = indicator.versions.filter(
        status=IndicatorVersion.Status.PUBLISHED
    ).order_by("version", "code")
    return {
        "code": indicator.code,
        "name": indicator.name,
        "description": indicator.description,
        "status": indicator.status,
        "versions": [serialize_indicator_version(version) for version in versions],
    }


def canonical_indicator_version_json(version: IndicatorVersion) -> str:
    return json.dumps(
        serialize_indicator_version(version),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
