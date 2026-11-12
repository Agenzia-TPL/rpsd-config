# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Draft removal guarded by ownership, audit and external references."""

from django.apps import apps
from django.contrib.admin.models import ADDITION, DELETION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.configuration_exports import (
    consistent_configuration_read,
)
from rpsd_config.exchange_agreement.services.contract_demo import (
    demo_package,
    fixture,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    require_revision_preparer,
)
from rpsd_config.exchange_agreement.services.formal_definitions import digest
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    lock_indicator_graph,
)
from rpsd_config.exchange_agreement.services.seed_manifests import object_fingerprint
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)

# Data/audit/storage/IAM models cannot be smuggled into a cleanup manifest.
MODELS = {
    name.lower()
    for name in (
        "Agency",
        "Company",
        "Lot",
        "Contract",
        "ContractConfigurationRevision",
        "ContractRevisionIndicator",
        "ContractInputSelection",
        "ContractDependencyConfiguration",
        "Dataset",
        "DatasetSpecification",
        "DatasetSpecificationAsset",
        "DatasetVersionRule",
        "Indicator",
        "IndicatorVersion",
        "IndicatorDimension",
        "IndicatorVersionDimension",
        "IndicatorVersionInput",
        "IndicatorVersionDependency",
        "DependencyRequiredDimension",
        "IndicatorVersionRule",
        "IndicatorVersionRuleDimension",
        "ValidationRule",
        "ValidationRuleVersion",
        "ValidationTypeVersion",
        "InputFlowVersion",
        "OrchestrationFlowVersion",
        "ProcessingProfileVersion",
        "ProcessingProfileInputFlow",
        "ProcessingProfileIndicatorVersion",
    )
}


def key(obj):
    return obj._meta.concrete_model._meta.label_lower, obj.pk


def validate_demo_manifest(manifest, *, actor):
    require_catalog_admin(actor)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "contract-demo-manifest-v1"
        or manifest.get("applied") is not True
    ):
        raise ValidationError("Serve il manifest di un seed applicato.")
    if digest(
        {k: v for k, v in manifest.items() if k != "manifest_digest"}
    ) != manifest.get("manifest_digest"):
        raise ValidationError("Digest del manifest non valido.")
    namespace = manifest.get("namespace", "")
    package = demo_package(namespace)
    if package.package_digest != manifest.get("package_digest") or digest(
        fixture()
    ) != manifest.get("fixture_digest"):
        raise ValidationError("Provenienza della fixture non coerente.")
    contract = domain.Contract.objects.get(
        contract_code=manifest["scenario"]["contract_code"]
    )
    if contract.contract_code != "DEMO-" + namespace.upper():
        raise ValidationError("Il contratto non corrisponde al namespace.")
    require_revision_preparer(user=actor, contract=contract)
    result, seen = [], set()
    for record in manifest.get("created", []):
        label = record.get("model", "")
        if label not in {"exchange_agreement." + name for name in MODELS}:
            raise ValidationError("Tipo di oggetto non ammesso nel manifest.")
        model = apps.get_model(label)
        obj = model.objects.get(pk=record["pk"])
        if key(obj) in seen:
            raise ValidationError("Oggetto duplicato nel manifest.")
        seen.add(key(obj))
        provenance = LogEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(obj),
            object_id=str(obj.pk),
            action_flag=ADDITION,
            change_message="Import catalog " + package.package_digest,
        )
        if not provenance.exists() or object_fingerprint(obj) != record["fingerprint"]:
            raise ValidationError(
                f"Record modificato o non creato da questo seed: {label} #{obj.pk}."
            )
        if (
            hasattr(obj, "status")
            and obj._meta.model_name not in {"indicator", "dataset"}
            and obj.status != "draft"
        ):
            raise ValidationError(f"Record non in bozza: {label} #{obj.pk}.")
        result.append(obj)
    return result


def _references(objects):
    """Reject every outside FK, regardless of on_delete; do not cascade silently."""
    own = {key(obj) for obj in objects}
    blockers = []
    for obj in objects:
        for relation in obj._meta.related_objects:
            if not (relation.one_to_many or relation.one_to_one):
                continue
            for related in relation.related_model._default_manager.filter(
                **{relation.field.attname: obj.pk}
            ):
                if key(related) not in own:
                    blockers.append(
                        f"{obj._meta.label} #{obj.pk} richiesto da "
                        f"{related._meta.label} #{related.pk}"
                    )
    codes = {obj.code for obj in objects if isinstance(obj, domain.IndicatorVersion)}
    for version in domain.IndicatorVersion.objects.exclude(
        pk__in=[o.pk for o in objects if isinstance(o, domain.IndicatorVersion)]
    ):
        if codes & set(
            version.formal_verification.get("context_bindings", {}).values()
        ):
            blockers.append(f"Contesto formale conservato: {version.code}")
    for revision in domain.ContractConfigurationRevision.objects.exclude(
        pk__in=[
            o.pk for o in objects if isinstance(o, domain.ContractConfigurationRevision)
        ]
    ).exclude(status="draft"):

        def has_code(value):
            if isinstance(value, str):
                return value in codes
            if isinstance(value, dict):
                return any(has_code(v) for v in value.values())
            if isinstance(value, list):
                return any(has_code(v) for v in value)
            return False

        if has_code(revision.configuration_snapshot):
            blockers.append(f"Snapshot conservato: {revision.code}")
    return sorted(set(blockers))


def _delete_order(objects):
    remaining = {key(obj): obj for obj in objects}
    result = []
    while remaining:
        parents = set()
        for obj in remaining.values():
            for field in obj._meta.fields:
                if field.is_relation and getattr(field, "remote_field", None):
                    parent_key = (
                        field.remote_field.model._meta.label_lower,
                        getattr(obj, field.attname),
                    )
                    if parent_key in remaining:
                        parents.add(parent_key)
        leaves = sorted(set(remaining) - parents)
        if not leaves:
            raise ValidationError(
                "Grafo di pulizia ciclico: nessuna rimozione applicata."
            )
        for leaf in leaves:
            result.append(remaining.pop(leaf))
    return result


def cleanup_demo(manifest, *, actor, apply=False):
    with transaction.atomic() if apply else consistent_configuration_read():
        if apply:
            lock_indicator_graph()
        objects = validate_demo_manifest(manifest, actor=actor)
        if apply:
            for obj in sorted(objects, key=key):
                fresh = type(obj).objects.select_for_update().get(pk=obj.pk)
                if object_fingerprint(fresh) != object_fingerprint(obj):
                    raise ValidationError("Modifica concorrente durante la pulizia.")
        blockers = _references(objects)
        report = {
            "namespace": manifest["namespace"],
            "applied": False,
            "candidates": [{"model": o._meta.label_lower, "pk": o.pk} for o in objects],
            "blockers": blockers,
            "preserved_reused": manifest.get("reused", []),
        }
        if blockers:
            if apply:
                raise ValidationError(blockers)
            return report
        if apply:
            for obj in _delete_order(objects):
                LogEntry.objects.create(
                    user_id=actor.pk,
                    content_type=ContentType.objects.get_for_model(obj),
                    object_id=str(obj.pk),
                    object_repr=str(obj)[:200],
                    action_flag=DELETION,
                    change_message="Cleanup draft demo " + manifest["namespace"],
                )
                obj.delete()
            report["applied"] = True
        return report


def draft_objects(root, *, actor):
    """Only ownership edges, never shared prerequisite/schema/rule identities."""
    root = root._meta.concrete_model.objects.get(pk=root.pk)
    if getattr(root, "status", None) != "draft":
        raise ValidationError("Si possono eliminare solo bozze.")
    if isinstance(root, domain.ContractConfigurationRevision):
        require_revision_preparer(user=actor, contract=root.contract)
    else:
        require_catalog_admin(actor)
    owned_edges = {
        "indicatorversion": {
            "indicatorversioninput",
            "indicatorextrarule",
            "indicatorversionrule",
            "indicatorversiondimension",
            "indicatorversiondependency",
        },
        "datasetspecification": {"datasetspecificationasset", "datasetversionrule"},
        "processingprofileversion": {
            "processingprofileinputflow",
            "processingprofileindicatorversion",
        },
        "contractconfigurationrevision": {
            "contractinputselection",
            "contractrevisionindicator",
            "contractdependencyconfiguration",
        },
        "contractrevisionindicator": {
            "indicatorevaluationthreshold",
            "indicatorpenalty",
        },
        "indicatorevaluationthreshold": {"evaluationthresholddimension"},
        "indicatorpenalty": {"evaluationpenaltydimension"},
        "indicatorversionrule": {"indicatorversionruledimension"},
        "indicatorversiondependency": {"dependencyrequireddimension"},
    }
    objects = {key(root): root}
    pending = [root]
    while pending:
        owner = pending.pop()
        for relation in owner._meta.related_objects:
            if relation.related_model._meta.model_name not in owned_edges.get(
                owner._meta.model_name, set()
            ):
                continue
            if (
                owner._meta.model_name == "indicatorversion"
                and relation.related_model is domain.IndicatorVersionDependency
                and relation.field.name != "dependent"
            ):
                continue
            for child in relation.related_model._default_manager.filter(
                **{relation.field.attname: owner.pk}
            ):
                if key(child) not in objects:
                    objects[key(child)] = child
                    pending.append(child)
    return list(objects.values())


def draft_deletion_plan(root, *, actor):
    objects = draft_objects(root, actor=actor)
    return objects, _references(objects)


@transaction.atomic
def delete_draft(root, *, actor):
    lock_indicator_graph()
    locked = root._meta.concrete_model.objects.select_for_update().get(pk=root.pk)
    objects, blockers = draft_deletion_plan(locked, actor=actor)
    if blockers:
        raise ValidationError(blockers)
    for obj in _delete_order(objects):
        LogEntry.objects.create(
            user_id=actor.pk,
            content_type=ContentType.objects.get_for_model(obj),
            object_id=str(obj.pk),
            object_repr=str(obj)[:200],
            action_flag=DELETION,
            change_message="Delete owned draft configuration",
        )
        obj.delete()
