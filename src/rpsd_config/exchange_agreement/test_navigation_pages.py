# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyMembership,
    Company,
    Contract,
    ContractMembership,
    IntegrationPrincipal,
    Lot,
)
from rpsd_config.server.keycloak_admin import KeycloakAdminConfigError
from rpsd_config.exchange_agreement.services.m2m_secret_store import (
    reveal_principal_secret,
    store_principal_secret,
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
            extra_data={"id_token": {"groups": [f"/rpsd/{self.agency.agency_key}/editor"]}},
        )
        SocialAccount.objects.create(
            user=self.agency_admin,
            provider="openid_connect",
            uid="kc-agency-admin-nav",
            extra_data={"id_token": {"groups": [f"/rpsd/{self.agency.agency_key}/admin"]}},
        )
        self.company = Company.objects.create(name="Azienda TPL Navigation")
        self.lot = Lot.objects.create(description="Lotto test navigation")
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

    def test_sidebar_for_platform_admin_shows_platform_configuration_and_companies(self):
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
        created_lot = Lot.objects.get(short_description="NORD", description="Lotto Nord")
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
        detail_url = reverse("exchange_agreement:company-detail", args=[self.company.id])
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
            {"name": "Create denied", "description": "agency-admin should not create here"},
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
            "contratti attivi",
        )
        self.assertTrue(Company.objects.filter(pk=self.company.id).exists())

        orphan = Company.objects.create(name="Orphan Company Delete")
        orphan_detail_url = reverse("exchange_agreement:company-detail", args=[orphan.id])
        deleted = self.client.post(
            orphan_detail_url,
            {"action": "delete-company", "tab": "descrizione"},
            follow=True,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(Company.objects.filter(pk=orphan.id).exists())
        self.assertContains(deleted, "eliminata correttamente")

    def test_company_delete_with_only_closed_contract_returns_feedback(self):
        historical_company = Company.objects.create(name="Historical Company Delete")
        historical_lot = Lot.objects.create(description="Lotto historical delete")
        Contract.objects.create(
            contract_code="NAV-CLOSED-DELETE-001",
            client_agency=self.agency,
            contractor_company=historical_company,
            lot=historical_lot,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            status=Contract.ContractStatus.CLOSED,
            closed_at=timezone.now(),
            closed_reason="Contract closed",
        )

        self.client.force_login(self.agency_admin)
        response = self.client.post(
            reverse("exchange_agreement:company-detail", args=[historical_company.id]),
            {"action": "delete-company", "tab": "descrizione"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contratti collegati")
        self.assertTrue(Company.objects.filter(pk=historical_company.id).exists())

    def test_company_delete_blocks_after_contract_closed_transition(self):
        self.contract.status = Contract.ContractStatus.CLOSED
        self.contract.closed_at = timezone.now()
        self.contract.closed_reason = "Lifecycle close before delete"
        self.contract.save(
            update_fields=["status", "closed_at", "closed_reason", "updated_at"]
        )

        self.client.force_login(self.agency_admin)
        with patch(
            "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings"
        ) as service_factory:
            response = self.client.post(
                reverse("exchange_agreement:company-detail", args=[self.company.id]),
                {"action": "delete-company", "tab": "descrizione"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "contratti collegati")
        self.assertTrue(Company.objects.filter(pk=self.company.id).exists())
        service_factory.assert_not_called()

    def test_company_delete_cleans_up_m2m_principals_before_delete(self):
        orphan = Company.objects.create(name="Orphan Company With M2M")
        principal = IntegrationPrincipal.objects.create(
            company=orphan,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="orphan-company-default-prod",
            keycloak_client_uuid="kc-orphan-delete-001",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="secret-to-delete")

        self.client.force_login(self.agency_admin)
        disable_mock = Mock(return_value=SimpleNamespace(enabled=False))
        keycloak_service = SimpleNamespace(
            disable_client=disable_mock,
            find_client_by_client_id=Mock(return_value=None),
        )
        with (
            patch(
                "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
                return_value=keycloak_service,
            ),
            patch("rpsd_config.exchange_agreement.views.audit_m2m_event"),
        ):
            response = self.client.post(
                reverse("exchange_agreement:company-detail", args=[orphan.id]),
                {"action": "delete-company", "tab": "descrizione"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Company.objects.filter(pk=orphan.id).exists())
        self.assertFalse(IntegrationPrincipal.objects.filter(pk=principal.id).exists())
        disable_mock.assert_called_once_with(client_uuid="kc-orphan-delete-001")

    def test_company_delete_blocks_when_m2m_cleanup_fails(self):
        orphan = Company.objects.create(name="Orphan Company Cleanup Fail")
        principal = IntegrationPrincipal.objects.create(
            company=orphan,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="orphan-cleanup-fail-default-prod",
            keycloak_client_uuid="kc-orphan-delete-err-001",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="secret-to-keep")

        self.client.force_login(self.agency_admin)
        disable_mock = Mock(side_effect=KeycloakAdminConfigError("boom"))
        keycloak_service = SimpleNamespace(
            disable_client=disable_mock,
            find_client_by_client_id=Mock(return_value=None),
        )
        with (
            patch(
                "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
                return_value=keycloak_service,
            ),
            patch("rpsd_config.exchange_agreement.views.audit_m2m_event"),
        ):
            response = self.client.post(
                reverse("exchange_agreement:company-detail", args=[orphan.id]),
                {"action": "delete-company", "tab": "descrizione"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "cleanup IAM")
        self.assertTrue(Company.objects.filter(pk=orphan.id).exists())
        principal.refresh_from_db()
        self.assertEqual(principal.status, IntegrationPrincipal.Status.ACTIVE)
        disable_mock.assert_called_once_with(client_uuid="kc-orphan-delete-err-001")

    def test_company_delete_resolves_client_uuid_when_missing(self):
        orphan = Company.objects.create(name="Orphan Company UUID Resolve")
        principal = IntegrationPrincipal.objects.create(
            company=orphan,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="orphan-company-lookup-prod",
            keycloak_client_uuid="",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="secret-to-lookup")

        self.client.force_login(self.agency_admin)
        disable_mock = Mock(return_value=SimpleNamespace(enabled=False))
        keycloak_service = SimpleNamespace(
            disable_client=disable_mock,
            find_client_by_client_id=Mock(
                return_value=SimpleNamespace(
                    id="kc-resolved-uuid-001",
                    client_id=principal.keycloak_client_id,
                    enabled=True,
                )
            ),
        )
        with (
            patch(
                "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
                return_value=keycloak_service,
            ),
            patch("rpsd_config.exchange_agreement.views.audit_m2m_event"),
        ):
            response = self.client.post(
                reverse("exchange_agreement:company-detail", args=[orphan.id]),
                {"action": "delete-company", "tab": "descrizione"},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Company.objects.filter(pk=orphan.id).exists())
        self.assertFalse(IntegrationPrincipal.objects.filter(pk=principal.id).exists())
        disable_mock.assert_called_once_with(client_uuid="kc-resolved-uuid-001")

    def test_company_list_create_success_and_duplicate_case_insensitive(self):
        self.client.force_login(self.platform_admin)
        list_url = reverse("exchange_agreement:company-list")

        with patch(
            "rpsd_config.exchange_agreement.views.provision_default_m2m_principal_for_company",
            return_value=SimpleNamespace(),
        ) as provision_mock:
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
        provision_mock.assert_called_once()

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
            "errore di vincolo",
        )
        self.assertEqual(Company.objects.filter(name__iexact="Race Company").count(), 0)

    def test_company_list_create_rolls_back_company_when_m2m_provisioning_fails(self):
        self.client.force_login(self.platform_admin)
        list_url = reverse("exchange_agreement:company-list")

        with patch(
            "rpsd_config.exchange_agreement.views.provision_default_m2m_principal_for_company",
            side_effect=KeycloakAdminConfigError("m2m provisioning failed"),
        ):
            response = self.client.post(
                list_url,
                {
                    "name": "Company No M2M",
                    "description": "Should rollback",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "provisioning credenziali M2M fallito")
        self.assertFalse(Company.objects.filter(name="Company No M2M").exists())

    def test_company_detail_shows_associated_contracts_and_404(self):
        self.client.force_login(self.platform_admin)
        detail_url = reverse("exchange_agreement:company-detail", args=[self.company.id])
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

    def test_company_detail_interscambio_reveal_and_rotate_secret_for_platform_admin(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-tpl-navigation-default-prod",
            keycloak_client_uuid="kc-nav-m2m-001",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="initial-secret")

        self.client.force_login(self.platform_admin)
        detail_url = reverse("exchange_agreement:company-detail", args=[self.company.id])

        interscambio_response = self.client.get(f"{detail_url}?tab=interscambio")
        self.assertEqual(interscambio_response.status_code, 200)
        self.assertContains(interscambio_response, principal.keycloak_client_id)
        self.assertContains(interscambio_response, "Mostra secret client")
        self.assertContains(interscambio_response, "Ruota secret client")
        self.assertContains(interscambio_response, "Revoca client M2M")
        self.assertContains(interscambio_response, "••••••••••••••••")

        with patch(
            "rpsd_config.exchange_agreement.views.audit_m2m_event",
        ) as audit_mock:
            reveal_response = self.client.post(
                detail_url,
                {
                    "action": "reveal-client-secret",
                    "tab": "interscambio",
                },
                follow=True,
            )

        self.assertEqual(reveal_response.status_code, 200)
        self.assertContains(reveal_response, "Secret client recuperato. Copialo ora.")
        self.assertContains(reveal_response, "initial-secret")
        self.assertTrue(audit_mock.called)
        self.assertEqual(audit_mock.call_args.kwargs.get("outcome"), "success")
        self.assertEqual(audit_mock.call_args.args[0], "secret.reveal")

        with (
            patch(
                "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
                return_value=SimpleNamespace(
                    rotate_client_secret=lambda **kwargs: "rotated-secret-001"
                ),
            ),
            patch(
                "rpsd_config.exchange_agreement.views.audit_m2m_event",
            ) as audit_mock,
        ):
            rotate_response = self.client.post(
                detail_url,
                {
                    "action": "rotate-client-secret",
                    "tab": "interscambio",
                },
                follow=True,
            )

        self.assertEqual(rotate_response.status_code, 200)
        self.assertContains(rotate_response, "Secret client ruotato correttamente.")
        self.assertContains(rotate_response, "rotated-secret-001")
        principal.refresh_from_db()
        self.assertIsNotNone(principal.last_secret_rotation_at)
        self.assertEqual(
            reveal_principal_secret(principal=principal),
            "rotated-secret-001",
        )
        self.assertTrue(audit_mock.called)
        self.assertEqual(audit_mock.call_args.kwargs.get("outcome"), "success")
        self.assertEqual(audit_mock.call_args.args[0], "secret.rotate")

    def test_company_detail_interscambio_reveal_secret_allowed_for_agency_admin(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-tpl-navigation-agency-admin-prod",
            keycloak_client_uuid="kc-nav-m2m-002",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="agency-admin-secret")

        self.client.force_login(self.agency_admin)
        detail_url = reverse("exchange_agreement:company-detail", args=[self.company.id])
        reveal_response = self.client.post(
            detail_url,
            {
                "action": "reveal-client-secret",
                "tab": "interscambio",
            },
            follow=True,
        )
        self.assertEqual(reveal_response.status_code, 200)
        self.assertContains(reveal_response, "agency-admin-secret")

    def test_company_detail_interscambio_revoke_client_audited(self):
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-tpl-navigation-revoke-prod",
            keycloak_client_uuid="kc-nav-m2m-003",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.platform_admin,
        )
        store_principal_secret(principal=principal, raw_secret="secret-to-revoke")

        self.client.force_login(self.platform_admin)
        detail_url = reverse("exchange_agreement:company-detail", args=[self.company.id])

        with (
            patch(
                "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
                return_value=SimpleNamespace(
                    disable_client=lambda **kwargs: SimpleNamespace(enabled=False)
                ),
            ),
            patch(
                "rpsd_config.exchange_agreement.views.audit_m2m_event",
            ) as audit_mock,
        ):
            response = self.client.post(
                detail_url,
                {
                    "action": "revoke-client",
                    "tab": "interscambio",
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Client M2M revocato correttamente.")
        principal.refresh_from_db()
        self.assertEqual(principal.status, IntegrationPrincipal.Status.REVOKED)
        self.assertEqual(principal.client_secret_ciphertext, "")
        self.assertEqual(principal.client_secret_key_id, "")
        self.assertIsNone(principal.client_secret_updated_at)
        self.assertTrue(audit_mock.called)
        self.assertEqual(audit_mock.call_args.args[0], "principal.revoke")
        self.assertEqual(audit_mock.call_args.kwargs.get("outcome"), "success")
