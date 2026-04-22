# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.test import TestCase, override_settings

from .models import Company, IntegrationPrincipal
from .services.m2m_client_naming import resolve_default_m2m_client_id


class M2MClientNamingTests(TestCase):
    def test_canonical_client_id_is_deterministic_for_same_company(self):
        company = Company.objects.create(name="ATM Milano")

        first = resolve_default_m2m_client_id(company=company)
        second = resolve_default_m2m_client_id(company=company)

        self.assertEqual(first, "atm-milano-default-prod")
        self.assertEqual(first, second)

    def test_existing_default_principal_is_reused_for_retry(self):
        company = Company.objects.create(name="Trenord")
        IntegrationPrincipal.objects.create(
            company=company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="trenord-custom-prod",
            status=IntegrationPrincipal.Status.ACTIVE,
        )

        resolved = resolve_default_m2m_client_id(company=company)
        self.assertEqual(resolved, "trenord-custom-prod")

    def test_collision_uses_deterministic_fallback(self):
        company_a = Company.objects.create(name="ATM Milano")
        IntegrationPrincipal.objects.create(
            company=company_a,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="atm-milano-default-prod",
            status=IntegrationPrincipal.Status.ACTIVE,
        )
        company_b = Company.objects.create(name="ATM Milano!")

        first = resolve_default_m2m_client_id(company=company_b)
        second = resolve_default_m2m_client_id(company=company_b)

        self.assertEqual(first, second)
        self.assertEqual(first, f"atm-milano-default-prod-c{company_b.pk}")

    @override_settings(M2M_CLIENT_ID_SUFFIX="ingest-prod")
    def test_suffix_is_read_from_settings(self):
        company = Company.objects.create(name="Azienda Delta")

        resolved = resolve_default_m2m_client_id(company=company)

        self.assertEqual(resolved, "azienda-delta-ingest-prod")
