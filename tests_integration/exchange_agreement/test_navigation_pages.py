# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import resolve, reverse

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyMembership,
    Company,
    Contract,
    ContractMembership,
    IntegrationPrincipal,
    Lot,
)
from rpsd_config.exchange_agreement.services.m2m_secret_store import (
    store_client_secret,
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
        self.agency_admin = user_model.objects.create_user(
            username="agency-admin-nav",
            email="agency-admin-nav@example.com",
            password="agency-admin-pass",
        )
        self.local_superuser = user_model.objects.create_superuser(
            username="local-superuser-nav",
            email="local-superuser-nav@example.com",
            password="super-pass",
        )
        self.agency = Agency.objects.create(name="ATPL Test Menu")
        self.other_agency = Agency.objects.create(name="ATPL Another Menu")
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.regular_user,
            role=AgencyMembership.Role.AGENCY_EDITOR,
            created_by=self.platform_admin,
        )
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.agency_admin,
            role=AgencyMembership.Role.AGENCY_ADMIN,
            created_by=self.platform_admin,
        )
        SocialAccount.objects.create(
            user=self.regular_user,
            provider="openid_connect",
            uid="kc-agency-user-nav",
            extra_data={
                "id_token": {"groups": [f"/rpsd/{self.agency.agency_key}/editor"]}
            },
        )
        SocialAccount.objects.create(
            user=self.agency_admin,
            provider="openid_connect",
            uid="kc-agency-admin-nav",
            extra_data={
                "id_token": {"groups": [f"/rpsd/{self.agency.agency_key}/admin"]}
            },
        )
        self.company = Company.objects.create(name="Azienda TPL Navigation")
        self.lot = Lot.objects.create(
            agency=self.agency,
            short_description="NAV",
            description="Lotto test navigation",
        )
        self.contract = Contract.objects.create(
            contract_code="NAV-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )
        ContractMembership.objects.create(
            contract=self.contract,
            user=self.regular_user,
            role=ContractMembership.Role.CONTRACT_READER,
            created_by=self.platform_admin,
        )
        ContractMembership.objects.create(
            contract=self.contract,
            user=self.agency_admin,
            role=ContractMembership.Role.CONTRACT_EDITOR,
            created_by=self.platform_admin,
        )

    def test_sidebar_for_regular_user_hides_platform_configuration_and_companies(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:user-area"))
        self.assertContains(response, reverse("exchange_agreement:agencies"))
        self.assertNotContains(response, reverse("exchange_agreement:company-list"))
        self.assertNotContains(
            response, reverse("exchange_agreement:platform-configuration")
        )

    def test_sidebar_for_platform_admin_shows_platform_configuration_and_companies(
        self,
    ):
        self.client.force_login(self.platform_admin)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:user-area"))
        self.assertContains(response, reverse("exchange_agreement:agencies"))
        self.assertContains(response, reverse("exchange_agreement:company-list"))
        self.assertContains(
            response, reverse("exchange_agreement:platform-configuration")
        )

    def test_sidebar_for_local_superuser_shows_companies_and_configuration(self):
        self.client.force_login(self.local_superuser)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:company-list"))
        self.assertContains(
            response, reverse("exchange_agreement:platform-configuration")
        )

    def test_sidebar_for_agency_admin_shows_companies(self):
        self.client.force_login(self.agency_admin)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("exchange_agreement:company-list"))

    def test_agencies_page_lists_user_memberships(self):
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse("exchange_agreement:agencies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.agency.name)
        self.assertContains(response, self.agency.agency_key)
        self.assertContains(
            response,
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key]),
        )
        self.assertNotContains(response, self.other_agency.name)

    def test_agencies_page_for_platform_admin_shows_all_agencies(self):
        self.client.force_login(self.platform_admin)
        response = self.client.get(reverse("exchange_agreement:agencies"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.agency.name)
        self.assertContains(response, self.other_agency.name)

    def test_agency_bootstrap_url_is_not_captured_by_agency_slug(self):
        match = resolve("/exchange_agreement/me/agencies/bootstrap/")

        self.assertEqual(match.url_name, "agency-bootstrap")

    def test_agency_detail_and_contract_pages(self):
        self.client.force_login(self.regular_user)
        detail = self.client.get(
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(
            detail,
            "Descrizione Agenzia",
        )

        contracts_tab = self.client.get(
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
            + "?tab=contratti"
        )
        self.assertEqual(contracts_tab.status_code, 200)
        self.assertContains(contracts_tab, self.contract.contract_code)
        self.assertContains(
            contracts_tab,
            reverse(
                "exchange_agreement:agency-contract-detail",
                args=[self.agency.agency_key, self.contract.contract_code],
            ),
        )

        lots_tab = self.client.get(
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
            + "?tab=lotti"
        )
        self.assertEqual(lots_tab.status_code, 200)
        self.assertContains(
            lots_tab,
            reverse(
                "exchange_agreement:agency-lot-detail",
                args=[self.agency.agency_key, self.lot.id],
            ),
        )

        users_tab = self.client.get(
            reverse("exchange_agreement:agency-detail", args=[self.agency.agency_key])
            + "?tab=utenti"
        )
        self.assertEqual(users_tab.status_code, 200)
        self.assertContains(users_tab, "Utenti associati")
        self.assertContains(users_tab, self.regular_user.username)
        self.assertContains(users_tab, self.agency_admin.username)

        self.assertContains(
            users_tab,
            self.regular_user.email,
        )

        contract_detail = self.client.get(
            reverse(
                "exchange_agreement:agency-contract-detail",
                args=[self.agency.agency_key, self.contract.contract_code],
            )
        )
        self.assertEqual(contract_detail.status_code, 200)
        self.assertContains(contract_detail, self.contract.contract_code)

    def test_contract_detail_shows_company_m2m_exchange_card(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment="prod",
            keycloak_client_id="tpl-navigation-default-prod",
            keycloak_client_uuid="uuid-navigation",
        )
        store_client_secret(principal, client_secret="secret-navigation")
        detail_url = reverse(
            "exchange_agreement:agency-contract-detail",
            args=[self.agency.agency_key, self.contract.contract_code],
        )

        self.client.force_login(self.regular_user)
        regular_response = self.client.get(detail_url)
        self.assertEqual(regular_response.status_code, 200)
        self.assertContains(regular_response, "Interscambio dati azienda")
        self.assertContains(regular_response, principal.keycloak_client_id)
        self.assertContains(regular_response, "api/m2m/v1/contracts/NAV-001")
        self.assertNotContains(regular_response, "secret-navigation")
        self.assertNotContains(regular_response, "Mostra secret client")

        self.client.force_login(self.agency_admin)
        reveal_response = self.client.post(
            detail_url,
            {"action": "reveal-contract-client-secret"},
        )
        self.assertEqual(reveal_response.status_code, 200)
        self.assertContains(reveal_response, "Secret client rivelato.")
        self.assertContains(reveal_response, "secret-navigation")

    def test_lot_management_from_agency_detail_and_lot_detail(self):
        agency_detail_url = reverse(
            "exchange_agreement:agency-detail", args=[self.agency.agency_key]
        )

        self.client.force_login(self.regular_user)
        regular_page = self.client.get(agency_detail_url + "?tab=lotti")
        self.assertEqual(regular_page.status_code, 200)
        self.assertNotContains(regular_page, "Crea nuovo lotto")

        denied_create = self.client.post(
            agency_detail_url,
            {
                "action": "create-lot",
                "tab": "lotti",
                "short_description": "EDT",
                "description": "Lotto editor denied",
            },
        )
        self.assertEqual(denied_create.status_code, 403)

        self.client.force_login(self.agency_admin)
        create_response = self.client.post(
            agency_detail_url,
            {
                "action": "create-lot",
                "tab": "lotti",
                "short_description": "NORD",
                "description": "Lotto Nord",
            },
        )
        self.assertEqual(create_response.status_code, 200)
        self.assertContains(create_response, "Lotto creato correttamente.")
        created_lot = Lot.objects.get(
            short_description="NORD", description="Lotto Nord"
        )
        self.assertEqual(created_lot.agency, self.agency)
        self.assertContains(
            create_response,
            reverse(
                "exchange_agreement:agency-lot-detail",
                args=[self.agency.agency_key, created_lot.id],
            ),
        )

        lot_detail_url = reverse(
            "exchange_agreement:agency-lot-detail",
            args=[self.agency.agency_key, created_lot.id],
        )
        detail_response = self.client.get(lot_detail_url)
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Lotto Nord")

        update_response = self.client.post(
            lot_detail_url,
            {
                "short_description": "NORD-1",
                "description": "Lotto Nord Aggiornato",
            },
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertContains(update_response, "Lotto aggiornato correttamente.")
        created_lot.refresh_from_db()
        self.assertEqual(created_lot.short_description, "NORD-1")
        self.assertEqual(created_lot.description, "Lotto Nord Aggiornato")

        self.client.force_login(self.regular_user)
        denied_update = self.client.post(
            lot_detail_url,
            {
                "short_description": "NOPE",
                "description": "Denied update",
            },
        )
        self.assertEqual(denied_update.status_code, 403)

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

        self.client.force_login(self.local_superuser)
        allowed_superuser = self.client.get(
            reverse("exchange_agreement:platform-configuration")
        )
        self.assertEqual(allowed_superuser.status_code, 200)

    def test_company_pages_require_platform_admin_or_superuser(self):
        detail_url = reverse(
            "exchange_agreement:company-detail", args=[self.company.id]
        )
        list_url = reverse("exchange_agreement:company-list")

        self.client.force_login(self.regular_user)
        denied_list = self.client.get(list_url)
        denied_detail = self.client.get(detail_url)
        self.assertEqual(denied_list.status_code, 403)
        self.assertEqual(denied_detail.status_code, 403)

        self.client.force_login(self.platform_admin)
        allowed_list = self.client.get(list_url)
        allowed_detail = self.client.get(detail_url)
        self.assertEqual(allowed_list.status_code, 200)
        self.assertEqual(allowed_detail.status_code, 200)

        self.client.force_login(self.local_superuser)
        allowed_superuser_list = self.client.get(list_url)
        allowed_superuser_detail = self.client.get(detail_url)
        self.assertEqual(allowed_superuser_list.status_code, 200)
        self.assertEqual(allowed_superuser_detail.status_code, 200)

        self.client.force_login(self.agency_admin)
        allowed_agency_admin_list = self.client.get(list_url)
        allowed_agency_admin_detail = self.client.get(detail_url)
        self.assertEqual(allowed_agency_admin_list.status_code, 200)
        self.assertEqual(allowed_agency_admin_detail.status_code, 200)

        denied_agency_admin_create = self.client.post(
            list_url,
            {
                "name": "Create denied",
                "description": "agency-admin should not create here",
            },
        )
        self.assertEqual(denied_agency_admin_create.status_code, 403)

    def test_company_delete_requires_no_contracts_and_allows_agency_admin(self):
        detail_url_with_contract = reverse(
            "exchange_agreement:company-detail", args=[self.company.id]
        )
        self.client.force_login(self.agency_admin)
        blocked_delete = self.client.post(
            detail_url_with_contract,
            {"action": "delete-company", "tab": "descrizione"},
        )
        self.assertEqual(blocked_delete.status_code, 200)
        self.assertContains(
            blocked_delete,
            "non puo' essere eliminata",
        )
        self.assertTrue(Company.objects.filter(pk=self.company.id).exists())

        orphan = Company.objects.create(name="Orphan Company Delete")
        orphan_detail_url = reverse(
            "exchange_agreement:company-detail", args=[orphan.id]
        )
        deleted = self.client.post(
            orphan_detail_url,
            {"action": "delete-company", "tab": "descrizione"},
            follow=True,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(Company.objects.filter(pk=orphan.id).exists())
        self.assertContains(deleted, "eliminata correttamente")

    def test_company_list_create_success_and_duplicate_case_insensitive(self):
        self.client.force_login(self.platform_admin)
        list_url = reverse("exchange_agreement:company-list")

        create_response = self.client.post(
            list_url,
            {
                "name": "Nuova Azienda",
                "description": "Descrizione test",
            },
            follow=True,
        )
        self.assertEqual(create_response.status_code, 200)
        self.assertContains(create_response, "Azienda creata correttamente.")
        self.assertTrue(Company.objects.filter(name="Nuova Azienda").exists())

        duplicate_response = self.client.post(
            list_url,
            {
                "name": "nuova azienda",
                "description": "Dup",
            },
            follow=True,
        )
        self.assertEqual(duplicate_response.status_code, 200)
        self.assertContains(duplicate_response, "Esiste gia")
        self.assertEqual(
            Company.objects.filter(name__iexact="nuova azienda").count(),
            1,
        )

    def test_company_list_create_handles_integrity_error_race(self):
        self.client.force_login(self.platform_admin)
        list_url = reverse("exchange_agreement:company-list")
        original_create = Company.objects.create

        def _race_side_effect(*args, **kwargs):
            if not Company.objects.filter(name__iexact="Race Company").exists():
                original_create(name="Race Company", description="Concurrent insert")
            raise IntegrityError("duplicate key value violates unique constraint")

        with patch(
            "rpsd_config.exchange_agreement.views.Company.objects.create",
            side_effect=_race_side_effect,
        ):
            response = self.client.post(
                list_url,
                {
                    "name": "Race Company",
                    "description": "First submit",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Azienda gia",
        )
        self.assertEqual(Company.objects.filter(name__iexact="Race Company").count(), 1)

    def test_company_detail_shows_associated_contracts_and_404(self):
        self.client.force_login(self.platform_admin)
        detail_url = reverse(
            "exchange_agreement:company-detail", args=[self.company.id]
        )
        default_response = self.client.get(detail_url)
        self.assertEqual(default_response.status_code, 200)
        self.assertContains(default_response, "Anagrafica")
        self.assertContains(default_response, self.company.name)

        contracts_response = self.client.get(f"{detail_url}?tab=contratti")
        self.assertEqual(contracts_response.status_code, 200)
        self.assertContains(contracts_response, self.contract.contract_code)
        self.assertContains(
            contracts_response,
            reverse(
                "exchange_agreement:agency-contract-detail",
                args=[self.agency.agency_key, self.contract.contract_code],
            ),
        )

        users_response = self.client.get(f"{detail_url}?tab=utenti")
        self.assertEqual(users_response.status_code, 200)
        self.assertContains(users_response, "Utenti associati")
        self.assertContains(users_response, self.regular_user.username)
        self.assertContains(users_response, self.agency_admin.username)
        self.assertContains(users_response, self.contract.contract_code)

        interscambio_response = self.client.get(f"{detail_url}?tab=interscambio")
        self.assertEqual(interscambio_response.status_code, 200)
        self.assertContains(interscambio_response, "Utility interscambio dati")
        self.assertContains(interscambio_response, "Ruota secret client")

        not_found = self.client.get(
            reverse("exchange_agreement:company-detail", args=[999999])
        )
        self.assertEqual(not_found.status_code, 404)
