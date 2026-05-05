# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from types import SimpleNamespace
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
)
from rpsd_config.server.keycloak_admin import KeycloakAdminAPIError


class _FakeKeycloakAdmin:
    def __init__(self):
        self.ensure_agency_groups_calls: list[str] = []
        self.find_user_by_email_calls: list[str] = []
        self.ensure_user_calls: list[tuple[str, str]] = []

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


class _FailingKeycloakAdmin(_FakeKeycloakAdmin):
    def ensure_agency_groups(self, agency_key: str):
        self.ensure_agency_groups_calls.append(agency_key)
        raise KeycloakAdminAPIError(
            method="GET",
            url="http://keycloak/admin/realms/rpsd/group-by-path",
            status_code=503,
            detail="simulated failure",
        )


class AgencyBootstrapPhase5Tests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.platform_admin = self._create_oidc_user(
            username="platform-admin-phase5",
            email="platform-admin-phase5@example.com",
            groups=["/rpsd/admin"],
        )
        self.agency_admin = self._create_oidc_user(
            username="agency-admin-phase5",
            email="agency-admin-phase5@example.com",
            groups=["/rpsd/existing-agency/admin"],
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

    def test_platform_admin_can_bootstrap_agency_via_api(self):
        fake_keycloak = _FakeKeycloakAdmin()
        self.client.force_login(self.platform_admin)

        with patch(
            "rpsd_config.exchange_agreement.services.agency_bootstrap.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                "/exchange_agreement/api/v1/agencies/bootstrap",
                data=json.dumps(
                    {
                        "agency_name": "Agenzia TPL Milano",
                        "initial_admin_email": "operatore1@example.com",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["agency_name"], "Agenzia TPL Milano")
        self.assertEqual(payload["agency_key"], "agenzia-tpl-milano")
        self.assertEqual(
            payload["assigned_group_path"], "/rpsd/agenzia-tpl-milano/admin"
        )
        self.assertEqual(
            fake_keycloak.ensure_agency_groups_calls, ["agenzia-tpl-milano"]
        )
        self.assertEqual(
            fake_keycloak.find_user_by_email_calls, ["operatore1@example.com"]
        )

        agency = Agency.objects.get(agency_key="agenzia-tpl-milano")
        invitation = AgencyInvitation.objects.get(token=payload["invitation_token"])
        self.assertEqual(invitation.agency_id, agency.id)
        self.assertEqual(invitation.role_to_assign, AgencyMembership.Role.AGENCY_ADMIN)
        self.assertEqual(invitation.invited_by_id, self.platform_admin.id)

    def test_non_platform_admin_is_forbidden_on_bootstrap_api_and_ui(self):
        self.client.force_login(self.agency_admin)

        api_response = self.client.post(
            "/exchange_agreement/api/v1/agencies/bootstrap",
            data=json.dumps(
                {
                    "agency_name": "Agenzia TPL Bergamo",
                    "initial_admin_email": "agency-bootstrap@example.com",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(api_response.status_code, 403)

        ui_response = self.client.get(reverse("exchange_agreement:agency-bootstrap"))
        self.assertEqual(ui_response.status_code, 403)
        self.assertEqual(Agency.objects.count(), 0)

    def test_duplicate_agency_key_is_rejected_without_keycloak_calls(self):
        Agency.objects.create(name="Agenzia Esistente", agency_key="atpl-milano")
        fake_keycloak = _FakeKeycloakAdmin()
        self.client.force_login(self.platform_admin)

        with patch(
            "rpsd_config.exchange_agreement.services.agency_bootstrap.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                "/exchange_agreement/api/v1/agencies/bootstrap",
                data=json.dumps(
                    {
                        "agency_name": "ATPL Milano",
                        "agency_key": "atpl-milano",
                        "initial_admin_email": "dup@example.com",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("already exists", response.json()["detail"])
        self.assertEqual(fake_keycloak.ensure_agency_groups_calls, [])
        self.assertEqual(Agency.objects.count(), 1)
        self.assertEqual(AgencyInvitation.objects.count(), 0)

    def test_keycloak_failure_keeps_bootstrap_state_consistent(self):
        failing_keycloak = _FailingKeycloakAdmin()
        self.client.force_login(self.platform_admin)

        with patch(
            "rpsd_config.exchange_agreement.services.agency_bootstrap.KeycloakAdminService.from_settings",
            return_value=failing_keycloak,
        ):
            response = self.client.post(
                "/exchange_agreement/api/v1/agencies/bootstrap",
                data=json.dumps(
                    {
                        "agency_name": "Agenzia TPL Como",
                        "initial_admin_email": "platform-admin-como@example.com",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(Agency.objects.count(), 0)
        self.assertEqual(AgencyInvitation.objects.count(), 0)

    def test_platform_admin_can_use_bootstrap_ui(self):
        fake_keycloak = _FakeKeycloakAdmin()
        self.client.force_login(self.platform_admin)

        with patch(
            "rpsd_config.exchange_agreement.services.agency_bootstrap.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                reverse("exchange_agreement:agency-bootstrap"),
                {
                    "agency_name": "Agenzia TPL Monza",
                    "initial_admin_email": "agency-monza-admin@example.com",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("exchange_agreement:agency-bootstrap-result"),
        )
        result_response = self.client.get(response["Location"])
        self.assertEqual(result_response.status_code, 200)
        self.assertContains(result_response, "Bootstrap completato")
        self.assertContains(result_response, "agenzia-tpl-monza")
        self.assertContains(result_response, "Copia")
        self.assertTrue(Agency.objects.filter(agency_key="agenzia-tpl-monza").exists())

    def test_agencies_page_shows_bootstrap_action_for_platform_admin_only(self):
        self.client.force_login(self.platform_admin)
        platform_page = self.client.get(reverse("exchange_agreement:agencies"))
        self.assertContains(
            platform_page,
            reverse("exchange_agreement:agency-bootstrap"),
        )

        self.client.force_login(self.agency_admin)
        agency_page = self.client.get(reverse("exchange_agreement:agencies"))
        self.assertNotContains(
            agency_page,
            reverse("exchange_agreement:agency-bootstrap"),
        )

        user_area = self.client.get(reverse("exchange_agreement:user-area"))
        self.assertNotContains(
            user_area,
            reverse("exchange_agreement:agency-bootstrap"),
        )
