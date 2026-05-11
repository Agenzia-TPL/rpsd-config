# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import base64
import json
import logging
from typing import Any

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings

LOGGER = logging.getLogger(__name__)
RPSD_ADMIN_GROUP_PATH = "/rpsd/admin"


def _decode_jwt_payload_without_verification(token: str) -> dict[str, Any]:
    """Decode JWT payload for claim extraction only (no signature verification)."""
    if "." not in token:
        return {}

    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
        claims = json.loads(decoded)
    except (UnicodeDecodeError, ValueError):
        return {}

    return claims if isinstance(claims, dict) else {}


def _extract_groups_from_claims(claims: Any) -> set[str]:
    if not isinstance(claims, dict):
        return set()
    groups = claims.get("groups")
    if not isinstance(groups, list):
        return set()
    return {group for group in groups if isinstance(group, str)}


def _extract_groups_from_extra_data(extra_data: dict[str, Any]) -> set[str]:
    groups = _extract_groups_from_claims(extra_data)
    id_token = extra_data.get("id_token")
    if isinstance(id_token, dict):
        groups.update(_extract_groups_from_claims(id_token))
    elif isinstance(id_token, str):
        claims = _decode_jwt_payload_without_verification(id_token)
        groups.update(_extract_groups_from_claims(claims))
    return groups


class RpsdSocialAccountAdapter(DefaultSocialAccountAdapter):
    def is_open_for_signup(self, request, sociallogin):
        if self._is_platform_admin_signup_allowed(sociallogin):
            return True
        return super().is_open_for_signup(request, sociallogin)

    def pre_social_login(self, request, sociallogin):
        self._sync_staff_from_oidc_groups(sociallogin)
        self._sync_agency_memberships_from_oidc_groups(sociallogin)
        return super().pre_social_login(request, sociallogin)

    def on_authentication_error(
        self,
        request,
        provider,
        error=None,
        exception=None,
        extra_context=None,
    ):
        # Useful diagnostics for OIDC callback failures during local development.
        state = request.GET.get("state")
        iss = request.GET.get("iss")
        code_present = "code" in request.GET
        session_key = request.session.session_key
        next_url = None
        if isinstance(extra_context, dict):
            state_ctx = extra_context.get("state") or {}
            next_url = state_ctx.get("next")

        LOGGER.error(
            (
                "OIDC authentication error provider=%s error=%s exception=%r "
                "path=%s host=%s state=%s iss=%s code_present=%s next=%s "
                "session_key=%s"
            ),
            getattr(provider, "id", "<unknown>"),
            error,
            exception,
            request.path,
            request.get_host(),
            state,
            iss,
            code_present,
            next_url,
            session_key,
        )

        return super().on_authentication_error(
            request,
            provider,
            error=error,
            exception=exception,
            extra_context=extra_context,
        )

    def _sync_staff_from_oidc_groups(self, sociallogin) -> None:
        user = getattr(sociallogin, "user", None)
        account = getattr(sociallogin, "account", None)
        extra_data = getattr(account, "extra_data", None)
        if user is None or not isinstance(extra_data, dict):
            return

        groups = _extract_groups_from_extra_data(extra_data)
        if RPSD_ADMIN_GROUP_PATH not in groups or bool(user.is_staff):
            return

        user.is_staff = True
        if getattr(user, "pk", None):
            user.save(update_fields=["is_staff"])
            LOGGER.info(
                "OIDC staff mapping applied: user_id=%s group=%s",
                user.pk,
                RPSD_ADMIN_GROUP_PATH,
            )
            return

        LOGGER.info(
            "OIDC staff mapping prepared for new user group=%s",
            RPSD_ADMIN_GROUP_PATH,
        )

    def _is_platform_admin_signup_allowed(self, sociallogin) -> bool:
        if not getattr(
            settings,
            "OIDC_ALLOW_PLATFORM_ADMIN_SIGNUP_WITHOUT_INVITATION",
            False,
        ):
            return False

        account = getattr(sociallogin, "account", None)
        extra_data = getattr(account, "extra_data", None)
        if not isinstance(extra_data, dict):
            return False

        return RPSD_ADMIN_GROUP_PATH in _extract_groups_from_extra_data(extra_data)

    def _sync_agency_memberships_from_oidc_groups(self, sociallogin) -> None:
        user = getattr(sociallogin, "user", None)
        account = getattr(sociallogin, "account", None)
        extra_data = getattr(account, "extra_data", None)
        if (
            user is None
            or getattr(user, "pk", None) is None
            or not isinstance(extra_data, dict)
        ):
            return

        groups = _extract_groups_from_extra_data(extra_data)
        if not groups:
            return

        from rpsd_config.exchange_agreement.services.agency_memberships import (
            sync_agency_memberships_from_groups,
        )

        result = sync_agency_memberships_from_groups(
            user=user,
            groups=groups,
            authoritative=False,
        )
        if result.touched:
            LOGGER.info(
                "OIDC agency membership sync applied: user_id=%s touched=%s",
                user.pk,
                result.touched,
            )
