# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.test import RequestFactory, SimpleTestCase

from rpsd_config.server.oidc_adapter import RpsdOpenIDConnectOAuth2Adapter


class OidcAdapterTests(SimpleTestCase):
    def test_issuer_candidates_respect_priority_and_deduplicate(self):
        request = RequestFactory().get(
            "/accounts/oidc/keycloak/login/callback/",
            data={"iss": "http://callback-issuer"},
        )
        adapter = RpsdOpenIDConnectOAuth2Adapter(request, "keycloak")
        provider = SimpleNamespace(
            app=SimpleNamespace(settings={"issuer": "http://configured-issuer"})
        )

        with patch.object(adapter, "get_provider", return_value=provider):
            with patch(
                "allauth.socialaccount.providers.openid_connect.views."
                "OpenIDConnectOAuth2Adapter.openid_config",
                new_callable=PropertyMock,
            ) as openid_config:
                openid_config.return_value = {"issuer": "http://configured-issuer"}
                candidates = adapter._issuer_candidates()

        assert candidates == ["http://configured-issuer", "http://callback-issuer"]

    def test_openid_config_rewrites_endpoints_to_server_origin(self):
        request = RequestFactory().get("/accounts/oidc/keycloak/login/callback/")
        adapter = RpsdOpenIDConnectOAuth2Adapter(request, "keycloak")
        provider = SimpleNamespace(
            server_url=(
                "http://keycloak:8080/realms/rpsd/.well-known/openid-configuration"
            )
        )

        discovered = {
            "issuer": "http://localhost:19300/realms/rpsd",
            "authorization_endpoint": (
                "http://localhost:19300/realms/rpsd/protocol/openid-connect/auth"
            ),
            "token_endpoint": (
                "http://localhost:19300/realms/rpsd/protocol/openid-connect/token"
            ),
            "jwks_uri": "http://localhost:19300/realms/rpsd/protocol/openid-connect/certs",
            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        }

        with patch.object(adapter, "get_provider", return_value=provider):
            with patch(
                "allauth.socialaccount.providers.openid_connect.views."
                "OpenIDConnectOAuth2Adapter.openid_config",
                new_callable=PropertyMock,
            ) as openid_config:
                openid_config.return_value = discovered
                rewritten = adapter.openid_config

        assert rewritten["token_endpoint"].startswith("http://keycloak:8080/")
        assert rewritten["jwks_uri"].startswith("http://keycloak:8080/")
        assert rewritten["authorization_endpoint"].startswith("http://keycloak:8080/")
        assert rewritten["issuer"].startswith("http://keycloak:8080/")
        assert rewritten["token_endpoint_auth_methods_supported"] == [
            "client_secret_basic"
        ]

    def test_decode_id_token_falls_back_to_next_issuer_candidate(self):
        request = RequestFactory().get("/accounts/oidc/keycloak/login/callback/")
        adapter = RpsdOpenIDConnectOAuth2Adapter(request, "keycloak")
        adapter._rpsd_openid_config = {
            "jwks_uri": "http://keycloak:8080/realms/rpsd/protocol/openid-connect/certs"
        }
        app = SimpleNamespace(client_id="rpsd-config")

        with patch.object(
            adapter,
            "_issuer_candidates",
            return_value=["http://issuer-wrong", "http://issuer-good"],
        ):
            with patch(
                "rpsd_config.server.oidc_adapter.jwtkit.verify_and_decode"
            ) as verify:
                verify.side_effect = [
                    OAuth2Error("wrong issuer"),
                    {"sub": "u-1", "iss": "http://issuer-good"},
                ]

                decoded = adapter._decode_id_token(app, "id-token")

        assert decoded["iss"] == "http://issuer-good"
        assert verify.call_count == 2
        first_issuer = verify.call_args_list[0].kwargs["issuer"]
        second_issuer = verify.call_args_list[1].kwargs["issuer"]
        assert first_issuer == "http://issuer-wrong"
        assert second_issuer == "http://issuer-good"
