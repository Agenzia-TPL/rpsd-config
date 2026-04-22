# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Company, IntegrationPrincipal
from .services.m2m_secret_store import (
    M2MSecretStorageError,
    reveal_principal_secret,
    store_principal_secret,
)


@override_settings(
    M2M_SECRET_ENCRYPTION_KEY="phase3-secret-key",
    M2M_SECRET_ENCRYPTION_KEY_ID="phase3-key-id",
)
class M2MSecretStoreTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.actor = self.user_model.objects.create_user(
            username="m2m-secret-actor",
            email="m2m-secret-actor@example.com",
            password="test-password",
        )
        self.company = Company.objects.create(name="Azienda Secret Store Test")
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-secret-store-test-default-prod",
            keycloak_client_uuid="kc-secret-store-001",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.actor,
        )

    def test_store_encrypts_secret_and_reveal_roundtrip(self):
        store_principal_secret(
            principal=self.principal,
            raw_secret="m2m-super-secret",
            mark_rotation=False,
        )
        self.principal.refresh_from_db()

        self.assertTrue(self.principal.client_secret_ciphertext)
        self.assertNotEqual(
            self.principal.client_secret_ciphertext,
            "m2m-super-secret",
        )
        self.assertEqual(self.principal.client_secret_key_id, "phase3-key-id")
        self.assertIsNotNone(self.principal.client_secret_updated_at)
        self.assertIsNone(self.principal.last_secret_rotation_at)
        self.assertEqual(
            reveal_principal_secret(principal=self.principal),
            "m2m-super-secret",
        )

    def test_store_with_rotation_updates_rotation_timestamp(self):
        store_principal_secret(
            principal=self.principal,
            raw_secret="rotated-secret",
            mark_rotation=True,
        )
        self.principal.refresh_from_db()

        self.assertIsNotNone(self.principal.last_secret_rotation_at)
        self.assertIsNotNone(self.principal.client_secret_updated_at)
        self.assertEqual(
            self.principal.last_secret_rotation_at,
            self.principal.client_secret_updated_at,
        )

    def test_reveal_returns_none_when_secret_not_stored(self):
        self.assertIsNone(reveal_principal_secret(principal=self.principal))

    @override_settings(M2M_SECRET_ENCRYPTION_KEY="wrong-key-material")
    def test_reveal_raises_if_encryption_key_changes(self):
        # Save encrypted secret with baseline key.
        with override_settings(
            M2M_SECRET_ENCRYPTION_KEY="phase3-secret-key",
            M2M_SECRET_ENCRYPTION_KEY_ID="phase3-key-id",
        ):
            store_principal_secret(
                principal=self.principal,
                raw_secret="secret-before-key-rotation",
            )
        self.principal.refresh_from_db()

        with self.assertRaises(M2MSecretStorageError):
            reveal_principal_secret(principal=self.principal)
