# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
    DatasetSpecificationStatusEvent,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    DatasetSpecificationTransitionError,
    deprecate_dataset_specification,
    publish_dataset_specification,
    withdraw_dataset_specification,
)
from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    INITIAL_DATASET_SPECIFICATIONS,
    ensure_initial_dataset_catalog,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class VersionedDatasetCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="dataset-admin",
            password="test-password",
        )
        self.dataset = Dataset.objects.create(
            code="siri-vm",
            name="SIRI VM",
            description="Vehicle monitoring data.",
        )

    def _specification(
        self,
        *,
        code: str = "siri-vm_v001",
        version: str = "001",
    ) -> DatasetSpecification:
        return DatasetSpecification.objects.create(
            format="xml",
            dataset=self.dataset,
            code=code,
            version=version,
            description="SIRI VM initial specification.",
            metadata={"standard": "SIRI"},
        )

    def _active_asset(self) -> ConfigurationAsset:
        return ConfigurationAsset.objects.create(
            asset_type=ConfigurationAsset.AssetType.SIRI_PROFILE,
            what="siri-vm",
            label="SIRI VM schema",
            version=1,
            status=ConfigurationAsset.Status.ACTIVE,
            is_active=True,
            storage_url="s3://not-accessed/siri-vm.xsd",
            storage_provider="s3",
            storage_key="schemas/siri-vm.xsd",
            original_filename="siri-vm.xsd",
            content_type="application/xml",
            checksum_sha256="a" * 64,
            size_bytes=123,
        )

    def test_dataset_code_is_canonical_and_unique(self):
        self.assertEqual(self.dataset.code, "siri-vm")
        with self.assertRaises(ValidationError):
            Dataset.objects.create(code="SIRI VM", name="Invalid")
        with self.assertRaises(ValidationError):
            Dataset.objects.create(code="siri-vm", name="Duplicate")

    def test_dataset_supports_multiple_unique_versions(self):
        first = self._specification()
        second = self._specification(code="siri-vm_v002", version="002")

        self.assertEqual(first.dataset, second.dataset)
        self.assertEqual(self.dataset.specifications.count(), 2)
        with self.assertRaises(ValidationError):
            self._specification(code="siri-vm-alias_v002", version="002")

    def test_lifecycle_is_audited_and_published_specification_is_immutable(self):
        specification = self._specification()

        specification = publish_dataset_specification(
            specification,
            actor=self.user,
        )

        self.assertEqual(specification.status, DatasetSpecification.Status.PUBLISHED)
        self.assertEqual(specification.published_by, self.user)
        self.assertIsNotNone(specification.published_at)
        event = DatasetSpecificationStatusEvent.objects.get(
            dataset_specification=specification
        )
        self.assertEqual(event.from_status, DatasetSpecification.Status.DRAFT)
        self.assertEqual(event.to_status, DatasetSpecification.Status.PUBLISHED)
        self.assertEqual(event.changed_by, self.user)

        specification.description = "Changed in place"
        with self.assertRaises(ValidationError):
            specification.save()
        with self.assertRaises(ValidationError):
            specification.delete()

        specification = deprecate_dataset_specification(
            specification,
            actor=self.user,
        )
        specification = withdraw_dataset_specification(
            specification,
            actor=self.user,
        )
        self.assertEqual(specification.status, DatasetSpecification.Status.WITHDRAWN)
        self.assertEqual(specification.status_events.count(), 3)
        with self.assertRaises(DatasetSpecificationTransitionError):
            publish_dataset_specification(specification, actor=self.user)

    def test_required_asset_must_be_active_and_is_protected_after_publication(self):
        specification = self._specification()
        asset = self._active_asset()
        asset.is_active = False
        asset.status = ConfigurationAsset.Status.STORED
        asset.save()
        link = DatasetSpecificationAsset.objects.create(
            dataset_specification=specification,
            configuration_asset=asset,
            role=DatasetSpecificationAsset.Role.VALIDATION_SCHEMA,
            required=True,
        )

        with self.assertRaises(DatasetSpecificationTransitionError):
            publish_dataset_specification(specification, actor=self.user)

        asset.is_active = True
        asset.status = ConfigurationAsset.Status.ACTIVE
        asset.save()
        specification = publish_dataset_specification(
            specification,
            actor=self.user,
        )

        with self.assertRaises(ValidationError):
            link.delete()
        with self.assertRaises(ProtectedError):
            asset.delete()
        self.assertEqual(specification.assets.get(), asset)

    def test_asset_code_is_independent_of_logical_dataset(self):
        specification = self._specification()
        asset = ConfigurationAsset.objects.create(
            asset_type=ConfigurationAsset.AssetType.NETEX_XSD,
            what="netex",
            version=1,
            status=ConfigurationAsset.Status.ACTIVE,
            is_active=True,
            storage_url="s3://not-accessed/netex.xsd",
            storage_provider="s3",
            original_filename="netex.xsd",
            checksum_sha256="b" * 64,
        )

        link = DatasetSpecificationAsset.objects.create(
            dataset_specification=specification,
            configuration_asset=asset,
            role=DatasetSpecificationAsset.Role.VALIDATION_SCHEMA,
        )
        self.assertEqual(link.configuration_asset, asset)

    def test_bootstrap_is_idempotent_and_does_not_duplicate_versions(self):
        first = ensure_initial_dataset_catalog()
        second = ensure_initial_dataset_catalog()

        expected = len(INITIAL_DATASET_SPECIFICATIONS)
        self.assertEqual(len(first), expected)
        self.assertEqual(len(second), expected)
        self.assertEqual(DatasetSpecification.objects.count(), expected)
        self.assertFalse(
            DatasetSpecification.objects.exclude(
                status=DatasetSpecification.Status.PUBLISHED
            ).exists()
        )

    def test_read_api_exposes_only_published_specifications(self):
        published = publish_dataset_specification(
            self._specification(),
            actor=self.user,
        )
        self._specification(code="siri-vm_v002", version="002")
        self.client.force_login(self.user)

        response = self.client.get("/exchange_agreement/api/v1/datasets")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["code"], self.dataset.code)
        self.assertEqual(
            [item["code"] for item in payload[0]["specifications"]],
            [published.code],
        )

    def test_publishing_does_not_open_or_interpret_asset_content(self):
        specification = self._specification()
        asset = self._active_asset()
        DatasetSpecificationAsset.objects.create(
            dataset_specification=specification,
            configuration_asset=asset,
            role=DatasetSpecificationAsset.Role.VALIDATION_SCHEMA,
        )

        published = publish_dataset_specification(specification, actor=self.user)

        self.assertEqual(published.status, DatasetSpecification.Status.PUBLISHED)
