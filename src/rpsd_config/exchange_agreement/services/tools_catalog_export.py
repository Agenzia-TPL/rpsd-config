# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Offline authoring adapter for the released Tools inputs, owned by Config."""

import hashlib
import json
import subprocess
from pathlib import Path

from django.core.exceptions import ValidationError
from pydantic import Field
from rpsd_core.config_input import load
from rpsd_core.validation_rules.export import used_namespaces
from rpsd_core.validation_rules.loader import load_rules
from rpsd_core.validation_rules.models import DbtRule, XPathRule

from rpsd_config.exchange_agreement.services.catalog_contract import (
    CatalogDataset,
    CatalogDependency,
    CatalogPackage,
    CatalogRecord,
    CatalogRule,
    DatasetRuleRecord,
    ProfileTemplate,
    analyze_package,
    seal_package,
)
from rpsd_config.exchange_agreement.services.formal_definitions import (
    KINDS,
    LANGUAGE_VERSION,
)


class IndicatorMapping(CatalogRecord):
    indicator_code: str
    code: str
    version: str
    execution_engine: str = ""
    execution_reference: str = ""
    artifact_identifier: str = ""
    output_schema: dict = Field(default_factory=dict)
    limitations: list[dict] = Field(default_factory=list)


class RuleMapping(CatalogRecord):
    code: str
    version: str
    execution_reference: str = ""
    failure_policy: str | None = None
    consumers: dict[str, dict] = Field(default_factory=dict)


class ToolsMapping(CatalogRecord):
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    roots: list[str]
    indicators: dict[str, IndicatorMapping]
    datasets: list[CatalogDataset]
    rules: dict[str, RuleMapping] = Field(default_factory=dict)
    extra_rules: list[CatalogRule] = Field(default_factory=list)
    dataset_rules: list[DatasetRuleRecord] = Field(default_factory=list)
    technical_dependencies: list[CatalogDependency] = Field(default_factory=list)
    profile_templates: list[ProfileTemplate] = Field(default_factory=list)


def _parameters(indicator) -> dict:
    properties = {}
    for item in indicator.parameters:
        description = f"{item.description} Fonte: {item.source}"
        if item.unit:
            description += f"; unità: {item.unit}"
        if item.type == "set":
            element = {"type": "string"}
            if item.allowed_values is not None:
                element["enum"] = list(item.allowed_values)
            properties[item.code] = {
                "type": "array",
                "items": element,
                "unique_items": True,
                "description": description,
            }
        else:
            prop = {
                "type": "integer" if item.type == "integer" else "number",
                "description": description,
            }
            if item.type == "percentage":
                prop.update(minimum=0, maximum=100)
            properties[item.code] = prop
    return (
        {
            "schema_version": 2,
            "properties": properties,
            "required": sorted(properties),
            "allow_extra": False,
        }
        if properties
        else {}
    )


def export_tools_catalog(
    source: Path, mapping: ToolsMapping, *, contexts_only: bool = False
) -> CatalogPackage:
    """Read a clean pinned source checkout and produce deterministic JSON metadata."""
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    if result.stdout.strip() != mapping.source_commit:
        raise ValidationError(
            "Il checkout Tools non è sul commit dichiarato dal mapping."
        )
    changed = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "inputs",
            "references",
            "rules",
        ],
        check=False,
    )
    untracked = subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            "inputs",
            "references",
            "rules",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    if untracked.stdout.strip():
        raise ValidationError("I dati Tools contengono file non versionati.")
    if changed.returncode:
        raise ValidationError("I dati Tools differiscono dal commit dichiarato.")
    loaded = load(source / "inputs", source / "references")
    rules = load_rules(source / "rules")
    if not loaded.ok or not rules.ok:
        raise ValidationError([str(i) for i in [*loaded.issues, *rules.issues]])
    inputs = loaded.inputs
    if contexts_only:
        mapping = ToolsMapping(
            source_commit=mapping.source_commit,
            roots=[],
            indicators={},
            datasets=[],
            rules=mapping.rules,
        )
    definitions, dimensions, edges, rule_defs, bindings, exclusions = (
        [],
        [],
        [],
        [],
        [],
        [],
    )
    by_symbol = inputs.indicators
    analysis = inputs.formulas
    needed = set(mapping.indicators)
    for symbol in needed:
        if symbol not in by_symbol:
            raise ValidationError(f"Simbolo assente dal catalogo Tools: {symbol}.")
        missing = set(analysis.closure(symbol)) - needed
        if missing:
            raise ValidationError(
                f"Chiusura non inclusa nel mapping: {sorted(missing)}."
            )
    dataset_map = {(d.source_dataset, d.source_schema): d for d in mapping.datasets}
    if len(dataset_map) != len(mapping.datasets):
        raise ValidationError("Mapping servizio/schema ambiguo.")
    own_codes = set()
    for symbol, target in sorted(mapping.indicators.items()):
        source_item = by_symbol[symbol]
        own = []
        for dimension in inputs.catalog.dimensions:
            flags = {
                "is_carried": symbol in dimension.carried_by,
                "is_monitoring": dimension.name in source_item.dimensions_mon,
                "is_contractual": dimension.name in source_item.dimensions_cds,
            }
            if any(flags.values()):
                own.append(
                    {
                        "code": dimension.code,
                        "allowed_values": None
                        if dimension.values is None
                        else list(dimension.values),
                        **flags,
                    }
                )
                own_codes.add(dimension.code)
        datasets = set()
        limits = list(target.limitations)
        for requirement in inputs.requirements.requirements:
            if symbol not in requirement.consumers:
                continue
            key = (requirement.dataset.value, requirement.dataset_version)
            if key not in dataset_map:
                raise ValidationError(f"Mapping dataset assente: {key}.")
            datasets.add(dataset_map[key].code)
        for parameter in source_item.parameters:
            if parameter.default is not None:
                limits.append(
                    {
                        "code": "parameter_default_review",
                        "parameter": parameter.code,
                        "default": parameter.default,
                        "reason": (
                            "Default sorgente conservato per revisione: "
                            "non applicato come valore contrattuale."
                        ),
                    }
                )
        definitions.append(
            {
                **target.model_dump(),
                "symbol": symbol,
                "name": source_item.name,
                "description": source_item.description
                or source_item.contract_description
                or source_item.name,
                "formula_description": source_item.description
                or source_item.contract_description
                or source_item.name,
                "definition_kind": KINDS[analysis.indicators[symbol].kind],
                "formula_definition": source_item.formula
                or source_item.projection_of
                or "",
                "formula_language_version": LANGUAGE_VERSION,
                "consistency_checks": source_item.consistency_checks or "",
                "consistency_notes": source_item.consistency_notes or "",
                "annual_aggregation_description": source_item.annual_aggregation or "",
                "dimensions": sorted(own, key=lambda d: d["code"]),
                "inputs": sorted(datasets),
                "parameter_schema": _parameters(source_item),
                "limitations": limits,
            }
        )
    definitions_by_symbol = {r["symbol"]: r for r in definitions}
    for dimension in inputs.catalog.dimensions:
        if dimension.code in own_codes:
            dimensions.append(
                {
                    "code": dimension.code,
                    "name": dimension.name,
                    "description": dimension.definition or "",
                    "allowed_values": None
                    if dimension.values is None
                    else list(dimension.values),
                }
            )
    for symbol, target in sorted(mapping.indicators.items()):
        item = analysis.indicators[symbol]
        from rpsd_core.formula_language.ast import refs

        for dependency in item.dependencies:
            required = sorted(
                {
                    f.dimension
                    for ref in refs(item.expression)
                    if ref.code == dependency
                    for f in ref.filters
                }
            )
            edges.append(
                {
                    "dependent": target.code,
                    "prerequisite": mapping.indicators[dependency].code,
                    "origin": "formula",
                    "technical_reason": "",
                    "required_dimensions": required,
                }
            )
    edges.extend(e.model_dump() for e in mapping.technical_dependencies)
    requirements = inputs.requirements_by_code
    dataset_rules = [r.model_dump() for r in mapping.dataset_rules]
    for group in sorted(rules.groups):
        for rule in sorted(rules.groups[group].rules, key=lambda r: r.code):
            requirement = requirements[rule.requirement]
            if isinstance(rule, DbtRule):
                policy = mapping.rules.get(rule.code)
                if policy is None:
                    raise ValidationError(
                        f"Mapping del contesto dbt assente: {rule.code}."
                    )
                refs = sorted(set(requirement.relations) | set(rule.relations))
                document = {
                    "schema_version": "dbt-context-v1",
                    "requirement": requirement.model_dump(mode="json"),
                    "rule": rule.model_dump(mode="json"),
                    "relations": [
                        inputs.relations_by_code[ref].model_dump(
                            mode="json", by_alias=True
                        )
                        for ref in refs
                    ],
                    "notes": ["Contesto editoriale: non genera né esegue un test dbt."],
                    "provenance": {
                        "repository": "https://github.com/Agenzia-TPL/rpsd-tools",
                        "commit": mapping.source_commit,
                        "files": [
                            "inputs/requirements.yaml",
                            "inputs/relations.yaml",
                            "rules/cross-dataset.yaml",
                        ],
                    },
                }
                rule_defs.append(
                    {
                        "code": policy.code,
                        "version": policy.version,
                        "name": rule.name,
                        "description": rule.description,
                        "validation_type": "dbt",
                        "language_version": "1",
                        "definition": json.dumps(
                            document, sort_keys=True, ensure_ascii=False, indent=2
                        ),
                        "options": {},
                        "result_contract": "structured_report",
                        "execution_reference": "",
                    }
                )
                continue
            consumers = sorted(set(requirement.consumers) & needed)
            if not consumers:
                continue
            policy = mapping.rules.get(rule.code)
            spec = dataset_map[(requirement.dataset.value, requirement.dataset_version)]
            if not isinstance(rule, XPathRule) or policy is None:
                limitation = {
                    "code": "unsupported_rule"
                    if not isinstance(rule, XPathRule)
                    else "binding_policy_not_mapped",
                    "rule": rule.code,
                    "requirement": rule.requirement,
                    "consumers": consumers,
                    "reason": (
                        "Regola Python/cross-dataset non rappresentabile nel registry "
                        "Config."
                    )
                    if not isinstance(rule, XPathRule)
                    else "Associazione non definita dal mapping esplicito.",
                }
                exclusions.append(limitation)
                for symbol in consumers:
                    definitions_by_symbol[symbol]["limitations"].append(limitation)
                continue
            rule_defs.append(
                {
                    "code": policy.code,
                    "version": policy.version,
                    "name": rule.name,
                    "description": (
                        f"{rule.description}\n\nTools: requisito {rule.requirement}; "
                        f"severity {rule.severity.value}; "
                        f"revisione {rule.status.value}. "
                        "Policy e impact provengono dal mapping Config, "
                        "non dalla severity."
                    ),
                    "validation_type": "xpath",
                    "language_version": rule.xpath_version,
                    "definition": rule.xpath,
                    "options": {"namespaces": used_namespaces(rule.xpath)},
                    "execution_reference": policy.execution_reference,
                }
            )
            if policy.failure_policy is not None:
                dataset_rules.append(
                    {
                        "specification": spec.code,
                        "rule_code": policy.code,
                        "rule_version": policy.version,
                        "failure_policy": policy.failure_policy,
                    }
                )
            for symbol in consumers:
                consumer = policy.consumers.get(symbol)
                if consumer is None:
                    limitation = {
                        "code": "consumer_policy_not_mapped",
                        "rule": rule.code,
                        "consumers": [symbol],
                        "reason": "Impact non configurato per questo consumatore.",
                    }
                    exclusions.append(limitation)
                    definitions_by_symbol[symbol]["limitations"].append(limitation)
                    continue
                bindings.append(
                    {
                        "indicator_version": mapping.indicators[symbol].code,
                        "specification": spec.code,
                        "rule_code": policy.code,
                        "rule_version": policy.version,
                        **consumer,
                    }
                )
    rule_defs.extend(r.model_dump() for r in mapping.extra_rules)
    files = sorted(
        [
            *source.joinpath("inputs").glob("*.yaml"),
            *source.joinpath("rules").glob("*.yaml"),
            *source.joinpath("references/xsd").glob("*/*/manifest.yaml"),
        ]
    )
    payload = {
        "sources": [
            {
                "repository": "https://github.com/Agenzia-TPL/rpsd-tools",
                "commit": mapping.source_commit,
                "files": {
                    p.relative_to(source).as_posix(): hashlib.sha256(
                        p.read_bytes()
                    ).hexdigest()
                    for p in files
                },
            }
        ],
        "selection": {"roots": mapping.roots, "exclusions": exclusions},
        "dimensions": sorted(dimensions, key=lambda d: d["code"]),
        "indicator_versions": definitions,
        "dependencies": sorted(
            edges, key=lambda e: (e["dependent"], e["prerequisite"])
        ),
        "dataset_bindings": [d.model_dump() for d in mapping.datasets],
        "rule_versions": sorted(rule_defs, key=lambda r: (r["code"], r["version"])),
        "dataset_rules": dataset_rules,
        "indicator_rules": bindings,
        "profile_templates": [p.model_dump() for p in mapping.profile_templates],
        "analysis": {},
    }
    package = seal_package(payload)
    payload["analysis"] = analyze_package(package)
    return seal_package(payload)
