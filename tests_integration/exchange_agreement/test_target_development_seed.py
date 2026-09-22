# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from django.core.management import call_command
from django.test import TestCase

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    ContractPublication,
    ProcessingProfileVersion,
)


class TargetDevelopmentSeedTests(TestCase):
    def test_seed_is_complete_and_idempotent(self):
        call_command("seed_target_demo", verbosity=0)
        call_command("seed_target_demo", verbosity=0)

        contract = Contract.objects.get(contract_code="DEMO-CONTRACT-001")
        revision = ContractConfigurationRevision.objects.get(contract=contract)
        publication = ContractPublication.objects.get(contract=contract)
        profile = ProcessingProfileVersion.objects.get(
            code="netex-siri-commercial-speed_001"
        )

        self.assertEqual(
            revision.status,
            ContractConfigurationRevision.Status.APPROVED,
        )
        self.assertEqual(profile.status, ProcessingProfileVersion.Status.PUBLISHED)
        self.assertEqual(publication.configuration_revision, revision)
        self.assertEqual(publication.snapshot, revision.configuration_snapshot)
        self.assertEqual(publication.snapshot_checksum, revision.snapshot_checksum)
        self.assertEqual(profile.input_flow_links.count(), 2)
        self.assertEqual(profile.indicator_version_links.count(), 1)
