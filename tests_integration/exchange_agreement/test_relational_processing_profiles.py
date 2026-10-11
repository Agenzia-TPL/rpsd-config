# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import RequestFactory, TestCase, override_settings

from rpsd_config.admin_dataset_exchange.proxies import (
    ProcessingProfileVersionAdminProxy,
)
from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    IndicatorVersionInput,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    ProcessingProfileTransitionError,
    deprecate_processing_profile,
    duplicate_processing_profile,
    legacy_flow_profile_options,
    publish_processing_profile,
    withdraw_processing_profile,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class RelationalProcessingProfileTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="processing-profile-admin",
            password="test-password",
        )
        self.netex, self.netex_specification = self._published_specification(
            "netex", "netex-ita_v001"
        )
        self.siri, self.siri_specification = self._published_specification(
            "siri-vm", "siri-vm_v001"
        )
        self.netex_input = self.netex_specification
        self.siri_input = self.siri_specification
        indicator = Indicator.objects.create(
            code="commercial-speed",
            name="Commercial speed",
            description="Average commercial speed.",
        )
        self.indicator_version = IndicatorVersion.objects.create(
            indicator=indicator,
            code="commercial-speed_002",
            version="002",
            description="Commercial speed from planned and observed movements.",
            formula_description="Distance divided by elapsed time.",
            execution_engine="prefect",
            execution_reference="indicators/test-fixture",
            artifact_identifier="git:rpsd-flows@test-fixture",
        )
        for required_specification in [self.netex_input, self.siri_input]:
            IndicatorVersionInput.objects.get_or_create(
                indicator_version=self.indicator_version,
                dataset_specification=required_specification,
            )
        self.indicator_version = publish_indicator_version(
            self.indicator_version, actor=self.user
        )
        self.netex_flow = self._published_input_flow(
            self.netex_specification, "netex-import_002"
        )
        self.siri_flow = self._published_input_flow(
            self.siri_specification, "siri-vm-import_003", version="003"
        )
        self.orchestration = publish_orchestration_flow_version(
            OrchestrationFlowVersion.objects.create(
                code="contract-processing_002",
                version="002",
                name="Contract processing",
                description="Coordinate contract processing.",
                deployment_name="contract-processing/default",
                artifact_identifier="git:rpsd-flows@contract-processing-002",
            ),
            actor=self.user,
        )

    def _published_specification(self, dataset_code, specification_code):
        dataset = Dataset.objects.create(code=dataset_code, name=dataset_code.upper())
        specification = DatasetSpecification.objects.create(
            dataset=dataset,
            code=specification_code,
            version="001",
            description=f"{dataset_code} specification",
        )
        return dataset, publish_dataset_specification(specification, actor=self.user)

    def _published_input_flow(self, specification, code, *, version="002"):
        return publish_input_flow_version(
            InputFlowVersion.objects.create(
                dataset_specification=specification,
                code=code,
                version=version,
                name=code,
                description=f"Import {specification.dataset.code}.",
                deployment_name=f"validators/{specification.dataset.code}",
                artifact_identifier=f"git:rpsd-flows@{code}",
            ),
            actor=self.user,
        )

    def _profile(self, *, code="tpl-netex-siri_002"):
        return ProcessingProfileVersion.objects.create(
            code=code,
            version="002",
            name="TPL NeTEx and SIRI",
            description="Planned and observed service monitoring.",
            orchestration_flow_version=self.orchestration,
        )

    def _add_input(self, profile, dataset, flow):
        return ProcessingProfileInputFlow.objects.create(
            processing_profile_version=profile,
            dataset=dataset,
            input_flow_version=flow,
        )

    def _complete_profile(self):
        profile = self._profile()
        self._add_input(profile, self.netex, self.netex_flow)
        self._add_input(profile, self.siri, self.siri_flow)
        ProcessingProfileIndicatorVersion.objects.create(
            processing_profile_version=profile,
            indicator_version=self.indicator_version,
            proposed_by_default=True,
        )
        return profile

    def test_input_relation_is_consistent_and_unique_per_dataset(self):
        profile = self._profile()
        with self.assertRaises(ValidationError):
            self._add_input(profile, self.netex, self.siri_flow)

        self._add_input(profile, self.netex, self.netex_flow)
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                self._add_input(profile, self.netex, self.netex_flow)

    def test_publication_requires_published_components(self):
        profile = self._complete_profile()
        InputFlowVersion.objects.filter(pk=self.siri_flow.pk).update(
            status="deprecated"
        )
        with self.assertRaisesMessage(
            ProcessingProfileTransitionError,
            "Input flow siri-vm-import_003 is not published.",
        ):
            publish_processing_profile(profile, actor=self.user)

    def test_publication_rejects_two_versions_of_same_logical_indicator(self):
        profile = self._complete_profile()
        second = IndicatorVersion.objects.create(
            indicator=self.indicator_version.indicator,
            code="commercial-speed_003",
            version="003",
            description="Alternative technical version.",
            formula_description="Alternative formula.",
            execution_engine="prefect",
            execution_reference="indicators/test-fixture",
            artifact_identifier="git:rpsd-flows@test-fixture",
        )
        for required_specification in [self.netex_input, self.siri_input]:
            IndicatorVersionInput.objects.get_or_create(
                indicator_version=second, dataset_specification=required_specification
            )
        second = publish_indicator_version(second, actor=self.user)
        ProcessingProfileIndicatorVersion.objects.create(
            processing_profile_version=profile,
            indicator_version=second,
        )

        with self.assertRaisesMessage(
            ProcessingProfileTransitionError,
            "multiple versions of indicator commercial-speed",
        ):
            publish_processing_profile(profile, actor=self.user)

    def test_published_profile_is_an_immutable_snapshot(self):
        profile = publish_processing_profile(self._complete_profile(), actor=self.user)
        profile.name = "Changed"
        with self.assertRaises(ValidationError):
            profile.save()

        input_link = profile.input_flow_links.first()
        input_link.input_flow_version = self.siri_flow
        with self.assertRaises(ValidationError):
            input_link.save()
        with self.assertRaises(ValidationError):
            input_link.delete()

        profile = deprecate_processing_profile(profile, actor=self.user)
        profile = withdraw_processing_profile(profile, actor=self.user)
        self.assertEqual(profile.status, ProcessingProfileVersion.Status.WITHDRAWN)
        self.assertEqual(profile.status_events.count(), 3)

    def test_duplicate_is_a_complete_independent_draft(self):
        source = publish_processing_profile(self._complete_profile(), actor=self.user)
        duplicate = duplicate_processing_profile(
            source,
            code="tpl-netex-siri_003",
            version="003",
        )
        self.assertEqual(duplicate.status, ProcessingProfileVersion.Status.DRAFT)
        self.assertEqual(duplicate.input_flow_links.count(), 2)
        self.assertEqual(duplicate.indicator_version_links.count(), 1)
        self.assertTrue(duplicate.indicator_version_links.get().proposed_by_default)

        duplicate.description = "Independent next version."
        duplicate.save()
        source.refresh_from_db()
        self.assertNotEqual(duplicate.description, source.description)

    def test_read_api_exposes_business_summary_only(self):
        profile = publish_processing_profile(self._complete_profile(), actor=self.user)
        self.client.force_login(self.user)
        response = self.client.get(
            f"/exchange_agreement/api/v1/processing-profiles/{profile.code}"
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["dataset_code"] for item in payload["inputs"]], ["netex", "siri-vm"]
        )
        self.assertEqual(
            payload["indicators"][0]["indicator_version_code"],
            "commercial-speed_002",
        )
        self.assertNotIn("deployment_name", payload)
        self.assertNotIn("orchestration_flow", payload)
        self.assertNotIn("input_flow_code", payload["inputs"][0])

        draft = self._profile(code="draft-profile_001")
        missing = self.client.get(
            f"/exchange_agreement/api/v1/processing-profiles/{draft.code}"
        )
        self.assertEqual(missing.status_code, 404)

    def test_legacy_projection_has_no_scheduling_or_retention_policy(self):
        profile = publish_processing_profile(self._complete_profile(), actor=self.user)
        options = legacy_flow_profile_options(profile)
        self.assertEqual(options["data_ingestion"]["netex"]["flow"], "netex-import_002")
        self.assertEqual(
            options["data_ingestion"]["netex"]["deployment_name"],
            "validators/netex",
        )
        self.assertEqual(options["data_retention"], {})
        serialized = str(options).lower()
        for forbidden in ("frequency", "cron", "trigger", "interval", "days"):
            self.assertNotIn(forbidden, serialized)

        self.client.force_login(self.user)
        response = self.client.get(
            f"/exchange_agreement/api/v1/flow-profiles/{profile.code}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["options"], options)

    def test_schema_contains_no_scheduler_or_dag_fields(self):
        forbidden = {
            "cron",
            "frequency",
            "interval",
            "trigger_mode",
            "nodes",
            "dependencies",
            "delivery_frequency",
        }
        profile_fields = {
            field.name for field in ProcessingProfileVersion._meta.get_fields()
        }
        input_fields = {
            field.name for field in ProcessingProfileInputFlow._meta.get_fields()
        }
        self.assertFalse(profile_fields & forbidden)
        self.assertFalse(input_fields & forbidden)

    def test_admin_permissions_are_limited_to_platform_roles(self):
        regular = get_user_model().objects.create_user(username="profile-regular")
        platform = get_user_model().objects.create_user(username="profile-platform")
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="profile-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        model_admin = admin.site._registry[ProcessingProfileVersionAdminProxy]
        request = RequestFactory().get("/")
        request.user = regular
        self.assertFalse(model_admin.has_add_permission(request))
        request.user = platform
        self.assertTrue(model_admin.has_add_permission(request))
