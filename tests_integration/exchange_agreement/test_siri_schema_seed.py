# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Pinned schema-only seeding preserves catalogs and detects integrity conflicts."""

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    DatasetSpecification,
    DatasetSpecificationAsset,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    archive_configuration_asset,
    load_configuration_asset_content,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.siri_profile_seed import (
    SCHEMA_RESOURCES,
    ensure_siri_italian_profile,
    ensure_siri_schema_asset,
)


class SiriSchemaSeedTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.storage = Path(directory.name)
        settings = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = get_user_model().objects.create_user(
            username="siri-schema-admin", is_superuser=True, is_staff=True
        )

    def test_command_reuses_one_new_bundle_and_preserves_legacy_catalog(self):
        ensure_siri_italian_profile(actor=self.actor)
        legacy_assets = list(ConfigurationAsset.objects.order_by("pk").values())
        specifications = list(DatasetSpecification.objects.order_by("pk").values())
        links = list(DatasetSpecificationAsset.objects.order_by("pk").values())
        output = io.StringIO()
        call_command("seed_siri_schema", actor=self.actor.username, stdout=output)
        asset = ConfigurationAsset.objects.get(what="siri-2-2-1-schema")
        self.assertEqual(asset.asset_type, "xsd_bundle")
        self.assertEqual(asset.original_filename, "siri-2.2.1.zip")
        self.assertTrue(asset.is_active)
        self.assertEqual(asset.version, 1)
        self.assertEqual(asset.bundle_manifest["entrypoint"], "siri.xsd")
        self.assertEqual(len(asset.bundle_manifest["files"]), 74)
        self.assertEqual(
            sum(f["path"].endswith(".xsd") for f in asset.bundle_manifest["files"]),
            73,
        )
        resources, _, filename = SCHEMA_RESOURCES["2.2.1"]
        self.assertEqual(
            load_configuration_asset_content(asset), (resources / filename).read_bytes()
        )
        self.assertEqual(asset.dataset_specification_links.count(), 0)
        paths = {p for p in self.storage.rglob("*") if p.is_file()}
        call_command(
            "seed_siri_schema",
            actor=self.actor.username,
            standard_version="2.2.1",
            stdout=output,
        )
        self.assertEqual(
            ConfigurationAsset.objects.get(what="siri-2-2-1-schema").pk, asset.pk
        )
        self.assertEqual(ConfigurationAsset.objects.count(), len(legacy_assets) + 1)
        self.assertEqual(paths, {p for p in self.storage.rglob("*") if p.is_file()})
        self.assertEqual(
            list(
                ConfigurationAsset.objects.exclude(pk=asset.pk).order_by("pk").values()
            ),
            legacy_assets,
        )
        self.assertEqual(
            list(DatasetSpecification.objects.order_by("pk").values()), specifications
        )
        self.assertEqual(
            list(DatasetSpecificationAsset.objects.order_by("pk").values()), links
        )
        self.assertIn("SIRI 2.2.1 schema ready: siri-2-2-1-schema", output.getvalue())

    def test_conflicting_content_is_not_replaced_or_activated(self):
        directory, _, filename = SCHEMA_RESOURCES["2.1"]
        asset = store_configuration_asset(
            uploaded_file=SimpleUploadedFile(
                "siri-2.2.1.zip", (directory / filename).read_bytes(), "application/zip"
            ),
            asset_type="xsd_bundle",
            what="siri-2-2-1-schema",
            activate=True,
            uploaded_by=self.actor,
        ).asset
        before = load_configuration_asset_content(asset)
        with self.assertRaisesMessage(CommandError, "Conflicting SIRI asset"):
            call_command("seed_siri_schema", actor=self.actor.username)
        asset.refresh_from_db()
        self.assertTrue(asset.is_active)
        self.assertEqual(load_configuration_asset_content(asset), before)
        self.assertEqual(ConfigurationAsset.objects.count(), 1)

    def test_archived_bundle_is_not_implicitly_reactivated(self):
        asset = ensure_siri_schema_asset(actor=self.actor)
        archive_configuration_asset(asset=asset)
        with self.assertRaisesMessage(ValidationError, "Conflicting SIRI asset"):
            ensure_siri_schema_asset(actor=self.actor)
        asset.refresh_from_db()
        self.assertFalse(asset.is_active)
        self.assertEqual(ConfigurationAsset.objects.count(), 1)

    def test_corrupt_packaged_bundle_never_writes_storage(self):
        directory, code, filename = SCHEMA_RESOURCES["2.2.1"]
        provenance = json.loads((directory / "sources.json").read_text())
        with tempfile.TemporaryDirectory() as temporary:
            resources = Path(temporary)
            (resources / "sources.json").write_text(json.dumps(provenance))
            (resources / filename).write_bytes(b"corrupt")
            with patch.dict(SCHEMA_RESOURCES, {"2.2.1": (resources, code, filename)}):
                with self.assertRaisesMessage(ValidationError, "checksum mismatch"):
                    ensure_siri_schema_asset(actor=self.actor)
        self.assertFalse(ConfigurationAsset.objects.exists())
        self.assertEqual(list(self.storage.rglob("*")), [])

    def test_non_admin_and_unknown_release_cannot_create_assets(self):
        user = get_user_model().objects.create_user(username="siri-reader")
        with self.assertRaises(PermissionDenied):
            ensure_siri_schema_asset(actor=user)
        with self.assertRaisesMessage(ValidationError, "Unsupported SIRI"):
            ensure_siri_schema_asset(actor=self.actor, standard_version="latest")
        self.assertFalse(ConfigurationAsset.objects.exists())
