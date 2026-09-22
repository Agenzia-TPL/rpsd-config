# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    ContractIndicator,
    Dataset,
    FlowProfile,
    IndicatorDef,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
    OperationalFlow,
    Structure,
)
from rpsd_config.server.m2m_auth import M2MAuthContext


@override_settings(
    ROOT_URLCONF="rpsd_config.server.urls",
    M2M_API_ENABLED=True,
    M2M_API_CLIENT_ID_CLAIM="azp",
)
class M2MApiV1ContractTests(TestCase):
    """Protect the M2M v1 API consumed by the ingest service."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fixture_path = Path(__file__).with_name("fixtures") / "m2m_api_v1_contract.json"
        cls.golden = json.loads(fixture_path.read_text(encoding="utf-8"))

    def setUp(self):
        today = date.today()
        self.agency = Agency.objects.create(name="Golden Agency")
        self.company = Company.objects.create(name="Golden Company")
        self.lot = Lot.objects.create(
            short_description="GOLDEN-LOT",
            description="Golden contract lot",
        )
        OperationalFlow.objects.create(
            code="netex-golden_001",
            deployment_name="netex-import/netex-ita-v001",
            supported_what="netex",
            description="Golden NeTEx flow",
        )
        OperationalFlow.objects.create(
            code="siri-golden_001",
            deployment_name="siri-import/siri-vm-v001",
            supported_what="siri",
            description="Golden SIRI flow",
        )
        self.flow_profile = FlowProfile.objects.create(
            code="golden-flow-profile",
            name="Golden Flow Profile",
            description="Stable profile used by the M2M v1 contract tests.",
            options={
                "general_profile": "golden-v1",
                "planned_master": {},
                "data_ingestion": {
                    "netex": {
                        "flow": "netex-golden_001",
                        "active": True,
                        "description": "NeTEx ingest",
                    },
                    "siri": {
                        "flow": "siri-golden_001",
                        "active": False,
                        "description": "SIRI ingest",
                    },
                },
                "data_retention": {},
            },
            is_active=True,
        )
        self.contract = Contract.objects.create(
            contract_code="CTR-GOLDEN-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=30),
            status=Contract.ContractStatus.ACTIVE,
            flow_profile=self.flow_profile,
        )
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="golden-client",
            environment="prod",
            keycloak_client_id="golden-company-ingest-prod",
            keycloak_client_uuid="golden-client-uuid",
        )
        self.grant = IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        dataset = Dataset.objects.create(
            code="netex",
            name="NeTEx",
            description="Scheduled public transport data.",
        )
        self.structure = Structure.objects.create(
            dataset=dataset,
            name="scheduled-journey-movement",
            description="Scheduled movements required by the indicator.",
            definition={
                "xpath": "//netex:ServiceJourney",
                "fields": ["LineRef", "JourneyPatternRef"],
            },
        )
        indicator = IndicatorDef.objects.create(
            code="commercial-speed_001",
            type="QUALITY",
            name="Commercial speed",
        )
        indicator.structures.add(self.structure)
        ContractIndicator.objects.create(
            contract=self.contract,
            indicator=indicator,
        )
        self.client = Client()

    def _auth_context(self) -> M2MAuthContext:
        return M2MAuthContext(
            principal=self.principal,
            client_id=self.principal.keycloak_client_id,
            claims={"azp": self.principal.keycloak_client_id},
        )

    def _get(self, path: str, *, authenticated: bool = True):
        if not authenticated:
            return self.client.get(path)
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token",
            return_value=self._auth_context(),
        ):
            return self.client.get(path, HTTP_AUTHORIZATION="Bearer golden-token")

    def _path(self, suffix: str) -> str:
        return (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.contract.contract_code}/{suffix}"
        )

    def _assert_golden(self, response, expected: dict, *, kind: str) -> None:
        payload = response.json()
        if kind == "required_inputs":
            for item in payload["required_inputs"]:
                for structure in item["structures"]:
                    structure["id"] = "<structure-id>"
        elif kind == "ingest_authorization" and payload.get("grant_id") is not None:
            payload["grant_id"] = "<grant-id>"

        self.assertEqual(response.status_code, expected["status"])
        self.assertEqual(payload, expected["payload"])

    def test_happy_path_matches_versioned_golden_contracts(self):
        cases = {
            "flow_profile": self._path("flow-profile"),
            "required_inputs": self._path("required-inputs"),
            "ingest_authorization": self._path(
                "ingest-authorization?data_category=netex"
            ),
        }

        for kind, path in cases.items():
            with self.subTest(kind=kind):
                response = self._get(path)
                self._assert_golden(
                    response,
                    self.golden["happy_path"][kind],
                    kind=kind,
                )

    def test_unauthenticated_request_matches_golden_rejection(self):
        response = self._get(self._path("flow-profile"), authenticated=False)

        self._assert_golden(
            response,
            self.golden["rejections"]["authentication_required"],
            kind="error",
        )

    def test_missing_grant_matches_golden_rejection(self):
        self.grant.delete()

        for suffix in ("flow-profile", "required-inputs"):
            with self.subTest(suffix=suffix):
                response = self._get(self._path(suffix))
                self._assert_golden(
                    response,
                    self.golden["rejections"]["grant_missing"],
                    kind="error",
                )

    def test_unsupported_category_matches_golden_rejection(self):
        response = self._get(self._path("ingest-authorization?data_category=gtfs"))

        self._assert_golden(
            response,
            self.golden["rejections"]["unsupported_data_category"],
            kind="error",
        )

    def test_inactive_category_matches_golden_rejection(self):
        response = self._get(self._path("ingest-authorization?data_category=siri"))

        self._assert_golden(
            response,
            self.golden["rejections"]["inactive_data_category"],
            kind="error",
        )
