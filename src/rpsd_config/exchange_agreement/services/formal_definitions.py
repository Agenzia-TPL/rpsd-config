# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Static formula verification on metadata, never execution on transferred data."""

import hashlib
import json

from django.core.exceptions import ValidationError
from django.db import models, transaction
from rpsd_core import __version__ as core_version
from rpsd_core.formula_language.analysis import (
    DimensionSource,
    IndicatorSource,
    Vocabulary,
    analyze,
)
from rpsd_core.formula_language.ast import refs
from rpsd_core.formula_language.parser import (
    FormulaSyntaxError,
    parse_check,
    parse_expression,
)

LANGUAGE_VERSION = "rpsd-formula-v1"
SUPPORTED_CORE_VERSION = "0.4.0"
CORE_COMMIT = "c4c268daaa6489bbda607821a1499a568fa0577e"
KINDS = {"base": "base", "proiezione": "projection", "composto": "composite"}
VALUES = {"insieme": "set", "numero": "number"}
FORMAL_FIELDS = (
    "definition_kind",
    "formula_definition",
    "formula_language_version",
    "consistency_checks",
    "consistency_notes",
    "annual_aggregation_description",
)


def digest(value: dict | list) -> str:
    """Stable SHA-256 of JSON metadata, excluding no fields implicitly."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def validate_dimension_values(value) -> None:
    """Distinguish an open domain from a closed, possibly empty domain."""
    if value is not None and (
        not isinstance(value, list)
        or any(not isinstance(v, str) or not v.strip() for v in value)
        or len(value) != len(set(value))
    ):
        raise ValidationError(
            {
                "allowed_values": (
                    "Usare null oppure una lista di stringhe non vuote e uniche."
                )
            }
        )


def validate_formal_fields(version) -> None:
    """Validate draft syntax and protect server-owned verification evidence."""
    errors = {}
    if version.definition_kind:
        if not version.indicator.formula_symbol:
            errors["indicator"] = "Dichiarare il simbolo matematico dell'indicatore."
        if version.definition_kind == "base" and version.formula_definition:
            errors["formula_definition"] = "Una base non ha formula o proiezione."
        if version.definition_kind != "base" and not version.formula_definition.strip():
            errors["formula_definition"] = "Dichiarare l'espressione controllata."
        if version.formula_language_version != LANGUAGE_VERSION:
            errors["formula_language_version"] = (
                f"Versione supportata: {LANGUAGE_VERSION}."
            )
        try:
            if version.formula_definition:
                parse_expression(version.formula_definition)
            for line in version.consistency_checks.splitlines():
                if line.strip():
                    parse_check(line)
        except FormulaSyntaxError as exc:
            errors["formula_definition"] = f"{exc.message} (offset {exc.offset})."
    elif (
        version.formula_definition
        or version.consistency_checks
        or version.formula_language_version
    ):
        errors["definition_kind"] = (
            "Selezionare il tipo della definizione formalizzata."
        )
    original = (
        type(version).objects.filter(pk=version.pk).first() if version.pk else None
    )
    if version.formal_verification != (
        original.formal_verification if original else {}
    ) or version.formula_value_kind != (
        original.formula_value_kind if original else ""
    ):
        errors["__all__"] = (
            "Tipo verificato ed evidenza sono gestiti dal servizio di verifica."
        )
    if errors:
        raise ValidationError(errors)


def analyze_records(records: list[dict]) -> dict:
    """Analyze normalized records using the one pinned rpsd-core grammar."""
    if core_version != SUPPORTED_CORE_VERSION:
        raise ValidationError(
            f"Installare rpsd-core {SUPPORTED_CORE_VERSION} e rigenerare il catalogo."
        )
    formal = [r for r in records if r["definition_kind"]]
    symbols = [r["symbol"] for r in formal]
    if any(not s for s in symbols) or len(symbols) != len(set(symbols)):
        raise ValidationError("Simboli mancanti o ambigui nel grafo delle versioni.")
    domains = {}
    carriers = {}
    by_code = {r["code"]: r for r in records}
    for record in formal:
        if record["formula_language_version"] != LANGUAGE_VERSION:
            raise ValidationError("Linguaggio di formula non supportato.")
        for dimension in record["dimensions"]:
            code, values = dimension["code"], dimension["allowed_values"]
            validate_dimension_values(values)
            if code in domains and domains[code] != values:
                raise ValidationError(f"Domini incompatibili per la dimensione {code}.")
            domains[code] = values
            carriers.setdefault(code, [])
            if dimension["is_carried"]:
                carriers[code].append(record["symbol"])
    vocabulary = Vocabulary(
        indicators=tuple(
            IndicatorSource(
                code=r["symbol"],
                formula=r["formula_definition"] or None
                if r["definition_kind"] == "composite"
                else None,
                projection_of=r["formula_definition"] or None
                if r["definition_kind"] == "projection"
                else None,
                consistency_checks=r["consistency_checks"] or None,
                dimensions=tuple(
                    d["code"]
                    for d in r["dimensions"]
                    if d["is_monitoring"] or d["is_contractual"]
                ),
            )
            for r in formal
        ),
        dimensions=tuple(
            DimensionSource(
                code, None if values is None else tuple(values), tuple(carriers[code])
            )
            for code, values in sorted(domains.items())
        ),
    )
    result = analyze(vocabulary)
    if result.problems:
        raise ValidationError(
            [f"{p.code}.{p.field}: {p.message}" for p in result.problems],
            code="invalid_formal_definition",
        )
    output = {}
    for record in formal:
        item = result.indicators[record["symbol"]]
        if KINDS[item.kind] != record["definition_kind"]:
            raise ValidationError(f"Tipo dichiarato incoerente: {record['code']}.")
        for edge in record["dependencies"]:
            target = by_code[edge["prerequisite"]]
            if target["definition_kind"]:
                analyzed_target = result.indicators[target["symbol"]]
                available = set(analyzed_target.own_dimensions) | {
                    d for d, _ in analyzed_target.inherited_dimensions
                }
                if not set(edge["required_dimensions"]) <= available:
                    raise ValidationError(
                        f"Dimensioni richieste non disponibili: {target['code']}."
                    )
        expected = set(item.dependencies)
        actual = set()
        edges = {e["prerequisite"]: e for e in record["dependencies"]}
        for edge in edges.values():
            target = by_code.get(edge["prerequisite"])
            if target is None:
                raise ValidationError("Prerequisito non risolto.")
            if edge["origin"] in {"formula", "both"}:
                actual.add(target["symbol"])
            if (
                edge["origin"] in {"technical", "both"}
                and not edge["technical_reason"].strip()
            ):
                raise ValidationError("Prerequisito tecnico senza motivazione.")
        if actual != expected:
            raise ValidationError(
                f"Dipendenze matematiche incoerenti per {record['code']}: "
                f"attese {sorted(expected)}, "
                f"dichiarate {sorted(str(x) for x in actual)}.",
                code="formula_dependency_mismatch",
            )
        if item.expression:
            for ref in refs(item.expression):
                target = next(r for r in formal if r["symbol"] == ref.code)
                required = set(edges[target["code"]]["required_dimensions"])
                if not {f.dimension for f in ref.filters} <= required:
                    raise ValidationError(
                        f"Dimensioni del filtro non dichiarate "
                        f"sull'arco verso {ref.code}."
                    )
        effective = sorted(
            set(item.own_dimensions) | {d for d, _ in item.inherited_dimensions}
        )
        for metric in record.get("output_schema", {}).get("metrics", []):
            if not set(metric["dimensions"]) <= set(effective):
                raise ValidationError(
                    f"Dimensioni della metrica non dichiarate: "
                    f"{record['code']}.{metric['code']}."
                )
        output[record["code"]] = {
            "symbol": record["symbol"],
            "kind": KINDS[item.kind],
            "value_kind": VALUES[item.value],
            "dependencies": list(item.dependencies),
            "own_dimensions": sorted(item.own_dimensions),
            "inherited_dimensions": [list(d) for d in item.inherited_dimensions],
            "effective_dimensions": effective,
        }
    return {"schema_version": "indicator-formal-analysis-v1", "indicators": output}


def definition_records(root, *, context_bindings=None) -> list[dict]:
    """Read an exact, cycle-free version graph without resolving latest versions."""
    records, active, logical = {}, set(), {}

    def rule_record(rule):
        return {
            "code": rule.rule.code,
            "version": rule.version,
            "validation_type": rule.validation_type,
            "language_version": rule.language_version,
            "definition": rule.definition,
            "options": rule.options,
            "result_contract": rule.result_contract,
            "execution_reference": rule.execution_reference,
        }

    def specification_record(spec):
        return {
            "code": spec.code,
            "dataset": spec.dataset.code,
            "version": spec.version,
            "format": spec.format,
            "metadata": spec.metadata,
            "assets": [
                {
                    "code": link.configuration_asset.what,
                    "version": link.configuration_asset.version,
                    "sha256": link.configuration_asset.checksum_sha256,
                    "role": link.role,
                    "required": link.required,
                }
                for link in spec.asset_links.select_related(
                    "configuration_asset"
                ).order_by(
                    "configuration_asset__what", "configuration_asset__version", "role"
                )
            ],
            "rules": [
                {
                    "rule": rule_record(link.rule_version),
                    "failure_policy": link.failure_policy,
                }
                for link in spec.rule_bindings.select_related(
                    "rule_version__rule", "rule_version__validation_type_version"
                ).order_by("rule_version__rule__code", "rule_version__version")
            ],
        }

    def visit(version):
        if version.pk in active:
            raise ValidationError(
                "Dipendenze cicliche.", code="cyclic_indicator_dependency"
            )
        if version.pk in records:
            return
        if (
            version.indicator_id in logical
            and logical[version.indicator_id] != version.pk
        ):
            raise ValidationError("Più versioni dello stesso indicatore nel grafo.")
        logical[version.indicator_id] = version.pk
        active.add(version.pk)
        edges = list(
            version.dependency_links.select_related("prerequisite__indicator")
            .prefetch_related("required_dimensions")
            .order_by("prerequisite__code")
        )
        record = {
            "code": version.code,
            "indicator_code": version.indicator.code,
            "symbol": version.indicator.formula_symbol,
            **{field: getattr(version, field) for field in FORMAL_FIELDS},
            "description": version.description,
            "formula_description": version.formula_description,
            "parameter_schema": version.parameter_schema,
            "input_schema": version.input_schema,
            "output_schema": version.output_schema,
            "execution_engine": version.execution_engine,
            "execution_reference": version.execution_reference,
            "artifact_identifier": version.artifact_identifier,
            "dimensions": [
                {
                    "code": d.dimension.code,
                    "allowed_values": d.allowed_values,
                    "is_carried": d.is_carried,
                    "is_monitoring": d.is_monitoring,
                    "is_contractual": d.is_contractual,
                }
                for d in version.dimension_links.select_related("dimension").order_by(
                    "dimension__code"
                )
            ],
            "dependencies": [
                {
                    "prerequisite": e.prerequisite.code,
                    "origin": e.origin,
                    "technical_reason": e.technical_reason,
                    "required_dimensions": sorted(
                        d.code for d in e.required_dimensions.all()
                    ),
                }
                for e in edges
            ],
            "inputs": [
                specification_record(link.dataset_specification)
                for link in version.dataset_inputs.select_related(
                    "dataset_specification__dataset"
                ).order_by("dataset_specification__code")
            ],
            "rule_bindings": [
                {
                    "rule": f"{b.rule_version.rule.code}@{b.rule_version.version}",
                    "rule_definition": rule_record(b.rule_version),
                    "specification": specification_record(b.dataset_specification),
                    "impact": b.impact,
                    "dimensions": sorted(
                        b.affected_dimensions.values_list("code", flat=True)
                    ),
                }
                for b in version.rule_bindings.select_related(
                    "rule_version__rule", "dataset_specification"
                ).order_by(
                    "dataset_specification__code",
                    "rule_version__rule__code",
                    "rule_version__version",
                )
            ],
        }
        for edge in edges:
            visit(edge.prerequisite)
        active.remove(version.pk)
        records[version.pk] = record

    visit(root)
    mathematical = set(records)
    bindings = (
        context_bindings
        if context_bindings is not None
        else root.formal_verification.get("context_bindings", {})
    )
    checked = set()
    while set(records) - checked:
        for key in sorted(set(records) - checked):
            record = records[key]
            checked.add(key)
            for line in record["consistency_checks"].splitlines():
                if not line.strip():
                    continue
                for ref in refs(parse_check(line)):
                    if any(r["symbol"] == ref.code for r in records.values()):
                        continue
                    code = bindings.get(ref.code)
                    target = (
                        type(root)
                        .objects.select_related("indicator")
                        .filter(code=code)
                        .first()
                        if code
                        else None
                    )
                    if target is None or target.indicator.formula_symbol != ref.code:
                        raise ValidationError(
                            f"Contesto di verifica non risolto per {ref.code}: "
                            "importare un mapping esplicito."
                        )
                    visit(target)
    for key, record in records.items():
        record["verification_context"] = key not in mathematical
    return sorted(records.values(), key=lambda r: r["code"])


def evaluate_definition(version, *, context_bindings=None) -> dict:
    """Return a deterministic current analysis and its semantic fingerprint."""
    records = definition_records(version, context_bindings=context_bindings)
    analysis = analyze_records(records)
    return {
        "schema_version": "indicator-formal-verification-v1",
        "core_version": core_version,
        "core_commit": CORE_COMMIT,
        "language_version": LANGUAGE_VERSION,
        "digest": digest(records),
        "context_bindings": {r["symbol"]: r["code"] for r in records},
        "analysis": analysis,
    }


def verification_state(version) -> str:
    """Compute freshness, including modifications of draft prerequisites."""
    if not version.definition_kind:
        return "not_formal"
    if not version.formal_verification:
        return "not_verified"
    try:
        current = evaluate_definition(version)
    except (ValidationError, KeyError, ValueError):
        return "stale"
    proof = version.formal_verification
    compatible = (
        proof.get("core_version") == SUPPORTED_CORE_VERSION
        and proof.get("core_commit") == CORE_COMMIT
    )
    return (
        "current"
        if compatible
        and all(
            proof.get(k) == v
            for k, v in current.items()
            if k not in {"core_version", "core_commit"}
        )
        else "stale"
    )


@transaction.atomic
def verify_definition(
    version, *, actor, provenance=None, limitations=None, context_bindings=None
):
    """Recompute evidence under the publication lock; never trust client flags."""
    from rpsd_config.exchange_agreement.services.indicator_dependencies import (
        lock_indicator_graph,
    )
    from rpsd_config.exchange_agreement.services.validation_catalog import (
        require_catalog_admin,
    )

    require_catalog_admin(actor)
    lock_indicator_graph()
    locked = (
        type(version)
        .objects.select_for_update()
        .select_related("indicator")
        .get(pk=version.pk)
    )
    if locked.status != "draft" or not locked.definition_kind:
        raise ValidationError("Verificare una definizione formalizzata in bozza.")
    proof = evaluate_definition(locked, context_bindings=context_bindings)
    proof["provenance"] = (
        provenance
        if provenance is not None
        else locked.formal_verification.get("provenance", {})
    )
    proof["limitations"] = (
        limitations
        if limitations is not None
        else locked.formal_verification.get("limitations", [])
    )
    models.QuerySet.update(
        type(version).objects.filter(pk=locked.pk),
        formal_verification=proof,
        formula_value_kind=proof["analysis"]["indicators"][locked.code]["value_kind"],
    )
    locked.refresh_from_db()
    return locked


def require_current_verification(version) -> None:
    """Formal versions require current static evidence and resolved requirements."""
    if version.definition_kind:
        if verification_state(version) != "current":
            raise ValidationError(
                "Verifica formale assente o obsoleta: eseguire nuovamente la verifica.",
                code="stale_formal_verification",
            )
        if version.formal_verification.get("limitations"):
            raise ValidationError(
                "Requisiti esclusi o non risolti: consultare il report del catalogo.",
                code="unresolved_catalog_requirements",
            )


def formal_metadata(version) -> dict:
    """Self-contained formal metadata for a frozen configuration or catalog view."""
    if not version.definition_kind:
        return {}
    return {
        "schema_version": "indicator-formal-metadata-v1",
        "root": version.code,
        "definitions": definition_records(version),
        "verification": version.formal_verification,
        "verification_state": verification_state(version),
    }


def validate_frozen_formal_metadata(snapshot: dict) -> None:
    """Check self-contained evidence using frozen JSON only, never live catalogs."""
    from rpsd_config.exchange_agreement.services.ingest_resolution import (
        IngestResolutionError,
    )

    try:
        metadata = snapshot["formal_metadata"]
        effective = {v["code"] for v in snapshot["effective_indicators"]}
        expected = {
            v["code"]
            for v in snapshot["effective_indicators"]
            if v.get("formal_definition")
        }
        if (
            not isinstance(metadata, dict)
            or not metadata
            or set(metadata) != expected
            or not set(metadata) <= effective
        ):
            raise ValueError
        for code, value in metadata.items():
            if (
                value["schema_version"] != "indicator-formal-metadata-v1"
                or value["root"] != code
            ):
                raise ValueError
            records, proof = value["definitions"], value["verification"]
            if (
                value["verification_state"] != "current"
                or not isinstance(records, list)
                or code not in {r["code"] for r in records}
            ):
                raise ValueError
            if (
                proof["schema_version"] != "indicator-formal-verification-v1"
                or proof["digest"] != digest(records)
                or proof.get("limitations")
            ):
                raise ValueError
            if (
                not {r["code"] for r in records if not r.get("verification_context")}
                <= effective
            ):
                raise ValueError
            if proof["analysis"]["indicators"][code]["kind"] not in {
                "base",
                "projection",
                "composite",
            }:
                raise ValueError
    except (KeyError, TypeError, ValueError, AttributeError):
        raise IngestResolutionError(
            "configuration_invariant_violation",
            "The frozen formal metadata are inconsistent",
        ) from None


def formal_display(version, *, snapshot=None) -> dict | None:
    """Render approved metadata from the snapshot; draft views use the catalog."""
    if snapshot is not None:
        wrapper = snapshot.get("formal_metadata", {}).get(version.code)
        if wrapper is None:
            return None
        record = next(r for r in wrapper["definitions"] if r["code"] == version.code)
        return {
            **record,
            "state": wrapper["verification_state"],
            "limitations": wrapper["verification"].get("limitations", []),
            "frozen": True,
        }
    if not version.definition_kind:
        return None
    return {
        **{f: getattr(version, f) for f in FORMAL_FIELDS},
        "symbol": version.indicator.formula_symbol,
        "state": verification_state(version),
        "limitations": version.formal_verification.get("limitations", []),
        "frozen": False,
    }
