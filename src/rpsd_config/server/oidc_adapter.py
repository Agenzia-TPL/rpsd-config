# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import logging

from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.openid_connect.views import (
    OpenIDConnectOAuth2Adapter,
)

LOGGER = logging.getLogger(__name__)


class RpsdOpenIDConnectOAuth2Adapter(OpenIDConnectOAuth2Adapter):
    def _issuer_candidates(self) -> list[str]:
        provider = self.get_provider()
        configured_issuer = provider.app.settings.get("issuer")
        callback_issuer = self.request.GET.get("iss")
        discovered_issuer = super().openid_config.get("issuer")

        candidates: list[str] = []
        for issuer in [configured_issuer, callback_issuer, discovered_issuer]:
            if issuer and issuer not in candidates:
                candidates.append(issuer)
        return candidates

    def _decode_id_token(self, app, id_token: str) -> dict:
        verify_signature = not self.did_fetch_access_token
        openid_config = super().openid_config
        candidates = self._issuer_candidates()

        last_exception: OAuth2Error | None = None
        for issuer in candidates:
            try:
                return jwtkit.verify_and_decode(
                    credential=id_token,
                    keys_url=openid_config["jwks_uri"],
                    issuer=issuer,
                    audience=app.client_id,
                    lookup_kid=jwtkit.lookup_kid_jwk,
                    verify_signature=verify_signature,
                )
            except OAuth2Error as exc:
                last_exception = exc
                continue

        LOGGER.warning(
            "OIDC id_token validation failed for issuer candidates: %s (%r)",
            candidates,
            last_exception,
        )
        if last_exception:
            raise last_exception
        return super()._decode_id_token(app, id_token)

    @property
    def authorize_url(self):
        authorization_endpoint = self.get_provider().app.settings.get(
            "authorization_endpoint"
        )
        if authorization_endpoint:
            return authorization_endpoint
        return super().authorize_url
