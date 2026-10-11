# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from django.core.management import call_command
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    ContractPublication,
    ProcessingProfileVersion,
)


@override_settings(DEBUG=True)
class TargetDevelopmentSeedTests(TestCase):
    def test_seed_is_complete_and_idempotent(self):
        call_command("seed_target_demo", verbosity=0)
        call_command("seed_target_demo", verbosity=0)

        contract = Contract.objects.get(contract_code="DEMO-CONTRACT-001")
        revision = ContractConfigurationRevision.objects.get(contract=contract)
        publication = ContractPublication.objects.get(contract=contract)
        profile = ProcessingProfileVersion.objects.get(code="validation-demo_001")

        self.assertEqual(
            revision.status,
            ContractConfigurationRevision.Status.APPROVED,
        )
        self.assertEqual(profile.status, ProcessingProfileVersion.Status.PUBLISHED)
        self.assertEqual(revision.snapshot_schema_version, "canonical-json-v2")
        self.assertEqual(
            len(revision.configuration_snapshot["effective_indicators"]), 2
        )
        self.assertTrue(
            profile.indicator_version_links.get().indicator_version.dependency_links.exists()
        )
        self.assertEqual(publication.configuration_revision, revision)
        self.assertEqual(publication.snapshot, revision.configuration_snapshot)
        self.assertEqual(publication.snapshot_checksum, revision.snapshot_checksum)
        self.assertEqual(profile.input_flow_links.count(), 2)
        self.assertEqual(profile.indicator_version_links.count(), 1)
        self.assertEqual(revision.input_selections.count(), 2)
        self.assertEqual(
            set(
                revision.input_selections.values_list(
                    "processing_profile_input_flow__dataset__code",
                    flat=True,
                )
            ),
            {"netex", "siri-vm"},
        )
