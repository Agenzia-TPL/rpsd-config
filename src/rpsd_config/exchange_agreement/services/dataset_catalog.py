# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Lifecycle operations for the versioned dataset catalog."""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    DatasetSpecification,
    DatasetSpecificationStatusEvent,
)


class DatasetSpecificationTransitionError(ValueError):
    """Raised when a dataset specification transition is not allowed."""

    def __init__(self, message: str, *, code: str = "invalid_dataset_specification"):
        super().__init__(message)
        self.code = code


ALLOWED_TRANSITIONS = {
    DatasetSpecification.Status.DRAFT: {
        DatasetSpecification.Status.PUBLISHED,
        DatasetSpecification.Status.WITHDRAWN,
    },
    DatasetSpecification.Status.PUBLISHED: {
        DatasetSpecification.Status.DEPRECATED,
        DatasetSpecification.Status.WITHDRAWN,
    },
    DatasetSpecification.Status.DEPRECATED: {
        DatasetSpecification.Status.WITHDRAWN,
    },
    DatasetSpecification.Status.WITHDRAWN: set(),
}


def _validate_assets_for_publication(specification: DatasetSpecification) -> None:
    links = specification.asset_links.select_related("configuration_asset")
    for link in links:
        asset = link.configuration_asset
        if link.required and (
            asset.status != ConfigurationAsset.Status.ACTIVE or not asset.is_active
        ):
            raise DatasetSpecificationTransitionError(
                f"Required asset {asset.pk} is not active."
            )


@transaction.atomic
def transition_dataset_specification(
    specification: DatasetSpecification,
    *,
    target_status: str,
    actor=None,
) -> DatasetSpecification:
    """Apply and audit one valid lifecycle transition."""

    locked = (
        DatasetSpecification.objects.select_for_update()
        .select_related("dataset")
        .get(pk=specification.pk)
    )
    source_status = locked.status
    if target_status not in ALLOWED_TRANSITIONS[source_status]:
        raise DatasetSpecificationTransitionError(
            f"Transition {source_status} -> {target_status} is not allowed."
        )

    update_fields = {
        "status": target_status,
        "updated_at": timezone.now(),
    }
    if target_status == DatasetSpecification.Status.PUBLISHED:
        _validate_assets_for_publication(locked)
        try:
            for binding in locked.rule_bindings.all():
                binding.full_clean()
        except ValidationError as exc:
            errors = getattr(exc, "error_dict", {}).values()
            code = next(
                (error.code for group in errors for error in group if error.code),
                getattr(exc, "code", "invalid_dataset_rules"),
            )
            raise DatasetSpecificationTransitionError(
                " ".join(exc.messages), code=code
            ) from exc
        update_fields.update(
            {
                "published_at": timezone.now(),
                "published_by_id": actor.pk if getattr(actor, "pk", None) else None,
            }
        )

    models.QuerySet.update(
        DatasetSpecification.objects.filter(pk=locked.pk), **update_fields
    )
    DatasetSpecificationStatusEvent.objects.create(
        dataset_specification=locked,
        from_status=source_status,
        to_status=target_status,
        changed_by=actor if getattr(actor, "pk", None) else None,
    )
    locked.refresh_from_db()
    return locked


def publish_dataset_specification(
    specification: DatasetSpecification, *, actor=None
) -> DatasetSpecification:
    """Publish a draft dataset specification."""

    return transition_dataset_specification(
        specification,
        target_status=DatasetSpecification.Status.PUBLISHED,
        actor=actor,
    )


def deprecate_dataset_specification(
    specification: DatasetSpecification, *, actor=None
) -> DatasetSpecification:
    """Prevent a published specification from being selected for new uses."""

    return transition_dataset_specification(
        specification,
        target_status=DatasetSpecification.Status.DEPRECATED,
        actor=actor,
    )


def withdraw_dataset_specification(
    specification: DatasetSpecification, *, actor=None
) -> DatasetSpecification:
    """Withdraw an erroneous or no longer valid specification."""

    return transition_dataset_specification(
        specification,
        target_status=DatasetSpecification.Status.WITHDRAWN,
        actor=actor,
    )
