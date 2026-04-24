# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import logging
from urllib.parse import urlparse

from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from allauth.socialaccount.providers.openid_connect.views import (
    OpenIDConnectOAuth2Adapter,
)

LOGGER = logging.getLogger(__name__)


def _url_origin(url: str) -> str:
    """Return ``scheme://host[:port]`` from *url*."""
    p = urlparse(url)
    origin = f"{p.scheme}://{p.hostname}"
    if p.port:
        origin += f":{p.port}"
    return origin


class RpsdOpenIDConnectOAuth2Adapter(OpenIDConnectOAuth2Adapter):
    @property
    def openid_config(self):
        """Fetch the discovery document and rewrite server-to-server URLs.

        Keycloak returns all endpoints using its public ``KC_HOSTNAME``
        (e.g. ``http://localhost:19300``).  When the Django container
        reaches Keycloak through a different address
        (``KEYCLOAK_DISCOVERY_URL``, e.g.
        ``http://host.docker.internal:19300`` or ``http://keycloak:8080``),
        the server-to-server URLs in the document are unreachable.

        This property replaces the origin of every URL value in the
        discovery document with the origin derived from ``server_url``
        (i.e. ``KEYCLOAK_DISCOVERY_URL``), so that ``token_endpoint``,
        ``jwks_uri``, ``userinfo_endpoint``, etc. all point to the
        address the container can actually reach.
        """
        if not hasattr(self, "_rpsd_openid_config"):
            config = dict(super().openid_config)  # shallow copy
            server_url = self.get_provider().server_url
            server_origin = _url_origin(server_url)
            discovered_issuer = config.get("issuer", "")
            discovered_origin = _url_origin(discovered_issuer)

            if server_origin != discovered_origin:
                LOGGER.debug(
                    "Rewriting OIDC discovery URLs: %s → %s",
                    discovered_origin,
                    server_origin,
                )
                for key, value in config.items():
                    if isinstance(value, str) and value.startswith(
                        discovered_origin + "/"
                    ):
                        config[key] = server_origin + value[len(discovered_origin) :]
            self._rpsd_openid_config = config
        return self._rpsd_openid_config

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
        openid_config = self.openid_config
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
