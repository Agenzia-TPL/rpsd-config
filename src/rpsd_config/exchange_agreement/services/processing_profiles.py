# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle, compatibility checks and projections for processing profiles."""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    ProcessingProfileVersionStatusEvent,
)


class ProcessingProfileTransitionError(ValueError):
    """Raised when a processing profile transition or composition is invalid."""

    def __init__(self, message: str, *, code: str = "invalid_processing_profile"):
        super().__init__(message)
        self.code = code


ALLOWED_TRANSITIONS = {
    ProcessingProfileVersion.Status.DRAFT: {
        ProcessingProfileVersion.Status.PUBLISHED,
        ProcessingProfileVersion.Status.WITHDRAWN,
    },
    ProcessingProfileVersion.Status.PUBLISHED: {
        ProcessingProfileVersion.Status.DEPRECATED,
        ProcessingProfileVersion.Status.WITHDRAWN,
    },
    ProcessingProfileVersion.Status.DEPRECATED: {
        ProcessingProfileVersion.Status.WITHDRAWN
    },
    ProcessingProfileVersion.Status.WITHDRAWN: set(),
}


def validate_processing_profile_for_publication(
    profile: ProcessingProfileVersion,
) -> None:
    """Validate the whole profile as one publishable snapshot."""

    if (
        profile.orchestration_flow_version.status
        != OrchestrationFlowVersion.Status.PUBLISHED
    ):
        raise ProcessingProfileTransitionError(
            "The orchestration flow version must be published."
        )

    input_links = list(
        profile.input_flow_links.select_related(
            "dataset",
            "input_flow_version__dataset_specification__dataset",
        ).order_by("dataset__code")
    )
    if not input_links:
        raise ProcessingProfileTransitionError(
            "The processing profile must contain at least one input flow."
        )

    covered_specification_ids: set[int] = set()
    for link in input_links:
        flow = link.input_flow_version
        specification = flow.dataset_specification
        if link.dataset_id != specification.dataset_id:
            raise ProcessingProfileTransitionError(
                f"Input {link.dataset.code} uses a flow for a different dataset."
            )
        if link.dataset.status != Dataset.Status.ACTIVE:
            raise ProcessingProfileTransitionError(
                f"Dataset {link.dataset.code} is not active."
            )
        if flow.status != InputFlowVersion.Status.PUBLISHED:
            raise ProcessingProfileTransitionError(
                f"Input flow {flow.code} is not published."
            )
        if specification.status != DatasetSpecification.Status.PUBLISHED:
            raise ProcessingProfileTransitionError(
                f"Dataset specification {specification.code} is not published."
            )
        covered_specification_ids.add(specification.pk)

    indicator_links = list(
        profile.indicator_version_links.select_related("indicator_version__indicator")
    )
    if not indicator_links:
        raise ProcessingProfileTransitionError(
            "The processing profile must contain at least one indicator version."
        )

    logical_indicator_ids: set[int] = set()
    for link in indicator_links:
        version = link.indicator_version
        if version.indicator_id in logical_indicator_ids:
            raise ProcessingProfileTransitionError(
                "A processing profile cannot expose multiple versions of "
                f"indicator {version.indicator.code}."
            )
        logical_indicator_ids.add(version.indicator_id)
        if version.status != IndicatorVersion.Status.PUBLISHED:
            raise ProcessingProfileTransitionError(
                f"Indicator version {version.code} is not published."
            )
        if version.indicator.status != Indicator.Status.ACTIVE:
            raise ProcessingProfileTransitionError(
                f"Indicator {version.indicator.code} is not active."
            )
    from rpsd_config.exchange_agreement.services.indicator_dependencies import (
        resolve_indicator_closure,
    )
    from rpsd_config.exchange_agreement.services.validation_bindings import (
        validate_profile_input_coverage,
    )

    try:
        closure = resolve_indicator_closure(
            [link.indicator_version for link in indicator_links]
        )
    except ValidationError as exc:
        raise ProcessingProfileTransitionError(
            " ".join(exc.messages),
            code=getattr(exc, "code", "invalid_processing_profile"),
        ) from exc

    try:
        validate_profile_input_coverage(profile, closure["versions"])
    except ValidationError as exc:
        raise ProcessingProfileTransitionError(
            " ".join(exc.messages),
            code=getattr(exc, "code", "invalid_processing_profile"),
        ) from exc


@transaction.atomic
def transition_processing_profile(
    profile: ProcessingProfileVersion,
    *,
    target_status: str,
    actor=None,
) -> ProcessingProfileVersion:
    locked = (
        ProcessingProfileVersion.objects.select_for_update()
        .select_related("orchestration_flow_version")
        .get(pk=profile.pk)
    )
    source_status = locked.status
    if target_status not in ALLOWED_TRANSITIONS[source_status]:
        raise ProcessingProfileTransitionError(
            f"Transition {source_status} -> {target_status} is not allowed."
        )

    update_fields = {"status": target_status, "updated_at": timezone.now()}
    if target_status == ProcessingProfileVersion.Status.PUBLISHED:
        locked.full_clean()
        validate_processing_profile_for_publication(locked)
        update_fields.update(
            {
                "published_at": timezone.now(),
                "published_by_id": actor.pk if getattr(actor, "pk", None) else None,
            }
        )

    models.QuerySet.update(
        ProcessingProfileVersion.objects.filter(pk=locked.pk), **update_fields
    )
    ProcessingProfileVersionStatusEvent.objects.create(
        processing_profile_version=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


def publish_processing_profile(profile, *, actor=None):
    return transition_processing_profile(
        profile,
        target_status=ProcessingProfileVersion.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_processing_profile(profile, *, actor=None):
    return transition_processing_profile(
        profile,
        target_status=ProcessingProfileVersion.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_processing_profile(profile, *, actor=None):
    return transition_processing_profile(
        profile,
        target_status=ProcessingProfileVersion.Status.WITHDRAWN,
        actor=actor,
    )


@transaction.atomic
def duplicate_processing_profile(
    source: ProcessingProfileVersion,
    *,
    code: str,
    version: str,
    name: str | None = None,
    description: str | None = None,
) -> ProcessingProfileVersion:
    source = ProcessingProfileVersion.objects.select_for_update().get(pk=source.pk)
    duplicate = ProcessingProfileVersion.objects.create(
        code=code,
        version=version,
        name=name if name is not None else source.name,
        description=description if description is not None else source.description,
        orchestration_flow_version=source.orchestration_flow_version,
    )
    ProcessingProfileInputFlow.objects.bulk_create(
        [
            ProcessingProfileInputFlow(
                processing_profile_version=duplicate,
                dataset_id=link.dataset_id,
                input_flow_version_id=link.input_flow_version_id,
            )
            for link in source.input_flow_links.all()
        ]
    )
    ProcessingProfileIndicatorVersion.objects.bulk_create(
        [
            ProcessingProfileIndicatorVersion(
                processing_profile_version=duplicate,
                indicator_version_id=link.indicator_version_id,
                proposed_by_default=link.proposed_by_default,
            )
            for link in source.indicator_version_links.all()
        ]
    )
    return duplicate


def serialize_processing_profile(profile: ProcessingProfileVersion) -> dict:
    input_links = profile.input_flow_links.select_related(
        "dataset", "input_flow_version__dataset_specification"
    ).order_by("dataset__code")
    indicator_links = profile.indicator_version_links.select_related(
        "indicator_version__indicator"
    ).order_by("indicator_version__indicator__code", "indicator_version__version")
    return {
        "code": profile.code,
        "version": profile.version,
        "name": profile.name,
        "description": profile.description,
        "status": profile.status,
        "published_at": (
            profile.published_at.isoformat() if profile.published_at else None
        ),
        "inputs": [
            {
                "dataset_code": link.dataset.code,
                "dataset_name": link.dataset.name,
                "dataset_specification_code": (
                    link.input_flow_version.dataset_specification.code
                ),
                "dataset_specification_version": (
                    link.input_flow_version.dataset_specification.version
                ),
            }
            for link in input_links
        ],
        "indicators": [
            {
                "indicator_code": link.indicator_version.indicator.code,
                "indicator_name": link.indicator_version.indicator.name,
                "indicator_version_code": link.indicator_version.code,
                "indicator_version": link.indicator_version.version,
                "proposed_by_default": link.proposed_by_default,
            }
            for link in indicator_links
        ],
    }


def legacy_flow_profile_options(profile: ProcessingProfileVersion) -> dict:
    """Project relational inputs to the legacy v1 options shape.

    The adapter deliberately carries no retention, frequency or scheduling data.
    """

    data_ingestion = {}
    for link in profile.input_flow_links.select_related(
        "dataset", "input_flow_version"
    ).order_by("dataset__code"):
        data_ingestion[link.dataset.code] = {
            "active": True,
            "flow": link.input_flow_version.code,
            "deployment_name": link.input_flow_version.deployment_name,
            "description": link.input_flow_version.description,
        }
    return {
        "general_profile": profile.code,
        "planned_master": {},
        "data_ingestion": data_ingestion,
        "data_retention": {},
    }
