# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Pinned CORSE_PDE file requirements; never execute XPath or workflow checks."""

import json
from importlib.resources import files

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
    DatasetVersionRule,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    bind_dataset_rule,
    bind_indicator_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.services.validation_seed import ensure_seed_version

DIMENSIONS = {
    "Linea": "line",
    "Percorso": "route",
    "Fermata": "stop",
    "Arco": "arc",
    "Fascia oraria": "time-band",
    "Tipo Domanda": "demand-type",
    "Contratto": "contract",
    "Veicolo": "vehicle",
}


def load_corse_pde_corpus() -> dict:
    """Read the checked-in transcription, including excluded workflow evidence."""
    resource = files("rpsd_config.exchange_agreement").joinpath("data/corse_pde.json")
    return json.loads(resource.read_text(encoding="utf-8"))


@transaction.atomic
def ensure_corse_pde_demo(
    *, actor, schema_asset: ConfigurationAsset
) -> ProcessingProfileVersion:
    """Publish a file-only fixture profile with an explicitly supplied Lev5 bundle."""
    require_catalog_admin(actor)
    corpus = load_corse_pde_corpus()
    expected_bundle = corpus["bundle"]
    schema_asset.refresh_from_db()
    if (
        not schema_asset.is_active
        or schema_asset.asset_type != "netex_xsd"
        or schema_asset.checksum_sha256 != expected_bundle["sha256"]
        or schema_asset.bundle_manifest.get("entrypoint")
        != expected_bundle["entrypoint"]
    ):
        raise ValidationError(
            "CORSE_PDE requires the active, pinned Lev5 corpus bundle.",
            code="corse_pde_bundle_mismatch",
        )
    load_configuration_asset_content(schema_asset)
    dataset, _ = Dataset.objects.get_or_create(code="netex", defaults={"name": "NeTEx"})
    specification, _ = ensure_seed_version(
        DatasetSpecification,
        code="netex-corse-pde_001",
        defaults={
            "dataset": dataset,
            "version": "corse-pde-001",
            "description": "CORSE_PDE Lev5 file-only fixture; EA workflow excluded",
            "metadata": {
                "format": "xml",
                "source": corpus["source"],
                "excluded_requirements": ["WF-001"],
            },
        },
    )
    link = specification.asset_links.filter(role="validation_schema").first()
    if link is None and specification.status == "draft":
        DatasetSpecificationAsset.objects.create(
            dataset_specification=specification,
            configuration_asset=schema_asset,
            role="validation_schema",
        )
    elif link is None or link.configuration_asset_id != schema_asset.pk:
        raise ValidationError("CORSE_PDE schema association conflicts with the seed.")
    bindings = {}
    for row in corpus["rules"]:
        if row["requirement_type"] == "STATO":
            continue
        identity, _ = ValidationRule.objects.get_or_create(
            code="corse-pde-" + row["code"].lower(), defaults={"name": row["name"]}
        )
        is_schema = row["requirement_type"] == "XSD"
        definition = (
            json.dumps(
                {
                    "asset_code": schema_asset.what,
                    "asset_version": str(schema_asset.version),
                    "entrypoint": expected_bundle["entrypoint"],
                    "bundle_sha256": expected_bundle["sha256"],
                },
                sort_keys=True,
            )
            if is_schema
            else row["definition"]
        )
        namespaces = {"n": "http://www.netex.org.uk/netex"}
        if "xs:" in definition:
            namespaces["xs"] = "http://www.w3.org/2001/XMLSchema"
        version, _ = ensure_seed_version(
            ValidationRuleVersion,
            rule=identity,
            version="001",
            defaults={
                "name": row["name"],
                "validation_type": "xsd_bundle" if is_schema else "xpath",
                "language_version": "1.0" if is_schema else row["language_version"],
                "definition": definition,
                "options": {} if is_schema else {"namespaces": namespaces},
                "result_contract": (
                    "structured_report" if is_schema else "violating_entities"
                ),
                "execution_reference": (
                    "fixture-validators/xsd"
                    if is_schema
                    else "fixture-validators/corse-pde-xpath"
                ),
            },
        )
        if version.status == "draft":
            version = transition_validation_rule(
                version, target_status="published", actor=actor
            )
        if version.status != "published":
            raise ValidationError("CORSE_PDE seed cannot reuse a retired rule version.")
        policy = "reject_import" if is_schema else "indicator_only"
        binding = DatasetVersionRule.objects.filter(
            dataset_specification=specification, rule_version=version
        ).first()
        if binding is None:
            if specification.status != "draft":
                raise ValidationError("Published CORSE_PDE dataset is incomplete.")
            binding = bind_dataset_rule(
                specification=specification,
                rule_version=version,
                import_policy=policy,
                actor=actor,
            )
        elif binding.import_policy != policy:
            raise ValidationError("CORSE_PDE import policy conflicts with the seed.")
        bindings[row["code"]] = binding
    if specification.rule_bindings.count() != len(bindings):
        raise ValidationError("CORSE_PDE dataset has unexpected rule associations.")
    if specification.status == "draft":
        specification = publish_dataset_specification(specification, actor=actor)
    logical, _ = Indicator.objects.get_or_create(
        code="corse-pde-file-checks",
        defaults={
            "name": "CORSE_PDE file requirements (fixture)",
            "description": "CORSE_PDE file compatibility fixture; EA workflow excluded",
        },
    )
    indicator, _ = ensure_seed_version(
        IndicatorVersion,
        code="corse-pde-file-checks_001",
        defaults={
            "indicator": logical,
            "version": "001",
            "description": "File compatibility fixture; WF-001 is not implemented",
            "formula_description": "External CORSE_PDE calculation fixture",
            "execution_engine": "prefect",
            "execution_reference": "fixture-indicators/corse-pde",
            "artifact_identifier": "git:fixture@corse-pde-001",
        },
    )
    for row in corpus["rules"]:
        if row["requirement_type"] in {"STATO", "XSD"}:
            continue
        dimensions = []
        for label in filter(None, (s.strip() for s in row["dimensions"].split(","))):
            dimension, _ = IndicatorDimension.objects.get_or_create(
                code=DIMENSIONS[label], defaults={"name": label}
            )
            dimensions.append(dimension)
        impact = "calculation" if row["blocking"] == "sì" else "dimension"
        binding = indicator.rule_bindings.filter(
            dataset_version_rule=bindings[row["code"]]
        ).first()
        if binding is None and indicator.status == "draft":
            bind_indicator_rule(
                indicator_version=indicator,
                dataset_rule=bindings[row["code"]],
                impact=impact,
                dimensions=dimensions,
                actor=actor,
            )
        elif (
            binding is None
            or binding.impact != impact
            or set(binding.affected_dimensions.values_list("code", flat=True))
            != {d.code for d in dimensions}
        ):
            raise ValidationError("CORSE_PDE indicator composition conflicts.")
    if indicator.rule_bindings.count() != 13:
        raise ValidationError("CORSE_PDE indicator has unexpected rule associations.")
    if indicator.status == "draft":
        indicator = publish_indicator_version(indicator, actor=actor)
    flow, _ = ensure_seed_version(
        InputFlowVersion,
        code="corse-pde-import_001",
        defaults={
            "dataset_specification": specification,
            "version": "001",
            "name": "CORSE_PDE fixture input",
            "description": "External file validation fixture reference",
            "engine": "prefect",
            "deployment_name": "fixture-validators/corse-pde",
            "artifact_identifier": "git:fixture@corse-pde-import-001",
        },
    )
    if flow.status == "draft":
        flow = publish_input_flow_version(flow, actor=actor)
    orchestration, _ = ensure_seed_version(
        OrchestrationFlowVersion,
        code="corse-pde-processing_001",
        defaults={
            "version": "001",
            "name": "CORSE_PDE fixture orchestration",
            "description": "External orchestration fixture reference",
            "engine": "prefect",
            "deployment_name": "fixture-contracts/corse-pde",
            "artifact_identifier": "git:fixture@corse-pde-processing-001",
        },
    )
    if orchestration.status == "draft":
        orchestration = publish_orchestration_flow_version(orchestration, actor=actor)
    profile, _ = ensure_seed_version(
        ProcessingProfileVersion,
        code="corse-pde-file-demo_001",
        defaults={
            "version": "001",
            "name": "CORSE_PDE file validation fixture",
            "description": "Lev5 XSD and 13 XPath checks; EA workflow excluded",
            "orchestration_flow_version": orchestration,
        },
    )
    if profile.status == "draft":
        ProcessingProfileInputFlow.objects.get_or_create(
            processing_profile_version=profile,
            dataset=dataset,
            defaults={"input_flow_version": flow},
        )
        ProcessingProfileIndicatorVersion.objects.get_or_create(
            processing_profile_version=profile,
            indicator_version=indicator,
            defaults={"proposed_by_default": True},
        )
        profile = publish_processing_profile(profile, actor=actor)
    return profile
