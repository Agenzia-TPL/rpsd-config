# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit local handoff; metadata first, optional verified original bundles."""

import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.http import Http404

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
)
from rpsd_config.exchange_agreement.services.configuration_exports import (
    ConfigurationExportError,
    consistent_configuration_read,
    export_contract_configuration,
)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_configuration_handoff(
    *,
    actor,
    contract_code,
    revision_code,
    directory,
    include_assets=False,
    seed_manifest=None,
):
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()):
        raise ConfigurationExportError(
            "La cartella di consegna deve essere vuota: "
            "gli export precedenti vanno conservati."
        )
    with consistent_configuration_read():
        common = {
            "actor": actor,
            "contract_code": contract_code,
            "revision_code": revision_code,
        }
        full = export_contract_configuration(**common)
        rule_sources = []
        if seed_manifest is not None:
            from rpsd_config.exchange_agreement.services.seed_manifests import (
                object_fingerprint,
                validate_manifest_digest,
            )

            validate_manifest_digest(seed_manifest)
            scenario = seed_manifest.get("scenario", {})
            if isinstance(scenario, dict) and any(
                scenario.get(key) != common[key]
                for key in ("contract_code", "revision_code")
            ):
                raise ConfigurationExportError(
                    "Il manifest appartiene a un'altra revisione."
                )
            keys = {
                (r["rule_code"], r["rule_version"])
                for r in full["configuration"].get("validation_rules", [])
            }
            rule_sources = [
                row
                for row in seed_manifest.get("rule_sources", [])
                if (row["rule_code"], row["rule_version"]) in keys
            ]
            if {(r["rule_code"], r["rule_version"]) for r in rule_sources} != keys:
                raise ConfigurationExportError(
                    "Provenienza delle regole incompleta nel manifest."
                )
            records = {
                row["pk"]: row
                for row in [
                    *seed_manifest.get("created", []),
                    *seed_manifest.get("reused", []),
                ]
                if row["model"] == "exchange_agreement.validationruleversion"
            }
            saved = {
                (obj.rule.code, obj.version): obj
                for obj in ValidationRuleVersion.objects.filter(
                    pk__in=records
                ).select_related("rule", "validation_type_version")
            }
            if any(
                key not in saved
                or object_fingerprint(saved[key])
                != records[saved[key].pk]["fingerprint"]
                for key in keys
            ):
                raise ConfigurationExportError(
                    "Le regole sono cambiate dal seed: esportare senza --seed-manifest "
                    "oppure revisionare la provenienza prima di consegnarla."
                )
        exports = [("revision.json", full)]
        for index, item in enumerate(full["configuration"].get("inputs", []), 1):
            exports.append(
                (
                    f"dataset-{index}.json",
                    export_contract_configuration(
                        **common, scope="dataset", dataset_code=item["dataset_code"]
                    ),
                )
            )
        for index, code in enumerate(
            full["configuration"].get("selected_indicators", []), 1
        ):
            exports.append(
                (
                    f"indicator-{index}.json",
                    export_contract_configuration(
                        **common, scope="indicator", indicator_version_code=code
                    ),
                )
            )
    directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "contract-configuration-handoff-v1",
        "files": [],
        "assets": [],
        "errors": [],
        "rule_sources": rule_sources,
        "catalog_sources": seed_manifest.get("sources", []) if seed_manifest else [],
    }
    for name, payload in exports:
        content = json_text(payload).encode()
        (directory / name).write_bytes(content)
        manifest["files"].append(
            {
                "path": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_digest": payload["content_digest"],
                "selection": payload["selection"],
            }
        )
    if include_assets:
        unique = {
            (a["code"], a["version"], a["checksum"]): a
            for item in full["configuration"].get("inputs", [])
            for a in item.get("assets", [])
        }
        for (code, version, checksum), reference in sorted(unique.items()):
            try:
                asset = ConfigurationAsset.objects.get(
                    what=code,
                    version=version,
                    checksum_sha256=checksum.removeprefix("sha256:"),
                )
                content = load_configuration_asset_content(asset)
                name = (
                    "asset-"
                    + asset.checksum_sha256
                    + (".zip" if asset.bundle_manifest else ".bin")
                )
                if hashlib.sha256(content).hexdigest() != checksum.removeprefix(
                    "sha256:"
                ):
                    raise ValidationError(
                        "Digest differente dalla configurazione esportata."
                    )
                (directory / name).write_bytes(content)
                manifest["assets"].append(
                    {
                        "code": code,
                        "version": version,
                        "checksum": checksum,
                        "path": name,
                        "required": reference["required"],
                    }
                )
            except (
                ConfigurationAsset.DoesNotExist,
                ConfigurationAsset.MultipleObjectsReturned,
                ValidationError,
                Http404,
            ) as exc:
                manifest["errors"].append(
                    {"code": code, "version": version, "message": str(exc)}
                )
    manifest["complete"] = not manifest["errors"]
    (directory / "manifest.json").write_text(json_text(manifest))
    (directory / "README.txt").write_text(
        "Configurazione RPSD per la prova del validatore.\n"
        "revision.json: revisione completa. dataset-N.json: uno specifico input; "
        "indicator-N.json: indicatore selezionato e prerequisiti. "
        "Il manifest identifica i target.\n"
        "draft_preview è una bozza; leggere issues prima della prova. "
        "Nessun processo viene eseguito.\n"
        "Le dipendenze esecutive sono distinte dal contesto delle verifiche formali.\n"
        "I riferimenti demo dei flow non attestano deployment esistenti.\n"
        "I file degli asset sono bundle originali verificati, "
        "quando richiesti; non sono estratti.\n"
        "I valori CORSE_PS del demo sono esempi espliciti, non clausole contrattuali.\n"
        "Le API operative continuano a usare solo revisioni approvate.\n"
    )
    return manifest
