# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Authorized and atomic lifecycle services for versioned rules."""

import logging
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    ValidationRule,
    ValidationRuleStatusEvent,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope
from rpsd_config.exchange_agreement.services.validation_registry import (
    capability_manifest,
)

ALLOWED_TRANSITIONS = {
    "draft": {"published", "withdrawn"},
    "published": {"deprecated", "withdrawn"},
    "deprecated": {"withdrawn"},
    "withdrawn": set(),
}
logger = logging.getLogger(__name__)


def require_catalog_admin(actor) -> None:
    """Require an authenticated platform administrator, including recovery users."""
    if (
        not getattr(actor, "is_authenticated", False)
        or not getattr(actor, "is_active", False)
        or not resolve_user_agency_scope(actor).is_platform_admin
    ):
        raise PermissionDenied("A platform administrator is required.")


@transaction.atomic
def save_validation_rule(rule: ValidationRule, *, actor) -> ValidationRule:
    """Create or edit the stable identity at the authorized catalog boundary."""
    require_catalog_admin(actor)
    rule.save()
    return rule


@transaction.atomic
def delete_validation_rule_version(version: ValidationRuleVersion, *, actor) -> None:
    """Delete an authorized draft while the model enforces lifecycle locks."""
    require_catalog_admin(actor)
    version.delete()


@transaction.atomic
def save_validation_rule_version(
    version: ValidationRuleVersion, *, actor
) -> ValidationRuleVersion:
    """Create or edit a draft through the authorized catalog boundary."""
    require_catalog_admin(actor)
    version.save()
    return version


@transaction.atomic
def transition_validation_rule(
    version: ValidationRuleVersion, *, target_status: str, actor, reason: str = ""
) -> ValidationRuleVersion:
    """Apply a locally validated lifecycle transition and append its audit."""
    require_catalog_admin(actor)
    locked = ValidationRuleVersion.objects.select_for_update().get(pk=version.pk)
    if target_status not in ALLOWED_TRANSITIONS[locked.status]:
        raise ValidationError(
            "Invalid rule lifecycle transition.", code="invalid_rule_transition"
        )
    values = {"status": target_status, "updated_at": timezone.now()}
    if target_status == "published":
        locked.full_clean()
        locked.validate_for_publication()
        values.update(published_at=timezone.now(), published_by_id=actor.pk)
    elif not reason.strip():
        raise ValidationError(
            "A reason is required for deprecation or withdrawal.",
            code="missing_transition_reason",
        )
    # Explicit internal bypass: only this audited, locked service changes status.
    models.QuerySet.update(ValidationRuleVersion.objects.filter(pk=locked.pk), **values)
    ValidationRuleStatusEvent.objects.create(
        rule_version=locked,
        from_status=locked.status,
        to_status=target_status,
        changed_by=actor,
        reason=reason.strip(),
    )
    locked.refresh_from_db()
    details = {
        "rule_code": locked.rule.code,
        "rule_version": locked.version,
        "rule_status": target_status,
        "correlation_id": str(uuid4()),
    }
    transaction.on_commit(
        lambda: logger.info("Validation rule lifecycle transition", extra=details)
    )
    return locked


def serialize_validation_rule(version: ValidationRuleVersion) -> dict:
    """Serialize a complete definition without database-local identifiers."""
    return {
        "rule_code": version.rule.code,
        "rule_version": version.version,
        "name": version.name,
        "description": version.description,
        "validation_type": version.validation_type,
        "definition": version.definition,
        "language_version": version.language_version,
        "options": version.options,
        "result_contract": version.result_contract,
        "execution_reference": version.execution_reference,
    }


def validation_execution_manifest() -> dict:
    """List published references and capability requirements; no network access."""
    versions = (
        ValidationRuleVersion.objects.filter(status="published")
        .select_related("rule", "validation_type_version")
        .order_by("rule__code", "version")
    )
    return {
        "schema_version": "validation-execution-manifest-v1",
        "capabilities": capability_manifest(),
        "rules": [serialize_validation_rule(v) for v in versions],
    }


def get_validation_type_version(validation_type: str, language_version: str):
    """Resolve an existing supported catalog pair without implicit registration."""
    from rpsd_config.exchange_agreement.models import ValidationTypeVersion

    try:
        return ValidationTypeVersion.objects.get(
            validation_type=validation_type, language_version=language_version
        )
    except ValidationTypeVersion.DoesNotExist as exc:
        raise ValidationError(
            "Select a registered validation type/language pair."
        ) from exc


def ensure_validation_type_catalog(*, using: str = "default") -> None:
    """Seed the supported definition pairs idempotently, independently of runtime."""
    from rpsd_config.exchange_agreement.models import ValidationTypeVersion
    from rpsd_config.exchange_agreement.services.validation_registry import CAPABILITIES

    for capability in CAPABILITIES.values():
        for version in capability.language_versions:
            ValidationTypeVersion.objects.using(using).get_or_create(
                validation_type=capability.validation_type, language_version=version
            )
