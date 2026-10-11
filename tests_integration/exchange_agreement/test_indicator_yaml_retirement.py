# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Retired YAML input is rejected; dataset assets and code provenance remain."""

import importlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import ConfigurationAsset
from rpsd_config.exchange_agreement.services.configuration_assets import (
    store_configuration_asset,
)


class IndicatorYamlRetirementTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="yaml-retirement-admin", is_superuser=True, is_staff=True
        )

    def test_models_and_tables_are_absent_and_asset_choices_are_dataset_only(self):
        self.assertNotIn(
            "indicatorprofile", {model._meta.model_name for model in apps.get_models()}
        )
        self.assertNotIn(
            "exchange_agreement_indicatorprofile",
            connection.introspection.table_names(),
        )
        self.assertEqual(
            set(ConfigurationAsset.AssetType.values), {"netex_xsd", "siri_profile"}
        )

    def test_yaml_upload_is_rejected_before_storage_is_contacted(self):
        with patch(
            "rpsd_config.exchange_agreement.services.configuration_assets._storage_provider"
        ) as storage:
            with self.assertRaises(ValidationError):
                store_configuration_asset(
                    uploaded_file=SimpleUploadedFile("indicators.yml", b"kpi: demo"),
                    asset_type="indicator_yaml",
                    uploaded_by=self.actor,
                )
            storage.assert_not_called()
        self.assertFalse(ConfigurationAsset.objects.exists())

    def test_web_upload_and_activation_actions_are_retired(self):
        self.client.force_login(self.actor)
        url = reverse("exchange_agreement:platform-configuration")
        with patch(
            "rpsd_config.exchange_agreement.views.store_configuration_asset"
        ) as store:
            for action in ["upload-indicator", "set-indicator-active"]:
                response = self.client.post(
                    url,
                    {
                        "tab": "inizializzazione",
                        "action": action,
                        "profile_id": "1",
                        "indicator_file": SimpleUploadedFile(
                            "indicators.yml", b"kpi: demo"
                        ),
                    },
                )
                self.assertContains(response, "Azione non supportata.")
            store.assert_not_called()
        response = self.client.get(url + "?tab=inizializzazione")
        self.assertNotContains(response, 'name="indicator_file"')
        self.assertContains(response, "Apri catalogo indicatori")
        self.assertContains(response, "Versioni indicatore pubblicate")

    def test_database_constraint_rejects_obsolete_asset_type(self):
        with self.assertRaises(IntegrityError) as error, transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO exchange_agreement_configurationasset "
                    "(asset_type, what, version, status, is_active, storage_url, "
                    "storage_provider, storage_key, original_filename, content_type, "
                    "checksum_sha256, size_bytes, label, publish_status, "
                    "last_publish_error, bundle_manifest, uploaded_at, "
                    "created_at, updated_at) "
                    "VALUES ('indicator_yaml', 'indicators', 1, 'stored', false, "
                    "'unused', 'fs', '', 'indicators.yml', '', '', 1, '', '', '', "
                    "'{}', now(), now(), now())"
                )
        self.assertIn("config_asset_supported_dataset_type", str(error.exception))

    def test_cleanup_deletes_only_yaml_metadata_and_preserves_physical_file(self):
        # The test transaction rolls back this temporary constraint removal.
        # Historical models reproduce RunPython without runtime save hooks.
        with connection.cursor() as cursor:
            cursor.execute(
                "ALTER TABLE exchange_agreement_configurationasset "
                "DROP CONSTRAINT config_asset_supported_dataset_type"
            )
        state = MigrationExecutor(connection).loader.project_state()
        asset_model = state.apps.get_model("exchange_agreement", "ConfigurationAsset")
        with tempfile.TemporaryDirectory() as directory:
            content = Path(directory) / "indicators.yml"
            content.write_text("kpi: demo\n")
            legacy = asset_model.objects.create(
                asset_type="indicator_yaml",
                what="indicators",
                storage_url=str(content),
                storage_provider="fs",
                original_filename="indicators.yml",
                checksum_sha256="a" * 64,
                size_bytes=10,
            )
            dataset_model = state.apps.get_model("exchange_agreement", "Dataset")
            spec_model = state.apps.get_model(
                "exchange_agreement", "DatasetSpecification"
            )
            link_model = state.apps.get_model(
                "exchange_agreement", "DatasetSpecificationAsset"
            )
            dataset = dataset_model.objects.create(code="old-yaml-link", name="Legacy")
            spec = spec_model.objects.create(
                dataset=dataset,
                code="old-yaml-link_001",
                version="001",
                description="Development-only obsolete association",
            )
            link_model.objects.create(
                dataset_specification=spec,
                configuration_asset=legacy,
                role="validation_schema",
            )
            dataset_asset = asset_model.objects.create(
                asset_type="netex_xsd",
                what="netex",
                storage_url="untouched",
                storage_provider="fs",
                original_filename="netex.xsd",
                checksum_sha256="b" * 64,
                size_bytes=10,
            )
            migration = importlib.import_module(
                "rpsd_config.exchange_agreement.migrations."
                "0047_remove_indicatorprofile_configuration_asset_and_more"
            )
            with connection.schema_editor() as editor:
                migration.remove_obsolete_indicator_asset_metadata(state.apps, editor)
            self.assertFalse(asset_model.objects.filter(pk=legacy.pk).exists())
            self.assertFalse(
                link_model.objects.filter(configuration_asset_id=legacy.pk).exists()
            )
            self.assertTrue(asset_model.objects.filter(pk=dataset_asset.pk).exists())
            self.assertEqual(content.read_text(), "kpi: demo\n")
