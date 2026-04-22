# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakClientCredentials,
    KeycloakClientRef,
)

from .models import Company, IntegrationPrincipal
from .services.m2m_provisioning import (
    M2MProvisioningError,
    provision_default_m2m_principal_for_company,
)
from .services.m2m_secret_store import M2MSecretStorageError, reveal_principal_secret


class _FakeKeycloakM2M:
    def __init__(self, *, created: bool = True):
        self.created = created
        self.create_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.disable_calls: list[str] = []
        self.raise_on_delete = False
        self.raise_on_disable = False

    def create_confidential_m2m_client(self, *, client_id: str, name: str, description: str):
        self.create_calls.append(client_id)
        return KeycloakClientCredentials(
            client=KeycloakClientRef(
                id="kc-client-001",
                client_id=client_id,
                enabled=True,
            ),
            secret="kc-secret-001",
            created=self.created,
        )

    def delete_client(self, *, client_uuid: str) -> bool:
        self.delete_calls.append(client_uuid)
        if self.raise_on_delete:
            raise KeycloakAdminAPIError(
                method="DELETE",
                url=f"http://keycloak/admin/realms/rpsd/clients/{client_uuid}",
                status_code=500,
                detail="delete failed",
            )
        return True

    def disable_client(self, *, client_uuid: str):
        self.disable_calls.append(client_uuid)
        if self.raise_on_disable:
            raise KeycloakAdminAPIError(
                method="PUT",
                url=f"http://keycloak/admin/realms/rpsd/clients/{client_uuid}",
                status_code=500,
                detail="disable failed",
            )
        return KeycloakClientRef(
            id=client_uuid,
            client_id="disabled-client",
            enabled=False,
        )


@override_settings(
    M2M_SECRET_ENCRYPTION_KEY="unit-test-secret-key",
    M2M_SECRET_ENCRYPTION_KEY_ID="unit-test-key-id",
)
class M2MProvisioningSagaTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.actor = self.user_model.objects.create_user(
            username="m2m-provision-actor",
            email="m2m-provision-actor@example.com",
            password="test-password",
        )
        self.company = Company.objects.create(name="Azienda Provisioning Test")

    def test_happy_path_creates_integration_principal(self):
        fake_keycloak = _FakeKeycloakM2M(created=True)

        result = provision_default_m2m_principal_for_company(
            company=self.company,
            actor=self.actor,
            keycloak=fake_keycloak,
        )

        self.assertTrue(result.principal_created)
        self.assertTrue(result.keycloak_client_created)
        self.assertEqual(result.client_secret, "kc-secret-001")
        self.assertEqual(result.principal.company_id, self.company.id)
        self.assertEqual(result.principal.name, "default")
        self.assertEqual(result.principal.environment, IntegrationPrincipal.Environment.PROD)
        self.assertEqual(result.principal.keycloak_client_uuid, "kc-client-001")
        self.assertTrue(result.principal.client_secret_ciphertext)
        self.assertNotEqual(
            result.principal.client_secret_ciphertext,
            "kc-secret-001",
        )
        self.assertEqual(result.principal.client_secret_key_id, "unit-test-key-id")
        self.assertIsNotNone(result.principal.client_secret_updated_at)
        self.assertEqual(
            reveal_principal_secret(principal=result.principal),
            "kc-secret-001",
        )
        self.assertEqual(fake_keycloak.delete_calls, [])
        self.assertEqual(fake_keycloak.disable_calls, [])

    def test_existing_default_principal_short_circuits_keycloak(self):
        existing = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-provisioning-test-default-prod",
            keycloak_client_uuid="kc-existing-001",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.actor,
        )
        fake_keycloak = _FakeKeycloakM2M(created=True)

        result = provision_default_m2m_principal_for_company(
            company=self.company,
            actor=self.actor,
            keycloak=fake_keycloak,
        )

        self.assertEqual(result.principal.id, existing.id)
        self.assertFalse(result.principal_created)
        self.assertFalse(result.keycloak_client_created)
        self.assertIsNone(result.client_secret)
        self.assertEqual(fake_keycloak.create_calls, [])

    def test_failure_post_keycloak_compensates_with_delete(self):
        fake_keycloak = _FakeKeycloakM2M(created=True)

        with patch(
            "rpsd_config.exchange_agreement.services.m2m_provisioning.IntegrationPrincipal.objects.create",
            side_effect=IntegrityError("simulated db failure"),
        ):
            with self.assertRaises(M2MProvisioningError) as ctx:
                provision_default_m2m_principal_for_company(
                    company=self.company,
                    actor=self.actor,
                    keycloak=fake_keycloak,
                )

        self.assertEqual(ctx.exception.compensation_action, "deleted")
        self.assertEqual(fake_keycloak.delete_calls, ["kc-client-001"])
        self.assertEqual(fake_keycloak.disable_calls, [])
        self.assertEqual(IntegrationPrincipal.objects.count(), 0)

    def test_failure_post_keycloak_fallbacks_to_disable_when_delete_fails(self):
        fake_keycloak = _FakeKeycloakM2M(created=True)
        fake_keycloak.raise_on_delete = True

        with patch(
            "rpsd_config.exchange_agreement.services.m2m_provisioning.IntegrationPrincipal.objects.create",
            side_effect=IntegrityError("simulated db failure"),
        ):
            with self.assertRaises(M2MProvisioningError) as ctx:
                provision_default_m2m_principal_for_company(
                    company=self.company,
                    actor=self.actor,
                    keycloak=fake_keycloak,
                )

        self.assertEqual(ctx.exception.compensation_action, "disabled")
        self.assertEqual(fake_keycloak.delete_calls, ["kc-client-001"])
        self.assertEqual(fake_keycloak.disable_calls, ["kc-client-001"])
        self.assertEqual(IntegrationPrincipal.objects.count(), 0)

    def test_failure_post_keycloak_marks_compensation_failed_when_disable_fails(self):
        fake_keycloak = _FakeKeycloakM2M(created=True)
        fake_keycloak.raise_on_delete = True
        fake_keycloak.raise_on_disable = True

        with patch(
            "rpsd_config.exchange_agreement.services.m2m_provisioning.IntegrationPrincipal.objects.create",
            side_effect=IntegrityError("simulated db failure"),
        ):
            with self.assertRaises(M2MProvisioningError) as ctx:
                provision_default_m2m_principal_for_company(
                    company=self.company,
                    actor=self.actor,
                    keycloak=fake_keycloak,
                )

        self.assertEqual(ctx.exception.compensation_action, "failed")
        self.assertEqual(fake_keycloak.delete_calls, ["kc-client-001"])
        self.assertEqual(fake_keycloak.disable_calls, ["kc-client-001"])
        self.assertEqual(IntegrationPrincipal.objects.count(), 0)

    def test_secret_storage_failure_triggers_compensation(self):
        fake_keycloak = _FakeKeycloakM2M(created=True)

        with patch(
            "rpsd_config.exchange_agreement.services.m2m_provisioning.store_principal_secret",
            side_effect=M2MSecretStorageError("cannot encrypt secret"),
        ):
            with self.assertRaises(M2MProvisioningError) as ctx:
                provision_default_m2m_principal_for_company(
                    company=self.company,
                    actor=self.actor,
                    keycloak=fake_keycloak,
                )

        self.assertEqual(ctx.exception.compensation_action, "deleted")
        self.assertEqual(fake_keycloak.delete_calls, ["kc-client-001"])
        self.assertEqual(fake_keycloak.disable_calls, [])
        self.assertEqual(IntegrationPrincipal.objects.count(), 0)
