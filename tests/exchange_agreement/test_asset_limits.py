# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Deployment limits are used at each upload and bundle inspection."""

import io
import json
import zipfile

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from pydantic import ValidationError as SettingsValidationError

from rpsd_config.exchange_agreement.asset_forms import ConfigurationAssetUploadForm
from rpsd_config.exchange_agreement.services.configuration_assets import (
    inspect_configuration_asset_upload,
)
from rpsd_config.exchange_agreement.services.schema_bundles import inspect_schema_bundle
from rpsd_config.server.settings import ProjectSettings


class AssetLimitTests(SimpleTestCase):
    @override_settings(CONFIG_ASSETS_MAX_UPLOAD_BYTES=3)
    def test_upload_limit_and_help_follow_settings(self):
        inspect_configuration_asset_upload(
            SimpleUploadedFile("data.txt", b"123"), asset_type="other", what="test"
        )
        with self.assertRaisesMessage(ValidationError, "3 bytes"):
            inspect_configuration_asset_upload(
                SimpleUploadedFile("data.txt", b"1234"), asset_type="other", what="test"
            )
        self.assertIn(
            "3 byte", ConfigurationAssetUploadForm().fields["uploaded_file"].help_text
        )

    def bundle(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("manifest.json", json.dumps({"entrypoint": "a.xsd"}))
            archive.writestr(
                "a.xsd", '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
            )
        return data.getvalue()

    def test_bundle_limits_are_dynamic_and_generic_archives_are_opaque(self):
        content = self.bundle()
        manifest = inspect_schema_bundle(content)
        size = manifest["files"][0]["size_bytes"]
        for setting, limit in (
            ("CONFIG_ASSETS_XSD_MAX_FILE_BYTES", size - 1),
            ("CONFIG_ASSETS_XSD_MAX_FILES", 1),
            ("CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES", 1),
        ):
            with self.subTest(setting=setting), override_settings(**{setting: limit}):
                with self.assertRaises(ValidationError):
                    inspect_schema_bundle(content)
                inspect_configuration_asset_upload(
                    SimpleUploadedFile("opaque.zip", content),
                    asset_type="archive",
                    what="test",
                )
        with override_settings(
            CONFIG_ASSETS_XSD_MAX_FILE_BYTES=size, CONFIG_ASSETS_XSD_MAX_FILES=2
        ):
            inspect_schema_bundle(content)

    def test_decompressed_limit_is_independent_of_zip_overhead(self):
        content = self.bundle()
        manifest = inspect_schema_bundle(content)
        total = sum(entry["size_bytes"] for entry in manifest["files"])
        self.assertGreater(len(content), total)
        with override_settings(CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES=total):
            inspect_schema_bundle(content)
        with override_settings(CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES=total - 1):
            with self.assertRaises(ValidationError):
                inspect_schema_bundle(content)

    def test_environment_limits_must_be_positive_integers(self):
        self.assertEqual(
            ProjectSettings(
                _env_file=None, CONFIG_ASSETS_MAX_UPLOAD_BYTES=1
            ).CONFIG_ASSETS_MAX_UPLOAD_BYTES,
            1,
        )
        for key in (
            "CONFIG_ASSETS_MAX_UPLOAD_BYTES",
            "CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES",
            "CONFIG_ASSETS_XSD_MAX_FILE_BYTES",
            "CONFIG_ASSETS_XSD_MAX_FILES",
        ):
            for value in (0, -1, "invalid"):
                with (
                    self.subTest(key=key, value=value),
                    self.assertRaises(SettingsValidationError),
                ):
                    ProjectSettings(_env_file=None, **{key: value})
