# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    FlowProfile,
    Lot,
    OperationalFlow,
)
from rpsd_config.exchange_agreement.services.flow_profiles import (
    NETEX_ONLY_PROFILE_CODE,
    STANDARD_TPL_PROFILE_CODE,
    ensure_standard_flow_profiles,
    ensure_standard_operational_flows,
)


class FlowProfileGovernanceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="admin",
        )
        self.agency = Agency.objects.create(name="Agenzia TPL Milano")
        self.company = Company.objects.create(name="ATM Milano")
        self.lot = Lot.objects.create(
            agency=self.agency,
            short_description="1",
            description="Lotto 1",
        )

    def test_standard_flow_profile_initialization_is_idempotent(self):
        first = ensure_standard_flow_profiles()
        second = ensure_standard_flow_profiles()

        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(
            FlowProfile.objects.filter(
                code__in={STANDARD_TPL_PROFILE_CODE, NETEX_ONLY_PROFILE_CODE}
            ).count(),
            2,
        )
        self.assertTrue(
            FlowProfile.objects.get(code=STANDARD_TPL_PROFILE_CODE).is_active
        )
        self.assertTrue(OperationalFlow.objects.filter(code="siri-pt_001").exists())

    def test_contract_create_page_uses_extended_default_profile(self):
        ensure_standard_flow_profiles()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "exchange_agreement:agency-contract-create",
                args=[self.agency.agency_key],
            ),
            {
                "action": "create-contract",
                "contract_code": "CTR-FLOW-001",
                "contractor_company_id": str(self.company.id),
                "lot_id": str(self.lot.id),
                "start_date": "2026-05-01",
                "end_date": "",
                "tender_id": "",
                "status": Contract.ContractStatus.ACTIVE,
                "flow_profile_id": str(
                    FlowProfile.objects.get(code=STANDARD_TPL_PROFILE_CODE).id
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        contract = Contract.objects.get(contract_code="CTR-FLOW-001")
        self.assertEqual(contract.flow_profile.code, STANDARD_TPL_PROFILE_CODE)

    def test_contract_create_page_blocks_without_active_profiles(self):
        FlowProfile.objects.all().delete()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                "exchange_agreement:agency-contract-create",
                args=[self.agency.agency_key],
            ),
            {
                "action": "create-contract",
                "contract_code": "CTR-FLOW-002",
                "contractor_company_id": str(self.company.id),
                "lot_id": str(self.lot.id),
                "start_date": "2026-05-01",
                "end_date": "",
                "tender_id": "",
                "status": Contract.ContractStatus.ACTIVE,
                "flow_profile_id": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seleziona un profilo flussi attivo")
        self.assertFalse(Contract.objects.filter(contract_code="CTR-FLOW-002").exists())

    def test_used_flow_profile_blocks_technical_modification(self):
        profile = ensure_standard_flow_profiles()[0]
        Contract.objects.create(
            contract_code="CTR-FLOW-003",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2026, 5, 1),
            status=Contract.ContractStatus.ACTIVE,
            flow_profile=profile,
        )

        profile.options = {
            **profile.options,
            "general_profile": "changed",
        }

        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_standard_profiles_drive_ingest_categories(self):
        profiles = {profile.code: profile for profile in ensure_standard_flow_profiles()}

        standard_ingestion = profiles[STANDARD_TPL_PROFILE_CODE].options[
            "data_ingestion"
        ]
        netex_only_ingestion = profiles[NETEX_ONLY_PROFILE_CODE].options[
            "data_ingestion"
        ]

        self.assertTrue(standard_ingestion["netex"]["active"])
        self.assertTrue(standard_ingestion["siri-pt"]["active"])
        self.assertEqual(standard_ingestion["siri-pt"]["flow"], "siri-pt_001")
        self.assertTrue(netex_only_ingestion["netex"]["active"])
        self.assertFalse(netex_only_ingestion["siri-pt"]["active"])

    def test_flow_profile_rejects_unknown_operational_flow(self):
        ensure_standard_operational_flows()
        profile = FlowProfile(
            code="invalid-flow-profile",
            name="Invalid flow profile",
            options={
                "general_profile": "invalid",
                "planned_master": {
                    "netex": {
                        "active": True,
                        "flow": "netex_001",
                        "description": "Netex master",
                    }
                },
                "data_ingestion": {
                    "siri-pt": {
                        "active": True,
                        "flow": "missing_001",
                        "description": "Missing flow",
                    }
                },
                "data_retention": {
                    "planned": {
                        "days": 365,
                        "flow": "retention-planned",
                        "description": "Retention",
                    }
                },
            },
        )

        with self.assertRaises(ValidationError):
            profile.full_clean()

    def test_flow_profile_rejects_flow_for_wrong_what(self):
        ensure_standard_operational_flows()
        profile = FlowProfile(
            code="wrong-what-flow-profile",
            name="Wrong what flow profile",
            options={
                "general_profile": "invalid",
                "planned_master": {
                    "netex": {
                        "active": True,
                        "flow": "netex_001",
                        "description": "Netex master",
                    }
                },
                "data_ingestion": {
                    "siri-pt": {
                        "active": True,
                        "flow": "netex_001",
                        "description": "Wrong flow",
                    }
                },
                "data_retention": {
                    "planned": {
                        "days": 365,
                        "flow": "retention-planned",
                        "description": "Retention",
                    }
                },
            },
        )

        with self.assertRaises(ValidationError):
            profile.full_clean()
