# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import tempfile

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    IndicatorProfile,
    NetexValidationProfile,
    SiriValidationProfile,
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
        self._media_override = override_settings(MEDIA_ROOT=self._tmpdir.name)
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

    def test_initialization_uploads_and_activation_rules(self):
        self.client.force_login(self.platform_admin)

        first_netex = SimpleUploadedFile(
            "netex-v1.xsd",
            b"<xsd:schema xmlns:xsd='http://www.w3.org/2001/XMLSchema'></xsd:schema>",
            content_type="application/xml",
        )
        first_upload = self.client.post(
            self.url,
            {
                "tab": "inizializzazione",
                "action": "upload-netex",
                "netex_label": "Netex v1",
                "netex_is_active": "on",
                "netex_file": first_netex,
            },
        )
        self.assertEqual(first_upload.status_code, 200)
        self.assertEqual(NetexValidationProfile.objects.count(), 1)
        self.assertEqual(
            NetexValidationProfile.objects.filter(is_active=True).count(), 1
        )

        second_netex = SimpleUploadedFile(
            "netex-v2.xsd",
            b"<xsd:schema xmlns:xsd='http://www.w3.org/2001/XMLSchema'></xsd:schema>",
            content_type="application/xml",
        )
        second_upload = self.client.post(
            self.url,
            {
                "tab": "inizializzazione",
                "action": "upload-netex",
                "netex_label": "Netex v2",
                "netex_is_active": "on",
                "netex_file": second_netex,
            },
        )
        self.assertEqual(second_upload.status_code, 200)
        self.assertEqual(NetexValidationProfile.objects.count(), 2)
        self.assertEqual(
            NetexValidationProfile.objects.filter(is_active=True).count(), 1
        )
        self.assertEqual(
            NetexValidationProfile.objects.get(is_active=True).label,
            "Netex v2",
        )

        first_siri = SimpleUploadedFile(
            "siri-pt-v1.xsd",
            b"<xsd:schema xmlns:xsd='http://www.w3.org/2001/XMLSchema'></xsd:schema>",
            content_type="application/xml",
        )
        self.client.post(
            self.url,
            {
                "tab": "inizializzazione",
                "action": "upload-siri",
                "siri_type": SiriValidationProfile.ProfileType.PT,
                "siri_label": "SIRI PT v1",
                "siri_is_active": "on",
                "siri_file": first_siri,
            },
        )

        second_siri = SimpleUploadedFile(
            "siri-pt-v2.xsd",
            b"<xsd:schema xmlns:xsd='http://www.w3.org/2001/XMLSchema'></xsd:schema>",
            content_type="application/xml",
        )
        self.client.post(
            self.url,
            {
                "tab": "inizializzazione",
                "action": "upload-siri",
                "siri_type": SiriValidationProfile.ProfileType.PT,
                "siri_label": "SIRI PT v2",
                "siri_is_active": "on",
                "siri_file": second_siri,
            },
        )

        self.assertEqual(
            SiriValidationProfile.objects.filter(
                profile_type=SiriValidationProfile.ProfileType.PT,
                is_active=True,
            ).count(),
            1,
        )
        self.assertEqual(
            SiriValidationProfile.objects.get(
                profile_type=SiriValidationProfile.ProfileType.PT,
                is_active=True,
            ).label,
            "SIRI PT v2",
        )

        indicator = SimpleUploadedFile(
            "indicatori-base.yml",
            b"indicator_code: KPI-01\nlabel: Demo\n",
            content_type="application/x-yaml",
        )
        indicator_upload = self.client.post(
            self.url,
            {
                "tab": "inizializzazione",
                "action": "upload-indicator",
                "indicator_label": "Indicatori base",
                "indicator_is_active": "on",
                "indicator_file": indicator,
            },
        )
        self.assertEqual(indicator_upload.status_code, 200)
        self.assertEqual(IndicatorProfile.objects.filter(is_active=True).count(), 1)

        final_page = self.client.get(self.url + "?tab=inizializzazione")
        self.assertEqual(final_page.status_code, 200)
        self.assertContains(final_page, "Sistema inizializzato")
