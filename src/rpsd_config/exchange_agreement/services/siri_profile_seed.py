# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Pinned SIRI schemas and Italian resources for service specifications."""

import hashlib
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    INITIAL_DATASET_SPECIFICATIONS,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    require_catalog_admin,
)

RESOURCES = Path(__file__).resolve().parents[1] / "seed_data" / "siri_2_1"
SCHEMA_RESOURCES = {
    "2.1": (RESOURCES, "siri-2-1-schema", "siri-2.1.zip"),
    "2.2.1": (
        RESOURCES.parent / "siri_2_2_1",
        "siri-2-2-1-schema",
        "siri-2.2.1.zip",
    ),
}
EXAMPLE_SERVICES = ("vm", "et", "sx", "fm", "pt")


def _ensure_resource_asset(
    *, actor, code, filename, asset_type, mime, content, checksum
):
    candidates = list(ConfigurationAsset.objects.filter(what=code))
    if candidates:
        if len(candidates) != 1:
            raise ValidationError(f"Conflicting SIRI asset versions: {code}")
        asset = candidates[0]
        if (
            asset.asset_type != asset_type
            or asset.original_filename != filename
            or asset.checksum_sha256 != checksum
            or not asset.is_active
        ):
            raise ValidationError(f"Conflicting SIRI asset: {code}")
        load_configuration_asset_content(asset)
        return asset
    return store_configuration_asset(
        uploaded_file=SimpleUploadedFile(filename, content, mime),
        asset_type=asset_type,
        what=code,
        label=code,
        activate=True,
        uploaded_by=actor,
    ).asset


def ensure_siri_schema_asset(
    *, actor, standard_version: str = "2.2.1"
) -> ConfigurationAsset:
    """Load one exact shared bundle, without creating dataset or profile links."""
    require_catalog_admin(actor)
    if standard_version not in SCHEMA_RESOURCES:
        raise ValidationError(f"Unsupported SIRI standard version: {standard_version}")
    directory, code, filename = SCHEMA_RESOURCES[standard_version]
    provenance = json.loads((directory / "sources.json").read_text())
    content = (directory / filename).read_bytes()
    checksum = provenance["files"][filename]["sha256"]
    if hashlib.sha256(content).hexdigest() != checksum:
        raise ValidationError(f"Packaged SIRI resource checksum mismatch: {filename}")
    return _ensure_resource_asset(
        actor=actor,
        code=code,
        filename=filename,
        asset_type="xsd_bundle",
        mime="application/zip",
        content=content,
        checksum=checksum,
    )


def _resources(actor):
    provenance = json.loads((RESOURCES / "sources.json").read_text())
    definitions = [
        ("siri-2-1-schema", "siri-2.1.zip", "xsd_bundle", "application/zip"),
        ("siri-it-guidelines", "siri-it-guidelines.pdf", "document", "application/pdf"),
        *[
            (
                f"siri-it-example-{s}",
                f"SIRI_{s.upper()}.xml",
                "other",
                "application/xml",
            )
            for s in EXAMPLE_SERVICES
        ],
    ]
    contents = {}
    for _, filename, _, _ in definitions:
        content = (RESOURCES / filename).read_bytes()
        if (
            hashlib.sha256(content).hexdigest()
            != provenance["files"][filename]["sha256"]
        ):
            raise ValidationError(
                f"Packaged SIRI resource checksum mismatch: {filename}"
            )
        contents[filename] = content
    assets = {}
    for code, filename, asset_type, mime in definitions:
        assets[code] = _ensure_resource_asset(
            actor=actor,
            code=code,
            filename=filename,
            asset_type=asset_type,
            mime=mime,
            content=contents[filename],
            checksum=provenance["files"][filename]["sha256"],
        )
    return provenance, assets


@transaction.atomic
def _associate_specifications(provenance, assets):
    specifications = []
    for initial in INITIAL_DATASET_SPECIFICATIONS:
        if not initial.dataset_code.startswith("siri-"):
            continue
        service = initial.dataset_code.removeprefix("siri-")
        expected = [
            (assets["siri-2-1-schema"], "validation_schema", True),
            (assets["siri-it-guidelines"], "documentation", False),
        ]
        if service in EXAMPLE_SERVICES:
            expected.append((assets[f"siri-it-example-{service}"], "example", False))
        wanted = {(asset.pk, role, required) for asset, role, required in expected}
        dataset, _ = Dataset.objects.get_or_create(
            code=initial.dataset_code, defaults={"name": initial.dataset_name}
        )
        spec = (
            DatasetSpecification.objects.select_for_update()
            .filter(code=initial.specification_code)
            .first()
        )
        code, version = initial.specification_code, initial.version
        if spec is not None and spec.status != "draft":
            existing = set(
                spec.asset_links.values_list(
                    "configuration_asset_id", "role", "required"
                )
            )
            if wanted <= existing:
                specifications.append(spec)
                continue
            code, version = f"{initial.dataset_code}_v002", "002"
            spec = (
                DatasetSpecification.objects.select_for_update()
                .filter(code=code)
                .first()
            )
        if spec is None:
            spec = DatasetSpecification.objects.create(
                dataset=dataset,
                code=code,
                version=version,
                format="xml",
                description=f"{initial.dataset_name}: SIRI 2.1, asset condivisi.",
                metadata={
                    "standard": "SIRI",
                    "standard_version": "2.1",
                    "source_repository": provenance["repository"],
                    "source_commit": provenance["commit"],
                },
            )
        if (
            spec.dataset_id != dataset.pk
            or spec.format != "xml"
            or spec.version != version
        ):
            raise ValidationError(f"Conflicting SIRI specification: {code}")
        if spec.metadata.get("standard_version", "2.1") != "2.1":
            raise ValidationError(f"Conflicting SIRI standard version: {code}")
        existing = set(
            spec.asset_links.values_list("configuration_asset_id", "role", "required")
        )
        if spec.status != "draft" and not wanted <= existing:
            raise ValidationError(
                f"Frozen SIRI specification needs a new version: {code}"
            )
        if any(
            role == "validation_schema" and asset_id != assets["siri-2-1-schema"].pk
            for asset_id, role, _ in existing
        ):
            raise ValidationError(f"Conflicting SIRI schema association: {code}")
        for asset, role, required in expected:
            link = spec.asset_links.filter(configuration_asset=asset, role=role).first()
            if link is None:
                DatasetSpecificationAsset.objects.create(
                    dataset_specification=spec,
                    configuration_asset=asset,
                    role=role,
                    required=required,
                )
            elif link.required != required:
                raise ValidationError(f"Conflicting SIRI association: {code}/{role}")
        specifications.append(spec)
    return specifications


def ensure_siri_italian_profile(*, actor):
    """Reuse exact assets; never edit frozen specifications or contract profiles."""
    require_catalog_admin(actor)
    provenance, assets = _resources(actor)
    return _associate_specifications(provenance, assets)
