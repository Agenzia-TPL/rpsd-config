# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only planning and locked, atomic application of a catalog package."""

from collections import Counter

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.http import Http404

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.catalog_contract import (
    CatalogPackage,
    analyze_package,
    package_payload,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
)
from rpsd_config.exchange_agreement.services.formal_definitions import (
    digest,
    validate_dimension_values,
    verify_definition,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    lock_indicator_graph,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)
from rpsd_config.exchange_agreement.services.validation_registry import (
    CAPABILITIES,
    validate_rule_definition,
)


class CatalogImportError(ValidationError):
    """A contextual planning failure with no applied mutation."""

    def __init__(self, report):
        self.report = report
        super().__init__(report["operations"][-1]["reason"])


class CatalogPlan:
    """In-memory model instances; constructing a plan never calls save()."""

    def __init__(self, package: CatalogPackage):
        self.package = package
        self.pending = []
        self.candidates = {}
        self.report = {
            "schema_version": "config-catalog-import-report-v1",
            "package_digest": package.package_digest,
            "applied": False,
            "operations": [],
            "limitations": [
                *package.selection.exclusions,
                *[
                    {"indicator_version": v.code, **limit}
                    for v in package.indicator_versions
                    for limit in v.limitations
                ],
            ],
            "profile_templates": [],
        }

    def fail(self, key, reason, *, action="conflict", field=""):
        self.report["operations"].append(
            {"action": action, "target": key, "field": field, "reason": str(reason)}
        )
        raise CatalogImportError(self.report)

    def stage(self, model, key, lookup, values, *, reference=False):
        cache_key = (
            model,
            tuple(
                (
                    name,
                    id(value)
                    if isinstance(value, models.Model) and not value.pk
                    else value.pk
                    if isinstance(value, models.Model)
                    else value,
                )
                for name, value in sorted(lookup.items())
            ),
        )
        unsaved_parent = any(
            isinstance(v, models.Model) and not v.pk for v in lookup.values()
        )
        found = self.candidates.get(cache_key)
        if found is None and not unsaved_parent:
            found = model.objects.filter(**lookup).first()
        if found:
            for field, value in values.items():
                actual = getattr(found, field)
                equal = (
                    actual.pk == value.pk
                    if isinstance(value, models.Model)
                    else actual == value
                )
                if not equal:
                    self.fail(
                        key, "Identità occupata con contenuto differente.", field=field
                    )
            self.candidates[cache_key] = found
            self.report["operations"].append(
                {
                    "action": "reuse",
                    "target": key,
                    "field": "",
                    "reason": "Contenuto identico.",
                }
            )
            return found
        if reference:
            self.fail(
                key, "Riferimento non presente nel catalogo.", action="unresolved"
            )
        candidate = model(**lookup, **values)
        try:
            from rpsd_config.exchange_agreement.validation_models import (
                FrozenComposition,
            )

            if isinstance(candidate, FrozenComposition):
                owner = getattr(candidate, candidate.OWNER_FIELD)
                if isinstance(owner, domain.IndicatorVersionDependency):
                    owner = owner.dependent
                if isinstance(owner, domain.IndicatorVersionRule):
                    owner = owner.indicator_version
                if owner.pk and getattr(owner, "status", "draft") != "draft":
                    self.fail(
                        key,
                        (
                            "Non è possibile aggiungere relazioni a una versione "
                            "pubblicata."
                        ),
                    )
                for field in candidate._meta.fields:
                    if not field.is_relation and not field.primary_key:
                        field.clean(getattr(candidate, field.attname), candidate)
            else:
                excluded = [f.name for f in candidate._meta.fields if f.is_relation]
                candidate.full_clean(
                    exclude=excluded, validate_unique=False, validate_constraints=False
                )
        except ValidationError as exc:
            self.fail(key, str(exc))
        self.pending.append(candidate)
        self.candidates[cache_key] = candidate
        self.report["operations"].append(
            {
                "action": "create",
                "target": key,
                "field": "",
                "reason": "Nuovo oggetto in bozza.",
            }
        )
        return candidate


def plan_catalog(package: CatalogPackage, *, actor) -> CatalogPlan:
    """Validate metadata and references without DB/storage/outbox writes."""
    require_catalog_admin(actor)
    plan = CatalogPlan(package)
    if digest(package_payload(package)) != package.package_digest:
        plan.fail("package_digest", "Digest del pacchetto non valido.")
    try:
        analysis = analyze_package(package)
    except ValidationError as exc:
        plan.fail("analysis", str(exc), field="analysis")
    if analysis != package.analysis:
        plan.fail(
            "analysis",
            "Analisi ricevuta diversa dall'analisi del nucleo condiviso.",
            field="analysis",
        )
    if not set(package.selection.roots) <= {
        v.symbol for v in package.indicator_versions
    }:
        plan.fail("selection", "Radice non presente nel pacchetto.")
    dimensions, specifications, rules, versions = {}, {}, {}, {}
    seen = set()

    def unique(key):
        if key in seen:
            plan.fail(str(key), "Identità duplicata nel pacchetto.")
        seen.add(key)

    for item in package.dimensions:
        unique(("dimension", item.code))
        validate_dimension_values(item.allowed_values)
        dimensions[item.code] = plan.stage(
            domain.IndicatorDimension,
            item.code,
            {"code": item.code},
            item.model_dump(exclude={"code"}),
        )
    for item in package.dataset_bindings:
        unique(("specification", item.code))
        dataset = plan.stage(
            domain.Dataset,
            item.dataset_code,
            {"code": item.dataset_code},
            {"name": item.dataset_name},
            reference=not item.create,
        )
        values = {"dataset": dataset, "version": item.version, "format": item.format}
        if item.create:
            values.update(description=item.description, metadata=item.metadata)
        spec = plan.stage(
            domain.DatasetSpecification,
            item.code,
            {"code": item.code},
            values,
            reference=not item.create,
        )
        specifications[item.code] = spec
        for ref in item.assets:
            assets = list(
                domain.ConfigurationAsset.objects.filter(
                    what=ref.code, version=ref.version
                )
            )
            if (
                len(assets) != 1
                or assets[0].checksum_sha256 != ref.sha256
                or (ref.required and not assets[0].is_active)
            ):
                plan.fail(
                    item.code,
                    "Asset assente, ambiguo, inattivo o checksum differente: "
                    f"{ref.code}@{ref.version}.",
                    action="unresolved",
                )
            try:
                load_configuration_asset_content(assets[0])
            except (ValidationError, Http404) as exc:
                plan.fail(item.code, str(exc), action="unresolved")
            plan.stage(
                domain.DatasetSpecificationAsset,
                f"{item.code}/{ref.code}",
                {
                    "dataset_specification": spec,
                    "configuration_asset": assets[0],
                    "role": ref.role,
                },
                {"required": ref.required},
                reference=not item.create,
            )
    for item in package.rule_versions:
        unique(("rule", item.code, item.version))
        identity = plan.stage(
            domain.ValidationRule, item.code, {"code": item.code}, {"name": item.name}
        )
        capability = domain.ValidationTypeVersion.objects.filter(
            validation_type=item.validation_type, language_version=item.language_version
        ).first()
        if (
            capability is None
            and item.validation_type in {"dbt", "python"}
            and item.language_version
            in CAPABILITIES[item.validation_type].language_versions
        ):
            capability = plan.stage(
                domain.ValidationTypeVersion,
                f"{item.validation_type}/{item.language_version}",
                {
                    "validation_type": item.validation_type,
                    "language_version": item.language_version,
                },
                {},
            )
        if capability is None or item.validation_type not in CAPABILITIES:
            plan.fail(
                item.code,
                "Coppia tipo/versione di validazione non registrata.",
                action="unresolved",
            )
        values = item.model_dump(
            exclude={
                "code",
                "version",
                "validation_type",
                "language_version",
                "artifact_identifier",
            }
        )
        try:
            validate_rule_definition(
                validation_type=item.validation_type,
                language_version=item.language_version,
                definition=item.definition,
                options=item.options,
                result_contract=item.result_contract,
            )
        except ValidationError as exc:
            plan.fail(item.code, str(exc))
        rules[(item.code, item.version)] = plan.stage(
            domain.ValidationRuleVersion,
            f"{item.code}@{item.version}",
            {"rule": identity, "version": item.version},
            {**values, "validation_type_version": capability},
        )
    for item in package.indicator_versions:
        unique(("indicator-version", item.code))
        identity = plan.stage(
            domain.Indicator,
            item.indicator_code,
            {"code": item.indicator_code},
            {
                "name": item.name,
                "description": item.description,
                "formula_symbol": item.symbol,
            },
        )
        values = item.model_dump(
            exclude={
                "symbol",
                "indicator_code",
                "name",
                "code",
                "dimensions",
                "inputs",
                "limitations",
            }
        )
        versions[item.code] = plan.stage(
            domain.IndicatorVersion,
            item.code,
            {"code": item.code},
            {**values, "indicator": identity},
        )

    def get(mapping, key):
        if key not in mapping:
            plan.fail(
                str(key),
                "Riferimento non dichiarato nel pacchetto.",
                action="unresolved",
            )
        return mapping[key]

    for item in package.indicator_versions:
        version = versions[item.code]
        for dimension in item.dimensions:
            unique(("dimension-link", item.code, dimension.code))
            plan.stage(
                domain.IndicatorVersionDimension,
                f"{item.code}/{dimension.code}",
                {
                    "indicator_version": version,
                    "dimension": get(dimensions, dimension.code),
                },
                dimension.model_dump(exclude={"code"}),
            )
        for specification in item.inputs:
            unique(("input", item.code, specification))
            plan.stage(
                domain.IndicatorVersionInput,
                f"{item.code}/{specification}",
                {
                    "indicator_version": version,
                    "dataset_specification": get(specifications, specification),
                },
                {},
            )
    for item in package.dependencies:
        unique(("edge", item.dependent, item.prerequisite))
        edge = plan.stage(
            domain.IndicatorVersionDependency,
            f"{item.dependent}->{item.prerequisite}",
            {
                "dependent": get(versions, item.dependent),
                "prerequisite": get(versions, item.prerequisite),
            },
            {"origin": item.origin, "technical_reason": item.technical_reason},
        )
        for code in item.required_dimensions:
            unique(("edge-dimension", item.dependent, item.prerequisite, code))
            plan.stage(
                domain.DependencyRequiredDimension,
                f"{item.dependent}->{item.prerequisite}/{code}",
                {"dependency": edge, "dimension": get(dimensions, code)},
                {},
            )
    for item in package.dataset_rules:
        unique(("dataset-rule", item.specification, item.rule_code, item.rule_version))
        spec = get(specifications, item.specification)
        rule = get(rules, (item.rule_code, item.rule_version))
        if spec.format not in CAPABILITIES[rule.validation_type].file_formats:
            plan.fail(item.specification, "Formato incompatibile con la regola.")
        plan.stage(
            domain.DatasetVersionRule,
            f"{item.specification}/{item.rule_code}@{item.rule_version}",
            {"dataset_specification": spec, "rule_version": rule},
            {"failure_policy": item.failure_policy},
        )
    for item in package.indicator_rules:
        unique(
            (
                "indicator-rule",
                item.indicator_version,
                item.specification,
                item.rule_code,
                item.rule_version,
            )
        )
        spec = get(specifications, item.specification)
        rule = get(rules, (item.rule_code, item.rule_version))
        if spec.format not in CAPABILITIES[rule.validation_type].file_formats:
            plan.fail(item.specification, "Formato incompatibile con la regola.")
        if (item.impact == "dimension") != bool(item.affected_dimensions):
            plan.fail(
                item.indicator_version, "Impact e dimensioni interessate incoerenti."
            )
        if not set(item.affected_dimensions) <= set(
            analysis["indicators"][item.indicator_version]["effective_dimensions"]
        ):
            plan.fail(
                item.indicator_version,
                ("Dimensioni interessate non dichiarate nella definizione formale."),
            )
        binding = plan.stage(
            domain.IndicatorVersionRule,
            f"{item.indicator_version}/{item.rule_code}@{item.rule_version}",
            {
                "indicator_version": get(versions, item.indicator_version),
                "dataset_specification": spec,
                "rule_version": rule,
            },
            {"impact": item.impact},
        )
        for code in item.affected_dimensions:
            plan.stage(
                domain.IndicatorVersionRuleDimension,
                f"{item.indicator_version}/{item.rule_code}/{code}",
                {"binding": binding, "dimension": get(dimensions, code)},
                {},
            )
    # Refuse to add relations to an existing identity, or silently retain extras.
    for item in package.indicator_versions:
        existing = versions[item.code]
        if existing.pk:
            expected_edges = {
                (
                    e.prerequisite,
                    e.origin,
                    e.technical_reason,
                    tuple(sorted(e.required_dimensions)),
                )
                for e in package.dependencies
                if e.dependent == item.code
            }
            actual_edges = {
                (
                    e.prerequisite.code,
                    e.origin,
                    e.technical_reason,
                    tuple(sorted(e.required_dimensions.values_list("code", flat=True))),
                )
                for e in existing.dependency_links.select_related("prerequisite")
            }
            expected_rules = {
                (
                    r.specification,
                    r.rule_code,
                    r.rule_version,
                    r.impact,
                    tuple(sorted(r.affected_dimensions)),
                )
                for r in package.indicator_rules
                if r.indicator_version == item.code
            }
            actual_rules = {
                (
                    r.dataset_specification.code,
                    r.rule_version.rule.code,
                    r.rule_version.version,
                    r.impact,
                    tuple(sorted(r.affected_dimensions.values_list("code", flat=True))),
                )
                for r in existing.rule_bindings.select_related(
                    "dataset_specification", "rule_version__rule"
                )
            }
            if (
                expected_edges != actual_edges
                or expected_rules != actual_rules
                or set(item.inputs)
                != set(
                    existing.dataset_inputs.values_list(
                        "dataset_specification__code", flat=True
                    )
                )
                or {d.code for d in item.dimensions}
                != set(
                    existing.dimension_links.values_list("dimension__code", flat=True)
                )
            ):
                plan.fail(item.code, "Composizione esistente differente dal pacchetto.")
    for item in package.dataset_bindings:
        existing = specifications[item.code]
        if item.create and existing.pk:
            expected_assets = {
                (r.code, r.version, r.role, r.required) for r in item.assets
            }
            actual_assets = {
                (
                    r.configuration_asset.what,
                    r.configuration_asset.version,
                    r.role,
                    r.required,
                )
                for r in existing.asset_links.select_related("configuration_asset")
            }
            expected_rules = {
                (r.rule_code, r.rule_version, r.failure_policy)
                for r in package.dataset_rules
                if r.specification == item.code
            }
            actual_rules = {
                (r.rule_version.rule.code, r.rule_version.version, r.failure_policy)
                for r in existing.rule_bindings.select_related("rule_version__rule")
            }
            if expected_assets != actual_assets or expected_rules != actual_rules:
                plan.fail(
                    item.code,
                    "Composizione della specifica esistente differente dal pacchetto.",
                )
    for template in package.profile_templates:
        selected = set(template.indicators)
        if not selected <= set(versions):
            plan.fail(
                template.code,
                "Il template cita indicatori non inclusi nel pacchetto.",
                action="unresolved",
            )
        effective = set(selected)
        while True:
            expanded = effective | {
                edge.prerequisite
                for edge in package.dependencies
                if edge.dependent in effective
            }
            if expanded == effective:
                break
            effective = expanded
        required_specs = {
            spec
            for item in package.indicator_versions
            if item.code in effective
            for spec in item.inputs
        }
        required_specs |= {
            item.specification
            for item in package.indicator_rules
            if item.indicator_version in effective
        }
        flows = list(
            domain.InputFlowVersion.objects.filter(
                code__in=template.input_flows, status="published"
            )
        )
        covered = {flow.dataset_specification.code for flow in flows}
        missing = {
            "unpublished_indicators": sorted(
                code for code in effective if versions[code].status != "published"
            ),
            "input_flow_references": sorted(
                set(template.input_flows) - {flow.code for flow in flows}
            ),
            "specifications_without_input_flow": sorted(required_specs - covered),
            "orchestration_flow": template.orchestration_flow
            if template.orchestration_flow
            and not domain.OrchestrationFlowVersion.objects.filter(
                code=template.orchestration_flow, status="published"
            ).exists()
            else None
            if template.orchestration_flow
            else "not_configured",
        }
        plan.report["profile_templates"].append(
            {
                "code": template.code,
                "state": "pending_publication"
                if any(missing.values())
                else "ready_for_manual_profile",
                "missing": missing,
                "reason": (
                    "Nessun profilo o contratto creato e nessuna "
                    "pubblicazione automatica."
                ),
                "template": template.model_dump(),
            }
        )
    plan.versions = versions
    plan.report["counts"] = dict(
        Counter(op["action"] for op in plan.report["operations"])
    )
    documentary = [r for r in package.rule_versions if r.validation_type == "dbt"]
    if documentary:
        from rpsd_config.exchange_agreement.services.dbt_contexts import (
            load_dbt_context,
        )

        codes = {load_dbt_context(r.definition).rule["code"] for r in documentary}
        plan.report["documentary_contexts"] = [r.code for r in documentary]
        plan.report["previous_dbt_limitations"] = [
            {"indicator_version": version.code, "limitation": limit}
            for version in domain.IndicatorVersion.objects.filter(status="draft")
            for limit in version.formal_verification.get("limitations", [])
            if limit.get("code") == "unsupported_rule" and limit.get("rule") in codes
        ]
    return plan


@transaction.atomic
def apply_catalog(
    package: CatalogPackage, *, actor, previous_manifest=None, scenario=None
) -> dict:
    """Replan under the shared graph lock and apply all or nothing."""
    require_catalog_admin(actor)
    lock_indicator_graph()
    plan = plan_catalog(package, actor=actor)
    created = list(plan.pending)
    apply_catalog_plan(plan, actor=actor)
    for obj in plan.candidates.values():
        obj.refresh_from_db()
    from rpsd_config.exchange_agreement.services.seed_manifests import catalog_manifest

    return catalog_manifest(
        plan, created=created, previous=previous_manifest, scenario=scenario
    )


def apply_catalog_plan(plan, *, actor):
    """Apply an already locked plan, also usable by the authorized demo seed."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("A catalog plan requires a locked atomic transaction.")
    require_catalog_admin(actor)
    package = plan.package
    for obj in plan.pending:
        for field in obj._meta.fields:
            if field.is_relation:
                parent = field.get_cached_value(obj, default=None)
                if parent is not None:
                    setattr(obj, field.attname, parent.pk)
        if isinstance(obj, domain.DatasetVersionRule):
            obj.created_by = actor
        obj.save()
        LogEntry.objects.create(
            user_id=actor.pk,
            content_type=ContentType.objects.get_for_model(obj),
            object_id=str(obj.pk),
            object_repr=str(obj)[:200],
            action_flag=ADDITION,
            change_message=f"Import catalog {package.package_digest}",
        )
    created_versions = {
        obj.code for obj in plan.pending if isinstance(obj, domain.IndicatorVersion)
    }
    for item in package.indicator_versions:
        if item.code in created_versions:
            verify_definition(
                plan.versions[item.code],
                actor=actor,
                provenance={
                    "package_digest": package.package_digest,
                    "sources": [s.model_dump() for s in package.sources],
                },
                limitations=item.limitations,
                context_bindings={v.symbol: v.code for v in package.indicator_versions},
            )
    plan.report["applied"] = True
    return plan.report
