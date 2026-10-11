# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Bundle upload, immutable metadata and dataset-specific descriptors (023)."""

import io
import json
import tempfile
import zipfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.test import TestCase, override_settings

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
from rpsd_config.exchange_agreement.services.validation_bindings import (
    bind_dataset_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    transition_validation_rule,
)


class SchemaBundleAssetTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=self.directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = get_user_model().objects.create_user(
            username="bundle-admin", is_superuser=True
        )
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr(
                "schema.xsd", '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
            )
        self.content = data.getvalue()
        self.asset = store_configuration_asset(
            uploaded_file=SimpleUploadedFile("netex.zip", self.content),
            asset_type="netex_xsd",
            uploaded_by=self.actor,
        ).asset
        self.spec = DatasetSpecification.objects.create(
            dataset=Dataset.objects.create(code="netex", name="NeTEx"),
            code="netex_v001",
            version="001",
        )

    def rule(self, **changes):
        descriptor = {
            "asset_code": self.asset.what,
            "asset_version": str(self.asset.version),
            "entrypoint": "schema.xsd",
            "bundle_sha256": self.asset.checksum_sha256,
        } | changes
        rule = ValidationRule.objects.create(code="bundle-check", name="Bundle check")
        version = ValidationRuleVersion.objects.create(
            rule=rule,
            version="1",
            name="Bundle check",
            validation_type="xsd_bundle",
            definition=json.dumps(descriptor),
            language_version="1.0",
            result_contract="structured_report",
            execution_reference="validators/xsd",
        )
        return transition_validation_rule(
            version, target_status="published", actor=self.actor
        )

    def bind(self, rule):
        return bind_dataset_rule(
            specification=self.spec,
            rule_version=rule,
            import_policy="reject_import",
            actor=self.actor,
        )

    def link(self):
        return DatasetSpecificationAsset.objects.create(
            dataset_specification=self.spec,
            configuration_asset=self.asset,
            role="validation_schema",
        )

    def test_upload_links_and_freezes_exact_bundle(self):
        self.assertEqual(load_configuration_asset_content(self.asset), self.content)
        self.link()
        binding = self.bind(self.rule())
        self.assertEqual(binding.rule_version.validation_type, "xsd_bundle")
        self.asset.bundle_manifest["entrypoint"] = "other.xsd"
        with self.assertRaises(ValidationError), transaction.atomic():
            self.asset.save()
        with self.assertRaises(ValidationError):
            ConfigurationAsset.objects.filter(pk=self.asset.pk).update(
                checksum_sha256="a" * 64
            )
        self.asset.refresh_from_db()
        self.asset.label = "Allowed descriptive label"
        self.asset.save()

    def test_missing_link_and_mismatching_digest_fail(self):
        rule = self.rule(bundle_sha256="a" * 64)
        with self.assertRaises(ValidationError) as error:
            self.bind(rule)
        self.assertEqual(error.exception.error_dict["__all__"][0].code, "missing_asset")
        self.link()
        with self.assertRaises(ValidationError) as error:
            self.bind(rule)
        self.assertEqual(
            error.exception.error_dict["__all__"][0].code, "invalid_schema_bundle"
        )
        self.assertFalse(self.spec.rule_bindings.exists())

    def test_download_checks_manifest_and_raw_digest(self):
        self.asset.bundle_manifest["files"][0]["sha256"] = "a" * 64
        with self.assertRaises(ValidationError) as error:
            load_configuration_asset_content(self.asset)
        self.assertEqual(error.exception.code, "invalid_schema_bundle")
        self.asset.refresh_from_db()
        provider_path = (
            "rpsd_config.exchange_agreement.services."
            "configuration_assets._storage_provider"
        )
        with patch(provider_path) as provider:
            provider.return_value.load.return_value = (b"tampered", None)
            with self.assertRaises(ValidationError):
                load_configuration_asset_content(self.asset)

    @override_settings(
        ROOT_URLCONF="rpsd_config.server.urls",
        VALIDATION_M2M_ALLOWED_CLIENT_IDS="test-validator",
    )
    def test_download_api_returns_content_and_explicit_integrity_error(self):
        path = (
            "/exchange_agreement/api/m2m/v3/validation-assets/netex_xsd/netex/"
            f"{self.asset.version}/download"
        )
        with (
            patch(
                "rpsd_config.exchange_agreement.api.M2MClientTokenAuth.authenticate",
                return_value=None,
            ),
            patch(
                "rpsd_config.exchange_agreement.api.validate_m2m_token",
                return_value={"azp": "test-validator"},
            ),
        ):
            response = self.client.get(path, HTTP_AUTHORIZATION="Bearer test-token")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, self.content)
            self.assertEqual(
                response["X-RPSD-Checksum-SHA256"], self.asset.checksum_sha256
            )
            with patch(
                "rpsd_config.exchange_agreement.api.load_configuration_asset_content",
                side_effect=ValidationError("Mismatch", code="invalid_schema_bundle"),
            ):
                response = self.client.get(path, HTTP_AUTHORIZATION="Bearer test-token")
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["code"], "invalid_schema_bundle")
