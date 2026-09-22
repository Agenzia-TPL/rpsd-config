# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle, serialization and runtime projection for registered flow versions."""

from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    DatasetSpecification,
    InputFlowVersion,
    InputFlowVersionStatusEvent,
    OrchestrationFlowVersion,
    OrchestrationFlowVersionStatusEvent,
)
from rpsd_config.exchange_agreement.services.flow_catalog_registry import (
    validate_flow_executable_references,
    validate_input_compatibility,
    validate_invocation_contract,
)


class FlowCatalogTransitionError(ValueError):
    """Raised when a flow catalog transition is invalid."""


ALLOWED_TRANSITIONS = {
    "draft": {"published", "withdrawn"},
    "published": {"deprecated", "withdrawn"},
    "deprecated": {"withdrawn"},
    "withdrawn": set(),
}


def _validate_common_for_publication(flow) -> None:
    validate_invocation_contract(flow.invocation_contract)
    validate_flow_executable_references(
        engine=flow.engine,
        deployment_name=flow.deployment_name,
        artifact_identifier=flow.artifact_identifier,
        require_complete=True,
    )


@transaction.atomic
def transition_input_flow_version(
    flow: InputFlowVersion,
    *,
    target_status: str,
    actor=None,
) -> InputFlowVersion:
    locked = (
        InputFlowVersion.objects.select_for_update()
        .select_related("dataset_specification__dataset")
        .get(pk=flow.pk)
    )
    if target_status not in ALLOWED_TRANSITIONS[locked.status]:
        raise FlowCatalogTransitionError(
            f"Transition {locked.status} -> {target_status} is not allowed."
        )
    if target_status == InputFlowVersion.Status.PUBLISHED:
        if locked.dataset_specification.status != DatasetSpecification.Status.PUBLISHED:
            raise FlowCatalogTransitionError(
                "The dataset specification must be published first."
            )
        locked.full_clean()
        _validate_common_for_publication(locked)
        validate_input_compatibility(
            locked.compatibility,
            expected_what=locked.dataset_specification.dataset.code,
        )

    source_status = locked.status
    update_fields = {"status": target_status, "updated_at": timezone.now()}
    if target_status == InputFlowVersion.Status.PUBLISHED:
        update_fields.update(
            {
                "published_at": timezone.now(),
                "published_by_id": actor.pk if getattr(actor, "pk", None) else None,
            }
        )
    InputFlowVersion.objects.filter(pk=locked.pk).update(**update_fields)
    InputFlowVersionStatusEvent.objects.create(
        input_flow_version=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


@transaction.atomic
def transition_orchestration_flow_version(
    flow: OrchestrationFlowVersion,
    *,
    target_status: str,
    actor=None,
) -> OrchestrationFlowVersion:
    locked = OrchestrationFlowVersion.objects.select_for_update().get(pk=flow.pk)
    if target_status not in ALLOWED_TRANSITIONS[locked.status]:
        raise FlowCatalogTransitionError(
            f"Transition {locked.status} -> {target_status} is not allowed."
        )
    if target_status == OrchestrationFlowVersion.Status.PUBLISHED:
        locked.full_clean()
        _validate_common_for_publication(locked)

    source_status = locked.status
    update_fields = {"status": target_status, "updated_at": timezone.now()}
    if target_status == OrchestrationFlowVersion.Status.PUBLISHED:
        update_fields.update(
            {
                "published_at": timezone.now(),
                "published_by_id": actor.pk if getattr(actor, "pk", None) else None,
            }
        )
    OrchestrationFlowVersion.objects.filter(pk=locked.pk).update(**update_fields)
    OrchestrationFlowVersionStatusEvent.objects.create(
        orchestration_flow_version=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


def publish_input_flow_version(flow, *, actor=None):
    return transition_input_flow_version(
        flow,
        target_status=InputFlowVersion.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_input_flow_version(flow, *, actor=None):
    return transition_input_flow_version(
        flow,
        target_status=InputFlowVersion.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_input_flow_version(flow, *, actor=None):
    return transition_input_flow_version(
        flow,
        target_status=InputFlowVersion.Status.WITHDRAWN,
        actor=actor,
    )


def publish_orchestration_flow_version(flow, *, actor=None):
    return transition_orchestration_flow_version(
        flow,
        target_status=OrchestrationFlowVersion.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_orchestration_flow_version(flow, *, actor=None):
    return transition_orchestration_flow_version(
        flow,
        target_status=OrchestrationFlowVersion.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_orchestration_flow_version(flow, *, actor=None):
    return transition_orchestration_flow_version(
        flow,
        target_status=OrchestrationFlowVersion.Status.WITHDRAWN,
        actor=actor,
    )


def input_flow_runtime_projection(flow: InputFlowVersion) -> dict:
    """Return runtime identifiers without assuming code equals deployment."""

    return {
        "code": flow.code,
        "version": flow.version,
        "deployment_name": flow.deployment_name,
        "artifact_identifier": flow.artifact_identifier,
        "engine": flow.engine,
        "invocation_contract": flow.invocation_contract,
        "compatibility": flow.compatibility,
        "dataset_specification_code": flow.dataset_specification.code,
        "what": flow.dataset_specification.dataset.code,
    }


def orchestration_flow_runtime_projection(flow: OrchestrationFlowVersion) -> dict:
    return {
        "code": flow.code,
        "version": flow.version,
        "deployment_name": flow.deployment_name,
        "artifact_identifier": flow.artifact_identifier,
        "engine": flow.engine,
        "invocation_contract": flow.invocation_contract,
    }
