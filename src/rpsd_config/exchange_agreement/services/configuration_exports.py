# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only, explicitly non-operational contract configuration exports."""

import copy
import json
import logging
import math
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.contract_revisions import (
    canonical_json_bytes,
    canonical_snapshot_checksum,
)
from rpsd_config.exchange_agreement.services.formal_definitions import (
    definition_records,
    verification_state,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    dependency_impact_contract,
    resolve_indicator_closure,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    resolve_dataset_rules,
)

logger = logging.getLogger(__name__)


class ConfigurationExportError(ValueError):
    """Invalid selection, inconsistent source, or incompatible transaction."""

    def __init__(self, message, *, code="invalid_export_selection", status=400):
        self.code, self.status = code, status
        super().__init__(message)


@contextmanager
def consistent_configuration_read():
    """Use one PostgreSQL snapshot; reject incompatible caller transactions."""
    if connection.in_atomic_block:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            isolation = cursor.fetchone()[0]
        if isolation not in {"repeatable read", "serializable"}:
            raise ConfigurationExportError(
                "Eseguire l’export fuori da transazioni READ COMMITTED già aperte.",
                code="export_transaction_conflict",
                status=409,
            )
        yield
    else:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
            yield


def require_export_reader(actor, contract):
    """Contract visibility grants only its reachable configuration, not catalogs."""
    from rpsd_config.exchange_agreement.views import (
        _can_view_contract_via_membership_or_agency,
    )

    if not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise PermissionDenied("Autenticazione richiesta per esportare la revisione.")
    if not _can_view_contract_via_membership_or_agency(user=actor, contract=contract):
        raise PermissionDenied("Non hai accesso alla configurazione del contratto.")


def normalise_export(value):
    """Use stable, explicit decimal strings without NaN or filesystem objects."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationExportError("Valore numerico non finito nella fonte.")
        return str(Decimal(str(value)))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: normalise_export(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalise_export(item) for item in value]
    return value


def _issue(issues, code, path, message, phase="approval"):
    row = {"code": code, "path": path, "message": str(message), "blocking_phase": phase}
    if row not in issues:
        issues.append(row)


def _state(issues, obj, path):
    status = obj.status
    if status != "published":
        _issue(
            issues,
            "component_not_published",
            path,
            f"{obj}: stato {status}; pubblicare il componente prima dell’approvazione.",
        )
    return status


def _flow(flow, issues, path):
    if not flow.deployment_name or not flow.artifact_identifier:
        _issue(
            issues,
            "incomplete_flow_reference",
            path,
            "Completare i riferimenti del processo prima della pubblicazione.",
        )
    return {
        "code": flow.code,
        "version": flow.version,
        "name": flow.name,
        "description": flow.description,
        "status": _state(issues, flow, path),
        "engine": flow.engine,
        "deployment_name": flow.deployment_name,
        "artifact_identifier": flow.artifact_identifier,
    }


def _asset(link, revision):
    asset = link.configuration_asset
    return {
        "asset_type": asset.asset_type,
        "code": asset.what,
        "version": asset.version,
        "checksum": "sha256:" + asset.checksum_sha256,
        "status": asset.status,
        "role": link.role,
        "required": link.required,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "bundle_manifest": copy.deepcopy(asset.bundle_manifest),
        "content_availability": "not_checked",
        "download_path": (
            f"/exchange_agreement/me/contracts/{revision.contract.contract_code}"
            f"/revisions/{revision.pk}/export-assets/{asset.pk}/"
        ),
    }


def _evaluation_rows(revision, issues):
    from rpsd_config.exchange_agreement.services.indicator_evaluations import (
        serialize_evaluation,
    )

    result = []
    for owner in revision.indicator_configurations.select_related(
        "processing_profile_indicator_version__indicator_version"
    ).order_by("processing_profile_indicator_version__indicator_version__code"):
        code = owner.processing_profile_indicator_version.indicator_version.code
        row = {
            "indicator_version_code": code,
            "penalty_combination_policy": "cumulative",
        }
        for name, values in (
            ("thresholds", owner.evaluation_thresholds),
            ("penalties", owner.evaluation_penalties),
        ):
            row[name] = []
            for item in values.order_by("code"):
                try:
                    payload = serialize_evaluation(item)
                except ValidationError as exc:
                    _issue(
                        issues,
                        "incomplete_evaluation",
                        f"indicators.{code}.{name}.{item.code}",
                        " ".join(exc.messages),
                    )
                    payload = {
                        field.name: getattr(item, field.name)
                        for field in item._meta.fields
                        if not field.is_relation
                        and field.name not in {"id", "created_at", "updated_at"}
                    }
                    threshold = getattr(item, "activation_threshold", None)
                    payload["activation_threshold_code"] = (
                        threshold.code if threshold else None
                    )
                    payload["group_by_dimensions"] = list(
                        item.group_by_dimensions.order_by("code").values_list(
                            "code", flat=True
                        )
                    )
                row[name].append(payload)
        if row["thresholds"] or row["penalties"]:
            result.append(row)
    return result


def collect_draft_configuration(revision, issues):
    """Read saved data only; missing publication requirements are diagnostics."""
    profile = revision.processing_profile_version
    _state(issues, profile, "processing_profile")
    configs = list(
        revision.indicator_configurations.select_related(
            "processing_profile_indicator_version__indicator_version__indicator"
        ).order_by("processing_profile_indicator_version__indicator_version__code")
    )
    roots = [c.processing_profile_indicator_version.indicator_version for c in configs]
    try:
        graph = resolve_indicator_closure(
            roots, allow_drafts=True, validate_bindings=False
        )
    except ValidationError as exc:
        raise ConfigurationExportError(
            " ".join(exc.messages), code="inconsistent_indicator_graph", status=409
        ) from exc
    if not configs:
        _issue(
            issues,
            "missing_indicators",
            "selected_indicators",
            "Selezionare almeno un indicatore.",
        )
    selected = {
        c.processing_profile_indicator_version.indicator_version_id: c for c in configs
    }
    implicit = {
        c.indicator_version_id: c for c in revision.dependency_configurations.all()
    }
    result = {
        "processing_profile": {
            "code": profile.code,
            "version": profile.version,
            "name": profile.name,
            "description": profile.description,
            "status": profile.status,
        },
        "orchestration_flow": _flow(
            profile.orchestration_flow_version, issues, "orchestration_flow"
        ),
        "inputs": [],
        "selected_indicators": sorted(v.code for v in roots),
        "effective_indicators": [],
        "indicator_configurations": [],
        "dependency_edges": [
            {
                **dependency_impact_contract(edge),
                "origin": edge.origin,
                "technical_reason": edge.technical_reason,
            }
            for edge in graph["edges"]
        ],
        "indicator_execution_order": graph["execution_order"],
        "validation_rules": [],
        "formal_metadata": {},
    }
    for config in configs:
        if (
            config.processing_profile_indicator_version.processing_profile_version_id
            != profile.pk
        ):
            _issue(
                issues,
                "selection_not_in_profile",
                "selected_indicators",
                "Una selezione non appartiene più al profilo della revisione.",
            )
    for version in graph["versions"]:
        path = f"indicators.{version.code}"
        _state(issues, version, path)
        config = selected.get(version.pk) or implicit.get(version.pk)
        values = {
            name: copy.deepcopy(getattr(config, name)) if config else {}
            for name in ("parameters", "thresholds", "penalties", "aggregation")
        }
        try:
            validate_indicator_parameters(
                version.parameter_schema, values["parameters"]
            )
        except ValidationError as exc:
            _issue(
                issues,
                "invalid_indicator_parameters",
                path + ".parameters",
                " ".join(exc.messages),
            )
        result["indicator_configurations"].append(
            {"indicator_version_code": version.code, **values}
        )
        result["effective_indicators"].append(
            {
                "code": version.code,
                "indicator_code": version.indicator.code,
                "name": version.indicator.name,
                "version": version.version,
                "status": version.status,
                "role": "selected" if version.pk in selected else "dependency",
                "input_schema": version.input_schema,
                "output_schema": version.output_schema,
                "parameter_schema": version.parameter_schema,
                "execution_engine": version.execution_engine,
                "execution_reference": version.execution_reference,
                "artifact_identifier": version.artifact_identifier,
                "definition_kind": version.definition_kind,
                "formula_definition": version.formula_definition,
                "formula_description": version.formula_description,
                "formula_language_version": version.formula_language_version,
                "dimensions": [
                    {
                        "code": d.dimension.code,
                        "allowed_values": d.allowed_values,
                        "is_carried": d.is_carried,
                        "is_monitoring": d.is_monitoring,
                        "is_contractual": d.is_contractual,
                    }
                    for d in version.dimension_links.select_related(
                        "dimension"
                    ).order_by("dimension__code")
                ],
                "required_specifications": sorted(
                    s.code
                    for s in domain.DatasetSpecification.objects.filter(
                        pk__in=list(
                            version.dataset_inputs.values_list(
                                "dataset_specification_id", flat=True
                            )
                        )
                        + list(
                            version.rule_bindings.values_list(
                                "dataset_specification_id", flat=True
                            )
                        )
                    )
                ),
            }
        )
        if version.definition_kind:
            state = verification_state(version)
            if state != "current":
                _issue(
                    issues,
                    "formal_verification_not_current",
                    path,
                    "Verifica formale assente o obsoleta.",
                )
            for limitation in version.formal_verification.get("limitations", []):
                _issue(
                    issues,
                    "unresolved_catalog_requirement",
                    path,
                    json.dumps(limitation, ensure_ascii=False, sort_keys=True),
                )
            try:
                definitions = definition_records(version)
            except (ValidationError, ValueError, KeyError) as exc:
                definitions = []
                _issue(issues, "unresolved_formal_context", path, str(exc))
            result["formal_metadata"][version.code] = {
                "definitions": definitions,
                "verification": copy.deepcopy(version.formal_verification),
                "verification_state": state,
            }
    rules = {}
    selected_specs = set()
    for choice in revision.input_selections.select_related(
        "processing_profile_input_flow__dataset",
        "processing_profile_input_flow__input_flow_version__dataset_specification",
    ).order_by("processing_profile_input_flow__dataset__code"):
        link = choice.processing_profile_input_flow
        if link.processing_profile_version_id != profile.pk:
            _issue(
                issues,
                "selection_not_in_profile",
                "inputs",
                "Un input non appartiene più al profilo.",
            )
        spec = link.input_flow_version.dataset_specification
        selected_specs.add(spec.pk)
        _state(issues, spec, f"inputs.{link.dataset.code}.specification")
        item = {
            "dataset_code": link.dataset.code,
            "dataset_name": link.dataset.name,
            "dataset_specification": {
                "code": spec.code,
                "version": spec.version,
                "format": spec.format,
                "status": spec.status,
                "description": spec.description,
                "metadata": spec.metadata,
            },
            "input_flow": _flow(
                link.input_flow_version, issues, f"inputs.{link.dataset.code}.flow"
            ),
            "assets": [],
            "rule_bindings": [],
        }
        for asset_link in spec.asset_links.select_related(
            "configuration_asset"
        ).order_by("configuration_asset__what", "configuration_asset__version", "role"):
            asset = asset_link.configuration_asset
            if asset_link.required and (
                asset.status != "active" or not asset.is_active
            ):
                _issue(
                    issues,
                    "required_asset_not_active",
                    f"inputs.{link.dataset.code}.assets.{asset.what}",
                    "Attivare l’asset richiesto prima dell’approvazione.",
                )
            item["assets"].append(_asset(asset_link, revision))
        for entry in resolve_dataset_rules(
            spec, graph["versions"], paths=graph["paths"], validate_bindings=False
        ):
            rule = entry["rule"]
            if rule["validation_type"] == "dbt":
                _issue(
                    issues,
                    "documentary_rule_binding",
                    "validation_rules",
                    "Un contesto dbt non può essere associato operativamente.",
                )
                continue
            key = (rule["rule_code"], rule["rule_version"])
            rules[key] = rule
            item["rule_bindings"].append(
                {
                    "rule_code": key[0],
                    "rule_version": key[1],
                    "import_policy": entry["import_policy"],
                    "consumers": entry["consumers"],
                }
            )
        result["inputs"].append(item)
    for spec in graph["specifications"]:
        if spec.pk not in selected_specs:
            _issue(
                issues,
                "missing_required_input",
                f"inputs.{spec.dataset.code}",
                f"Selezionare l’input {spec.code}.",
            )
    for key, data in sorted(rules.items()):
        rule = domain.ValidationRuleVersion.objects.select_related("rule").get(
            rule__code=key[0], version=key[1]
        )
        _state(issues, rule, f"rules.{key[0]}@{key[1]}")
        try:
            rule.validate_for_publication()
        except ValidationError as exc:
            _issue(
                issues,
                "incomplete_rule_definition",
                f"rules.{key[0]}@{key[1]}",
                " ".join(exc.messages),
            )
        result["validation_rules"].append({**data, "status": rule.status})
    result["evaluation_configurations"] = _evaluation_rows(revision, issues)
    return result


def _project(configuration, selection):
    """Prune execution data while retaining self-contained formal context."""
    result = copy.deepcopy(configuration)
    scope = selection["scope"]
    if scope == "revision":
        return result
    if scope == "indicator":
        code = selection["indicator_version_code"]
        known = {v["code"] for v in result.get("effective_indicators", [])}
        if not known:
            historical = [
                row
                for row in result.get("indicators", [])
                if row.get("indicator_version", {}).get("code") == code
            ]
            if historical:
                result["indicators"] = historical
                result["export_root_indicators"] = [code]
                result["input_scope"] = "historical_context_unresolved"
                return result
        if code not in known:
            raise ConfigurationExportError(
                "L’indicatore non appartiene alla revisione."
            )
        needed = {code}
        while True:
            more = {
                e["prerequisite"]
                for e in result.get("dependency_edges", [])
                if e["dependent"] in needed
            }
            if more <= needed:
                break
            needed |= more
        result["effective_indicators"] = [
            v for v in result["effective_indicators"] if v["code"] in needed
        ]
        for name in ("indicator_configurations", "evaluation_configurations"):
            result[name] = [
                v for v in result.get(name, []) if v["indicator_version_code"] in needed
            ]
        result["selected_indicators"] = [
            v for v in result.get("selected_indicators", []) if v in needed
        ]
        result["dependency_edges"] = [
            e
            for e in result.get("dependency_edges", [])
            if e["dependent"] in needed and e["prerequisite"] in needed
        ]
        result["indicator_execution_order"] = [
            v for v in result.get("indicator_execution_order", []) if v in needed
        ]
        result["formal_metadata"] = {
            k: v for k, v in result.get("formal_metadata", {}).items() if k in needed
        }
        paths = {}

        def collect_paths(current, path):
            if current in path:
                raise ConfigurationExportError("Grafo congelato ciclico.", status=409)
            path = [*path, current]
            paths.setdefault(current, []).append(path)
            for edge in result.get("dependency_edges", []):
                if edge["dependent"] == current:
                    collect_paths(edge["prerequisite"], path)

        collect_paths(code, [])
        result["export_root_indicators"] = [code]
        retained = []
        for item in result.get("inputs", []):
            bindings = []
            for binding in item.get("rule_bindings", []):
                consumers = [
                    {
                        **c,
                        "dependency_paths": sorted(paths[c["indicator_version_code"]]),
                    }
                    for c in binding.get("consumers", [])
                    if c["indicator_version_code"] in needed
                ]
                if consumers or binding.get("import_policy") != "indicator_only":
                    bindings.append({**binding, "consumers": consumers})
            required = any(
                item["dataset_specification"]["code"]
                in v.get("required_specifications", [])
                for v in result["effective_indicators"]
            )
            if not required:
                required = bool(
                    needed & set(item.get("required_by_indicator_versions", []))
                )
            if not required:
                required = any(
                    c["indicator_version_code"] in needed
                    for b in item.get("rule_bindings", [])
                    for c in b.get("consumers", [])
                )
            if required:
                retained.append({**item, "rule_bindings": bindings})
        result["inputs"] = retained
    else:
        code = selection["dataset_code"]
        rows = result.get("inputs", [])
        if code not in {i["dataset_code"] for i in rows}:
            raise ConfigurationExportError(
                "Il dataset non è selezionato nella revisione."
            )
        result["context_inputs"] = [
            {**i, "rule_bindings": [], "role": "context_only"}
            for i in rows
            if i["dataset_code"] != code
        ]
        result["inputs"] = [i for i in rows if i["dataset_code"] == code]
    used = {
        (b["rule_code"], b["rule_version"])
        for i in result.get("inputs", [])
        for b in i.get("rule_bindings", [])
    }
    result["validation_rules"] = [
        r
        for r in result.get("validation_rules", [])
        if (r["rule_code"], r["rule_version"]) in used
    ]
    return result


def export_contract_configuration(
    *,
    actor,
    contract_code,
    revision_code,
    scope="revision",
    dataset_code=None,
    indicator_version_code=None,
):
    """Export an exact authorized revision without modifying its saved state."""
    if (
        scope not in {"revision", "dataset", "indicator"}
        or (scope == "dataset") != bool(dataset_code)
        or (scope == "indicator") != bool(indicator_version_code)
    ):
        raise ConfigurationExportError(
            "Specificare un perimetro e soltanto il target pertinente."
        )
    selection = {"scope": scope}
    if dataset_code:
        selection["dataset_code"] = dataset_code
    if indicator_version_code:
        selection["indicator_version_code"] = indicator_version_code
    with consistent_configuration_read():
        revision = (
            domain.ContractConfigurationRevision.objects.select_related(
                "contract__client_agency",
                "contract__contractor_company",
                "contract__lot",
                "processing_profile_version__orchestration_flow_version",
            )
            .filter(code=revision_code, contract__contract_code=contract_code)
            .first()
        )
        if revision is None:
            raise domain.ContractConfigurationRevision.DoesNotExist
        contract = revision.contract
        require_export_reader(actor, contract)
        issues = []
        if revision.status == "draft":
            configuration = collect_draft_configuration(revision, issues)
            mode = "draft_preview"
            if revision.valid_from is None:
                _issue(
                    issues,
                    "missing_valid_from",
                    "revision.valid_from",
                    "Indicare la decorrenza prima dell’approvazione.",
                )
        else:
            configuration = copy.deepcopy(revision.configuration_snapshot)
            if (
                not configuration
                or canonical_snapshot_checksum(configuration)
                != revision.snapshot_checksum
            ):
                raise ConfigurationExportError(
                    "Lo snapshot salvato è incoerente.",
                    code="snapshot_checksum_mismatch",
                    status=409,
                )
            mode = "frozen_revision"
            if "validation_rules" not in configuration:
                _issue(
                    issues,
                    "legacy_snapshot_without_rules",
                    "configuration",
                    "Lo snapshot storico non contiene il catalogo delle regole.",
                    "export",
                )
        configuration = _project(configuration, selection)
        if configuration.get("input_scope") == "historical_context_unresolved":
            _issue(
                issues,
                "legacy_indicator_scope_limit",
                "configuration.inputs",
                "Lo snapshot storico non conserva dipendenze e associazioni "
                "indicatore/input: tutti gli input storici sono inclusi come contesto.",
                "export",
            )

        def report_noncanonical_numbers(value, path="configuration"):
            if isinstance(value, float):
                _issue(
                    issues,
                    "noncanonical_number",
                    path,
                    "Numero non intero rappresentato come stringa decimale; "
                    "completare la configurazione canonica prima dell’approvazione.",
                )
            elif isinstance(value, dict):
                for name, item in value.items():
                    report_noncanonical_numbers(item, path + "." + name)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    report_noncanonical_numbers(item, f"{path}[{index}]")

        report_noncanonical_numbers(configuration)
        if scope == "dataset":
            issues = [
                i
                for i in issues
                if not i["path"].startswith("inputs.")
                or i["path"].startswith("inputs." + dataset_code + ".")
                or i["path"] == "inputs." + dataset_code
            ]
        if scope == "indicator":
            retained = {
                v["code"] for v in configuration.get("effective_indicators", [])
            }
            issues = [
                i
                for i in issues
                if not i["path"].startswith("indicators.")
                or any(
                    i["path"] == "indicators." + code
                    or i["path"].startswith("indicators." + code + ".")
                    for code in retained
                )
            ]
        if scope != "revision":
            inputs = {row["dataset_code"] for row in configuration.get("inputs", [])}
            rules = {
                f"{row['rule_code']}@{row['rule_version']}"
                for row in configuration.get("validation_rules", [])
            }
            issues = [
                issue
                for issue in issues
                if (
                    not issue["path"].startswith("rules.") or issue["path"][6:] in rules
                )
                and (
                    scope != "indicator"
                    or not issue["path"].startswith("inputs.")
                    or issue["code"] == "missing_required_input"
                    or any(
                        issue["path"] == "inputs." + code
                        or issue["path"].startswith("inputs." + code + ".")
                        for code in inputs
                    )
                )
            ]
        payload = normalise_export(
            {
                "schema_version": "contract-configuration-export-v1",
                "mode": mode,
                "source": {
                    "contract_code": contract.contract_code,
                    "contract_status": contract.status,
                    "revision_code": revision.code,
                    "revision_status": revision.status,
                    "revision_number": revision.revision_number,
                    "valid_from": revision.valid_from,
                    "profile_code": (configuration.get("processing_profile") or {}).get(
                        "code"
                    ),
                    "profile_status": (
                        configuration.get("processing_profile") or {}
                    ).get("status"),
                    "snapshot_schema_version": revision.snapshot_schema_version
                    if mode == "frozen_revision"
                    else None,
                    "snapshot_checksum": revision.snapshot_checksum or None,
                },
                "selection": selection,
                "contract": {
                    "metadata_source": "current_database",
                    "code": contract.contract_code,
                    "start_date": contract.start_date,
                    "end_date": contract.end_date,
                    "client_agency": {
                        "key": contract.client_agency.agency_key,
                        "name": contract.client_agency.name,
                    },
                    "contractor_company": {
                        "id": contract.contractor_company_id,
                        "name": contract.contractor_company.name,
                    },
                    "lot": {
                        "id": contract.lot_id,
                        "description": contract.lot.description,
                    },
                    "tender_id": contract.tender_id,
                },
                "configuration": configuration,
                "issues": sorted(
                    issues, key=lambda i: (i["path"], i["code"], i["message"])
                ),
            }
        )
        payload["content_digest"] = canonical_snapshot_checksum(
            {
                k: payload[k]
                for k in ("source", "selection", "contract", "configuration", "issues")
            }
        )
        payload["exported_at"] = timezone.now().isoformat()
    logger.info(
        "Contract configuration exported",
        extra={
            "contract_code": contract_code,
            "revision_code": revision_code,
            "scope": scope,
            "actor_id": actor.pk,
        },
    )
    return json.loads(canonical_json_bytes(payload))


def load_revision_asset(*, actor, contract_code, revision_code, asset_id):
    """Authorize through saved revision metadata and verify original asset bytes."""
    from django.http import Http404

    from rpsd_config.exchange_agreement.services.configuration_assets import (
        load_configuration_asset_content,
    )

    payload = export_contract_configuration(
        actor=actor, contract_code=contract_code, revision_code=revision_code
    )
    asset = domain.ConfigurationAsset.objects.filter(pk=asset_id).first()
    configuration = payload["configuration"]
    references = [
        a for row in configuration.get("inputs", []) for a in row.get("assets", [])
    ]
    if asset is None or not any(
        a["code"] == asset.what
        and a["version"] == asset.version
        and a["checksum"] == "sha256:" + asset.checksum_sha256
        for a in references
    ):
        raise Http404("Asset non raggiungibile dalla revisione.")
    return asset, load_configuration_asset_content(asset)
