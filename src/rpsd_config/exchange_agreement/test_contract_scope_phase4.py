# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import date
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    ContractInvitation,
    ContractMembership,
    FlowProfile,
    Lot,
)


def _flow_profile_options() -> dict:
    return {
        "general_profile": "it",
        "planned_master": {
            "netex": {
                "active": True,
                "flow": "planned-master-netex",
                "description": "Planned master ingestion",
            }
        },
        "data_ingestion": {
            "avm": {
                "active": True,
                "flow": "data-ingestion-avm",
                "description": "AVM ingestion",
            }
        },
        "data_retention": {
            "avm": {
                "days": 30,
                "flow": "retention-avm",
                "description": "AVM retention policy",
            }
        },
    }


class ContractScopeAndInvitationsPhase4Tests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.agency_a = Agency.objects.create(name="ATPL Milano")
        self.agency_b = Agency.objects.create(name="ATPL Bergamo")
        self.company = Company.objects.create(name="ATM")
        self.lot = Lot.objects.create(description="Lot A")

        self.contract_a = Contract.objects.create(
            contract_code="CTR-A-001",
            client_agency=self.agency_a,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )
        self.contract_b = Contract.objects.create(
            contract_code="CTR-B-001",
            client_agency=self.agency_b,
            contractor_company=self.company,
            lot=self.lot,
            start_date=date(2035, 1, 2),
            status=Contract.ContractStatus.DRAFT,
        )

        self.flow_profile = FlowProfile.objects.create(
            code="flow-profile-v1",
            name="Flow profile v1",
            options=_flow_profile_options(),
            is_active=True,
        )

        self.platform_admin = self._create_oidc_user(
            username="platform-admin",
            email="platform-admin@example.com",
            groups=["/rpsd/admin"],
        )
        self.agency_admin_a = self._create_oidc_user(
            username="agency-admin-a",
            email="agency-admin-a@example.com",
            groups=[f"/rpsd/{self.agency_a.agency_key}/admin"],
        )
        self.agency_editor_a = self._create_oidc_user(
            username="agency-editor-a",
            email="agency-editor-a@example.com",
            groups=[f"/rpsd/{self.agency_a.agency_key}/editor"],
        )
        self.agency_reader_a = self._create_oidc_user(
            username="agency-reader-a",
            email="agency-reader-a@example.com",
            groups=[f"/rpsd/{self.agency_a.agency_key}/reader"],
        )
        self.agency_editor_b = self._create_oidc_user(
            username="agency-editor-b",
            email="agency-editor-b@example.com",
            groups=[f"/rpsd/{self.agency_b.agency_key}/editor"],
        )

    def _create_oidc_user(self, *, username: str, email: str, groups: list[str]):
        user = self.user_model.objects.create_user(
            username=username,
            email=email,
            password="test-pass",
        )
        SocialAccount.objects.create(
            user=user,
            provider="openid_connect",
            uid=f"kc-{username}",
            extra_data={"id_token": {"groups": groups}},
        )
        return user

    def test_agency_admin_can_create_contract_only_in_own_scope(self):
        self.client.force_login(self.agency_admin_a)

        in_scope_response = self.client.post(
            "/exchange_agreement/api/v1/contracts",
            data=json.dumps(
                {
                    "contract_code": "CTR-A-NEW-001",
                    "client_agency_id": self.agency_a.id,
                    "contractor_company_id": self.company.id,
                    "lot_id": self.lot.id,
                    "start_date": "2043-01-01",
                    "status": "draft",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(in_scope_response.status_code, 200)

        out_scope_response = self.client.post(
            "/exchange_agreement/api/v1/contracts",
            data=json.dumps(
                {
                    "contract_code": "CTR-B-NEW-001",
                    "client_agency_id": self.agency_b.id,
                    "contractor_company_id": self.company.id,
                    "lot_id": self.lot.id,
                    "start_date": "2044-01-01",
                    "status": "draft",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(out_scope_response.status_code, 403)

    def test_agency_editor_cannot_create_contract(self):
        self.client.force_login(self.agency_editor_a)

        response = self.client.post(
            "/exchange_agreement/api/v1/contracts",
            data=json.dumps(
                {
                    "contract_code": "CTR-A-NEW-002",
                    "client_agency_id": self.agency_a.id,
                    "contractor_company_id": self.company.id,
                    "lot_id": self.lot.id,
                    "start_date": "2036-01-01",
                    "status": "draft",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_contract_write_scope_allows_editor_and_denies_reader(self):
        self.client.force_login(self.agency_editor_a)
        editor_response = self.client.put(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/flow-profile",
            data=json.dumps({"flow_profile_code": self.flow_profile.code}),
            content_type="application/json",
        )
        self.assertEqual(editor_response.status_code, 200)

        self.client.force_login(self.agency_reader_a)
        reader_response = self.client.put(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/flow-profile",
            data=json.dumps({"flow_profile_code": self.flow_profile.code}),
            content_type="application/json",
        )
        self.assertEqual(reader_response.status_code, 403)

        self.client.force_login(self.agency_editor_b)
        out_scope_response = self.client.put(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/flow-profile",
            data=json.dumps({"flow_profile_code": self.flow_profile.code}),
            content_type="application/json",
        )
        self.assertEqual(out_scope_response.status_code, 404)

    def test_contract_invitation_api_allows_editor_reader_and_rejects_admin_role(self):
        self.client.force_login(self.agency_editor_a)

        ok_response = self.client.post(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/invitations",
            data=json.dumps(
                {
                    "role_to_assign": ContractMembership.Role.CONTRACT_READER,
                    "email": "tpl-reader@example.com",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(ok_response.status_code, 200)
        payload = ok_response.json()
        self.assertEqual(payload["contract_code"], self.contract_a.contract_code)
        self.assertEqual(
            payload["role_to_assign"],
            ContractMembership.Role.CONTRACT_READER,
        )

        bad_role_response = self.client.post(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/invitations",
            data=json.dumps(
                {
                    "role_to_assign": ContractMembership.Role.CONTRACT_ADMIN,
                    "email": "tpl-admin@example.com",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(bad_role_response.status_code, 400)

        invitation = ContractInvitation.objects.get(token=payload["token"])
        self.assertEqual(invitation.invited_by_id, self.agency_editor_a.id)

    def test_contract_invitation_scope_denies_reader_and_ui_is_scoped(self):
        self.client.force_login(self.agency_reader_a)
        denied_response = self.client.post(
            f"/exchange_agreement/api/v1/contracts/{self.contract_a.contract_code}/invitations",
            data=json.dumps(
                {"role_to_assign": ContractMembership.Role.CONTRACT_READER}
            ),
            content_type="application/json",
        )
        self.assertEqual(denied_response.status_code, 403)

        self.client.force_login(self.agency_editor_a)
        page_response = self.client.get(
            reverse("exchange_agreement:contract-invitation-create")
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, self.contract_a.contract_code)
        self.assertNotContains(page_response, self.contract_b.contract_code)

        form_response = self.client.post(
            reverse("exchange_agreement:contract-invitation-create"),
            {
                "contract_code": self.contract_a.contract_code,
                "role_to_assign": ContractMembership.Role.CONTRACT_EDITOR,
                "email": "tpl-editor@example.com",
            },
        )
        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, "Invito contratto creato correttamente")

        self.assertTrue(
            ContractInvitation.objects.filter(
                contract=self.contract_a,
                email="tpl-editor@example.com",
                role_to_assign=ContractMembership.Role.CONTRACT_EDITOR,
            ).exists()
        )

    def test_user_area_shows_contract_invite_action_for_editor_only(self):
        self.client.force_login(self.agency_editor_a)
        editor_page = self.client.get(reverse("exchange_agreement:user-area"))
        self.assertContains(
            editor_page,
            reverse("exchange_agreement:contract-invitation-create"),
        )

        self.client.force_login(self.agency_reader_a)
        reader_page = self.client.get(reverse("exchange_agreement:user-area"))
        self.assertNotContains(
            reader_page,
            reverse("exchange_agreement:contract-invitation-create"),
        )

    def test_agency_contract_create_page_can_create_company_inline(self):
        self.client.force_login(self.agency_admin_a)
        url = reverse(
            "exchange_agreement:agency-contract-create",
            args=[self.agency_a.agency_key],
        )

        response = self.client.post(
            url,
            {
                "action": "create-company",
                "company_name": "TPER Bologna",
                "company_description": "Operatore TPL",
                "contract_code": "CTR-A-UI-001",
                "contractor_company_id": "",
                "lot_id": self.lot.id,
                "start_date": "2036-01-01",
                "end_date": "",
                "tender_id": "TENDER-UI-001",
                "status": Contract.ContractStatus.DRAFT,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Azienda creata correttamente.")
        created_company = Company.objects.get(name="TPER Bologna")
        self.assertContains(response, f'value="{created_company.id}" selected')
        self.assertContains(response, 'value="CTR-A-UI-001"')

    def test_agency_contract_create_page_rejects_duplicate_company_case_insensitive(self):
        self.client.force_login(self.agency_admin_a)
        url = reverse(
            "exchange_agreement:agency-contract-create",
            args=[self.agency_a.agency_key],
        )

        response = self.client.post(
            url,
            {
                "action": "create-company",
                "company_name": "atm",
                "company_description": "Duplicate case-insensitive",
                "contract_code": "",
                "contractor_company_id": "",
                "lot_id": "",
                "start_date": "",
                "end_date": "",
                "tender_id": "",
                "status": Contract.ContractStatus.DRAFT,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Esiste gia' una azienda con questo nome.")
        self.assertEqual(Company.objects.filter(name__iexact="atm").count(), 1)

    def test_agency_contract_create_page_handles_company_create_race_integrity_error(self):
        self.client.force_login(self.agency_admin_a)
        url = reverse(
            "exchange_agreement:agency-contract-create",
            args=[self.agency_a.agency_key],
        )
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
                url,
                {
                    "action": "create-company",
                    "company_name": "Race Company",
                    "company_description": "Race",
                    "contract_code": "",
                    "contractor_company_id": "",
                    "lot_id": "",
                    "start_date": "",
                    "end_date": "",
                    "tender_id": "",
                    "status": Contract.ContractStatus.DRAFT,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Azienda gia' creata da un altro utente in parallelo.",
        )
        self.assertEqual(Company.objects.filter(name__iexact="Race Company").count(), 1)
