# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Ownership evidence shared by independent catalog and contract seed scenarios."""

from django.core.exceptions import ValidationError
from django.db import connection

from rpsd_config.exchange_agreement.services.configuration_exports import (
    normalise_export,
)
from rpsd_config.exchange_agreement.services.formal_definitions import digest


def object_fingerprint(obj):
    """Opaque manifest fingerprint: no secrets or model dumps in the report."""
    values = {}
    for field in obj._meta.concrete_fields:
        value = getattr(obj, field.attname)
        if hasattr(value, "name"):
            value = value.name
        values[field.attname] = normalise_export(value)
    return digest(values)


def object_record(obj):
    return {
        "model": obj._meta.label_lower,
        "pk": obj.pk,
        "fingerprint": object_fingerprint(obj),
    }


def validate_manifest_digest(manifest):
    """Check an applied ownership document before interpreting any identities."""
    if (
        not isinstance(manifest, dict)
        or manifest.get("applied") is not True
        or manifest.get("schema_version")
        not in {"tools-seed-manifest-v1", "contract-demo-manifest-v1"}
        or digest({k: v for k, v in manifest.items() if k != "manifest_digest"})
        != manifest.get("manifest_digest")
    ):
        raise ValidationError("Manifest applicato assente o digest non valido.")


def catalog_manifest(plan, *, created, previous=None, scenario=None):
    """Retain initial ownership; shared reuse never becomes ownership of this seed."""
    scenario = scenario or plan.package.package_digest[:20]
    records = {}
    if previous:
        validate_manifest_digest(previous)
        if (
            previous.get("scenario") != scenario
            or previous.get("package_digest") != plan.package.package_digest
        ):
            raise ValidationError(
                "Il manifest appartiene a un altro scenario/pacchetto."
            )
        from rpsd_config.exchange_agreement.services.seed_cleanup import (
            manifest_objects,
        )

        records.update(
            {
                (obj._meta.label_lower, obj.pk): object_record(obj)
                for obj in manifest_objects(previous)
            }
        )
    for obj in created:
        records[(obj._meta.label_lower, obj.pk)] = object_record(obj)
    report = {
        **plan.report,
        "schema_version": "tools-seed-manifest-v1",
        "scenario": scenario,
        "database": connection.settings_dict["NAME"],
        "created": list(records.values()),
        "created_this_run": len(created),
        "reused": [
            object_record(obj)
            for obj in plan.candidates.values()
            if (obj._meta.label_lower, obj.pk) not in records
        ],
        "sources": [s.model_dump() for s in plan.package.sources],
        "rule_sources": [s.model_dump() for s in plan.package.rule_sources],
    }
    report["manifest_digest"] = digest(report)
    return report
