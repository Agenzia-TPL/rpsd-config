# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    AgencyMembership,
    ContractConfigurationRevision,
    ContractMembership,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    can_approve_contract_revision,
    can_prepare_contract_revision,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    create_revision_draft,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


class Feature018ConfigUiTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.platform_admin = user_model.objects.create_user(
            username="feature-018-platform-admin",
            password="test-password",
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="feature-018-platform-admin-kc",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.agency_editor = user_model.objects.create_user(
            username="feature-018-agency-editor",
            password="test-password",
        )
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.agency_editor,
            role=AgencyMembership.Role.AGENCY_EDITOR,
            status=AgencyMembership.Status.ACTIVE,
            created_by=self.user,
        )
        self.contract_admin = user_model.objects.create_user(
            username="feature-018-contract-admin",
            password="test-password",
        )
        ContractMembership.objects.create(
            contract=self.contract,
            user=self.contract_admin,
            role=ContractMembership.Role.CONTRACT_ADMIN,
            created_by=self.user,
        )

    def test_platform_role_publishes_catalogs_but_does_not_own_contract(self):
        self.assertFalse(
            can_prepare_contract_revision(
                user=self.platform_admin,
                contract=self.contract,
            )
        )
        self.assertFalse(
            can_approve_contract_revision(
                user=self.platform_admin,
                contract=self.contract,
            )
        )
        self.assertTrue(
            can_approve_contract_revision(
                user=self.contract_admin,
                contract=self.contract,
            )
        )

        self.client.force_login(self.platform_admin)
        queue = self.client.get(
            reverse("exchange_agreement:platform-revision-queue")
        )
        self.assertEqual(queue.status_code, 200)
        denied = self.client.post(
            reverse("exchange_agreement:platform-revision-queue"),
            {"action": "approve-contract-revision"},
        )
        self.assertEqual(denied.status_code, 403)

    def test_revision_ui_selects_subset_and_derives_mandatory_inputs(self):
        revision = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_editor,
        )
        detail_url = reverse(
            "exchange_agreement:contract-revision-detail",
            args=[self.contract.contract_code, revision.pk],
        )
        self.client.force_login(self.agency_editor)

        cleared = self.client.post(
            detail_url,
            {"action": "save-revision-composition"},
        )
        self.assertEqual(cleared.status_code, 200)
        revision.refresh_from_db()
        self.assertEqual(revision.indicator_configurations.count(), 0)
        self.assertEqual(revision.input_selections.count(), 0)

        selected = self.client.post(
            detail_url,
            {
                "action": "save-revision-composition",
                "indicator_link_ids": [str(self.profile_indicator.pk)],
            },
        )
        self.assertEqual(selected.status_code, 200)
        revision.refresh_from_db()
        self.assertEqual(revision.indicator_configurations.count(), 1)
        self.assertEqual(revision.input_selections.count(), 2)
        self.assertContains(selected, "obbligatorio")

        self.client.force_login(self.contract_admin)
        with patch(
            "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
            return_value=self.contract.start_date,
        ):
            approved = self.client.post(
                detail_url,
                {"action": "approve-contract-revision"},
            )
        self.assertEqual(approved.status_code, 200)
        revision.refresh_from_db()
        self.assertEqual(
            revision.status,
            ContractConfigurationRevision.Status.APPROVED,
        )
        self.assertEqual(revision.approved_by, self.contract_admin)

    def test_product_catalog_ui_hides_removed_json_and_shows_assets(self):
        self.client.force_login(self.platform_admin)
        flow_list = self.client.get(
            reverse(
                "exchange_agreement:technical-catalog-list",
                args=["input-flows"],
            )
        )
        self.assertEqual(flow_list.status_code, 200)
        self.assertNotContains(flow_list, "invocation_contract")
        self.assertNotContains(flow_list, "compatibility")

        specification = self.client.get(
            reverse(
                "exchange_agreement:technical-catalog-detail",
                args=["dataset-specifications", self.netex_specification.pk],
            )
        )
        self.assertEqual(specification.status_code, 200)
        self.assertContains(specification, "Asset della specifica")
        self.assertContains(specification, self.netex_asset.checksum_sha256)

        profile = self.client.get(
            reverse(
                "exchange_agreement:technical-catalog-detail",
                args=["processing-profiles", self.profile.pk],
            )
        )
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, "Input ammessi")
        self.assertContains(profile, "Indicatori ammessi")
        self.assertContains(profile, "preselezionato")

        immutable = self.client.post(
            reverse(
                "exchange_agreement:technical-catalog-detail",
                args=["processing-profiles", self.profile.pk],
            ),
            {
                "action": "remove-indicator",
                "link_id": self.profile_indicator.pk,
            },
        )
        self.assertEqual(immutable.status_code, 200)
        self.assertContains(immutable, "immutabile")
        self.assertTrue(
            self.profile.indicator_version_links.filter(
                pk=self.profile_indicator.pk
            ).exists()
        )
