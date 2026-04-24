# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib.auth import get_user_model
from django.test import TestCase


class HomeAdminAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff-user",
            password="test-pass-1",
            is_staff=True,
        )
        self.regular_user = user_model.objects.create_user(
            username="regular-user",
            password="test-pass-2",
            is_staff=False,
        )

    def test_home_shows_admin_action_for_staff(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/admin/"')

    def test_home_hides_admin_action_for_non_staff(self):
        self.client.force_login(self.regular_user)
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/admin/"')

    def test_home_anon_shows_direct_oidc_login_action(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'href="/accounts/oidc/keycloak/login/?process=login&amp;next=%2F"',
        )
