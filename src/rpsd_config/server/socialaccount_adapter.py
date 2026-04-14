# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import logging

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

LOGGER = logging.getLogger(__name__)


class RpsdSocialAccountAdapter(DefaultSocialAccountAdapter):
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
