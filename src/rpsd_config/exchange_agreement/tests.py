# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import base64
import json
from datetime import date, timedelta

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    Company,
    Contract,
    ContractInvitation,
    ContractMembership,
    Lot,
)
from rpsd_config.exchange_agreement.views import _build_identity_privileges


def _make_jwt(payload: dict) -> str:
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).rstrip(b"=")
    return f"header.{encoded_payload.decode('ascii')}.signature"


class IdentityPrivilegesTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()

    def test_identity_privileges_extract_groups_and_realm_roles_from_nested_claims(self):
        user = self.user_model.objects.create_user(
            username="oidc-admin",
            password="test-pass-1",
        )
        SocialAccount.objects.create(
            user=user,
            provider="openid_connect",
            uid="kc-admin-1",
            extra_data={
                "id_token": {
                    "groups": ["/rpsd/admin"],
                    "realm_access": {"roles": ["rpsd-admin"]},
                }
            },
        )

        privileges = _build_identity_privileges(user)

        assert privileges["auth_source"] == "OIDC"
        assert privileges["groups"] == ["/rpsd/admin"]
        assert privileges["realm_roles"] == ["rpsd-admin"]
        assert privileges["derived_roles"] == ["admin"]

    def test_identity_privileges_extract_from_raw_jwt_when_needed(self):
        user = self.user_model.objects.create_user(
            username="oidc-reader",
            password="test-pass-2",
        )
        token = _make_jwt(
            {
                "groups": ["/rpsd/reader"],
                "realm_access": {"roles": ["rpsd-reader"]},
            }
        )
        SocialAccount.objects.create(
            user=user,
            provider="openid_connect",
            uid="kc-reader-1",
            extra_data={"id_token": token},
        )

        privileges = _build_identity_privileges(user)

        assert privileges["groups"] == ["/rpsd/reader"]
        assert privileges["realm_roles"] == ["rpsd-reader"]
        assert privileges["derived_roles"] == ["reader"]

    def test_identity_privileges_reflect_django_staff_and_superuser_flags(self):
        staff_user = self.user_model.objects.create_user(
            username="staff-user",
            password="test-pass-3",
            is_staff=True,
        )
        local_user = self.user_model.objects.create_user(
            username="local-user",
            password="test-pass-4",
            is_staff=False,
            is_superuser=False,
        )

        staff_privileges = _build_identity_privileges(staff_user)
        local_privileges = _build_identity_privileges(local_user)

        assert staff_privileges["is_staff"] is True
        assert staff_privileges["is_superuser"] is False
        assert local_privileges["is_staff"] is False
        assert local_privileges["is_superuser"] is False


class InvitationOnboardingFlowTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.inviter = self.user_model.objects.create_user(
            username="inviter",
            email="inviter@example.com",
            password="inviter-pass",
        )
        self.target_user = self.user_model.objects.create_user(
            username="invitee",
            email="invitee@example.com",
            password="invitee-pass",
        )
        self.contract = self._create_contract("CTR-INV-001")

    def _create_contract(self, contract_code: str) -> Contract:
        agency = Agency.objects.create(name=f"Agency {contract_code}")
        company = Company.objects.create(name=f"Company {contract_code}")
        lot = Lot.objects.create(description=f"Lot {contract_code}")
        return Contract.objects.create(
            contract_code=contract_code,
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )

    def _create_invitation(self, *, email: str | None = None) -> ContractInvitation:
        return ContractInvitation.objects.create(
            contract=self.contract,
            email=email,
            role_to_assign=ContractMembership.Role.CONTRACT_EDITOR,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=14),
        )

    def test_invitation_landing_post_starts_onboarding_session(self):
        invitation = self._create_invitation(email=self.target_user.email)
        url = reverse("invitation-landing-root", kwargs={"token": invitation.token})

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertNotContains(get_response, "Torna alla lista inviti")

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/oidc/", response["Location"])
        self.assertIn("process=login", response["Location"])
        self.assertIn("next=%2Fexchange_agreement%2Fonboarding%2Fcallback%2F", response["Location"])
        self.assertEqual(
            self.client.session.get("onboarding_invitation_token"),
            str(invitation.token),
        )

    def test_invitation_landing_for_authenticated_user_goes_to_acceptance(self):
        invitation = self._create_invitation(email=self.target_user.email)
        url = reverse("invitation-landing-root", kwargs={"token": invitation.token})
        self.client.force_login(self.target_user)

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Accetta invito")
        self.assertContains(get_response, "Torna alla lista inviti")
        self.assertContains(
            get_response,
            reverse("exchange_agreement:received-invitations"),
        )

        post_response = self.client.post(url)
        self.assertEqual(post_response.status_code, 302)
        self.assertEqual(
            post_response["Location"],
            reverse("exchange_agreement:onboarding-callback"),
        )
        self.assertEqual(
            self.client.session.get("onboarding_invitation_token"),
            str(invitation.token),
        )
        self.assertEqual(
            self.client.session.get("onboarding_invitation_kind"),
            "contract",
        )

    def test_invitation_landing_rejects_targeted_invitation_for_matching_user(self):
        invitation = self._create_invitation(email=self.target_user.email)
        url = reverse("invitation-landing-root", kwargs={"token": invitation.token})
        self.client.force_login(self.target_user)

        get_response = self.client.get(url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Rifiuta invito")

        post_response = self.client.post(url, data={"action": "reject-invitation"})
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Invito rifiutato correttamente")
        self.assertContains(post_response, "Stato: rifiutato")

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, ContractInvitation.Status.REJECTED)
        self.assertEqual(invitation.rejected_by_id, self.target_user.id)
        self.assertIsNotNone(invitation.rejected_at)

    def test_invitation_landing_hides_reject_for_open_invitation(self):
        invitation = self._create_invitation(email=None)
        url = reverse("invitation-landing-root", kwargs={"token": invitation.token})
        self.client.force_login(self.target_user)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Rifiuta invito")

        post_response = self.client.post(url, data={"action": "reject-invitation"})
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(
            post_response,
            "disponibile per inviti aperti",
        )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, ContractInvitation.Status.PENDING)

    def test_invitation_landing_reject_denies_email_mismatch(self):
        invitation = self._create_invitation(email="other@example.com")
        url = reverse("invitation-landing-root", kwargs={"token": invitation.token})
        self.client.force_login(self.target_user)

        response = self.client.post(url, data={"action": "reject-invitation"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "non corrisponde",
        )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, ContractInvitation.Status.PENDING)

    def test_onboarding_callback_consumes_invitation_and_creates_membership(self):
        invitation = self._create_invitation(email=self.target_user.email)
        session = self.client.session
        session["onboarding_invitation_token"] = str(invitation.token)
        session.save()
        self.client.force_login(self.target_user)

        response = self.client.get(reverse("exchange_agreement:onboarding-callback"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Onboarding completato")
        self.assertContains(response, self.contract.contract_code)

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, ContractInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by_id, self.target_user.id)
        self.assertIsNotNone(invitation.accepted_at)
        self.assertNotIn("onboarding_invitation_token", self.client.session)

        membership = ContractMembership.objects.get(
            contract=self.contract,
            user=self.target_user,
        )
        self.assertEqual(membership.role, ContractMembership.Role.CONTRACT_EDITOR)

        user_area = self.client.get(reverse("exchange_agreement:user-area"))
        self.assertEqual(user_area.status_code, 200)
        self.assertContains(user_area, self.contract.contract_code)

    def test_onboarding_callback_without_invitation_session_is_rejected(self):
        self.client.force_login(self.target_user)

        response = self.client.get(reverse("exchange_agreement:onboarding-callback"))

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Sessione onboarding non trovata",
            status_code=400,
        )

    def test_contract_invitation_rejects_contract_admin_role(self):
        with self.assertRaises(ValidationError):
            ContractInvitation.objects.create(
                contract=self.contract,
                email="invalid@example.com",
                role_to_assign=ContractMembership.Role.CONTRACT_ADMIN,
                invited_by=self.inviter,
                expires_at=timezone.now() + timedelta(days=7),
            )

    def test_received_invitations_page_contains_action_links(self):
        contract_invitation = self._create_invitation(email=self.target_user.email)
        agency = Agency.objects.create(name="ATPL Received Invite")
        agency_invitation = AgencyInvitation.objects.create(
            agency=agency,
            email=self.target_user.email,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=7),
        )

        self.client.force_login(self.target_user)
        response = self.client.get(reverse("exchange_agreement:received-invitations"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "invitation-landing-root",
                kwargs={"token": contract_invitation.token},
            ),
        )
        self.assertContains(
            response,
            reverse(
                "invitation-landing-root",
                kwargs={"token": agency_invitation.token},
            ),
        )

    def test_user_area_shows_invitation_summary_card(self):
        self._create_invitation(email=self.target_user.email)
        ContractInvitation.objects.create(
            contract=self.contract,
            email=self.target_user.email,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=ContractInvitation.Status.REJECTED,
            rejected_by=self.target_user,
            rejected_at=timezone.now(),
        )
        ContractInvitation.objects.create(
            contract=self.contract,
            email=self.target_user.email,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=ContractInvitation.Status.REVOKED,
        )
        ContractInvitation.objects.create(
            contract=self.contract,
            email=self.target_user.email,
            role_to_assign=ContractMembership.Role.CONTRACT_EDITOR,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=ContractInvitation.Status.ACCEPTED,
            accepted_by=self.target_user,
            accepted_at=timezone.now(),
        )

        agency = Agency.objects.create(name="ATPL Summary Invite")
        AgencyInvitation.objects.create(
            agency=agency,
            email=self.target_user.email,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=AgencyInvitation.Status.PENDING,
        )
        AgencyInvitation.objects.create(
            agency=agency,
            email=self.target_user.email,
            role_to_assign=AgencyMembership.Role.AGENCY_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=AgencyInvitation.Status.ACCEPTED,
            accepted_by=self.target_user,
            accepted_at=timezone.now(),
        )

        self.client.force_login(self.target_user)
        response = self.client.get(reverse("exchange_agreement:user-area"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vedi inviti ricevuti")
        self.assertContains(response, "Pending: 2")
        self.assertContains(response, "Accettati: 2")
        self.assertContains(response, "Rifiutati: 1")
        self.assertContains(response, "Revocati: 1")


class AgencyRbacModelTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.inviter = self.user_model.objects.create_user(
            username="agency-inviter",
            email="agency-inviter@example.com",
            password="inviter-pass",
        )

    def test_agency_key_is_autogenerated_and_immutable(self):
        agency = Agency.objects.create(name="ATPL Milano")

        self.assertEqual(agency.agency_key, "atpl-milano")

        agency.agency_key = "changed-key"
        with self.assertRaises(ValidationError):
            agency.save()

    def test_agency_invitation_pending_requires_future_expiration(self):
        agency = Agency.objects.create(name="ATPL Bergamo")

        with self.assertRaises(ValidationError):
            AgencyInvitation.objects.create(
                agency=agency,
                email="operator@example.com",
                role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
                invited_by=self.inviter,
                expires_at=timezone.now() - timedelta(minutes=5),
            )

    def test_agency_invitation_rejected_requires_reject_audit_fields(self):
        agency = Agency.objects.create(name="ATPL Lecco")
        invitee = self.user_model.objects.create_user(
            username="agency-reject-invitee",
            email="agency-reject@example.com",
            password="invitee-pass",
        )

        with self.assertRaises(ValidationError):
            AgencyInvitation.objects.create(
                agency=agency,
                email=invitee.email,
                role_to_assign=AgencyMembership.Role.AGENCY_READER,
                invited_by=self.inviter,
                expires_at=timezone.now() + timedelta(days=5),
                status=AgencyInvitation.Status.REJECTED,
            )

        rejected_invitation = AgencyInvitation.objects.create(
            agency=agency,
            email=invitee.email,
            role_to_assign=AgencyMembership.Role.AGENCY_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=AgencyInvitation.Status.REJECTED,
            rejected_by=invitee,
            rejected_at=timezone.now(),
        )
        self.assertEqual(rejected_invitation.status, AgencyInvitation.Status.REJECTED)

    def test_contract_invitation_rejected_requires_reject_audit_fields(self):
        agency = Agency.objects.create(name="ATPL Como")
        company = Company.objects.create(name="Company Como")
        lot = Lot.objects.create(description="Lot Como")
        contract = Contract.objects.create(
            contract_code="CTR-REJECT-001",
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )
        invitee = self.user_model.objects.create_user(
            username="contract-reject-invitee",
            email="contract-reject@example.com",
            password="invitee-pass",
        )

        with self.assertRaises(ValidationError):
            ContractInvitation.objects.create(
                contract=contract,
                email=invitee.email,
                role_to_assign=ContractMembership.Role.CONTRACT_READER,
                invited_by=self.inviter,
                expires_at=timezone.now() + timedelta(days=5),
                status=ContractInvitation.Status.REJECTED,
            )

        rejected_invitation = ContractInvitation.objects.create(
            contract=contract,
            email=invitee.email,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=5),
            status=ContractInvitation.Status.REJECTED,
            rejected_by=invitee,
            rejected_at=timezone.now(),
        )
        self.assertEqual(rejected_invitation.status, ContractInvitation.Status.REJECTED)
