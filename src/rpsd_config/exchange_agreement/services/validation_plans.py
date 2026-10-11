# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Self-contained validation snapshots and per-dataset plans for external consumers."""

import copy

from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    dependency_impact_contract,
    resolve_indicator_closure,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)

SCHEMA_VERSION = "canonical-json-v2"


def build_validation_snapshot(revision, base: dict) -> dict:
    """Freeze definitions, applications and provenance without local primary keys."""
    configs = list(
        revision.indicator_configurations.select_related(
            "processing_profile_indicator_version__indicator_version__indicator"
        )
    )
    roots = [c.processing_profile_indicator_version.indicator_version for c in configs]
    closure = resolve_indicator_closure(roots)
    uses_target = any(
        v.rule_bindings.exists()
        or v.dataset_inputs.exists()
        or v.dependency_links.exists()
        or bool(v.parameter_schema)
        for v in closure["versions"]
    )
    for selection in revision.input_selections.select_related(
        "processing_profile_input_flow__input_flow_version__dataset_specification"
    ):
        flow = selection.processing_profile_input_flow.input_flow_version
        selected_spec = flow.dataset_specification
        uses_target |= selected_spec.rule_bindings.exists()
    if not uses_target:
        return base
    if any(v.required_fragments.exists() for v in closure["versions"]):
        raise ValidationError(
            "Migrate legacy fragments before publishing a target validation plan.",
            code="validation_plan_not_available",
        )
    result = copy.deepcopy(base)
    result["snapshot_schema_version"] = SCHEMA_VERSION
    selected = {
        c.processing_profile_indicator_version.indicator_version_id: c for c in configs
    }
    dependencies = {
        c.indicator_version_id: c for c in revision.dependency_configurations.all()
    }
    extras = set(dependencies) - ({v.pk for v in closure["versions"]} - set(selected))
    if extras:
        raise ValidationError("Dependency configuration is not an implicit indicator.")
    result["selected_indicators"] = sorted(v.code for v in roots)
    result["effective_indicators"] = []
    result["indicator_configurations"] = []
    for version in closure["versions"]:
        if (
            version.status != "published"
            or version.execution_engine != "prefect"
            or not version.execution_reference
        ):
            raise ValidationError(
                "Effective indicator must be published with a Prefect reference."
            )
        config = selected.get(version.pk) or dependencies.get(version.pk)
        values = {
            field: getattr(config, field) if config is not None else {}
            for field in ("parameters", "thresholds", "aggregation", "penalties")
        }
        try:
            validate_indicator_parameters(
                version.parameter_schema, values["parameters"]
            )
        except ValidationError as exc:
            raise ValidationError(
                f"Indicator {version.code}, required through "
                f"{closure['paths'][version.pk]}: " + " ".join(exc.messages),
                code=getattr(exc, "code", "invalid_indicator_parameters"),
                params={
                    "indicator_version_code": version.code,
                    "dependency_paths": closure["paths"][version.pk],
                },
            ) from exc
        result["effective_indicators"].append(
            {
                "code": version.code,
                "indicator_code": version.indicator.code,
                "version": version.version,
                "role": "selected" if version.pk in selected else "dependency",
                "input_schema": version.input_schema,
                "output_schema": version.output_schema,
                "parameter_schema": version.parameter_schema,
                "execution_reference": version.execution_reference,
                "artifact_identifier": version.artifact_identifier,
            }
        )
        result["indicator_configurations"].append(
            {"indicator_version_code": version.code, **values}
        )
    result["dependency_edges"] = [
        dependency_impact_contract(edge) for edge in closure["edges"]
    ]
    result["indicator_execution_order"] = closure["execution_order"]
    rule_catalog = {}
    selected_specs = {
        item["dataset_specification"]["code"] for item in result["inputs"]
    }
    if any(spec.code not in selected_specs for spec in closure["specifications"]):
        raise ValidationError(
            "Missing required dataset input.", code="missing_profile_input"
        )
    from rpsd_config.exchange_agreement.models import DatasetSpecification

    for item in result["inputs"]:
        spec = DatasetSpecification.objects.get(
            code=item["dataset_specification"]["code"]
        )
        item["assets"] = [
            {
                "asset_type": link.configuration_asset.asset_type,
                "code": link.configuration_asset.what,
                "version": link.configuration_asset.version,
                "checksum": "sha256:" + link.configuration_asset.checksum_sha256,
                "role": link.role,
                "required": link.required,
                "bundle_manifest": copy.deepcopy(
                    link.configuration_asset.bundle_manifest
                ),
                "download_path": (
                    "/exchange_agreement/api/m2m/v3/validation-assets/"
                    f"{link.configuration_asset.asset_type}/"
                    f"{link.configuration_asset.what}/"
                    f"{link.configuration_asset.version}/download"
                ),
            }
            for link in spec.asset_links.select_related("configuration_asset").order_by(
                "configuration_asset__asset_type",
                "configuration_asset__version",
                "role",
            )
        ]
        item["rule_bindings"] = []
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            resolve_dataset_rules,
        )

        for entry in resolve_dataset_rules(
            spec, closure["versions"], paths=closure["paths"]
        ):
            rule = entry["rule"]
            key = (rule["rule_code"], rule["rule_version"])
            rule_catalog[key] = rule
            item["rule_bindings"].append(
                {
                    "rule_code": key[0],
                    "rule_version": key[1],
                    "import_policy": entry["import_policy"],
                    "consumers": entry["consumers"],
                }
            )
    result["validation_rules"] = [rule_catalog[key] for key in sorted(rule_catalog)]
    return result


def validation_plan_from_resolution(resolution) -> dict:
    """Project a dataset subset from the approved snapshot, never from live rules."""
    from rpsd_config.exchange_agreement.services.contract_revisions import (
        canonical_snapshot_checksum,
    )
    from rpsd_config.exchange_agreement.services.ingest_resolution import (
        IngestResolutionError,
    )

    if resolution.snapshot_schema_version != SCHEMA_VERSION:
        raise IngestResolutionError(
            "validation_plan_not_available",
            "Adopt a target revision before requesting validation rules",
        )
    snapshot = resolution.snapshot
    item = next(
        i for i in snapshot["inputs"] if i["dataset_code"] == resolution.data_category
    )
    if not isinstance(item.get("rule_bindings"), list) or not isinstance(
        snapshot.get("validation_rules"), list
    ):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "The snapshot has no valid rule catalog",
        )
    selected = {(b["rule_code"], b["rule_version"]) for b in item["rule_bindings"]}
    rules = [
        rule
        for rule in snapshot["validation_rules"]
        if (rule["rule_code"], rule["rule_version"]) in selected
    ]
    if {(r["rule_code"], r["rule_version"]) for r in rules} != selected:
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "The rule catalog does not cover all bindings",
        )
    plan = {
        "schema_version": "validation-plan-v1",
        "contract_code": resolution.contract.contract_code,
        "configuration_revision_code": resolution.revision.code,
        "snapshot_schema_version": resolution.snapshot_schema_version,
        "snapshot_checksum": resolution.snapshot_checksum,
        "data_category": resolution.data_category,
        "input": copy.deepcopy(item),
        "validation_rules": copy.deepcopy(rules),
        "effective_indicators": copy.deepcopy(snapshot["effective_indicators"]),
        "dependency_edges": copy.deepcopy(snapshot["dependency_edges"]),
        "indicator_execution_order": copy.deepcopy(
            snapshot.get("indicator_execution_order", [])
        ),
        "indicator_configurations": copy.deepcopy(snapshot["indicator_configurations"]),
        "scope": "transfer",
        "orchestration_flow": copy.deepcopy(snapshot["orchestration_flow"]),
    }
    # Digest of the response without its own digest; distinct from full snapshot.
    plan["plan_digest"] = canonical_snapshot_checksum(plan)
    return plan
