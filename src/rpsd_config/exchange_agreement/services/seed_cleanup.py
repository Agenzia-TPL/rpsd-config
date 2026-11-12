# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit scenario cleanup, retaining shared objects and lifecycle protections."""

import json
import re

from django.apps import apps
from django.conf import settings
from django.contrib.admin.models import ADDITION, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.configuration_exports import (
    consistent_configuration_read,
    normalise_export,
)
from rpsd_config.exchange_agreement.services.draft_cleanup import (
    MODELS,
    _delete_order,
    key,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    lock_indicator_graph,
)
from rpsd_config.exchange_agreement.services.seed_manifests import (
    object_fingerprint,
    object_record,
    validate_manifest_digest,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)

STATUS_EVENTS = {
    "datasetspecificationstatusevent",
    "indicatorversionstatusevent",
    "inputflowversionstatusevent",
    "orchestrationflowversionstatusevent",
    "processingprofileversionstatusevent",
    "validationrulestatusevent",
    "contractconfigurationrevisionstatusevent",
}


def inventory_seed(package_digests, *, actor, scenario):
    """Read exact ADDITION evidence without a reader for retired seed formats."""
    from rpsd_config.exchange_agreement.services.formal_definitions import digest

    require_catalog_admin(actor)
    if not package_digests or any(
        not re.fullmatch(r"[a-f0-9]{64}", d) for d in package_digests
    ):
        raise ValidationError("Specificare i digest esatti dei pacchetti applicati.")
    records = {}
    allowed = {"exchange_agreement." + name for name in MODELS}
    with consistent_configuration_read():
        entries = (
            LogEntry.objects.filter(
                action_flag=ADDITION,
                change_message__in=["Import catalog " + d for d in package_digests],
            )
            .select_related("content_type")
            .order_by("pk")
        )
        for entry in entries:
            model = entry.content_type.model_class()
            if model is None or model._meta.label_lower not in allowed:
                continue
            obj = model.objects.filter(pk=entry.object_id).first()
            if obj is not None:
                records[key(obj)] = {
                    **object_record(obj),
                    "creation_message": entry.change_message,
                }
        # Composition children belong to their root even when added later in admin.
        # A child created by another seed remains outside this retirement scope.
        selected_messages = {"Import catalog " + d for d in package_digests}
        while True:
            added = False
            for name in sorted(MODELS):
                model = apps.get_model("exchange_agreement", name)
                field = _owned_parent_field(model)
                if field is None:
                    continue
                label = field.related_model._meta.label_lower
                parent_ids = [pk for own_label, pk in records if own_label == label]
                if not parent_ids:
                    continue
                for obj in model.objects.filter(**{field.attname + "__in": parent_ids}):
                    if key(obj) in records:
                        continue
                    other_seed = LogEntry.objects.filter(
                        content_type=ContentType.objects.get_for_model(obj),
                        object_id=str(obj.pk),
                        action_flag=ADDITION,
                        change_message__startswith="Import catalog ",
                    ).exclude(change_message__in=selected_messages)
                    if other_seed.exists():
                        continue
                    records[key(obj)] = {
                        **object_record(obj),
                        "owned_by": {"model": label, "pk": getattr(obj, field.attname)},
                    }
                    added = True
            if not added:
                break
        report = {
            "schema_version": "tools-seed-manifest-v1",
            "applied": True,
            "scenario": scenario,
            "database": connection.settings_dict["NAME"],
            "source_package_digests": sorted(set(package_digests)),
            "created": list(records.values()),
            "reused": [],
        }
        report["manifest_digest"] = digest(report)
        return report


def manifest_objects(manifest):
    """Resolve exact ownership and original ADDITION evidence without legacy readers."""
    validate_manifest_digest(manifest)
    if (
        manifest.get("database", connection.settings_dict["NAME"])
        != connection.settings_dict["NAME"]
    ):
        raise ValidationError("Il manifest appartiene a un altro database.")
    objects, seen = [], set()
    for row in manifest.get("created", []):
        label = row.get("model", "")
        if label not in {"exchange_agreement." + name for name in MODELS}:
            raise ValidationError("Modello non ammesso nel manifest di pulizia.")
        obj = apps.get_model(label).objects.filter(pk=row.get("pk")).first()
        if obj is None or key(obj) in seen:
            raise ValidationError(
                f"Record assente o duplicato: {label} #{row.get('pk')}."
            )
        seen.add(key(obj))
        if "owned_by" in row:
            owner = row["owned_by"]
            if not isinstance(owner, dict) or _owned_parent(obj) != (
                owner.get("model"),
                owner.get("pk"),
            ):
                raise ValidationError(
                    "La relazione di proprietà non corrisponde al DB."
                )
        else:
            message = row.get(
                "creation_message",
                "Import catalog " + manifest.get("package_digest", ""),
            )
            if (
                not re.fullmatch(r"Import catalog [a-f0-9]{64}", message)
                or not LogEntry.objects.filter(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=str(obj.pk),
                    action_flag=ADDITION,
                    change_message=message,
                ).exists()
            ):
                raise ValidationError(
                    f"Provenienza non verificabile: {label} #{obj.pk}."
                )
        if object_fingerprint(obj) != row.get("fingerprint"):
            raise ValidationError(
                f"Record modificato dopo il manifest: {label} #{obj.pk}."
            )
        objects.append(obj)
    rows = {(row["model"], row["pk"]): row for row in manifest["created"]}
    approved_messages = {
        row.get(
            "creation_message", "Import catalog " + manifest.get("package_digest", "")
        )
        for row in rows.values()
        if "owned_by" not in row
    }
    by_key = {key(obj): obj for obj in objects}
    for start in rows:
        if "owned_by" in rows[start]:
            obj = by_key[start]
            if (
                LogEntry.objects.filter(
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=str(obj.pk),
                    action_flag=ADDITION,
                    change_message__startswith="Import catalog ",
                )
                .exclude(change_message__in=approved_messages)
                .exists()
            ):
                raise ValidationError("L'associazione è stata creata da un altro seed.")
        active = set()
        current = start
        while "owned_by" in rows[current]:
            if current in active:
                raise ValidationError("Proprietà ciclica nel manifest.")
            active.add(current)
            parent = rows[current]["owned_by"]
            current = parent["model"], parent["pk"]
            if current not in rows:
                raise ValidationError("Il proprietario non è incluso nel manifest.")
    return objects


def _audit_events(objects):
    result = {}
    for obj in objects:
        for rel in obj._meta.related_objects:
            if rel.related_model._meta.model_name in STATUS_EVENTS:
                for event in rel.related_model.objects.filter(
                    **{rel.field.attname: obj.pk}
                ):
                    result[key(event)] = event
    return list(result.values())


def _required_outside(objects, *, retiring):
    """Map candidate identities referenced by retained ORM or formal JSON data."""
    own = {key(o) for o in objects}
    required = set()
    for obj in objects:
        for rel in obj._meta.related_objects:
            if not (rel.one_to_many or rel.one_to_one):
                continue
            if rel.related_model._meta.model_name in STATUS_EVENTS:
                continue
            if any(
                key(row) not in own
                for row in rel.related_model._default_manager.filter(
                    **{rel.field.attname: obj.pk}
                )
            ):
                required.add(key(obj))
    codes = {
        obj.code: key(obj)
        for obj in objects
        if isinstance(obj, domain.IndicatorVersion)
    }
    for version in domain.IndicatorVersion.objects.exclude(
        pk__in=[o.pk for o in objects if isinstance(o, domain.IndicatorVersion)]
    ):
        for code in (
            set(version.formal_verification.get("context_bindings", {}).values())
            & codes.keys()
        ):
            required.add(codes[code])

    snapshot_codes = {}
    rule_keys = {}
    for obj in objects:
        if hasattr(obj, "code"):
            snapshot_codes.setdefault(obj.code, set()).add(key(obj))
        if isinstance(obj, domain.ValidationRuleVersion):
            rule_keys[(obj.rule.code, obj.version)] = key(obj)

    def referenced(value):
        if isinstance(value, str):
            required.update(snapshot_codes.get(value, set()))
        elif isinstance(value, dict):
            rule_key = value.get("rule_code"), value.get("rule_version")
            if (
                all(isinstance(part, str) for part in rule_key)
                and rule_key in rule_keys
            ):
                required.add(rule_keys[rule_key])
            for v in value.values():
                referenced(v)
        elif isinstance(value, list):
            for v in value:
                referenced(v)

    for revision in domain.ContractConfigurationRevision.objects.exclude(
        pk__in=[
            o.pk for o in objects if isinstance(o, domain.ContractConfigurationRevision)
        ]
    ).exclude(status="draft"):
        referenced(revision.configuration_snapshot)
    return required


def _owned_parent_field(model):
    name = getattr(model, "OWNER_FIELD", None)
    if not name and "revision" in {f.name for f in model._meta.fields}:
        name = "revision"
    return model._meta.get_field(name) if name else None


def _owned_parent(obj):
    field = _owned_parent_field(type(obj))
    if field is not None:
        return field.related_model._meta.label_lower, getattr(obj, field.attname)
    return None


def _delete_exact(obj):
    """One guarded development retirement, without changing model delete permissions."""
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {q(obj._meta.db_table)} WHERE {q(obj._meta.pk.column)} = %s",
            [obj.pk],
        )
        if cursor.rowcount != 1:
            raise ValidationError("Il record è cambiato durante il ritiro.")


def cleanup_seed(
    manifest, *, actor, apply=False, retire_published=False, confirm_database=None
):
    """Plan first; deletion and audit transfer share one locked transaction."""
    require_catalog_admin(actor)
    if retire_published and (
        not settings.DEBUG
        or connection.vendor != "postgresql"
        or connection.alias != "default"
        or (apply and confirm_database != connection.settings_dict["NAME"])
    ):
        raise ValidationError(
            "Il ritiro richiede sviluppo DEBUG, PostgreSQL default "
            "e --confirm-database esatto."
        )
    with transaction.atomic() if apply else consistent_configuration_read():
        if apply:
            lock_indicator_graph()
        objects = manifest_objects(manifest)
        if apply:
            for obj in sorted(objects, key=key):
                fresh = type(obj).objects.select_for_update().get(pk=obj.pk)
                if object_fingerprint(fresh) != object_fingerprint(obj):
                    raise ValidationError("Modifica concorrente: rigenerare il piano.")
        kept = set()
        while True:
            pending = [o for o in objects if key(o) not in kept]
            more = _required_outside(pending, retiring=retire_published)
            more |= {key(o) for o in pending if _owned_parent(o) in kept}
            if not more - kept:
                break
            kept |= more
        candidates = [o for o in objects if key(o) not in kept]
        blockers = []
        for obj in candidates:
            if (
                not retire_published
                and hasattr(obj, "status")
                and obj._meta.model_name not in {"indicator", "dataset"}
                and obj.status != "draft"
            ):
                blockers.append(f"Record non in bozza: {obj._meta.label} #{obj.pk}.")
        scenario = manifest.get("scenario", {})
        contract_code = (
            scenario.get("contract_code") if isinstance(scenario, dict) else None
        )
        for obj in objects:
            if (
                contract_code
                and isinstance(obj, domain.Contract)
                and obj.contract_code == contract_code
                and key(obj) in kept
            ):
                blockers.append(
                    "Il contratto dello scenario è richiesto da dati conservati."
                )
        events = _audit_events(candidates) if retire_published else []
        report = {
            "schema_version": "tools-seed-cleanup-report-v1",
            "applied": False,
            "scenario": scenario,
            "database": connection.settings_dict["NAME"],
            "candidates": [
                {"model": o._meta.label_lower, "pk": o.pk} for o in candidates
            ],
            "preserved_shared": [
                {"model": o._meta.label_lower, "pk": o.pk}
                for o in objects
                if key(o) in kept
            ],
            "preserved_reused": manifest.get("reused", []),
            "blockers": blockers,
            "audit_events_transferred": [
                {"model": o._meta.label_lower, "pk": o.pk} for o in events
            ],
        }
        if blockers:
            if apply:
                raise ValidationError(blockers)
            return report
        if apply:
            for event in events:
                fields = normalise_export(
                    {
                        f.attname: getattr(event, f.attname)
                        for f in event._meta.concrete_fields
                    }
                )
                LogEntry.objects.create(
                    user_id=actor.pk,
                    content_type=ContentType.objects.get_for_model(event),
                    object_id=str(event.pk),
                    object_repr=str(event)[:200],
                    action_flag=DELETION,
                    change_message=json.dumps(
                        {
                            "retired_status_event": {
                                "model": event._meta.label_lower,
                                "pk": event.pk,
                                "fields": fields,
                            }
                        },
                        sort_keys=True,
                    ),
                )
                _delete_exact(event)
            for obj in _delete_order(candidates):
                LogEntry.objects.create(
                    user_id=actor.pk,
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=str(obj.pk),
                    object_repr=str(obj)[:200],
                    action_flag=DELETION,
                    change_message="Cleanup seed "
                    + manifest.get("manifest_digest", ""),
                )
                if retire_published:
                    _delete_exact(obj)
                else:
                    obj.delete()
            report["applied"] = True
        return report
