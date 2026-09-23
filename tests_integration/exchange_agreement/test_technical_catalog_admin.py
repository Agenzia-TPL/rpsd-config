# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    OrchestrationFlowVersion,
    ProcessingProfileVersion,
)


class TechnicalCatalogAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.platform_admin = user_model.objects.create_user(
            username="catalog-platform-admin",
            password="test-password",
            is_staff=True,
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="catalog-platform-admin-keycloak",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.ordinary_staff = user_model.objects.create_user(
            username="catalog-ordinary-staff",
            password="test-password",
            is_staff=True,
        )
        self.dataset = Dataset.objects.create(code="netex", name="NeTEx")
        self.specification = DatasetSpecification.objects.create(
            dataset=self.dataset,
            code="netex-it-v001",
            version="001",
            description="Prima specifica NeTEx italiana.",
        )

    def test_anonymous_user_can_open_admin_login(self):
        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="login-form"')

    def test_platform_admin_can_open_all_target_catalogs(self):
        self.client.force_login(self.platform_admin)

        model_names = (
            "datasetadminproxy",
            "datasetspecificationadminproxy",
            "requirementfragmentadminproxy",
            "indicatoradminproxy",
            "indicatorversionadminproxy",
            "inputflowversionadminproxy",
            "orchestrationflowversionadminproxy",
            "processingprofileversionadminproxy",
        )
        for model_name in model_names:
            with self.subTest(model=model_name):
                response = self.client.get(
                    reverse(f"admin:admin_dataset_exchange_{model_name}_changelist")
                )
                self.assertEqual(response.status_code, 200)

    def test_ordinary_staff_cannot_open_target_catalog(self):
        self.client.force_login(self.ordinary_staff)

        response = self.client.get(
            reverse("admin:admin_dataset_exchange_datasetadminproxy_changelist")
        )

        self.assertEqual(response.status_code, 403)

    def test_publish_action_uses_lifecycle_service_and_records_actor(self):
        self.client.force_login(self.platform_admin)
        response = self.client.post(
            reverse(
                "admin:admin_dataset_exchange_datasetspecificationadminproxy_changelist"
            ),
            {
                "action": "publish_selected",
                "_selected_action": [str(self.specification.pk)],
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.specification.refresh_from_db()
        self.assertEqual(
            self.specification.status,
            DatasetSpecification.Status.PUBLISHED,
        )
        self.assertEqual(self.specification.published_by, self.platform_admin)
        event = self.specification.status_events.get()
        self.assertEqual(event.from_status, DatasetSpecification.Status.DRAFT)
        self.assertEqual(event.to_status, DatasetSpecification.Status.PUBLISHED)
        self.assertEqual(event.changed_by, self.platform_admin)

    def test_published_specification_is_read_only_and_not_deletable(self):
        self.client.force_login(self.platform_admin)
        self.client.post(
            reverse(
                "admin:admin_dataset_exchange_datasetspecificationadminproxy_changelist"
            ),
            {
                "action": "publish_selected",
                "_selected_action": [str(self.specification.pk)],
            },
        )

        response = self.client.get(
            reverse(
                "admin:admin_dataset_exchange_datasetspecificationadminproxy_change",
                args=[self.specification.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("code", response.context["adminform"].form.fields)
        self.assertFalse(response.context["has_delete_permission"])
        self.assertNotContains(response, "Add another Dataset specification asset")

    def test_processing_profile_editor_exposes_both_compositions(self):
        orchestration = OrchestrationFlowVersion.objects.create(
            code="contract-consolidation-v001",
            version="001",
            name="Consolidamento contratto",
            description="Orchestratore generale del contratto.",
        )
        profile = ProcessingProfileVersion.objects.create(
            code="netex-siri-commercial-speed-v001",
            version="001",
            name="NeTEx e SIRI per velocita commerciale",
            description="Profilo tecnico di esempio.",
            orchestration_flow_version=orchestration,
        )
        self.client.force_login(self.platform_admin)

        response = self.client.get(
            reverse(
                "admin:admin_dataset_exchange_processingprofileversionadminproxy_change",
                args=[profile.pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Processing profile input flows")
        self.assertContains(response, "Processing profile indicator versions")

    def test_platform_configuration_links_to_technical_catalogs(self):
        self.client.force_login(self.platform_admin)

        response = self.client.get(reverse("exchange_agreement:platform-configuration"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cataloghi tecnici")
        self.assertContains(response, reverse("admin:index"))
