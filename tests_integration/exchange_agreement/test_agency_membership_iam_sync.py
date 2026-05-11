# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from types import SimpleNamespace
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import Agency, AgencyMembership
from rpsd_config.exchange_agreement.services.agency_memberships import (
    AgencyMembershipProvisioningError,
    revoke_agency_membership,
    sync_agency_memberships_from_groups,
)
from rpsd_config.server.keycloak_admin import KeycloakAdminConfigError


class _FakeKeycloakAdmin:
    def __init__(self, *, fail_remove: bool = False):
        self.fail_remove = fail_remove
        self.assign_user_to_group_calls: list[tuple[str, str]] = []
        self.remove_user_from_group_calls: list[tuple[str, str]] = []
        self.ensure_agency_groups_calls: list[str] = []
        self.get_group_by_path_calls: list[str] = []

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

    def ensure_user(self, *, username: str, email: str):
        return SimpleNamespace(id=f"kc-{username}", username=username, email=email)

    def assign_user_to_group(self, *, user_id: str, group_id: str):
        self.assign_user_to_group_calls.append((user_id, group_id))

    def get_group_by_path(self, group_path: str):
        self.get_group_by_path_calls.append(group_path)
        return SimpleNamespace(
            id=f"group-{group_path.rsplit('/', 1)[-1]}",
            path=group_path,
        )

    def remove_user_from_group(self, *, user_id: str, group_id: str):
        if self.fail_remove:
            raise KeycloakAdminConfigError("Keycloak unavailable")
        self.remove_user_from_group_calls.append((user_id, group_id))


class AgencyMembershipIamSyncTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.platform_admin = user_model.objects.create_user(
            username="iam-platform-admin",
            email="iam-platform-admin@example.com",
            password="platform-pass",
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="kc-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.user = user_model.objects.create_user(
            username="iam-agency-user",
            email="iam-agency-user@example.com",
            password="user-pass",
        )
        SocialAccount.objects.create(
            user=self.user,
            provider="openid_connect",
            uid="kc-agency-user",
            extra_data={},
        )
        self.agency = Agency.objects.create(name="Agenzia IAM Sync")

    def test_sync_from_keycloak_groups_creates_active_membership(self):
        result = sync_agency_memberships_from_groups(
            user=self.user,
            groups=[f"/rpsd/{self.agency.agency_key}/editor"],
        )

        self.assertEqual(result.touched, 1)
        membership = AgencyMembership.objects.get(agency=self.agency, user=self.user)
        self.assertEqual(membership.role, AgencyMembership.Role.AGENCY_EDITOR)
        self.assertEqual(membership.status, AgencyMembership.Status.ACTIVE)
        self.assertEqual(membership.source, AgencyMembership.Source.KEYCLOAK_SYNC)
        self.assertEqual(
            membership.keycloak_group_path,
            f"/rpsd/{self.agency.agency_key}/editor",
        )
        self.assertEqual(membership.keycloak_user_id, "kc-agency-user")
        self.assertIsNotNone(membership.last_synced_at)

    def test_non_authoritative_sync_does_not_revoke_missing_local_membership(self):
        membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
        )

        result = sync_agency_memberships_from_groups(
            user=self.user,
            groups=[],
            authoritative=False,
        )

        self.assertEqual(result.revoked, 0)
        membership.refresh_from_db()
        self.assertEqual(membership.status, AgencyMembership.Status.ACTIVE)

    def test_authoritative_sync_revokes_missing_local_membership(self):
        membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
        )

        result = sync_agency_memberships_from_groups(
            user=self.user,
            groups=[],
            authoritative=True,
        )

        self.assertEqual(result.revoked, 1)
        membership.refresh_from_db()
        self.assertEqual(membership.status, AgencyMembership.Status.REVOKED)

    def test_revoke_is_keycloak_first_and_does_not_update_django_on_failure(self):
        membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
            keycloak_group_path=f"/rpsd/{self.agency.agency_key}/reader",
            keycloak_user_id="kc-agency-user",
        )
        fake_keycloak = _FakeKeycloakAdmin(fail_remove=True)

        with self.assertRaises(AgencyMembershipProvisioningError):
            revoke_agency_membership(
                actor=self.platform_admin,
                membership=membership,
                keycloak=fake_keycloak,
            )

        membership.refresh_from_db()
        self.assertEqual(membership.status, AgencyMembership.Status.ACTIVE)
        self.assertIsNone(membership.revoked_at)

    def test_agency_detail_revoke_action_updates_keycloak_and_django(self):
        membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
            keycloak_group_path=f"/rpsd/{self.agency.agency_key}/reader",
            keycloak_user_id="kc-agency-user",
        )
        fake_keycloak = _FakeKeycloakAdmin()

        self.client.force_login(self.platform_admin)
        with patch(
            "rpsd_config.exchange_agreement.services.agency_memberships.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                reverse(
                    "exchange_agreement:agency-detail",
                    args=[self.agency.agency_key],
                ),
                data={
                    "tab": "utenti",
                    "action": "revoke-agency-membership",
                    "membership_id": membership.id,
                },
            )

        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertEqual(membership.status, AgencyMembership.Status.REVOKED)
        self.assertEqual(membership.revoked_by_id, self.platform_admin.id)
        self.assertEqual(
            fake_keycloak.remove_user_from_group_calls,
            [("kc-agency-user", "group-reader")],
        )

    def test_agency_detail_change_role_assigns_new_group_then_removes_old_group(self):
        membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
            keycloak_group_path=f"/rpsd/{self.agency.agency_key}/reader",
            keycloak_user_id="kc-agency-user",
        )
        fake_keycloak = _FakeKeycloakAdmin()

        self.client.force_login(self.platform_admin)
        with patch(
            "rpsd_config.exchange_agreement.services.agency_memberships.KeycloakAdminService.from_settings",
            return_value=fake_keycloak,
        ):
            response = self.client.post(
                reverse(
                    "exchange_agreement:agency-detail",
                    args=[self.agency.agency_key],
                ),
                data={
                    "tab": "utenti",
                    "action": "change-agency-membership-role",
                    "membership_id": membership.id,
                    "role": AgencyMembership.Role.AGENCY_EDITOR,
                },
            )

        self.assertEqual(response.status_code, 302)
        membership.refresh_from_db()
        self.assertEqual(membership.role, AgencyMembership.Role.AGENCY_EDITOR)
        self.assertEqual(membership.status, AgencyMembership.Status.ACTIVE)
        self.assertEqual(
            fake_keycloak.assign_user_to_group_calls,
            [("kc-agency-user", f"group-{self.agency.agency_key}-editor")],
        )
        self.assertEqual(
            fake_keycloak.remove_user_from_group_calls,
            [("kc-agency-user", "group-reader")],
        )

    def test_reader_membership_cannot_manage_agency_memberships(self):
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.user,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
        )
        target = get_user_model().objects.create_user(
            username="iam-target",
            email="iam-target@example.com",
            password="target-pass",
        )
        target_membership = AgencyMembership.objects.create(
            agency=self.agency,
            user=target,
            role=AgencyMembership.Role.AGENCY_READER,
            status=AgencyMembership.Status.ACTIVE,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse(
                "exchange_agreement:agency-detail",
                args=[self.agency.agency_key],
            ),
            data={
                "tab": "utenti",
                "action": "revoke-agency-membership",
                "membership_id": target_membership.id,
            },
        )

        self.assertEqual(response.status_code, 403)
        target_membership.refresh_from_db()
        self.assertEqual(target_membership.status, AgencyMembership.Status.ACTIVE)
