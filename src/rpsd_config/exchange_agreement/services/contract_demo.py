# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Pinned, namespaced draft FID authoring scenario; never publishes a record."""

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.catalog_contract import (
    analyze_package,
    load_package,
    package_payload,
    seal_package,
)
from rpsd_config.exchange_agreement.services.catalog_import import (
    apply_catalog_plan,
    plan_catalog,
)
from rpsd_config.exchange_agreement.services.configuration_exports import (
    consistent_configuration_read,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    require_revision_preparer,
)
from rpsd_config.exchange_agreement.services.formal_definitions import digest
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    lock_indicator_graph,
)
from rpsd_config.exchange_agreement.services.seed_manifests import object_record
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)

SEEDS = Path(__file__).resolve().parents[1] / "seed_data"


def fixture():
    return json.loads((SEEDS / "contract_demo/fid.json").read_text())


def demo_package(namespace):
    """Keep formula symbols; map exact versions, including verification context."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,19}", namespace):
        raise ValidationError(
            "Namespace: 1–20 lettere minuscole, cifre o trattini, iniziale alfabetica."
        )
    source = load_package((SEEDS / "tools/catalog.json").read_text())
    spec = fixture()
    if source.package_digest != spec["catalog_digest"]:
        raise ValidationError(
            "Le sorgenti non corrispondono alla fixture demo fissata."
        )
    payload = package_payload(source)
    codes = {v.code: namespace + "-" + v.code for v in source.indicator_versions}
    specs = {v.code: namespace + "-" + v.code for v in source.dataset_bindings}
    for item in payload["indicator_versions"]:
        item["code"], item["version"] = codes[item["code"]], namespace
        item["inputs"] = [specs[code] for code in item["inputs"]]
        item["limitations"] = [
            x
            for x in item["limitations"]
            if x.get("rule") != "NETEX_PASSING_TIMES_INCREASING"
        ]
    for item in payload["dataset_bindings"]:
        item["code"], item["version"] = specs[item["code"]], namespace
    for item in payload["dependencies"]:
        item["dependent"], item["prerequisite"] = (
            codes[item["dependent"]],
            codes[item["prerequisite"]],
        )
    # Global documentary contexts are imported once by the catalog seed.
    payload["rule_versions"] = [
        r for r in payload["rule_versions"] if r["validation_type"] != "dbt"
    ]
    own_rules = {(r["code"], r["version"]) for r in payload["rule_versions"]}
    payload["rule_sources"] = [
        r
        for r in payload["rule_sources"]
        if (r["rule_code"], r["rule_version"]) in own_rules
    ]
    for item in payload["rule_versions"]:
        item["version"] = namespace + "-" + item["version"]
    for item in payload["rule_sources"]:
        item["rule_version"] = namespace + "-" + item["rule_version"]
    for group in ("dataset_rules", "indicator_rules"):
        for item in payload[group]:
            item["specification"] = specs[item["specification"]]
            item["rule_version"] = namespace + "-" + item["rule_version"]
            if group == "indicator_rules":
                item["indicator_version"] = codes[item["indicator_version"]]
    payload["profile_templates"] = []
    package = seal_package(payload)
    payload["analysis"] = analyze_package(package)
    return seal_package(payload)


def _scenario_plan(namespace, actor):
    require_catalog_admin(actor)
    package = demo_package(namespace)
    plan = plan_catalog(package, actor=actor)
    spec = fixture()
    stage = plan.stage
    agency = stage(
        domain.Agency,
        "demo-agency",
        {"agency_key": "demo-" + namespace},
        {"name": "Demo FID " + namespace},
    )
    company = stage(
        domain.Company,
        "demo-company",
        {"name": "Demo TPL " + namespace},
        {"description": "Scenario FID di prova"},
    )
    lot = stage(
        domain.Lot,
        "demo-lot",
        {"agency": agency, "short_description": namespace.upper()},
        {"description": "Lotto demo FID " + namespace},
    )
    contract = stage(
        domain.Contract,
        "demo-contract",
        {"contract_code": "DEMO-" + namespace.upper()},
        {
            "client_agency": agency,
            "contractor_company": company,
            "lot": lot,
            "contract_type": "start",
            "version": 0,
            "start_date": date.fromisoformat(spec["start_date"]),
            "end_date": date.fromisoformat(spec["end_date"]),
            "status": "draft",
        },
    )
    # The existing preparer policy requires a saved agency unless actor is superuser.
    if agency.pk is None and not actor.is_superuser:
        raise PermissionDenied(
            "La nuova agenzia demo richiede un superuser; "
            "nessun ruolo viene assegnato dal seed."
        )
    require_revision_preparer(user=actor, contract=contract)
    orchestrator = stage(
        domain.OrchestrationFlowVersion,
        "demo-orchestrator",
        {"code": namespace + "-orchestrator"},
        {
            "version": namespace,
            "name": "Orchestratore demo",
            "description": "Riferimento dimostrativo, nessun deployment predisposto.",
            "engine": "prefect",
            "deployment_name": "demo/fid",
            "artifact_identifier": "demo:fid",
            "status": "draft",
        },
    )
    profile = stage(
        domain.ProcessingProfileVersion,
        "demo-profile",
        {"code": namespace + "-profile"},
        {
            "version": namespace,
            "name": "FID demo " + namespace,
            "description": "Preparazione in bozza per il validatore.",
            "orchestration_flow_version": orchestrator,
            "status": "draft",
        },
    )
    specifications = {
        obj.code: obj
        for obj in plan.candidates.values()
        if isinstance(obj, domain.DatasetSpecification)
    }
    input_links = []
    for dataset_code in spec["input_datasets"]:
        binding = next(
            b for b in package.dataset_bindings if b.dataset_code == dataset_code
        )
        specification = specifications[binding.code]
        flow = stage(
            domain.InputFlowVersion,
            "demo-flow-" + dataset_code,
            {"code": namespace + "-" + dataset_code + "-input"},
            {
                "dataset_specification": specification,
                "version": namespace,
                "name": dataset_code + " demo input",
                "description": "Processo demo, non distribuito.",
                "engine": "prefect",
                "deployment_name": "demo/" + dataset_code,
                "artifact_identifier": "demo:fid",
                "status": "draft",
            },
        )
        input_links.append(
            stage(
                domain.ProcessingProfileInputFlow,
                "demo-input-" + dataset_code,
                {
                    "processing_profile_version": profile,
                    "dataset": specification.dataset,
                },
                {"input_flow_version": flow},
            )
        )
    by_symbol = {v.symbol: plan.versions[v.code] for v in package.indicator_versions}
    root = by_symbol["FID"]
    selected = stage(
        domain.ProcessingProfileIndicatorVersion,
        "demo-fid-selection",
        {"processing_profile_version": profile, "indicator_version": root},
        {"proposed_by_default": True},
    )
    revision = stage(
        domain.ContractConfigurationRevision,
        "demo-revision",
        {"code": "DEMO-" + namespace.upper() + "-r001"},
        {
            "contract": contract,
            "revision_number": 1,
            "processing_profile_version": profile,
            "valid_from": date.fromisoformat(spec["start_date"]),
            "change_reason": "Fixture FID: dati dimostrativi espliciti",
            "created_by": actor,
            "status": "draft",
        },
    )
    for link in input_links:
        stage(
            domain.ContractInputSelection,
            "demo-revision-input",
            {"revision": revision, "processing_profile_input_flow": link},
            {},
        )
    stage(
        domain.ContractRevisionIndicator,
        "demo-revision-indicator",
        {"revision": revision, "processing_profile_indicator_version": selected},
        {"parameters": {}, "aggregation": {}, "thresholds": {}, "penalties": {}},
    )
    stage(
        domain.ContractDependencyConfiguration,
        "demo-CORSE-PS-values",
        {
            "revision": revision,
            "indicator_version": by_symbol["CORSE_PS"],
        },
        {
            "parameters": spec["parameters_CORSE_PS"],
            "aggregation": {},
            "thresholds": {},
            "penalties": {},
        },
    )
    for obj in plan.candidates.values():
        if (
            hasattr(obj, "status")
            and obj._meta.model_name
            in {"indicatorversion", "datasetspecification", "validationruleversion"}
            and obj.status != "draft"
        ):
            plan.fail(str(obj), "Il namespace contiene versioni non più in bozza.")
    plan.report["fixture_digest"] = digest(spec)
    plan.report["namespace"] = namespace
    plan.report["scenario"] = {
        "contract_code": contract.contract_code,
        "revision_code": revision.code,
        "profile_code": profile.code,
    }
    plan.report["counts"] = dict(
        Counter(row["action"] for row in plan.report["operations"])
    )
    return plan


def seed_contract_demo(*, namespace, actor, apply=False, previous_manifest=None):
    """Dry-run is genuinely read-only; apply replans atomically under the graph lock."""
    if not apply:
        with consistent_configuration_read():
            plan = _scenario_plan(namespace, actor)
            return {
                **plan.report,
                "schema_version": "contract-demo-manifest-v1",
                "applied": False,
            }
    with transaction.atomic():
        lock_indicator_graph()
        plan = _scenario_plan(namespace, actor)
        previous = []
        if previous_manifest:
            from rpsd_config.exchange_agreement.services.draft_cleanup import (
                validate_demo_manifest,
            )

            previous = validate_demo_manifest(previous_manifest, actor=actor)
            if previous_manifest["namespace"] != namespace:
                raise ValidationError("Il manifest appartiene a un namespace diverso.")
        created = list(plan.pending)
        apply_catalog_plan(plan, actor=actor)
        for obj in plan.candidates.values():
            obj.refresh_from_db()
        records = {
            (obj._meta.label_lower, obj.pk): obj for obj in [*previous, *created]
        }
        report = {
            **plan.report,
            "schema_version": "contract-demo-manifest-v1",
            "applied": True,
            "created": [object_record(obj) for obj in records.values()],
            "reused": [
                object_record(obj)
                for obj in plan.candidates.values()
                if (obj._meta.label_lower, obj.pk) not in records
            ],
            "created_this_run": len(created),
            "fixture_digest": digest(fixture()),
            "rule_sources": [r.model_dump() for r in plan.package.rule_sources],
            "sources": [r.model_dump() for r in plan.package.sources],
        }
        report["manifest_digest"] = digest(report)
        return report
