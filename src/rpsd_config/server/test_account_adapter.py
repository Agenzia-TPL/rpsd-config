# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
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
from rpsd_config.server.account_adapter import RpsdAccountAdapter


class AccountAdapterSignupPolicyTests(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.adapter = RpsdAccountAdapter()
        self.user_model = get_user_model()
        self.inviter = self.user_model.objects.create_user(
            username="signup-policy-inviter",
            email="inviter-policy@example.com",
            password="inviter-pass",
        )
        self.contract = self._create_contract("CTR-SIGNUP-001")

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

    def _create_request(self):
        request = self.request_factory.get("/accounts/signup/")
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        return request

    def _create_invitation(self, *, expires_delta_days: int) -> ContractInvitation:
        return ContractInvitation.objects.create(
            contract=self.contract,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=expires_delta_days),
        )

    def _create_agency_invitation(
        self, *, expires_delta_days: int
    ) -> AgencyInvitation:
        agency = Agency.objects.create(name="Agency Signup")
        return AgencyInvitation.objects.create(
            agency=agency,
            role_to_assign=AgencyMembership.Role.AGENCY_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=expires_delta_days),
        )

    def test_signup_is_closed_without_invitation_token(self):
        request = self._create_request()

        self.assertFalse(self.adapter.is_open_for_signup(request))

    def test_signup_is_closed_with_invalid_invitation_token(self):
        request = self._create_request()
        request.session["onboarding_invitation_token"] = "invalid-token"
        request.session.save()

        self.assertFalse(self.adapter.is_open_for_signup(request))

    def test_signup_is_open_with_valid_pending_invitation_token(self):
        invitation = self._create_invitation(expires_delta_days=7)
        request = self._create_request()
        request.session["onboarding_invitation_token"] = str(invitation.token)
        request.session.save()

        self.assertTrue(self.adapter.is_open_for_signup(request))

    def test_signup_is_closed_with_expired_invitation_token(self):
        invitation = self._create_invitation(expires_delta_days=1)
        ContractInvitation.objects.filter(pk=invitation.pk).update(
            status=ContractInvitation.Status.EXPIRED,
            expires_at=timezone.now() - timedelta(days=1),
        )
        request = self._create_request()
        request.session["onboarding_invitation_token"] = str(invitation.token)
        request.session.save()

        self.assertFalse(self.adapter.is_open_for_signup(request))

    def test_signup_is_open_with_valid_agency_invitation_token(self):
        invitation = self._create_agency_invitation(expires_delta_days=7)
        request = self._create_request()
        request.session["onboarding_invitation_token"] = str(invitation.token)
        request.session["onboarding_invitation_kind"] = "agency"
        request.session.save()

        self.assertTrue(self.adapter.is_open_for_signup(request))
