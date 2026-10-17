# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Inventory or explicitly recover legacy-only files before the terminal drop."""

import hashlib
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from rpsd_config.exchange_agreement.models import ConfigurationAsset
from rpsd_config.exchange_agreement.services.configuration_assets import (
    load_configuration_asset_content,
    store_configuration_asset,
)


class Command(BaseCommand):
    help = (
        "Inventory legacy profile files; "
        "--apply recovers bytes into configuration assets."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        historical = (
            MigrationExecutor(connection)
            .loader.project_state(
                [("exchange_agreement", "0053_explicit_orm_relations")]
            )
            .apps
        )
        tables = connection.introspection.table_names()
        for model_name in ("NetexValidationProfile", "SiriValidationProfile"):
            model = historical.get_model("exchange_agreement", model_name)
            if model._meta.db_table not in tables:
                continue
            for profile in model.objects.all():
                if not profile.file:
                    continue
                try:
                    with profile.file.open("rb") as stream:
                        content = stream.read()
                    digest = hashlib.sha256(content).hexdigest()
                    asset = ConfigurationAsset.objects.filter(
                        pk=profile.configuration_asset_id
                    ).first()
                    matched = bool(
                        asset
                        and hashlib.sha256(
                            load_configuration_asset_content(asset)
                        ).hexdigest()
                        == digest
                    )
                    self.stdout.write(
                        f"{model_name} ID={profile.pk}: "
                        f"{'matched asset' if matched else 'recovery required'} "
                        f"sha256={digest}"
                    )
                    if matched or not options["apply"]:
                        continue
                    code = f"legacy-{model_name.lower()}-{profile.pk}"
                    asset = ConfigurationAsset.objects.filter(
                        what=code, checksum_sha256=digest
                    ).first()
                    if asset:
                        load_configuration_asset_content(asset)
                    else:
                        asset = store_configuration_asset(
                            uploaded_file=SimpleUploadedFile(
                                Path(profile.file.name).name, content
                            ),
                            asset_type="other",
                            what=code,
                            label=profile.label,
                        ).asset
                    model.objects.filter(pk=profile.pk).update(
                        configuration_asset_id=asset.pk
                    )
                    self.stdout.write(
                        f"Recovered as ConfigurationAsset ID={asset.pk}; "
                        "original bytes retained."
                    )
                except Exception as exc:
                    raise CommandError(
                        f"Cannot verify/recover {model_name} ID={profile.pk}: {exc}"
                    ) from exc
