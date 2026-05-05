# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    ContractMembership,
    FlowProfile,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
)
from rpsd_config.server.m2m_auth import (
    M2MAuthContext,
    M2MTokenValidationError,
    authenticate_m2m_token,
    extract_m2m_client_id,
)


@override_settings(
    ROOT_URLCONF="rpsd_config.server.urls",
    M2M_API_ENABLED=True,
    M2M_API_CLIENT_ID_CLAIM="azp",
)
class CompanyM2MApiAuthTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="contract-user",
            email="contract-user@example.com",
            first_name="Contract",
            last_name="User",
        )
        self.agency = Agency.objects.create(name="Agency M2M API")
        self.company = Company.objects.create(name="Company M2M API")
        self.other_company = Company.objects.create(name="Other Company M2M API")
        self.lot = Lot.objects.create(
            short_description="M2M-API",
            description="Lot M2M API",
        )
        self.other_lot = Lot.objects.create(
            short_description="M2M-API-OTHER",
            description="Other Lot M2M API",
        )
        self.flow_profile = FlowProfile.objects.create(
            code="m2m-api-flow-profile",
            name="M2M API Flow Profile",
            options={
                "general_profile": "m2m-api",
                "planned_master": {},
                "data_ingestion": {
                    "netex": {
                        "flow": "ingest-flow/netex",
                        "active": True,
                        "description": "NeTEx ingest",
                    },
                    "siri": {
                        "flow": "ingest-flow/siri",
                        "active": False,
                        "description": "SIRI ingest",
                    },
                },
                "data_retention": {},
            },
            is_active=True,
        )
        self.contract = Contract.objects.create(
            contract_code="CTR-M2M-API-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=Contract.ContractStatus.ACTIVE,
            flow_profile=self.flow_profile,
        )
        self.other_contract = Contract.objects.create(
            contract_code="CTR-M2M-API-OTHER",
            client_agency=self.agency,
            contractor_company=self.other_company,
            lot=self.other_lot,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=Contract.ContractStatus.ACTIVE,
        )
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment="prod",
            keycloak_client_id="company-m2m-api-default-prod",
            keycloak_client_uuid="uuid-m2m-api",
        )
        IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        ContractMembership.objects.create(
            contract=self.contract,
            user=self.user,
            role=ContractMembership.Role.CONTRACT_READER,
        )
        self.client = Client()

    def _auth_context(self):
        return M2MAuthContext(
            principal=self.principal,
            client_id=self.principal.keycloak_client_id,
            claims={"azp": self.principal.keycloak_client_id},
        )

    def _get(self, path: str):
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token",
            return_value=self._auth_context(),
        ):
            return self.client.get(
                path,
                HTTP_AUTHORIZATION="Bearer test-token",
            )

    def test_extract_m2m_client_id_uses_azp(self):
        self.assertEqual(
            extract_m2m_client_id({"azp": self.principal.keycloak_client_id}),
            self.principal.keycloak_client_id,
        )

    def test_authenticate_m2m_token_resolves_active_principal(self):
        with patch(
            "rpsd_config.server.m2m_auth.validate_m2m_token",
            return_value={"azp": self.principal.keycloak_client_id},
        ):
            context = authenticate_m2m_token("token")

        self.assertEqual(context.principal, self.principal)
        self.assertEqual(context.client_id, self.principal.keycloak_client_id)

    def test_authenticate_m2m_token_rejects_revoked_principal(self):
        self.principal.status = IntegrationPrincipal.Status.REVOKED
        self.principal.save(update_fields=["status", "updated_at"])

        with patch(
            "rpsd_config.server.m2m_auth.validate_m2m_token",
            return_value={"azp": self.principal.keycloak_client_id},
        ):
            with self.assertRaises(M2MTokenValidationError) as exc:
                authenticate_m2m_token("token")

        self.assertEqual(exc.exception.reason, "principal-revoked")

    def test_m2m_me_does_not_require_user_session(self):
        response = self._get("/exchange_agreement/api/m2m/v1/me")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["keycloak_client_id"],
            self.principal.keycloak_client_id,
        )
        self.assertEqual(payload["company"]["id"], self.company.id)

    def test_m2m_contracts_returns_only_granted_contracts(self):
        response = self._get("/exchange_agreement/api/m2m/v1/contracts")

        self.assertEqual(response.status_code, 200)
        contract_codes = {item["contract_code"] for item in response.json()}
        self.assertEqual(contract_codes, {self.contract.contract_code})
        self.assertNotIn(self.other_contract.contract_code, contract_codes)

    def test_m2m_contract_detail_requires_grant(self):
        path = (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.other_contract.contract_code}"
        )
        response = self._get(path)

        self.assertEqual(response.status_code, 404)

    def test_m2m_ingest_authorization_allows_active_data_category(self):
        path = (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.contract.contract_code}/ingest-authorization"
        )
        response = self._get(f"{path}?data_category=netex")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["contract_code"], self.contract.contract_code)
        self.assertEqual(payload["data_category"], "netex")
        self.assertEqual(payload["flow_profile_code"], self.flow_profile.code)
        self.assertEqual(payload["flow"], "ingest-flow/netex")

    def test_m2m_ingest_authorization_rejects_inactive_data_category(self):
        path = (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.contract.contract_code}/ingest-authorization"
        )
        response = self._get(f"{path}?data_category=siri")

        self.assertEqual(response.status_code, 400)

    def test_m2m_ingest_authorization_requires_contract_grant(self):
        path = (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.other_contract.contract_code}/ingest-authorization"
        )
        response = self._get(f"{path}?data_category=netex")

        self.assertEqual(response.status_code, 404)

    def test_m2m_contract_users_returns_contract_memberships(self):
        path = (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.contract.contract_code}/users"
        )
        response = self._get(
            path,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["username"], self.user.username)
        self.assertEqual(payload[0]["contract_codes"], [self.contract.contract_code])
