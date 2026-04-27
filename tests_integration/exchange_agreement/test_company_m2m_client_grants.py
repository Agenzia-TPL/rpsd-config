# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
)
from rpsd_config.exchange_agreement.services.m2m_grants import (
    can_client_ingest_for_contract,
)
from rpsd_config.exchange_agreement.services.m2m_provisioning import (
    provision_default_m2m_principal_for_company,
)
from rpsd_config.exchange_agreement.services.m2m_secret_store import (
    reveal_client_secret,
    store_client_secret,
)
from rpsd_config.server.keycloak_admin import KeycloakClientRef


class _FakeM2MKeycloak:
    def __init__(self):
        self.clients: dict[str, KeycloakClientRef] = {}
        self.secrets: dict[str, str] = {}
        self.deleted: list[str] = []
        self.disabled: list[str] = []

    def create_confidential_m2m_client(
        self,
        *,
        client_id: str,
        name: str,
        enabled=True,
    ):
        client = self.clients.get(client_id)
        if client is None:
            client = KeycloakClientRef(
                id=f"uuid-{len(self.clients) + 1}",
                client_id=client_id,
                name=name,
                enabled=enabled,
            )
            self.clients[client_id] = client
            self.secrets[client.id] = f"secret-{client_id}"
        return client

    def get_client_secret(self, *, client_uuid: str):
        return self.secrets[client_uuid]

    def rotate_client_secret(self, *, client_uuid: str):
        self.secrets[client_uuid] = f"rotated-{client_uuid}"
        return self.secrets[client_uuid]

    def delete_client(self, *, client_uuid: str):
        self.deleted.append(client_uuid)

    def disable_client(self, *, client_uuid: str):
        self.disabled.append(client_uuid)


@override_settings(
    M2M_CLIENT_SECRET_ENCRYPTION_KEY="test-secret-key",
    M2M_CLIENT_SECRET_KEY_ID="test-key",
)
class CompanyM2MClientGrantsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.actor = user_model.objects.create_user(
            username="m2m-admin",
            email="m2m-admin@example.com",
        )
        self.agency = Agency.objects.create(name="Agency M2M")
        self.company = Company.objects.create(name="Company M2M")
        self.other_company = Company.objects.create(name="Other Company M2M")
        self.lot = Lot.objects.create(description="Lot M2M")
        self.contract = Contract.objects.create(
            contract_code="CTR-M2M-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=Contract.ContractStatus.ACTIVE,
        )

    def test_secret_store_encrypts_and_reveals_secret(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment="prod",
            keycloak_client_id="company-m2m-default-prod",
            keycloak_client_uuid="uuid-1",
            created_by=self.actor,
        )

        store_client_secret(principal, client_secret="plain-secret")
        principal.refresh_from_db()

        self.assertNotEqual(principal.client_secret_ciphertext, "plain-secret")
        self.assertEqual(principal.client_secret_key_id, "test-key")
        self.assertEqual(reveal_client_secret(principal), "plain-secret")

    def test_grant_rejects_cross_company_contract(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.other_company,
            name="default",
            environment="prod",
            keycloak_client_id="other-m2m-default-prod",
            keycloak_client_uuid="uuid-2",
        )
        grant = IntegrationGrant(
            principal=principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )

        with self.assertRaises(ValidationError):
            grant.full_clean()

    def test_decision_allows_active_principal_and_grant(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment="prod",
            keycloak_client_id="allow-m2m-default-prod",
            keycloak_client_uuid="uuid-3",
        )
        IntegrationGrant.objects.create(
            principal=principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            data_category="netex",
        )

        decision = can_client_ingest_for_contract(
            keycloak_client_id=principal.keycloak_client_id,
            contract_code=self.contract.contract_code,
            data_category="netex",
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "grant-active")

    def test_provisioning_creates_principal_and_encrypted_secret(self):
        keycloak = _FakeM2MKeycloak()

        result = provision_default_m2m_principal_for_company(
            company=self.company,
            actor=self.actor,
            keycloak=keycloak,
        )

        self.assertTrue(result.created)
        principal = result.principal
        self.assertEqual(principal.company, self.company)
        self.assertTrue(principal.keycloak_client_id.endswith("default-prod"))
        self.assertNotEqual(
            principal.client_secret_ciphertext,
            f"secret-{principal.keycloak_client_id}",
        )
        self.assertEqual(
            reveal_client_secret(principal),
            f"secret-{principal.keycloak_client_id}",
        )
