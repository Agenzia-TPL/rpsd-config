# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import tempfile

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
)


class PlatformConfigurationPhase9Tests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.platform_admin = user_model.objects.create_user(
            username="platform-config-admin",
            email="platform-config-admin@example.com",
            password="platform-pass",
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="kc-platform-config-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.regular_user = user_model.objects.create_user(
            username="regular-config-user",
            email="regular-config-user@example.com",
            password="regular-pass",
        )
        self.superuser = user_model.objects.create_superuser(
            username="superuser-config",
            email="superuser-config@example.com",
            password="super-pass",
        )
        self.url = reverse("exchange_agreement:platform-configuration")

        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._media_override = override_settings(
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=self._tmpdir.name,
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            MEDIA_ROOT=self._tmpdir.name,
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)

    def test_platform_configuration_permissions(self):
        self.client.force_login(self.regular_user)
        denied = self.client.get(self.url)
        self.assertEqual(denied.status_code, 403)

        self.client.force_login(self.platform_admin)
        allowed_admin = self.client.get(self.url)
        self.assertEqual(allowed_admin.status_code, 200)
        self.assertContains(allowed_admin, "Configurazione Piattaforma")

        self.client.force_login(self.superuser)
        allowed_superuser = self.client.get(self.url)
        self.assertEqual(allowed_superuser.status_code, 200)

    def test_platform_configuration_users_tab_shows_groups(self):
        self.client.force_login(self.platform_admin)
        response = self.client.get(self.url + "?tab=utenti")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.platform_admin.username)
        self.assertContains(response, "/rpsd/admin")
        self.assertContains(response, "Platform admin")

    def test_legacy_initialization_redirects_and_actions_have_no_effect(self):
        self.client.force_login(self.platform_admin)
        self.assertRedirects(
            self.client.get(self.url + "?tab=inizializzazione"), self.url + "?tab=asset"
        )
        for action in (
            "upload-netex",
            "upload-siri",
            "set-netex-active",
            "set-siri-active",
        ):
            response = self.client.post(
                self.url,
                {
                    "tab": "inizializzazione",
                    "action": action,
                    "netex_file": SimpleUploadedFile("netex.xsd", b"schema"),
                },
            )
            self.assertEqual(response.status_code, 400)
        self.assertFalse(ConfigurationAsset.objects.exists())
        self.assertNotContains(
            self.client.get(self.url), "Stato inizializzazione sistema"
        )
