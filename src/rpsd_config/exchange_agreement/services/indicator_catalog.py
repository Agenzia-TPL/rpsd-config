# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle and deterministic serialization for versioned indicators."""

import json

from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Indicator,
    IndicatorVersion,
    IndicatorVersionStatusEvent,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.fragment_registry import (
    validate_locator_definition,
    validate_rule_parameters,
)
from rpsd_config.exchange_agreement.services.indicator_registry import (
    validate_execution_reference_fields,
)
from rpsd_config.exchange_agreement.services.requirement_fragments import (
    serialize_requirement_fragment,
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
    validate_execution_reference_fields(
        engine=version.execution_engine,
        execution_reference=version.execution_reference,
        artifact_identifier=version.artifact_identifier,
        require_complete=True,
    )
    fragments = version.required_fragments.prefetch_related("validation_rules")
    for fragment in fragments:
        if fragment.status != RequirementFragment.Status.PUBLISHED:
            raise IndicatorVersionTransitionError(
                f"Required fragment {fragment} is not published."
            )
        validate_locator_definition(
            fragment.locator_type,
            fragment.result_kind,
            fragment.locator_definition,
        )
        for rule in fragment.validation_rules.all():
            validate_rule_parameters(
                rule.rule_type,
                rule.rule_version,
                fragment.result_kind,
                rule.parameters,
            )


@transaction.atomic
def transition_indicator_version(
    version: IndicatorVersion,
    *,
    target_status: str,
    actor=None,
) -> IndicatorVersion:
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

    IndicatorVersion.objects.filter(pk=locked.pk).update(**update_fields)
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
    fragments = [
        serialize_requirement_fragment(fragment)
        for fragment in version.required_fragments.prefetch_related(
            "validation_rules"
        ).order_by("dataset_specification__code", "code", "id")
    ]
    return {
        "code": version.code,
        "version": version.version,
        "description": version.description,
        "formula_description": version.formula_description,
        "input_contract": version.input_contract,
        "output_contract": version.output_contract,
        "execution_engine": version.execution_engine,
        "execution_reference": version.execution_reference,
        "artifact_identifier": version.artifact_identifier,
        "status": version.status,
        "published_at": (
            version.published_at.isoformat() if version.published_at else None
        ),
        "required_fragments": fragments,
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
