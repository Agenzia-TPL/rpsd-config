# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope


class _FakeKeycloakAdmin:
    def __init__(self):
        self.ensure_agency_groups_calls: list[str] = []
        self.find_user_by_email_calls: list[str] = []
        self.ensure_user_calls: list[tuple[str, str]] = []
        self.assign_user_to_group_calls: list[tuple[str, str]] = []
        self.set_user_password_calls: list[tuple[str, str, bool]] = []

    def ensure_agency_groups(self, agency_key: str):
        self.ensure_agency_groups_calls.append(agency_key)
        return {
            "admin": SimpleNamespace(
                id=f"group-{agency_key}-admin",
                path=f"/rpsd/{agency_key}/admin",
            ),
            "editor": SimpleNamespace(
                id=f"group-{agency_key}-editor",
                path=f"/rpsd/{agency_key}/editor",
            ),
            "reader": SimpleNamespace(
                id=f"group-{agency_key}-reader",
                path=f"/rpsd/{agency_key}/reader",
            ),
        }

    def find_user_by_email(self, email: str):
        self.find_user_by_email_calls.append(email)
        return None

    def ensure_user(self, *, username: str, email: str):
        self.ensure_user_calls.append((username, email))
        return SimpleNamespace(id=f"kc-{username}", username=username, email=email)

    def assign_user_to_group(self, *, user_id: str, group_id: str):
        self.assign_user_to_group_calls.append((user_id, group_id))

    def set_user_password(
        self, *, user_id: str, password: str, temporary: bool = False
    ):
        self.set_user_password_calls.append((user_id, password, temporary))


class AgencyInvitationApiAndOnboardingTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.platform_admin = self.user_model.objects.create_user(
            username="platform-admin",
            email="platform-admin@example.com",
            password="platform-pass",
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="kc-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )

    def test_create_agency_invitation_endpoint_provisions_groups_and_user(self):
        agency = Agency.objects.create(name="ATPL Milano")
        fake_keycloak = _FakeKeycloakAdmin()
        self.client.force_login(self.platform_admin)

        with patch(
            "rpsd_config.exchange_agreement.services.agency_invitations.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                "/exchange_agreement/api/v1/agency-invitations",
                data=json.dumps(
                    {
                        "agency_id": agency.id,
                        "role_to_assign": AgencyMembership.Role.AGENCY_ADMIN,
                        "email": "operatore1@example.com",
                        "provision_user_if_missing": True,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["agency_key"], agency.agency_key)
        self.assertEqual(
            payload["assigned_group_path"], f"/rpsd/{agency.agency_key}/admin"
        )
        provisioned_username = fake_keycloak.ensure_user_calls[0][0]
        self.assertEqual(
            payload["provisioned_user_id"],
            f"kc-{provisioned_username}",
        )
        self.assertEqual(fake_keycloak.ensure_agency_groups_calls, [agency.agency_key])
        self.assertEqual(
            fake_keycloak.find_user_by_email_calls,
            ["operatore1@example.com"],
        )

        invitation = AgencyInvitation.objects.get(token=payload["token"])
        self.assertEqual(invitation.invited_by_id, self.platform_admin.id)
        self.assertEqual(invitation.role_to_assign, AgencyMembership.Role.AGENCY_ADMIN)

    def test_cross_agency_scope_is_denied_for_agency_admin(self):
        agency_a = Agency.objects.create(name="Agenzia Bergamo")
        agency_b = Agency.objects.create(name="Agenzia Como")

        agency_admin = self.user_model.objects.create_user(
            username="agency-admin",
            email="agency-admin@example.com",
            password="agency-pass",
        )
        SocialAccount.objects.create(
            user=agency_admin,
            provider="openid_connect",
            uid="kc-agency-admin",
            extra_data={
                "id_token": {
                    "groups": [f"/rpsd/{agency_a.agency_key}/admin"],
                }
            },
        )

        self.client.force_login(agency_admin)
        fake_keycloak = _FakeKeycloakAdmin()
        with patch(
            "rpsd_config.exchange_agreement.services.agency_invitations.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                "/exchange_agreement/api/v1/agency-invitations",
                data=json.dumps(
                    {
                        "agency_id": agency_b.id,
                        "role_to_assign": AgencyMembership.Role.AGENCY_READER,
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(AgencyInvitation.objects.count(), 0)

    def test_agency_invitation_landing_sets_onboarding_kind(self):
        agency = Agency.objects.create(name="ATPL Monza")
        invitation = AgencyInvitation.objects.create(
            agency=agency,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.platform_admin,
            expires_at=timezone.now() + timedelta(days=14),
        )

        response = self.client.post(
            reverse("invitation-landing-root", kwargs={"token": invitation.token})
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.session.get("onboarding_invitation_kind"),
            "agency",
        )
        self.assertEqual(
            self.client.session.get("onboarding_invitation_token"),
            str(invitation.token),
        )

    def test_agency_invitation_landing_prepares_credentials_before_login(self):
        agency = Agency.objects.create(name="ATPL Pavia")
        invitation = AgencyInvitation.objects.create(
            agency=agency,
            email="operatore-pavia@example.com",
            role_to_assign=AgencyMembership.Role.AGENCY_ADMIN,
            invited_by=self.platform_admin,
            expires_at=timezone.now() + timedelta(days=14),
        )
        fake_keycloak = _FakeKeycloakAdmin()

        with patch(
            "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                reverse("invitation-landing-root", kwargs={"token": invitation.token}),
                data={
                    "action": "prepare-credentials",
                    "email": "operatore-pavia@example.com",
                    "password1": "PasswordSicura123!",
                    "password2": "PasswordSicura123!",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Credenziali iniziali impostate correttamente")
        self.assertContains(response, "Accedi e accetta invito")
        self.assertNotContains(response, "Crea credenziali iniziali")
        self.assertEqual(
            self.client.session.get("onboarding_invitation_token"),
            str(invitation.token),
        )
        self.assertEqual(self.client.session.get("onboarding_invitation_kind"), "agency")
        self.assertEqual(
            self.client.session.get("prepared_invitation_credentials_token"),
            str(invitation.token),
        )
        self.assertIn(
            ("operatore-pavia@example.com", "operatore-pavia@example.com"),
            fake_keycloak.ensure_user_calls,
        )
        self.assertIn(
            ("kc-operatore-pavia@example.com", "PasswordSicura123!", False),
            fake_keycloak.set_user_password_calls,
        )

    def test_agency_invitation_landing_rejects_credentials_email_mismatch(self):
        agency = Agency.objects.create(name="ATPL Mantova")
        invitation = AgencyInvitation.objects.create(
            agency=agency,
            email="operatore-mantova@example.com",
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.platform_admin,
            expires_at=timezone.now() + timedelta(days=14),
        )
        fake_keycloak = _FakeKeycloakAdmin()

        with patch(
            "rpsd_config.exchange_agreement.views.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                reverse("invitation-landing-root", kwargs={"token": invitation.token}),
                data={
                    "action": "prepare-credentials",
                    "email": "altro@example.com",
                    "password1": "PasswordSicura123!",
                    "password2": "PasswordSicura123!",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email non coerente")
        self.assertEqual(fake_keycloak.ensure_user_calls, [])
        self.assertEqual(fake_keycloak.set_user_password_calls, [])

    def test_agency_invitation_landing_rejects_targeted_invitation(self):
        agency = Agency.objects.create(name="ATPL Cremona")
        invitee = self.user_model.objects.create_user(
            username="agency-reject-user",
            email="agency-reject-user@example.com",
            password="agency-reject-pass",
        )
        invitation = AgencyInvitation.objects.create(
            agency=agency,
            email=invitee.email,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.platform_admin,
            expires_at=timezone.now() + timedelta(days=14),
        )

        self.client.force_login(invitee)
        response = self.client.post(
            reverse("invitation-landing-root", kwargs={"token": invitation.token}),
            data={"action": "reject-invitation"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invito rifiutato correttamente")
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, AgencyInvitation.Status.REJECTED)
        self.assertEqual(invitation.rejected_by_id, invitee.id)

    def test_onboarding_callback_accepts_agency_invitation_and_assigns_group(self):
        agency = Agency.objects.create(name="ATPL Lodi")
        invitee = self.user_model.objects.create_user(
            username="invitee-agency",
            email="invitee-agency@example.com",
            password="invitee-pass",
        )
        SocialAccount.objects.create(
            user=invitee,
            provider="openid_connect",
            uid="kc-invitee-agency",
            extra_data={"id_token": {"groups": ["/rpsd/reader"]}},
        )

        invitation = AgencyInvitation.objects.create(
            agency=agency,
            email=invitee.email,
            role_to_assign=AgencyMembership.Role.AGENCY_EDITOR,
            invited_by=self.platform_admin,
            expires_at=timezone.now() + timedelta(days=14),
        )

        fake_keycloak = _FakeKeycloakAdmin()
        session = self.client.session
        session["onboarding_invitation_token"] = str(invitation.token)
        session["onboarding_invitation_kind"] = "agency"
        session.save()

        self.client.force_login(invitee)
        with patch(
            "rpsd_config.exchange_agreement.services.agency_invitations.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.get(
                reverse("exchange_agreement:onboarding-callback")
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Onboarding completato")
        self.assertContains(response, agency.agency_key)

        invitation.refresh_from_db()
        self.assertEqual(invitation.status, AgencyInvitation.Status.ACCEPTED)
        self.assertEqual(invitation.accepted_by_id, invitee.id)

        membership = AgencyMembership.objects.get(agency=agency, user=invitee)
        self.assertEqual(membership.role, AgencyMembership.Role.AGENCY_EDITOR)

        self.assertEqual(fake_keycloak.ensure_agency_groups_calls, [agency.agency_key])
        self.assertIn(
            ("kc-invitee-agency", f"group-{agency.agency_key}-editor"),
            fake_keycloak.assign_user_to_group_calls,
        )

        social_account = SocialAccount.objects.get(
            user=invitee, provider="openid_connect"
        )
        self.assertIn(
            f"/rpsd/{agency.agency_key}/editor",
            social_account.extra_data.get("groups", []),
        )
        scope = resolve_user_agency_scope(invitee)
        self.assertIn(agency.agency_key, scope.editor_agency_keys)

        user_area = self.client.get(reverse("exchange_agreement:user-area"))
        self.assertEqual(user_area.status_code, 200)
        self.assertContains(user_area, agency.agency_key)
