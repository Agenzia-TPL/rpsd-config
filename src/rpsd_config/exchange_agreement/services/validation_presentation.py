# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only presentation of catalog previews and frozen validation plans."""

import json
from copy import deepcopy

from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    resolve_indicator_closure,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    resolve_dataset_rules,
)


def catalog_validation_preview(roots, *, specifications=()) -> dict:
    """Show roles, all provenance paths and per-input controls, without execution."""
    closure = resolve_indicator_closure(roots)
    specs = {spec.code: spec for spec in [*closure["specifications"], *specifications]}
    return {
        "effective_indicator_rows": [
            {
                "code": v.code,
                "role": "selezionato"
                if v.pk in closure["root_ids"]
                else "dipendenza implicita",
                "paths": [" → ".join(path) for path in closure["paths"][v.pk]],
            }
            for v in closure["versions"]
        ],
        "validation_preview_inputs": [
            {
                "specification_code": spec.code,
                "rules": resolve_dataset_rules(
                    spec, closure["versions"], paths=closure["paths"]
                ),
            }
            for spec in sorted(specs.values(), key=lambda spec: spec.code)
        ],
    }


def frozen_validation_rows(snapshot: dict) -> list[dict]:
    """Render definitions from an approved v2 snapshot, never from live catalog."""
    if snapshot.get("snapshot_schema_version") not in {
        "canonical-json-v2",
        "canonical-json-v3",
    }:
        return []
    from rpsd_config.exchange_agreement.services.validation_plans import (
        validate_frozen_validation_snapshot,
    )

    validate_frozen_validation_snapshot(snapshot)
    catalog = {
        (r["rule_code"], r["rule_version"]): r for r in snapshot["validation_rules"]
    }
    rows = []
    for item in snapshot["inputs"]:
        base, indicator = [], []
        for binding in item["rule_bindings"]:
            row = {
                **deepcopy(binding),
                "definition": catalog[(binding["rule_code"], binding["rule_version"])][
                    "definition"
                ],
            }
            (
                indicator if binding["import_policy"] == "indicator_only" else base
            ).append(row)
        rows.append(
            {
                "dataset_code": item["dataset_code"],
                "specification_code": item["dataset_specification"]["code"],
                "base_rules": base,
                "indicator_rules": indicator,
            }
        )
    return rows


def frozen_indicator_value_rows(snapshot: dict) -> list[dict]:
    """Display approved parameter values and roles independently of live versions."""
    if snapshot.get("snapshot_schema_version") not in {
        "canonical-json-v2",
        "canonical-json-v3",
    }:
        return []
    roles = {v["code"]: v["role"] for v in snapshot["effective_indicators"]}
    return [
        {
            "code": config["indicator_version_code"],
            "role": "selezionato"
            if roles[config["indicator_version_code"]] == "selected"
            else "dipendenza implicita",
            "values": [
                {
                    "name": field,
                    "json": json.dumps(
                        config[field], ensure_ascii=False, sort_keys=True
                    ),
                }
                for field in ("parameters", "thresholds", "aggregation", "penalties")
            ],
        }
        for config in snapshot["indicator_configurations"]
    ]
