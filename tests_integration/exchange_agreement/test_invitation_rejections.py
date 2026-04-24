# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
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
from rpsd_config.exchange_agreement.services.invitation_rejections import (
    InvitationRejectValidationError,
    reject_agency_invitation_for_user,
    reject_contract_invitation_for_user,
)


class InvitationRejectionsServiceTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.inviter = self.user_model.objects.create_user(
            username="inviter-reject",
            email="inviter-reject@example.com",
            password="inviter-pass",
        )
        self.invitee = self.user_model.objects.create_user(
            username="invitee-reject",
            email="invitee-reject@example.com",
            password="invitee-pass",
        )
        self.other_user = self.user_model.objects.create_user(
            username="other-reject",
            email="other-reject@example.com",
            password="other-pass",
        )

        self.agency = Agency.objects.create(name="ATPL Reject")
        self.contract = Contract.objects.create(
            contract_code="CTR-REJECT-SVC",
            client_agency=self.agency,
            contractor_company=Company.objects.create(name="Reject Company"),
            lot=Lot.objects.create(description="Reject Lot"),
            start_date=date(2026, 1, 1),
            status=Contract.ContractStatus.ACTIVE,
        )

    def test_reject_contract_invitation_sets_rejected_state_and_audit(self):
        invitation = ContractInvitation.objects.create(
            contract=self.contract,
            email=self.invitee.email,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=3),
            status=ContractInvitation.Status.PENDING,
        )

        result = reject_contract_invitation_for_user(
            token=str(invitation.token),
            user=self.invitee,
        )

        invitation.refresh_from_db()
        self.assertEqual(result.invitation_type, "contract")
        self.assertEqual(invitation.status, ContractInvitation.Status.REJECTED)
        self.assertEqual(invitation.rejected_by_id, self.invitee.id)
        self.assertIsNotNone(invitation.rejected_at)

    def test_reject_contract_invitation_denies_open_invites(self):
        invitation = ContractInvitation.objects.create(
            contract=self.contract,
            email=None,
            role_to_assign=ContractMembership.Role.CONTRACT_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=3),
            status=ContractInvitation.Status.PENDING,
        )

        with self.assertRaises(InvitationRejectValidationError):
            reject_contract_invitation_for_user(
                token=str(invitation.token),
                user=self.invitee,
            )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, ContractInvitation.Status.PENDING)

    def test_reject_agency_invitation_denies_email_mismatch(self):
        invitation = AgencyInvitation.objects.create(
            agency=self.agency,
            email=self.invitee.email,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(days=3),
            status=AgencyInvitation.Status.PENDING,
        )

        with self.assertRaises(InvitationRejectValidationError):
            reject_agency_invitation_for_user(
                token=str(invitation.token),
                user=self.other_user,
            )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, AgencyInvitation.Status.PENDING)

    def test_reject_agency_invitation_marks_expired_when_token_is_expired(self):
        invitation = AgencyInvitation.objects.create(
            agency=self.agency,
            email=self.invitee.email,
            role_to_assign=AgencyMembership.Role.AGENCY_READER,
            invited_by=self.inviter,
            expires_at=timezone.now() + timedelta(minutes=30),
            status=AgencyInvitation.Status.PENDING,
        )
        AgencyInvitation.objects.filter(id=invitation.id).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )

        with self.assertRaises(InvitationRejectValidationError):
            reject_agency_invitation_for_user(
                token=str(invitation.token),
                user=self.invitee,
            )

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, AgencyInvitation.Status.EXPIRED)
