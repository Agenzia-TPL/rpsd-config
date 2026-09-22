# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
)
from rpsd_config.exchange_agreement.services.api_usage import (
    api_usage_count,
    reset_api_usage_counts,
)
from rpsd_config.server.m2m_auth import M2MAuthContext

from .runtime_configuration_fixtures import (
    RuntimeInputFixture,
    install_approved_runtime_configuration,
)


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
        reset_api_usage_counts()
        self.configuration_admin = get_user_model().objects.create_superuser(
            username="golden-configuration-admin",
            password="test-password",
        )
        self.agency = Agency.objects.create(name="Golden Agency")
        self.company = Company.objects.create(name="Golden Company")
        self.lot = Lot.objects.create(
            agency=self.agency,
            short_description="GOLDEN-LOT",
            description="Golden contract lot",
        )
        self.contract = Contract.objects.create(
            contract_code="CTR-GOLDEN-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=30),
            status=Contract.ContractStatus.ACTIVE,
        )
        self.flow_profile, self.revision = install_approved_runtime_configuration(
            contract=self.contract,
            actor=self.configuration_admin,
            profile_code="golden-flow-profile_001",
            profile_version="001",
            profile_name="Golden Flow Profile",
            profile_description="Stable profile used by the M2M v1 contract tests.",
            orchestration_deployment_name="golden-contract-processing/default",
            inputs=(
                RuntimeInputFixture(
                    category="netex",
                    dataset_name="NeTEx",
                    dataset_description="Scheduled public transport data.",
                    specification_code="netex-ita_v001",
                    specification_version="001",
                    flow_code="netex-golden_001",
                    flow_version="001",
                    deployment_name="netex-import/netex-ita-v001",
                    flow_description="NeTEx ingest",
                    selected=True,
                    required=True,
                ),
                RuntimeInputFixture(
                    category="siri",
                    dataset_name="SIRI",
                    dataset_description="Real-time public transport data.",
                    specification_code="siri-vm_v001",
                    specification_version="001",
                    flow_code="siri-golden_001",
                    flow_version="001",
                    deployment_name="siri-import/siri-vm-v001",
                    flow_description="SIRI ingest",
                ),
            ),
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
                self.assertEqual(response.headers["Deprecation"], "true")
                self.assertIn('rel="successor-version"', response.headers["Link"])
                self.assertTrue(response.headers["X-Correlation-ID"])
                self.assertEqual(
                    api_usage_count(
                        version="v1",
                        endpoint=kind.replace("_", "-"),
                        outcome="success",
                    ),
                    1,
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
