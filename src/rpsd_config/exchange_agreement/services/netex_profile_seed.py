# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Seed pinned Italian NeTEx Lev5 resources independently of sibling repositories."""

import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
    require_catalog_admin,
)
from rpsd_config.exchange_agreement.services.validation_seed import ensure_seed_version

RESOURCES = Path(__file__).resolve().parents[1] / "seed_data" / "netex_it_lev5"
SPEC_CODE = "netex-it-lev5_001"


def ensure_netex_italian_profile(*, actor):
    """Add three exact assets and a draft specification/rule; never invent a flow."""
    require_catalog_admin(actor)
    provenance = json.loads((RESOURCES / "sources.json").read_text())
    definitions = (
        (
            "netex-it-lev5-schema",
            "netex-it-lev5.zip",
            "xsd_bundle",
            "validation_schema",
            True,
            "application/zip",
        ),
        (
            "netex-it-lev5-example",
            "netex-it-lev5-example.xml",
            "other",
            "example",
            False,
            "application/xml",
        ),
        (
            "netex-it-guidelines",
            "netex-it-guidelines-5.0.1.pdf",
            "document",
            "documentation",
            False,
            "application/pdf",
        ),
    )
    # Check every packaged resource before the first database/storage write.
    contents = {}
    for _, filename, _, _, _, _ in definitions:
        content = (RESOURCES / filename).read_bytes()
        if (
            hashlib.sha256(content).hexdigest()
            != provenance["files"][filename]["sha256"]
        ):
            raise ValidationError(
                f"Packaged NeTEx resource checksum mismatch: {filename}"
            )
        contents[filename] = content
    assets = []
    for code, filename, asset_type, role, required, mime in definitions:
        content = contents[filename]
        candidates = list(ConfigurationAsset.objects.filter(what=code))
        if candidates:
            if len(candidates) != 1:
                raise ValidationError(f"Conflicting NeTEx asset versions: {code}")
            asset = candidates[0]
            if (
                asset.asset_type != asset_type
                or asset.checksum_sha256 != provenance["files"][filename]["sha256"]
                or asset.original_filename != filename
                or not asset.is_active
            ):
                raise ValidationError(f"Conflicting NeTEx asset: {code}")
            load_configuration_asset_content(asset)
        else:
            asset = store_configuration_asset(
                uploaded_file=SimpleUploadedFile(filename, content, content_type=mime),
                asset_type=asset_type,
                what=code,
                label=code,
                activate=True,
                uploaded_by=actor,
            ).asset
        assets.append((asset, role, required))
    dataset, _ = Dataset.objects.get_or_create(code="netex", defaults={"name": "NeTEx"})
    specification, _ = ensure_seed_version(
        DatasetSpecification,
        code=SPEC_CODE,
        defaults={
            "dataset": dataset,
            "version": "it-lev5-001",
            "format": "xml",
            "description": "Profilo italiano NeTEx livello 5, risorse 5T versionate.",
            "metadata": {
                "source_repository": provenance["repository"],
                "source_commit": provenance["commit"],
                "schema_entrypoint": provenance["entrypoint"],
            },
        },
    )
    for asset, role, required in assets:
        link = specification.asset_links.filter(
            configuration_asset=asset, role=role
        ).first()
        if link is None:
            DatasetSpecificationAsset.objects.create(
                dataset_specification=specification,
                configuration_asset=asset,
                role=role,
                required=required,
            )
        elif link.required != required:
            raise ValidationError(f"Conflicting NeTEx asset association: {role}")
    schema = assets[0][0]
    rule, _ = ValidationRule.objects.get_or_create(
        code="netex-it-lev5-xsd",
        defaults={"name": "Validazione XSD NeTEx italiano Lev5"},
    )
    ensure_seed_version(
        ValidationRuleVersion,
        rule=rule,
        version="001",
        defaults={
            "name": rule.name,
            "validation_type_version": get_validation_type_version("xsd_bundle", "1.0"),
            "definition": json.dumps(
                {
                    "asset_code": schema.what,
                    "asset_version": str(schema.version),
                    "entrypoint": provenance["entrypoint"],
                    "bundle_sha256": schema.checksum_sha256,
                },
                sort_keys=True,
            ),
            "options": {},
            "result_contract": "structured_report",
        },
    )
    return specification
