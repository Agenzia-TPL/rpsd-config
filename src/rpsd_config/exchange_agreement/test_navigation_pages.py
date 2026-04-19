# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyMembership,
    Company,
    Contract,
    Lot,
)


class NavigationAndPagesTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.platform_admin = user_model.objects.create_user(
            username="platform-admin-nav",
            email="platform-admin-nav@example.com",
            password="platform-pass",
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="kc-platform-admin-nav",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )

        self.regular_user = user_model.objects.create_user(
            username="agency-user-nav",
            email="agency-user-nav@example.com",
            password="agency-pass",
        )
        self.agency = Agency.objects.create(name="ATPL Test Menu")
        self.other_agency = Agency.objects.create(name="ATPL Another Menu")
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.regular_user,
            role=AgencyMembership.Role.AGENCY_EDITOR,
            created_by=self.platform_admin,
        )
        SocialAccount.objects.create(
            user=self.regular_user,
            provider="openid_connect",
            uid="kc-agency-user-nav",
            extra_data={"id_token": {"groups": [f"/rpsd/{self.agency.agency_key}/editor"]}},
        )
        company = Company.objects.create(name="Azienda TPL Navigation")
        lot = Lot.objects.create(description="Lotto test navigation")
        self.contract = Contract.objects.create(
            contract_code="NAV-001",
            client_agency=self.agency,
            contractor_company=company,
            lot=lot,
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )

    def test_sidebar_for_regular_user_hides_platform_configuration(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:user-area"))
        self.assertContains(response, reverse("exchange_agreement:agencies"))
        self.assertNotContains(
            response, reverse("exchange_agreement:platform-configuration")
        )

    def test_sidebar_for_platform_admin_shows_platform_configuration(self):
        self.client.force_login(self.platform_admin)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:user-area"))
        self.assertContains(response, reverse("exchange_agreement:agencies"))
        self.assertContains(
            response, reverse("exchange_agreement:platform-configuration")
        )

    def test_agencies_page_lists_user_memberships(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("exchange_agreement:agencies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.agency.name)
        self.assertContains(response, self.agency.agency_key)
        self.assertContains(
            response, reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
        )
        self.assertNotContains(response, self.other_agency.name)

    def test_agencies_page_for_platform_admin_shows_all_agencies(self):
        self.client.force_login(self.platform_admin)
        response = self.client.get(reverse("exchange_agreement:agencies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.agency.name)
        self.assertContains(response, self.other_agency.name)

    def test_agency_detail_and_contract_pages(self):
        self.client.force_login(self.regular_user)
        detail = self.client.get(
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, self.contract.contract_code)
        self.assertContains(
            detail,
            reverse(
                "exchange_agreement:agency-contract-detail",
                args=[self.agency.agency_key, self.contract.contract_code],
            ),
        )

        contract_detail = self.client.get(
            reverse(
                "exchange_agreement:agency-contract-detail",
                args=[self.agency.agency_key, self.contract.contract_code],
            )
        )
        self.assertEqual(contract_detail.status_code, 200)
        self.assertContains(contract_detail, self.contract.contract_code)

    def test_agency_detail_forbidden_out_of_scope(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(
            reverse(
                "exchange_agreement:agency-detail",
                args=[self.other_agency.agency_key],
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_agency_invitation_create_preselected_by_agency_key(self):
        self.client.force_login(self.platform_admin)
        response = self.client.get(
            reverse("exchange_agreement:agency-invitation-create")
            + f"?agency_key={self.agency.agency_key}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.agency.agency_key)
        self.assertContains(response, 'name="selected_agency_key"')

    def test_platform_configuration_requires_platform_admin_group(self):
        self.client.force_login(self.regular_user)
        denied = self.client.get(reverse("exchange_agreement:platform-configuration"))
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.platform_admin)
        allowed = self.client.get(reverse("exchange_agreement:platform-configuration"))
        self.assertEqual(allowed.status_code, 200)
        self.assertContains(allowed, "Configurazione Piattaforma")
