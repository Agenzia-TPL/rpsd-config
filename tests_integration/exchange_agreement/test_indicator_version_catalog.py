# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from rpsd_config.admin_dataset_exchange.proxies import IndicatorVersionAdminProxy
from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    IndicatorVersionInput,
    IndicatorVersionStatusEvent,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    deprecate_indicator_version,
    publish_indicator_version,
    withdraw_indicator_version,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class IndicatorVersionCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="indicator-admin",
            password="test-password",
        )
        self.netex = self._published_specification(
            dataset_code="netex",
            specification_code="netex-ita_v001",
        )
        self.siri = self._published_specification(
            dataset_code="siri-vm",
            specification_code="siri-vm_v001",
        )
        self.netex_input = self.netex
        self.siri_input = self.siri
        self.indicator = Indicator.objects.create(
            code="commercial-speed",
            name="Commercial speed",
            description="Average commercial speed.",
        )

    def _published_specification(self, *, dataset_code, specification_code):
        dataset = Dataset.objects.create(code=dataset_code, name=dataset_code.upper())
        specification = DatasetSpecification.objects.create(
            dataset=dataset,
            code=specification_code,
            version="001",
            description=f"{dataset_code} specification",
        )
        return publish_dataset_specification(specification, actor=self.user)

    def _version(self, *, code="commercial-speed_001", version="001", **kwargs):
        values = {
            "indicator": self.indicator,
            "code": code,
            "version": version,
            "description": "Commercial speed technical definition.",
            "formula_description": "Distance divided by elapsed travel time.",
            "execution_engine": "prefect",
            "execution_reference": "indicators/test-fixture",
            "artifact_identifier": "git:rpsd-flows@test-fixture",
        }
        values.update(kwargs)
        return IndicatorVersion.objects.create(**values)

    def test_indicator_identity_and_versions_are_separate_and_unique(self):
        first = self._version()
        second = self._version(code="commercial-speed_002", version="002")

        self.assertEqual(first.indicator, second.indicator)
        self.assertEqual(self.indicator.versions.count(), 2)
        with self.assertRaises(ValidationError):
            self._version(code="commercial-speed-alias_002", version="002")
        with self.assertRaises(ValidationError):
            Indicator.objects.create(
                code="Commercial Speed",
                name="Invalid",
                description="Invalid non-canonical code.",
            )

    def test_contracts_are_closed_versioned_references(self):
        version = self._version(
            input_contract={"identifier": "commercial-speed-input-v1"},
            output_contract={
                "schema_version": 1,
                "identifier": "commercial-speed-output-v1",
                "description": "Line and journey commercial speed.",
            },
        )
        self.assertEqual(version.input_contract["schema_version"], 1)
        self.assertEqual(version.input_contract["description"], "")

        with self.assertRaises(ValidationError):
            self._version(
                code="invalid-contract_002",
                version="002",
                input_contract={
                    "identifier": "contract-v1",
                    "python": "run()",
                },
            )

    def test_execution_reference_is_required_for_publication_but_not_draft(self):
        external = self._version(
            execution_engine="", execution_reference="", artifact_identifier=""
        )
        with self.assertRaises(ValidationError):
            publish_indicator_version(external, actor=self.user)
        self.assertEqual(external.status, "draft")

        incomplete = self._version(
            code="commercial-speed_002",
            version="002",
            execution_engine=IndicatorVersion.ExecutionEngine.DBT,
        )
        with self.assertRaises(ValidationError):
            publish_indicator_version(incomplete, actor=self.user)

        with self.assertRaises(ValidationError):
            self._version(
                code="commercial-speed_003",
                version="003",
                execution_engine="",
                execution_reference="dbt/model",
                artifact_identifier="",
            )
        with self.assertRaises(ValidationError):
            self._version(
                code="commercial-speed_004",
                version="004",
                execution_engine=IndicatorVersion.ExecutionEngine.DBT,
                execution_reference="dbt/model",
                artifact_identifier="not-an-artifact",
            )

    def test_lifecycle_is_audited_and_published_version_is_immutable(self):
        version = self._version(
            execution_engine=IndicatorVersion.ExecutionEngine.PREFECT,
            execution_reference="rpsd-monitoring/commercial-speed",
            artifact_identifier="dbt:rpsd-monitoring/commercial_speed@sha256:abc123",
        )
        for required_specification in [self.netex_input, self.siri_input]:
            IndicatorVersionInput.objects.get_or_create(
                indicator_version=version, dataset_specification=required_specification
            )
        version = publish_indicator_version(version, actor=self.user)

        event = IndicatorVersionStatusEvent.objects.get(indicator_version=version)
        self.assertEqual(event.changed_by, self.user)
        self.assertEqual(event.to_status, IndicatorVersion.Status.PUBLISHED)
        version.formula_description = "Changed formula"
        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            version.delete()

        version = deprecate_indicator_version(version, actor=self.user)
        version = withdraw_indicator_version(version, actor=self.user)
        self.assertEqual(version.status, IndicatorVersion.Status.WITHDRAWN)
        self.assertEqual(version.status_events.count(), 3)

    def test_model_contains_no_results_or_scheduling_fields(self):
        field_names = {field.name for field in IndicatorVersion._meta.get_fields()}
        self.assertFalse(
            field_names
            & {
                "result",
                "measure",
                "cron",
                "frequency",
                "interval",
                "trigger",
            }
        )

    def test_admin_permissions_are_limited_to_platform_roles(self):
        regular = get_user_model().objects.create_user(username="indicator-regular")
        platform = get_user_model().objects.create_user(username="indicator-platform")
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="indicator-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        model_admin = admin.site._registry[IndicatorVersionAdminProxy]
        request = RequestFactory().get("/")
        request.user = regular
        self.assertFalse(model_admin.has_add_permission(request))
        request.user = platform
        self.assertTrue(model_admin.has_add_permission(request))
