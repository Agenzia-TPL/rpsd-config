# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Deterministic examples of reusable dataset assets, without runtime execution."""

import hashlib
import io
import zipfile

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
    store_configuration_asset,
)


def dataset_asset_examples() -> list[tuple[str, str, str, bytes]]:
    """Return reproducible XSD, text and CSV assets with independent codes."""
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("schema.xsd", date_time=(2026, 1, 1, 0, 0, 0)),
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>',
        )
    return [
        ("xsd_bundle", "demo-schema", "schema-locale.zip", bundle.getvalue()),
        (
            "document",
            "demo-manuale",
            "istruzioni.txt",
            b"Dataset configuration example.\n",
        ),
        ("other", "demo-colonne", "colonne.csv", b"column,type\nid,string\n"),
    ]


def ensure_dataset_asset_examples(*, actor) -> list[ConfigurationAsset]:
    """Reuse exact content and links; report conflicts instead of replacing data."""
    if not (actor.is_superuser or resolve_user_agency_scope(actor).is_platform_admin):
        raise PermissionDenied("Only platform administrators can seed dataset assets.")
    assets = []
    for asset_type, code, filename, content in dataset_asset_examples():
        candidates = list(
            ConfigurationAsset.objects.filter(asset_type=asset_type, what=code)
        )
        if candidates:
            if len(candidates) != 1:
                raise ValidationError(f"Conflicting example asset versions: {code}.")
            asset = candidates[0]
            if (
                asset.checksum_sha256 != hashlib.sha256(content).hexdigest()
                or asset.original_filename != filename
            ):
                raise ValidationError(f"Conflicting example asset content: {code}.")
            load_configuration_asset_content(asset)
        else:
            asset = store_configuration_asset(
                uploaded_file=SimpleUploadedFile(filename, content),
                asset_type=asset_type,
                what=code,
                uploaded_by=actor,
            ).asset
        assets.append(asset)
    for code in ("demo-assets-a", "demo-assets-b"):
        dataset, _ = Dataset.objects.get_or_create(code=code, defaults={"name": code})
        spec, created = DatasetSpecification.objects.get_or_create(
            code=f"{code}_001",
            defaults={"dataset": dataset, "version": "001", "format": "xml"},
        )
        if (
            spec.dataset_id != dataset.pk
            or spec.version != "001"
            or spec.format != "xml"
        ):
            raise ValidationError(f"Conflicting example specification: {spec.code}.")
        expected = {
            (
                asset.pk,
                "validation_schema" if asset.bundle_manifest else "documentation",
            )
            for asset in assets
        }
        existing = {
            (link.configuration_asset_id, link.role) for link in spec.asset_links.all()
        }
        if not created and (
            existing - expected or (spec.status != "draft" and existing != expected)
        ):
            raise ValidationError(f"Conflicting example composition: {spec.code}.")
        for asset in assets:
            DatasetSpecificationAsset.objects.get_or_create(
                dataset_specification=spec,
                configuration_asset=asset,
                role="validation_schema" if asset.bundle_manifest else "documentation",
                defaults={"required": False},
            )
    return assets
