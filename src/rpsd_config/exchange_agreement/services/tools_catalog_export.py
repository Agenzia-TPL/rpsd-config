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
from rpsd_core.validation_rules import checks
from rpsd_core.validation_rules.common import used_namespaces
from rpsd_core.validation_rules.export import build
from rpsd_core.validation_rules.loader import load_fixtures, load_rules
from rpsd_core.validation_rules.models import DbtRule, PythonRule, XPathRule

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
    CORE_COMMIT,
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


class ToolsMapping(CatalogRecord):
    source_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    roots: list[str]
    indicators: dict[str, IndicatorMapping]
    datasets: list[CatalogDataset]
    rule_codes: dict[str, str] = Field(default_factory=dict)
    rule_execution_references: dict[str, str] = Field(default_factory=dict)
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
    if mapping.source_commit != CORE_COMMIT:
        raise ValidationError(
            "Il mapping non corrisponde alla baseline Core corrente: "
            "revisionare versione/commit e rigenerare il pacchetto."
        )
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
            "fixtures",
            "packages/rpsd-core",
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
            "fixtures",
            "packages/rpsd-core",
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
    fixtures, fixture_issues = load_fixtures(source / "fixtures")
    if fixture_issues:
        raise ValidationError([str(i) for i in fixture_issues])
    verified = checks.check_all(
        loaded.inputs, rules, fixtures, source, source / "references"
    )
    if not verified.ok:
        raise ValidationError([str(i) for i in verified.issues])
    exported = build(loaded.inputs, rules, source, source / "references", fixtures)
    verified_rules = {r.code: r for r in exported.rules}
    inputs = loaded.inputs
    if contexts_only:
        mapping = ToolsMapping(
            source_commit=mapping.source_commit,
            roots=[],
            indicators={},
            datasets=[],
            rule_codes=mapping.rule_codes,
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
    rule_sources = []
    for rule in sorted(rules.all_rules(), key=lambda r: r.code):
        requirement = requirements[rule.requirement]
        source_rule = verified_rules[rule.code]
        code = mapping.rule_codes.get(
            rule.code, "tools-" + rule.code.lower().replace("_", "-")
        )
        version = str(rule.version)
        common = {
            "code": code,
            "version": version,
            "name": rule.name,
            "description": rule.description,
            "execution_reference": mapping.rule_execution_references.get(rule.code, ""),
        }
        if isinstance(rule, DbtRule):
            refs = sorted(set(requirement.relations) | set(rule.relations))
            document = {
                "schema_version": "dbt-context-v1",
                "requirement": requirement.model_dump(mode="json"),
                "rule": rule.model_dump(mode="json"),
                "relations": [
                    inputs.relations_by_code[ref].model_dump(mode="json", by_alias=True)
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
                    **common,
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
        else:
            key = (requirement.dataset.value, requirement.dataset_version)
            spec = dataset_map.get(key)
            if spec is None:
                if set(requirement.consumers) & needed:
                    raise ValidationError(
                        f"Mapping dataset assente per {rule.code}: {key}."
                    )
                continue
            if isinstance(rule, XPathRule):
                descriptor = {
                    "validation_type": "xpath",
                    "language_version": rule.xpath_version,
                    "definition": rule.xpath,
                    "options": {"namespaces": used_namespaces(rule.xpath)},
                }
            elif isinstance(rule, PythonRule):
                namespaces = {}
                for path in rule.paths:
                    namespaces.update(used_namespaces(path))
                descriptor = {
                    "validation_type": "python",
                    "language_version": source_rule.core_version,
                    "definition": json.dumps(
                        {
                            "function": rule.function,
                            "paths": list(rule.paths),
                            "namespaces": namespaces,
                            "definition_sha256": source_rule.fingerprint,
                        },
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                    "options": {"python_version": source_rule.python_version},
                }
            else:
                raise ValidationError(
                    f"Tipo di regola Tools non rappresentabile: {rule.code}."
                )
            rule_defs.append({**common, **descriptor})
            dataset_rules.append(
                {
                    "specification": spec.code,
                    "rule_code": code,
                    "rule_version": version,
                    "failure_policy": str(rule.failure_policy),
                }
            )
            for symbol in sorted(set(requirement.consumers) & needed):
                impact = rule.impacts[symbol]
                bindings.append(
                    {
                        "indicator_version": mapping.indicators[symbol].code,
                        "specification": spec.code,
                        "rule_code": code,
                        "rule_version": version,
                        "impact": str(impact.impact),
                        "affected_dimensions": list(impact.dimensions or ()),
                    }
                )
        rule_sources.append(
            {
                "rule_code": code,
                "rule_version": version,
                "origin": "tools",
                "source_code": rule.code,
                "source_version": rule.version,
                "fingerprint": source_rule.fingerprint,
            }
        )
    rule_defs.extend(r.model_dump() for r in mapping.extra_rules)
    rule_sources.extend(
        {"rule_code": r.code, "rule_version": r.version, "origin": "config"}
        for r in mapping.extra_rules
    )
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
        "rule_sources": rule_sources,
        "dataset_rules": sorted(
            dataset_rules,
            key=lambda r: (r["specification"], r["rule_code"], r["rule_version"]),
        ),
        "indicator_rules": bindings,
        "profile_templates": [p.model_dump() for p in mapping.profile_templates],
        "analysis": {},
    }
    package = seal_package(payload)
    payload["analysis"] = analyze_package(package)
    return seal_package(payload)
