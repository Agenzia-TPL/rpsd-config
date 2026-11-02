# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed producer/consumer contract for an offline, version-pinned catalog."""

import json
from typing import Literal

from django.core.exceptions import ValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rpsd_config.exchange_agreement.services.formal_definitions import (
    CORE_COMMIT,
    LANGUAGE_VERSION,
    analyze_records,
    digest,
)


class CatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Producer(CatalogRecord):
    name: Literal["rpsd-config-tools-adapter"] = "rpsd-config-tools-adapter"
    version: Literal["1"] = "1"
    core_version: Literal["0.2.0"] = "0.2.0"
    core_commit: Literal[CORE_COMMIT] = CORE_COMMIT
    language_version: Literal[LANGUAGE_VERSION] = LANGUAGE_VERSION


class CatalogSource(CatalogRecord):
    repository: str
    commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: dict[str, str]


class CatalogSelection(CatalogRecord):
    roots: list[str]
    exclusions: list[dict] = Field(default_factory=list)


class DimensionRecord(CatalogRecord):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=96)
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    allowed_values: list[str] | None = None


class OwnDimension(CatalogRecord):
    code: str
    allowed_values: list[str] | None = None
    is_carried: bool = False
    is_monitoring: bool = False
    is_contractual: bool = False

    @model_validator(mode="after")
    def usage_required(self):
        if not any((self.is_carried, self.is_monitoring, self.is_contractual)):
            raise ValueError("A dimension requires a declared usage.")
        return self


class CatalogIndicator(CatalogRecord):
    symbol: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$", max_length=96)
    indicator_code: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=96)
    name: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=96)
    version: str = Field(min_length=1, max_length=32)
    description: str = Field(min_length=1)
    formula_description: str = Field(min_length=1)
    definition_kind: Literal["base", "projection", "composite"]
    formula_definition: str = ""
    formula_language_version: Literal[LANGUAGE_VERSION] = LANGUAGE_VERSION
    consistency_checks: str = ""
    consistency_notes: str = ""
    annual_aggregation_description: str = ""
    parameter_schema: dict = Field(default_factory=dict)
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    execution_engine: Literal["", "prefect", "dbt", "external"] = ""
    execution_reference: str = ""
    artifact_identifier: str = ""
    dimensions: list[OwnDimension] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    limitations: list[dict] = Field(default_factory=list)


class CatalogDependency(CatalogRecord):
    dependent: str
    prerequisite: str
    origin: Literal["formula", "technical", "both"]
    technical_reason: str = ""
    required_dimensions: list[str] = Field(default_factory=list)


class AssetReference(CatalogRecord):
    code: str
    version: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal[
        "validation_schema", "constraint", "documentation", "example", "other"
    ]
    required: bool


class CatalogDataset(CatalogRecord):
    source_dataset: str
    source_schema: str
    dataset_code: str
    dataset_name: str
    code: str = Field(min_length=1, max_length=96)
    version: str = Field(min_length=1, max_length=32)
    create: bool = False
    format: Literal["xml", "csv", "xlsx", "txt"] = "xml"
    description: str = ""
    metadata: dict = Field(default_factory=dict)
    assets: list[AssetReference] = Field(default_factory=list)


class CatalogRule(CatalogRecord):
    code: str
    version: str
    name: str
    description: str
    validation_type: str
    language_version: str
    definition: str
    options: dict = Field(default_factory=dict)
    result_contract: Literal["violating_entities", "structured_report"] = (
        "violating_entities"
    )
    execution_reference: str = ""
    artifact_identifier: Literal[""] = ""


class DatasetRuleRecord(CatalogRecord):
    specification: str
    rule_code: str
    rule_version: str
    failure_policy: Literal["reject_import", "warn"]


class IndicatorRuleRecord(CatalogRecord):
    indicator_version: str
    specification: str
    rule_code: str
    rule_version: str
    impact: Literal["calculation", "dimension"]
    affected_dimensions: list[str] = Field(default_factory=list)


class ProfileTemplate(CatalogRecord):
    code: str
    version: str
    name: str
    description: str
    indicators: list[str]
    input_flows: list[str] = Field(default_factory=list)
    orchestration_flow: str | None = None


class CatalogPackage(CatalogRecord):
    schema_version: Literal["config-catalog-import-v1"] = "config-catalog-import-v1"
    producer: Producer = Field(default_factory=Producer)
    sources: list[CatalogSource]
    selection: CatalogSelection
    dimensions: list[DimensionRecord]
    indicator_versions: list[CatalogIndicator]
    dependencies: list[CatalogDependency]
    dataset_bindings: list[CatalogDataset] = Field(default_factory=list)
    rule_versions: list[CatalogRule] = Field(default_factory=list)
    dataset_rules: list[DatasetRuleRecord] = Field(default_factory=list)
    indicator_rules: list[IndicatorRuleRecord] = Field(default_factory=list)
    profile_templates: list[ProfileTemplate] = Field(default_factory=list)
    analysis: dict
    package_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def package_payload(package: CatalogPackage) -> dict:
    """Canonical payload covered by the digest; never the digest itself."""
    return package.model_dump(mode="json", exclude={"package_digest"})


def seal_package(payload: dict) -> CatalogPackage:
    """Validate and seal a producer result with normalized contract defaults."""
    package = CatalogPackage.model_validate({**payload, "package_digest": "0" * 64})
    package.package_digest = digest(package_payload(package))
    return package


def load_package(content: str) -> CatalogPackage:
    """Reject duplicate JSON keys, non-finite numbers and tampered packages."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Non-finite JSON number: {value}")

    package = CatalogPackage.model_validate(
        json.loads(content, object_pairs_hook=unique, parse_constant=nonfinite)
    )
    if digest(package_payload(package)) != package.package_digest:
        raise ValueError("Catalog package digest mismatch.")
    return package


def analysis_records(package: CatalogPackage) -> list[dict]:
    """Normalize the contract to the shared static-verification boundary."""
    records = []
    for item in package.indicator_versions:
        record = item.model_dump(
            mode="json", exclude={"name", "version", "limitations"}
        )
        record["dependencies"] = [
            e.model_dump(exclude={"dependent"})
            for e in package.dependencies
            if e.dependent == item.code
        ]
        records.append(record)
    return records


def analyze_package(package: CatalogPackage) -> dict:
    """Verify each exact graph, allowing different versions in separate graphs."""
    records = analysis_records(package)
    by_code = {r["code"]: r for r in records}
    if len(by_code) != len(records):
        raise ValidationError("Versioni indicatore duplicate nel pacchetto.")
    output = {}
    for record in records:
        collected, active, logical = {}, set(), {}

        def visit(item):
            code = item["code"]
            if code in active:
                raise ValidationError("Dipendenze cicliche nel pacchetto.")
            if code in collected:
                return
            identity = item["indicator_code"]
            if identity in logical and logical[identity] != code:
                raise ValidationError("Versioni logiche incompatibili nella chiusura.")
            logical[identity] = code
            active.add(code)
            for edge in item["dependencies"]:
                if edge["prerequisite"] not in by_code:
                    raise ValidationError(
                        f"Prerequisito assente: {edge['prerequisite']}."
                    )
                visit(by_code[edge["prerequisite"]])
            active.remove(code)
            collected[code] = item

        visit(record)
        mathematical = set(collected)
        # Invariants may mention another indicator without making it an input.
        from rpsd_core.formula_language.ast import refs
        from rpsd_core.formula_language.parser import parse_check

        checked = set()
        while set(collected) - checked:
            for code in sorted(set(collected) - checked):
                item = collected[code]
                checked.add(code)
                for line in item["consistency_checks"].splitlines():
                    if not line.strip():
                        continue
                    for ref in refs(parse_check(line)):
                        if any(r["symbol"] == ref.code for r in collected.values()):
                            continue
                        candidates = [r for r in records if r["symbol"] == ref.code]
                        if len(candidates) != 1:
                            raise ValidationError(
                                "Riferimento di consistenza ambiguo o assente: "
                                f"{ref.code}."
                            )
                        visit(candidates[0])
        for code, item in collected.items():
            item["verification_context"] = code not in mathematical
        analyzed = analyze_records(sorted(collected.values(), key=lambda r: r["code"]))
        output[record["code"]] = analyzed["indicators"][record["code"]]
    return {"schema_version": "indicator-formal-analysis-v1", "indicators": output}
