# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
)
from rpsd_config.exchange_agreement.services.contract_drafts import (
    delete_revision_draft,
    update_draft_contract_dates,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    ContractRevisionPermissionError,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


class ContractDraftTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        Contract.objects.filter(pk=self.contract.pk).update(
            status=Contract.ContractStatus.DRAFT
        )
        self.contract.refresh_from_db()
        self.reader = get_user_model().objects.create_user(username="draft-reader")

    def revision(self):
        return self._revision(number=1, valid_from=self.contract.start_date)

    def test_date_edit_is_available_and_persists(self):
        self.client.force_login(self.user)
        url = reverse(
            "exchange_agreement:agency-contract-detail",
            args=[self.agency.agency_key, self.contract.contract_code],
        )
        self.assertContains(self.client.get(url), "Salva date")
        start = self.contract.start_date + timedelta(days=2)
        response = self.client.post(
            url,
            {
                "action": "update-contract-dates",
                "start_date": start.isoformat(),
                "end_date": self.contract.end_date.isoformat(),
            },
        )
        self.assertContains(response, "Date del contratto aggiornate")
        self.contract.refresh_from_db()
        self.assertEqual(self.contract.start_date, start)

    def test_date_change_rejects_invalid_range_and_outside_draft(self):
        old_start = self.contract.start_date
        self.revision()
        for start, end in (
            (self.contract.end_date, old_start),
            (old_start + timedelta(days=1), self.contract.end_date),
        ):
            with self.assertRaises(ValidationError):
                update_draft_contract_dates(
                    self.contract, start_date=start, end_date=end, actor=self.user
                )
            self.contract.refresh_from_db()
            self.assertEqual(self.contract.start_date, old_start)

    def test_approved_revision_blocks_contract_date_change(self):
        revision = self.revision()
        self._approve_first_revision(revision)
        with self.assertRaises(ValidationError):
            update_draft_contract_dates(
                self.contract,
                start_date=self.contract.start_date,
                end_date=self.contract.end_date + timedelta(days=1),
                actor=self.user,
            )

    def test_active_contract_dates_cannot_be_changed(self):
        Contract.objects.filter(pk=self.contract.pk).update(
            status=Contract.ContractStatus.ACTIVE
        )
        with self.assertRaises(ValidationError):
            update_draft_contract_dates(
                self.contract,
                start_date=self.contract.start_date,
                end_date=self.contract.end_date,
                actor=self.user,
            )

    def test_unauthorized_actor_cannot_edit_dates_or_delete_revision(self):
        revision = self.revision()
        with self.assertRaises(ContractRevisionPermissionError):
            delete_revision_draft(revision, actor=self.reader)
        with self.assertRaises(ContractRevisionPermissionError):
            update_draft_contract_dates(
                self.contract,
                start_date=self.contract.start_date,
                end_date=self.contract.end_date,
                actor=self.reader,
            )

    def test_delete_requires_confirmation_and_preserves_contract(self):
        revision = self.revision()
        self.client.force_login(self.user)
        url = reverse(
            "exchange_agreement:contract-revision-detail",
            args=[self.contract.contract_code, revision.pk],
        )
        self.assertContains(self.client.get(url), "Elimina bozza")
        self.assertContains(
            self.client.post(url, {"action": "delete-revision-draft"}),
            "Conferma l&#x27;eliminazione",
        )
        self.assertTrue(
            ContractConfigurationRevision.objects.filter(pk=revision.pk).exists()
        )
        response = self.client.post(
            url, {"action": "delete-revision-draft", "confirm_delete": "yes"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            ContractConfigurationRevision.objects.filter(pk=revision.pk).exists()
        )
        self.assertTrue(Contract.objects.filter(pk=self.contract.pk).exists())

    def test_delete_rechecks_approved_status_from_database(self):
        revision = self.revision()
        stale = ContractConfigurationRevision.objects.get(pk=revision.pk)
        self._approve_first_revision(revision)
        with self.assertRaises(ValidationError):
            delete_revision_draft(stale, actor=self.user)
        self.assertTrue(
            ContractConfigurationRevision.objects.filter(pk=revision.pk).exists()
        )
