# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import base64
import json
from types import SimpleNamespace

from django.test import RequestFactory
from django.test import SimpleTestCase

from rpsd_config.server.socialaccount_adapter import (
    RpsdSocialAccountAdapter,
    _extract_groups_from_extra_data,
)


def _make_jwt(payload: dict) -> str:
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload).encode("utf-8")
    ).rstrip(b"=")
    return f"header.{encoded_payload.decode('ascii')}.signature"


class _DummyUser:
    def __init__(self, *, is_staff: bool, is_superuser: bool = False, pk=None):
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        self.pk = pk
        self.saved_update_fields = None

    def save(self, update_fields=None):
        self.saved_update_fields = update_fields


class _DummyAccount:
    def __init__(self, extra_data):
        self.extra_data = extra_data


class _DummySocialLogin:
    def __init__(self, *, user, extra_data):
        self.user = user
        self.account = _DummyAccount(extra_data=extra_data)


class SocialAccountAdapterTests(SimpleTestCase):
    def test_extract_groups_from_extra_data_reads_nested_id_token_claims(self):
        extra_data = {"id_token": {"groups": ["/rpsd/admin", "/rpsd/viewer"]}}
        groups = _extract_groups_from_extra_data(extra_data)
        assert "/rpsd/admin" in groups
        assert "/rpsd/viewer" in groups

    def test_extract_groups_from_extra_data_reads_jwt_id_token_claims(self):
        token = _make_jwt({"groups": ["/rpsd/admin"]})
        groups = _extract_groups_from_extra_data({"id_token": token})
        assert groups == {"/rpsd/admin"}

    def test_sync_staff_mapping_sets_staff_for_admin_group(self):
        adapter = RpsdSocialAccountAdapter()
        user = _DummyUser(is_staff=False, pk=101)
        sociallogin = _DummySocialLogin(
            user=user,
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )

        adapter._sync_staff_from_oidc_groups(sociallogin)

        assert user.is_staff is True
        assert user.saved_update_fields == ["is_staff"]
        assert user.is_superuser is False

    def test_sync_staff_mapping_does_not_change_user_without_admin_group(self):
        adapter = RpsdSocialAccountAdapter()
        user = _DummyUser(is_staff=False, pk=202)
        sociallogin = _DummySocialLogin(
            user=user,
            extra_data={"id_token": {"groups": ["/rpsd/reader"]}},
        )

        adapter._sync_staff_from_oidc_groups(sociallogin)

        assert user.is_staff is False
        assert user.saved_update_fields is None

    def test_sync_staff_mapping_does_not_change_superuser_flag(self):
        adapter = RpsdSocialAccountAdapter()
        user = _DummyUser(is_staff=False, is_superuser=True, pk=303)
        sociallogin = _DummySocialLogin(
            user=user,
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )

        adapter._sync_staff_from_oidc_groups(sociallogin)

        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.saved_update_fields == ["is_staff"]

    def test_on_authentication_error_logs_diagnostic_fields(self):
        adapter = RpsdSocialAccountAdapter()
        request = RequestFactory().get(
            "/accounts/oidc/keycloak/login/callback/",
            data={"state": "s-123", "iss": "http://issuer.local", "code": "abc"},
        )
        request.session = SimpleNamespace(session_key="sess-1")
        provider = SimpleNamespace(id="keycloak")

        with self.assertLogs(
            "rpsd_config.server.socialaccount_adapter", level="ERROR"
        ) as logs:
            adapter.on_authentication_error(
                request,
                provider,
                error="invalid_state",
                exception=RuntimeError("boom"),
                extra_context={"state": {"next": "/exchange_agreement/me/contracts/"}},
            )

        log_output = "\n".join(logs.output)
        assert "error=invalid_state" in log_output
        assert "state=s-123" in log_output
        assert "iss=http://issuer.local" in log_output
