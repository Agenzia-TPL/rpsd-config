# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle and deterministic serialization for requirement fragments."""

import json

from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    DatasetSpecification,
    RequirementFragment,
    RequirementFragmentStatusEvent,
)


class RequirementFragmentTransitionError(ValueError):
    """Raised when a requirement-fragment transition is invalid."""


ALLOWED_TRANSITIONS = {
    RequirementFragment.Status.DRAFT: {
        RequirementFragment.Status.PUBLISHED,
        RequirementFragment.Status.WITHDRAWN,
    },
    RequirementFragment.Status.PUBLISHED: {
        RequirementFragment.Status.DEPRECATED,
        RequirementFragment.Status.WITHDRAWN,
    },
    RequirementFragment.Status.DEPRECATED: {
        RequirementFragment.Status.WITHDRAWN,
    },
    RequirementFragment.Status.WITHDRAWN: set(),
}


@transaction.atomic
def transition_requirement_fragment(
    fragment: RequirementFragment,
    *,
    target_status: str,
    actor=None,
) -> RequirementFragment:
    locked = (
        RequirementFragment.objects.select_for_update()
        .select_related("dataset_specification")
        .get(pk=fragment.pk)
    )
    source_status = locked.status
    if target_status not in ALLOWED_TRANSITIONS[source_status]:
        raise RequirementFragmentTransitionError(
            f"Transition {source_status} -> {target_status} is not allowed."
        )
    if (
        target_status == RequirementFragment.Status.PUBLISHED
        and locked.dataset_specification.status != DatasetSpecification.Status.PUBLISHED
    ):
        raise RequirementFragmentTransitionError(
            "The dataset specification must be published first."
        )

    if target_status == RequirementFragment.Status.PUBLISHED:
        locked.full_clean()
        for rule in locked.validation_rules.all():
            rule.full_clean()

    RequirementFragment.objects.filter(pk=locked.pk).update(
        status=target_status,
        updated_at=timezone.now(),
    )
    RequirementFragmentStatusEvent.objects.create(
        requirement_fragment=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


def publish_requirement_fragment(
    fragment: RequirementFragment, *, actor=None
) -> RequirementFragment:
    return transition_requirement_fragment(
        fragment,
        target_status=RequirementFragment.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_requirement_fragment(
    fragment: RequirementFragment, *, actor=None
) -> RequirementFragment:
    return transition_requirement_fragment(
        fragment,
        target_status=RequirementFragment.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_requirement_fragment(
    fragment: RequirementFragment, *, actor=None
) -> RequirementFragment:
    return transition_requirement_fragment(
        fragment,
        target_status=RequirementFragment.Status.WITHDRAWN,
        actor=actor,
    )


def serialize_requirement_fragment(fragment: RequirementFragment) -> dict:
    """Return a stable, execution-free representation of one fragment."""

    rules = [
        {
            "rule_type": rule.rule_type,
            "rule_version": rule.rule_version,
            "severity": rule.severity,
            "parameters": rule.parameters,
        }
        for rule in fragment.validation_rules.all().order_by(
            "rule_type", "rule_version", "id"
        )
    ]
    return {
        "code": fragment.code,
        "name": fragment.name,
        "description": fragment.description,
        "locator_type": fragment.locator_type,
        "result_kind": fragment.result_kind,
        "locator_definition": fragment.locator_definition,
        "status": fragment.status,
        "rules": rules,
    }


def serialize_requirement_fragment_catalog(
    specification: DatasetSpecification,
    *,
    published_only: bool = True,
) -> list[dict]:
    fragments = specification.requirement_fragments.all()
    if published_only:
        fragments = fragments.filter(status=RequirementFragment.Status.PUBLISHED)
    fragments = fragments.prefetch_related("validation_rules").order_by("code", "id")
    return [serialize_requirement_fragment(fragment) for fragment in fragments]


def canonical_requirement_fragment_catalog_json(
    specification: DatasetSpecification,
    *,
    published_only: bool = True,
) -> str:
    return json.dumps(
        serialize_requirement_fragment_catalog(
            specification,
            published_only=published_only,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
