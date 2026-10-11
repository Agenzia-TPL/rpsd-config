# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only inventory and conservative, resumable legacy conversion."""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    DatasetSpecification,
    FragmentValidationRule,
    IndicatorVersion,
    LegacyValidationRuleMapping,
    RequirementFragment,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)


def legacy_source(rule) -> dict:
    """Freeze the complete source semantically, including locator and severity."""
    fragment = rule.requirement_fragment
    return {
        "source_id": rule.pk,
        "fragment_code": fragment.code,
        "dataset_specification_code": fragment.dataset_specification.code,
        "locator_type": fragment.locator_type,
        "result_kind": fragment.result_kind,
        "locator_definition": fragment.locator_definition,
        "rule_type": rule.rule_type,
        "rule_version": rule.rule_version,
        "parameters": rule.parameters,
        "severity": rule.severity,
    }


def source_digest(source: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            source, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def validation_migration_inventory() -> dict:
    """Return counts, dependencies and ambiguous conversions without mutating data."""
    rows = []
    for rule in FragmentValidationRule.objects.select_related(
        "requirement_fragment__dataset_specification"
    ).order_by("pk"):
        source = legacy_source(rule)
        automatic = (
            source["locator_type"] == "xpath"
            and source["rule_type"] == "exists"
            and source["parameters"] == {}
        )
        rows.append(
            {
                "source": source,
                "source_digest": source_digest(source),
                "classification": "migrate" if automatic else "manual_review",
                "reason": "Explicit exists-to-violations conversion"
                if automatic
                else (
                    "Preserve trim/case/set/vacuity semantics in a "
                    "reviewed interpreter definition"
                ),
            }
        )
    return {
        "schema_version": "validation-migration-inventory-v1",
        "counts": {
            "fragments": RequirementFragment.objects.count(),
            "rules": len(rows),
            "indicators": IndicatorVersion.objects.count(),
            "specifications": DatasetSpecification.objects.count(),
            "approved_revisions": ContractConfigurationRevision.objects.filter(
                status="approved"
            ).count(),
        },
        "rules": rows,
        "contract_migration": (
                            "New profiles and authorized revisions required; "
                            "existing snapshots remain untouched"
                        ),
        "cleanup": (
                            "No automatic deletion; historical readers and "
                            "zero consumer references required"
                        ),
    }


@transaction.atomic
def convert_legacy_rules(*, actor, expected_inventory: dict) -> dict:
    """Preserve global exists semantics; flag ambiguous rules for review."""
    require_catalog_admin(actor)
    # Serialize the source rules and recheck the reviewed inventory before writing.
    list(FragmentValidationRule.objects.select_for_update().order_by("pk"))
    current = validation_migration_inventory()
    if current != expected_inventory:
        raise ValidationError(
            "Legacy source changed since inventory; produce a new dry-run."
        )
    converted = 0
    review = 0
    for row in current["rules"]:
        source = row["source"]
        existing = LegacyValidationRuleMapping.objects.filter(
            source_legacy_id=source["source_id"]
        ).first()
        if existing:
            if existing.source_digest != row["source_digest"]:
                raise ValidationError("A previously converted source changed.")
            continue
        if row["classification"] == "manual_review":
            LegacyValidationRuleMapping.objects.create(
                source_legacy_id=source["source_id"],
                source_digest=row["source_digest"],
                source_definition=source,
                status="manual_review",
                reason=row["reason"],
            )
            review += 1
            continue
        locator = source["locator_definition"]
        rule = ValidationRule.objects.create(
            code=f"legacy-rule-{source['source_id']}",
            name=f"Legacy {source['fragment_code']}",
        )
        version = ValidationRuleVersion.objects.create(
            rule=rule,
            version="001",
            name=rule.name,
            description=(
                "Preserves file-global exists semantics; review "
                "indicator entity mapping before adoption"
            ),
            validation_type="xpath",
            language_version="1.0",
            definition="/*[not(" + locator["path"] + ")]",
            options={"namespaces": locator.get("namespaces", {})},
            execution_reference="",
        )
        # Leave as draft: migration must not fabricate a reachable deployment or policy.
        LegacyValidationRuleMapping.objects.create(
            source_legacy_id=source["source_id"],
            source_digest=row["source_digest"],
            source_definition=source,
            rule_version=version,
            status="converted",
            reason=(
                "Definition converted; "
                "deployment/policy/impact/adoption require explicit "
                "review"
            ),
        )
        converted += 1
    return {
        "converted_drafts": converted,
        "manual_review": review,
        "snapshots_modified": 0,
        "rows_deleted": 0,
    }
