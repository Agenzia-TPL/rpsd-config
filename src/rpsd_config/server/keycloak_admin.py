# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings

AGENCY_KEY_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$")


class KeycloakAdminConfigError(ValueError):
    """Invalid/incomplete Keycloak Admin API configuration."""


class KeycloakAdminAPIError(RuntimeError):
    """HTTP-level error raised by the Keycloak Admin API client."""

    def __init__(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        detail: str,
    ) -> None:
        self.method = method
        self.url = url
        self.status_code = status_code
        self.detail = detail
        super().__init__(
            f"Keycloak Admin API error {status_code} on {method} {url}: {detail}"
        )

    @classmethod
    def from_response(
        cls, *, method: str, url: str, response: requests.Response
    ) -> "KeycloakAdminAPIError":
        detail = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            detail = (
                str(payload.get("error_description") or "")
                or str(payload.get("error") or "")
                or str(payload)
            )
        elif payload is not None:
            detail = str(payload)

        if not detail:
            detail = (response.text or "").strip()[:500]
        if not detail:
            detail = "Unknown error"

        return cls(
            method=method,
            url=url,
            status_code=response.status_code,
            detail=detail,
        )


@dataclass(frozen=True)
class KeycloakGroupRef:
    id: str
    name: str
    path: str


@dataclass(frozen=True)
class KeycloakUserRef:
    id: str
    username: str
    email: str


@dataclass
class _AccessTokenCache:
    token: str
    expires_at: datetime


class KeycloakAdminService:
    AGENCY_ROLES = ("admin", "editor", "reader")

    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        request_timeout_seconds: float = 10.0,
        verify_tls: bool = True,
        group_root: str = "/rpsd",
        session: requests.Session | None = None,
    ) -> None:
        missing = [
            name
            for name, value in {
                "base_url": base_url,
                "realm": realm,
                "client_id": client_id,
                "client_secret": client_secret,
            }.items()
            if not value
        ]
        if missing:
            missing_joined = ", ".join(missing)
            raise KeycloakAdminConfigError(
                f"Missing Keycloak Admin API configuration fields: {missing_joined}."
            )

        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.request_timeout_seconds = request_timeout_seconds
        self.verify_tls = verify_tls
        self.group_root = self._normalize_group_path(group_root)
        self._session = session or requests.Session()
        self._token_cache: _AccessTokenCache | None = None

    @classmethod
    def from_settings(cls) -> "KeycloakAdminService":
        return cls(
            base_url=settings.KEYCLOAK_ADMIN_BASE_URL,
            realm=settings.KEYCLOAK_ADMIN_REALM,
            client_id=settings.KEYCLOAK_ADMIN_CLIENT_ID,
            client_secret=settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
            request_timeout_seconds=settings.KEYCLOAK_ADMIN_REQUEST_TIMEOUT_SECONDS,
            verify_tls=settings.KEYCLOAK_ADMIN_VERIFY_TLS,
            group_root=settings.KEYCLOAK_ADMIN_GROUP_ROOT,
        )

    @property
    def _token_endpoint(self) -> str:
        return f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token"

    @property
    def _realm_admin_base_url(self) -> str:
        return f"{self.base_url}/admin/realms/{self.realm}"

    def _obtain_access_token(self, *, force_refresh: bool = False) -> str:
        now = datetime.now(UTC)
        if (
            not force_refresh
            and self._token_cache
            and self._token_cache.expires_at > now
        ):
            return self._token_cache.token

        response = self._session.request(
            "POST",
            self._token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=self.request_timeout_seconds,
            verify=self.verify_tls,
        )
        if response.status_code != 200:
            raise KeycloakAdminAPIError.from_response(
                method="POST",
                url=self._token_endpoint,
                response=response,
            )

        payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise KeycloakAdminAPIError(
                method="POST",
                url=self._token_endpoint,
                status_code=200,
                detail="Token response does not contain access_token.",
            )

        expires_in = payload.get("expires_in", 60)
        try:
            expires_in_seconds = max(int(expires_in), 1)
        except (TypeError, ValueError):
            expires_in_seconds = 60

        # Keep a small leeway so refresh happens before effective expiration.
        leeway_seconds = min(15, max(expires_in_seconds - 1, 0))
        self._token_cache = _AccessTokenCache(
            token=access_token,
            expires_at=now + timedelta(seconds=expires_in_seconds - leeway_seconds),
        )
        return access_token

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: tuple[int, ...] = (200,),
        retry_on_unauthorized: bool = True,
        **kwargs,
    ) -> requests.Response:
        url = f"{self._realm_admin_base_url}/{path.lstrip('/')}"

        headers = dict(kwargs.pop("headers", {}))
        token = self._obtain_access_token()
        headers["Authorization"] = f"Bearer {token}"

        response = self._session.request(
            method,
            url,
            headers=headers,
            timeout=self.request_timeout_seconds,
            verify=self.verify_tls,
            **kwargs,
        )

        if response.status_code == 401 and retry_on_unauthorized:
            token = self._obtain_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            response = self._session.request(
                method,
                url,
                headers=headers,
                timeout=self.request_timeout_seconds,
                verify=self.verify_tls,
                **kwargs,
            )

        if response.status_code not in expected_status:
            raise KeycloakAdminAPIError.from_response(
                method=method,
                url=url,
                response=response,
            )
        return response

    @staticmethod
    def _normalize_group_path(group_path: str) -> str:
        normalized = "/" + "/".join(
            [segment for segment in (group_path or "").split("/") if segment]
        )
        return normalized if normalized != "/" else "/"

    @staticmethod
    def _to_group_ref(payload: dict[str, Any]) -> KeycloakGroupRef:
        return KeycloakGroupRef(
            id=str(payload.get("id") or ""),
            name=str(payload.get("name") or ""),
            path=str(payload.get("path") or ""),
        )

    @staticmethod
    def _to_user_ref(payload: dict[str, Any]) -> KeycloakUserRef:
        return KeycloakUserRef(
            id=str(payload.get("id") or ""),
            username=str(payload.get("username") or ""),
            email=str(payload.get("email") or ""),
        )

    def get_group_by_path(self, group_path: str) -> KeycloakGroupRef | None:
        normalized = self._normalize_group_path(group_path)
        encoded = quote(normalized, safe="")
        response = self._request(
            "GET",
            f"group-by-path/{encoded}",
            expected_status=(200, 404),
        )
        if response.status_code == 404:
            return None
        payload = response.json()
        if not isinstance(payload, dict):
            raise KeycloakAdminAPIError(
                method="GET",
                url=f"{self._realm_admin_base_url}/group-by-path/{encoded}",
                status_code=200,
                detail="Unexpected group response payload type.",
            )
        return self._to_group_ref(payload)

    def create_group(
        self, *, name: str, parent_group_id: str | None = None
    ) -> str | None:
        path = "groups" if not parent_group_id else f"groups/{parent_group_id}/children"
        response = self._request(
            "POST",
            path,
            expected_status=(201, 204),
            json={"name": name},
        )
        location = response.headers.get("Location") or ""
        if not location:
            return None
        return location.rstrip("/").split("/")[-1]

    def ensure_group_path(self, group_path: str) -> KeycloakGroupRef:
        normalized = self._normalize_group_path(group_path)
        segments = [segment for segment in normalized.split("/") if segment]

        parent_group_id: str | None = None
        current_path = ""

        for segment in segments:
            current_path = (
                f"{current_path}/{segment}" if current_path else f"/{segment}"
            )
            group = self.get_group_by_path(current_path)
            if group is None:
                self.create_group(name=segment, parent_group_id=parent_group_id)
                group = self.get_group_by_path(current_path)
                if group is None:
                    raise KeycloakAdminAPIError(
                        method="POST",
                        url=f"{self._realm_admin_base_url}/groups",
                        status_code=500,
                        detail=(
                            "Group creation did not materialize in Keycloak "
                            f"for path {current_path}."
                        ),
                    )
            parent_group_id = group.id

        if not segments:
            raise KeycloakAdminConfigError("Group path cannot be empty.")
        return group

    def ensure_agency_groups(self, agency_key: str) -> dict[str, KeycloakGroupRef]:
        if not AGENCY_KEY_PATTERN.fullmatch(agency_key or ""):
            raise KeycloakAdminConfigError(
                "Invalid agency_key. Expected regex: "
                "^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$."
            )

        self.ensure_group_path(self.group_root)
        agency_root_path = self._normalize_group_path(f"{self.group_root}/{agency_key}")
        self.ensure_group_path(agency_root_path)

        result: dict[str, KeycloakGroupRef] = {}
        for role in self.AGENCY_ROLES:
            role_path = f"{agency_root_path}/{role}"
            result[role] = self.ensure_group_path(role_path)

        return result

    def get_user_by_id(self, user_id: str) -> KeycloakUserRef:
        response = self._request("GET", f"users/{user_id}", expected_status=(200,))
        payload = response.json()
        if not isinstance(payload, dict):
            raise KeycloakAdminAPIError(
                method="GET",
                url=f"{self._realm_admin_base_url}/users/{user_id}",
                status_code=200,
                detail="Unexpected user response payload type.",
            )
        return self._to_user_ref(payload)

    def find_user_by_email(self, email: str) -> KeycloakUserRef | None:
        response = self._request(
            "GET",
            "users",
            expected_status=(200,),
            params={"email": email, "exact": "true", "max": 2},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise KeycloakAdminAPIError(
                method="GET",
                url=f"{self._realm_admin_base_url}/users",
                status_code=200,
                detail="Unexpected users response payload type.",
            )
        if not payload:
            return None
        exact = next(
            (
                item
                for item in payload
                if isinstance(item, dict)
                and str(item.get("email") or "").lower() == email.lower()
            ),
            payload[0],
        )
        if not isinstance(exact, dict):
            return None
        return self._to_user_ref(exact)

    def find_user_by_username(self, username: str) -> KeycloakUserRef | None:
        response = self._request(
            "GET",
            "users",
            expected_status=(200,),
            params={"username": username, "exact": "true", "max": 2},
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise KeycloakAdminAPIError(
                method="GET",
                url=f"{self._realm_admin_base_url}/users",
                status_code=200,
                detail="Unexpected users response payload type.",
            )
        if not payload:
            return None
        candidate = payload[0]
        if not isinstance(candidate, dict):
            return None
        return self._to_user_ref(candidate)

    def create_user(
        self,
        *,
        username: str,
        email: str,
        enabled: bool = True,
        email_verified: bool = True,
        first_name: str = "",
        last_name: str = "",
    ) -> KeycloakUserRef:
        response = self._request(
            "POST",
            "users",
            expected_status=(201, 204, 409),
            json={
                "username": username,
                "email": email,
                "enabled": enabled,
                "emailVerified": email_verified,
                "firstName": first_name,
                "lastName": last_name,
            },
        )

        if response.status_code == 409:
            existing = self.find_user_by_username(username) or self.find_user_by_email(
                email
            )
            if existing is None:
                raise KeycloakAdminAPIError(
                    method="POST",
                    url=f"{self._realm_admin_base_url}/users",
                    status_code=409,
                    detail=(
                        "User conflict reported by Keycloak, but user lookup "
                        "did not return an existing identity."
                    ),
                )
            return existing

        location = response.headers.get("Location") or ""
        if location:
            user_id = location.rstrip("/").split("/")[-1]
            if user_id:
                return self.get_user_by_id(user_id)

        fallback = self.find_user_by_username(username) or self.find_user_by_email(
            email
        )
        if fallback is None:
            raise KeycloakAdminAPIError(
                method="POST",
                url=f"{self._realm_admin_base_url}/users",
                status_code=response.status_code,
                detail="User created but unable to resolve resulting user id.",
            )
        return fallback

    def ensure_user(self, *, username: str, email: str) -> KeycloakUserRef:
        existing = self.find_user_by_username(username)
        if existing is not None:
            return existing

        existing_by_email = self.find_user_by_email(email)
        if existing_by_email is not None:
            return existing_by_email

        return self.create_user(username=username, email=email)

    def set_user_password(
        self,
        *,
        user_id: str,
        password: str,
        temporary: bool = False,
    ) -> None:
        self._request(
            "PUT",
            f"users/{user_id}/reset-password",
            expected_status=(204,),
            json={
                "type": "password",
                "value": password,
                "temporary": temporary,
            },
        )

    def assign_user_to_group(self, *, user_id: str, group_id: str) -> None:
        self._request(
            "PUT",
            f"users/{user_id}/groups/{group_id}",
            expected_status=(204,),
        )
