# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""The terminal migration cannot discard unverified legacy-only file references."""

import importlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase


class LegacyProfileDropTests(SimpleTestCase):
    def test_drop_requires_matching_recovered_bytes(self):
        migration = importlib.import_module(
            "rpsd_config.exchange_agreement.migrations.0054_remove_legacy_validation_profiles"
        )
        profile = SimpleNamespace(
            pk=42,
            file=SimpleUploadedFile("schema.xsd", b"original"),
            configuration_asset_id=1,
        )
        historical = Mock()

        def legacy_model(*args):
            profile.file = SimpleUploadedFile("schema.xsd", b"original")
            model = Mock()
            model.objects.using.return_value.all.return_value = [profile]
            return model

        historical.get_model.side_effect = legacy_model
        with (
            patch(
                "rpsd_config.exchange_agreement.models.ConfigurationAsset.objects.get",
                return_value=Mock(),
            ),
            patch(
                "rpsd_config.exchange_agreement.services.configuration_assets.load_configuration_asset_content",
                return_value=b"original",
            ),
        ):
            migration.verify_recovered_files(
                historical, Mock(connection=Mock(alias="default"))
            )
        with (
            patch(
                "rpsd_config.exchange_agreement.models.ConfigurationAsset.objects.get",
                return_value=Mock(),
            ),
            patch(
                "rpsd_config.exchange_agreement.services.configuration_assets.load_configuration_asset_content",
                return_value=b"different",
            ),
            self.assertRaisesMessage(
                RuntimeError, "recover_legacy_validation_profiles --apply"
            ),
        ):
            migration.verify_recovered_files(
                historical, Mock(connection=Mock(alias="default"))
            )
