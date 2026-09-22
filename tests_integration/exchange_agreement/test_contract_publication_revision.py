# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from rpsd_config.exchange_agreement.api import (
    _contract_publication_detail_schema,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_contract_revision,
)
from rpsd_config.exchange_agreement.services.publication import (
    PublishContractError,
    publish_contract,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


class ContractPublicationRevisionTests(_ContractRevisionFixtureMixin, TestCase):
    def _approved_current_revision(self):
        return self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )

    def test_publication_is_exact_copy_of_current_approved_revision(self):
        revision = self._approved_current_revision()

        publication = publish_contract(contract=self.contract, user=self.user)

        self.assertEqual(publication.configuration_revision, revision)
        self.assertEqual(publication.snapshot, revision.configuration_snapshot)
        self.assertEqual(
            publication.snapshot_schema_version,
            revision.snapshot_schema_version,
        )
        self.assertEqual(publication.snapshot_checksum, revision.snapshot_checksum)
        self.assertRegex(publication.snapshot_checksum, r"^sha256:[0-9a-f]{64}$")

    def test_republication_is_versioned_without_changing_the_snapshot(self):
        revision = self._approved_current_revision()

        first = publish_contract(contract=self.contract, user=self.user)
        second = publish_contract(contract=self.contract, user=self.user)

        self.assertEqual(first.publication_version, 1)
        self.assertEqual(second.publication_version, 2)
        self.assertEqual(second.configuration_revision, revision)
        self.assertEqual(second.snapshot_checksum, first.snapshot_checksum)

    def test_publication_resolves_the_revision_current_on_the_server_date(self):
        first_revision = self._approved_current_revision()
        future_date = timezone.localdate() + timedelta(days=10)
        second_revision = approve_contract_revision(
            self._revision(
                number=2,
                valid_from=future_date,
                replaces=first_revision,
            ),
            actor=self.user,
        )

        current_publication = publish_contract(
            contract=self.contract,
            user=self.user,
        )
        with patch(
            "rpsd_config.exchange_agreement.services.publication.timezone.localdate",
            return_value=future_date,
        ):
            future_publication = publish_contract(
                contract=self.contract,
                user=self.user,
            )

        self.assertEqual(current_publication.configuration_revision, first_revision)
        self.assertEqual(future_publication.configuration_revision, second_revision)

    def test_contract_without_current_approved_revision_cannot_be_published(self):
        with self.assertRaisesMessage(
            PublishContractError,
            "no current approved configuration revision",
        ):
            publish_contract(contract=self.contract, user=self.user)

    def test_publication_content_is_immutable(self):
        self._approved_current_revision()
        publication = publish_contract(contract=self.contract, user=self.user)
        publication.snapshot = {"tampered": True}

        with self.assertRaises(ValidationError):
            publication.save()
        with self.assertRaises(ValidationError):
            publication.delete()

    def test_publication_api_projection_identifies_the_revision(self):
        revision = self._approved_current_revision()
        publication = publish_contract(contract=self.contract, user=self.user)

        payload = _contract_publication_detail_schema(publication).model_dump()

        self.assertEqual(payload["configuration_revision_code"], revision.code)
        self.assertEqual(
            payload["configuration_revision_number"],
            revision.revision_number,
        )
        self.assertEqual(
            payload["configuration_valid_from"],
            revision.valid_from.isoformat(),
        )
        self.assertEqual(payload["snapshot"], revision.configuration_snapshot)
