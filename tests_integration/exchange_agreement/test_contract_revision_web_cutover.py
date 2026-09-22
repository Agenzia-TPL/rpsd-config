# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    AgencyMembership,
    Authority,
    AuthorityMembership,
    Contract,
    ContractConfigurationRevision,
    Lot,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


class ContractRevisionWebCutoverTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.agency_editor = user_model.objects.create_user(
            username="revision-web-agency-editor",
            password="test-password",
        )
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.agency_editor,
            role=AgencyMembership.Role.AGENCY_EDITOR,
            status=AgencyMembership.Status.ACTIVE,
            created_by=self.user,
        )
        self.authority_viewer = user_model.objects.create_user(
            username="revision-web-authority-viewer",
            password="test-password",
        )
        self.authority = Authority.objects.create(
            name="Regione test revisioni",
            authority_type=Authority.AuthorityType.REGION,
        )
        AuthorityMembership.objects.create(
            authority=self.authority,
            user=self.authority_viewer,
            created_by=self.user,
        )
        Contract.objects.filter(pk=self.contract.pk).update(
            governing_authority=self.authority
        )
        self.contract.refresh_from_db()

    def _agency_detail_url(self):
        return reverse(
            "exchange_agreement:agency-contract-detail",
            args=[self.agency.agency_key, self.contract.contract_code],
        )

    def _direct_detail_url(self):
        return reverse(
            "exchange_agreement:user-contract-detail",
            args=[self.contract.contract_code],
        )

    def test_contract_creation_keeps_technical_profile_outside_contract(self):
        new_lot = Lot.objects.create(
            agency=self.agency,
            short_description="LOT-WEB",
            description="Web cutover lot",
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "exchange_agreement:agency-contract-create",
                args=[self.agency.agency_key],
            ),
            {
                "action": "create-contract",
                "contract_code": "CTR-WEB-CUTOVER",
                "contractor_company_id": self.company.pk,
                "governing_authority_id": self.authority.pk,
                "lot_id": new_lot.pk,
                "start_date": self.contract.start_date.isoformat(),
                "end_date": self.contract.end_date.isoformat(),
                "status": Contract.ContractStatus.DRAFT,
                "flow_profile_id": "legacy-value-must-be-ignored",
            },
        )

        self.assertEqual(response.status_code, 200)
        created = Contract.objects.get(contract_code="CTR-WEB-CUTOVER")
        self.assertEqual(created.governing_authority, self.authority)
        self.assertIsNone(created.flow_profile)
        self.assertContains(response, "configurazione tecnica")

    def test_agency_creates_guided_draft_and_platform_admin_approves_it(self):
        self.client.force_login(self.agency_editor)
        created = self.client.post(
            self._agency_detail_url(),
            {
                "action": "create-contract-revision",
                "processing_profile_id": self.profile.pk,
                "valid_from": self.contract.start_date.isoformat(),
                "change_reason": "Prima configurazione web.",
            },
        )
        self.assertEqual(created.status_code, 200)
        self.assertContains(created, "pronta per la verifica tecnica")
        revision = ContractConfigurationRevision.objects.get(contract=self.contract)
        self.assertEqual(revision.status, ContractConfigurationRevision.Status.DRAFT)
        self.assertEqual(revision.input_selections.count(), 2)
        self.assertEqual(revision.indicator_configurations.count(), 1)

        self.client.force_login(self.user)
        queue_url = reverse("exchange_agreement:platform-revision-queue")
        queue = self.client.get(queue_url)
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, revision.code)
        self.assertNotContains(queue, "Controlli da risolvere")

        with patch(
            "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
            return_value=self.contract.start_date,
        ):
            approved = self.client.post(
                queue_url,
                {
                    "action": "approve-contract-revision",
                    "revision_id": revision.pk,
                },
            )
        self.assertEqual(approved.status_code, 200)
        self.assertContains(approved, "approvata")
        revision.refresh_from_db()
        self.assertEqual(
            revision.status,
            ContractConfigurationRevision.Status.APPROVED,
        )
        self.assertTrue(revision.snapshot_checksum.startswith("sha256:"))

        detail = self.client.get(self._agency_detail_url())
        self.assertContains(detail, "Configurazioni del contratto")
        self.assertContains(detail, revision.code)
        self.assertContains(detail, self.profile.name)

    def test_authority_membership_is_strictly_read_only(self):
        self.client.force_login(self.authority_viewer)
        detail = self.client.get(self._direct_detail_url())
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.contract.contract_code)
        self.assertNotContains(detail, "Crea una nuova bozza")
        self.assertNotContains(detail, "Mostra secret client")

        denied = self.client.post(
            self._direct_detail_url(),
            {
                "action": "create-contract-revision",
                "processing_profile_id": self.profile.pk,
                "valid_from": self.contract.start_date.isoformat(),
            },
        )
        self.assertEqual(denied.status_code, 403)

        queue_denied = self.client.get(
            reverse("exchange_agreement:platform-revision-queue")
        )
        self.assertEqual(queue_denied.status_code, 403)
