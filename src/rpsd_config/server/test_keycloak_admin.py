# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from django.test import SimpleTestCase, override_settings

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminConfigError,
    KeycloakAdminService,
)


@dataclass
class _FakeResponse:
    status_code: int
    payload: object | None = None
    headers: dict | None = None
    text: str = ""

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _FakeKeycloakSession:
    def __init__(self, *, token_error: bool = False):
        self.token_error = token_error
        self.calls: list[tuple[str, str, dict]] = []
        self.token_requests = 0
        self.group_creations = 0
        self.groups_by_path: dict[str, dict] = {}
        self.groups_by_id: dict[str, dict] = {}
        self.users_by_id: dict[str, dict] = {}
        self.users_by_username: dict[str, str] = {}
        self.users_by_email: dict[str, str] = {}
        self.user_group_assignments: set[tuple[str, str]] = set()
        self.user_password_resets: list[tuple[str, str, bool]] = []
        self.clients_by_id: dict[str, dict] = {}
        self.clients_by_client_id: dict[str, str] = {}
        self.client_secrets_by_id: dict[str, str] = {}
        self._next_group_id = 1
        self._next_user_id = 1
        self._next_client_id = 1
        self._secret_rotation_count = 0

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))

        parsed = urlparse(url)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path.endswith("/protocol/openid-connect/token") and method == "POST":
            self.token_requests += 1
            if self.token_error:
                return _FakeResponse(
                    status_code=401,
                    payload={"error": "invalid_client"},
                    text="invalid_client",
                )
            return _FakeResponse(
                status_code=200,
                payload={"access_token": "kc-token", "expires_in": 300},
            )

        if "/group-by-path/" in path and method == "GET":
            encoded = path.split("/group-by-path/", 1)[1]
            group_path = unquote(encoded)
            group = self.groups_by_path.get(group_path)
            if group is None:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            return _FakeResponse(status_code=200, payload=group)

        if path.endswith("/groups") and method == "POST":
            payload = kwargs.get("json") or {}
            name = str(payload.get("name") or "")
            full_path = f"/{name}"
            group = self._create_group(full_path=full_path, name=name)
            return _FakeResponse(
                status_code=201,
                headers={
                    "Location": (
                        f"http://keycloak:8080/admin/realms/rpsd/groups/{group['id']}"
                    )
                },
            )

        if "/groups/" in path and path.endswith("/children") and method == "POST":
            payload = kwargs.get("json") or {}
            name = str(payload.get("name") or "")
            parent_id = path.rstrip("/").split("/")[-2]
            parent = self.groups_by_id[parent_id]
            full_path = f"{parent['path']}/{name}".replace("//", "/")
            group = self._create_group(full_path=full_path, name=name)
            return _FakeResponse(
                status_code=201,
                headers={
                    "Location": (
                        f"http://keycloak:8080/admin/realms/rpsd/groups/{group['id']}"
                    )
                },
            )

        if "/clients/" in path and path.endswith("/client-secret") and method == "GET":
            client_uuid = path.rstrip("/").split("/")[-2]
            if client_uuid not in self.clients_by_id:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            return _FakeResponse(
                status_code=200,
                payload={
                    "type": "secret",
                    "value": self.client_secrets_by_id[client_uuid],
                },
            )

        if "/clients/" in path and path.endswith("/client-secret") and method == "POST":
            client_uuid = path.rstrip("/").split("/")[-2]
            if client_uuid not in self.clients_by_id:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            self._secret_rotation_count += 1
            rotated = f"rotated-{client_uuid}-{self._secret_rotation_count}"
            self.client_secrets_by_id[client_uuid] = rotated
            return _FakeResponse(
                status_code=200,
                payload={
                    "type": "secret",
                    "value": rotated,
                },
            )

        if path.endswith("/clients") and method == "GET":
            client_id = query.get("clientId", [""])[0]
            if client_id:
                match_id = self.clients_by_client_id.get(client_id)
                if match_id:
                    return _FakeResponse(
                        status_code=200, payload=[self.clients_by_id[match_id]]
                    )
                return _FakeResponse(status_code=200, payload=[])
            return _FakeResponse(status_code=200, payload=list(self.clients_by_id.values()))

        if path.endswith("/clients") and method == "POST":
            payload = kwargs.get("json") or {}
            client_id = str(payload.get("clientId") or "")
            if not client_id:
                return _FakeResponse(status_code=400, payload={"error": "clientId_missing"})
            if client_id in self.clients_by_client_id:
                return _FakeResponse(status_code=409, payload={"error": "conflict"})

            client_uuid = str(self._next_client_id)
            self._next_client_id += 1
            client = {
                "id": client_uuid,
                "clientId": client_id,
                "enabled": bool(payload.get("enabled", True)),
                "serviceAccountsEnabled": bool(
                    payload.get("serviceAccountsEnabled", False)
                ),
                "publicClient": bool(payload.get("publicClient", False)),
                "protocol": str(payload.get("protocol") or "openid-connect"),
            }
            self.clients_by_id[client_uuid] = client
            self.clients_by_client_id[client_id] = client_uuid
            self.client_secrets_by_id[client_uuid] = f"secret-{client_uuid}"
            return _FakeResponse(
                status_code=201,
                headers={
                    "Location": (
                        f"http://keycloak:8080/admin/realms/rpsd/clients/{client_uuid}"
                    )
                },
            )

        if "/clients/" in path and method == "GET":
            client_uuid = path.rstrip("/").split("/")[-1]
            client = self.clients_by_id.get(client_uuid)
            if client is None:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            return _FakeResponse(status_code=200, payload=client)

        if "/clients/" in path and method == "PUT":
            client_uuid = path.rstrip("/").split("/")[-1]
            client = self.clients_by_id.get(client_uuid)
            if client is None:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            payload = kwargs.get("json") or {}
            client.update(payload)
            self.clients_by_id[client_uuid] = client
            return _FakeResponse(status_code=204)

        if "/clients/" in path and method == "DELETE":
            client_uuid = path.rstrip("/").split("/")[-1]
            client = self.clients_by_id.pop(client_uuid, None)
            if client is None:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            self.clients_by_client_id.pop(str(client.get("clientId") or ""), None)
            self.client_secrets_by_id.pop(client_uuid, None)
            return _FakeResponse(status_code=204)

        if path.endswith("/users") and method == "GET":
            if "username" in query:
                username = query["username"][0]
                user_id = self.users_by_username.get(username)
                if user_id:
                    return _FakeResponse(
                        status_code=200,
                        payload=[self.users_by_id[user_id]],
                    )
                return _FakeResponse(status_code=200, payload=[])

            if "email" in query:
                email = query["email"][0].lower()
                user_id = self.users_by_email.get(email)
                if user_id:
                    return _FakeResponse(
                        status_code=200,
                        payload=[self.users_by_id[user_id]],
                    )
                return _FakeResponse(status_code=200, payload=[])

            return _FakeResponse(status_code=200, payload=[])

        if path.endswith("/users") and method == "POST":
            payload = kwargs.get("json") or {}
            username = str(payload.get("username") or "")
            email = str(payload.get("email") or "")
            if username in self.users_by_username:
                return _FakeResponse(status_code=409, payload={"error": "conflict"})

            user_id = str(self._next_user_id)
            self._next_user_id += 1
            user = {
                "id": user_id,
                "username": username,
                "email": email,
            }
            self.users_by_id[user_id] = user
            self.users_by_username[username] = user_id
            self.users_by_email[email.lower()] = user_id
            return _FakeResponse(
                status_code=201,
                headers={
                    "Location": (
                        f"http://keycloak:8080/admin/realms/rpsd/users/{user_id}"
                    )
                },
            )

        if "/users/" in path and method == "GET":
            user_id = path.rstrip("/").split("/")[-1]
            user = self.users_by_id.get(user_id)
            if user is None:
                return _FakeResponse(status_code=404, payload={"error": "not_found"})
            return _FakeResponse(status_code=200, payload=user)

        if "/users/" in path and "/groups/" in path and method == "PUT":
            parts = path.rstrip("/").split("/")
            user_id = parts[-3]
            group_id = parts[-1]
            self.user_group_assignments.add((user_id, group_id))
            return _FakeResponse(status_code=204)

        if path.endswith("/reset-password") and "/users/" in path and method == "PUT":
            parts = path.rstrip("/").split("/")
            user_id = parts[-2]
            payload = kwargs.get("json") or {}
            password = str(payload.get("value") or "")
            temporary = bool(payload.get("temporary", False))
            self.user_password_resets.append((user_id, password, temporary))
            return _FakeResponse(status_code=204)

        return _FakeResponse(status_code=500, payload={"error": "unhandled_route"})

    def _create_group(self, *, full_path: str, name: str) -> dict:
        existing = self.groups_by_path.get(full_path)
        if existing is not None:
            return existing

        group_id = str(self._next_group_id)
        self._next_group_id += 1
        group = {"id": group_id, "name": name, "path": full_path}
        self.groups_by_path[full_path] = group
        self.groups_by_id[group_id] = group
        self.group_creations += 1
        return group


class KeycloakAdminServiceTests(SimpleTestCase):
    def test_from_settings_requires_secret(self):
        with override_settings(
            KEYCLOAK_ADMIN_BASE_URL="http://keycloak:8080",
            KEYCLOAK_ADMIN_REALM="rpsd",
            KEYCLOAK_ADMIN_CLIENT_ID="rpsd-config-admin-api",
            KEYCLOAK_ADMIN_CLIENT_SECRET="",
        ):
            with self.assertRaises(KeycloakAdminConfigError):
                KeycloakAdminService.from_settings()

    def test_from_settings_uses_runtime_values(self):
        with override_settings(
            KEYCLOAK_ADMIN_BASE_URL="http://keycloak:8080",
            KEYCLOAK_ADMIN_REALM="rpsd",
            KEYCLOAK_ADMIN_CLIENT_ID="rpsd-config-admin-api",
            KEYCLOAK_ADMIN_CLIENT_SECRET="super-secret",
            KEYCLOAK_ADMIN_GROUP_ROOT="/rpsd",
        ):
            service = KeycloakAdminService.from_settings()

        self.assertEqual(service.base_url, "http://keycloak:8080")
        self.assertEqual(service.realm, "rpsd")
        self.assertEqual(service.client_id, "rpsd-config-admin-api")
        self.assertEqual(service.group_root, "/rpsd")

    def test_ensure_agency_groups_is_idempotent(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        first = service.ensure_agency_groups("atpl-milano")
        created_after_first = session.group_creations
        second = service.ensure_agency_groups("atpl-milano")

        self.assertEqual(created_after_first, 5)
        self.assertEqual(session.group_creations, created_after_first)
        self.assertEqual(sorted(first.keys()), ["admin", "editor", "reader"])
        self.assertEqual(sorted(second.keys()), ["admin", "editor", "reader"])
        self.assertEqual(first["admin"].path, "/rpsd/atpl-milano/admin")
        self.assertEqual(second["reader"].path, "/rpsd/atpl-milano/reader")

    def test_ensure_user_and_assign_group(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        group = service.ensure_group_path("/rpsd/demo-agency/admin")
        user = service.ensure_user(
            username="operatore1",
            email="operatore1@example.com",
        )
        service.assign_user_to_group(user_id=user.id, group_id=group.id)

        self.assertEqual(user.username, "operatore1")
        self.assertIn((user.id, group.id), session.user_group_assignments)

    def test_set_user_password(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )
        user = service.ensure_user(
            username="operatore2@example.com",
            email="operatore2@example.com",
        )
        service.set_user_password(
            user_id=user.id,
            password="PasswordSicura123!",
            temporary=False,
        )
        self.assertIn(
            (user.id, "PasswordSicura123!", False),
            session.user_password_resets,
        )

    def test_create_confidential_m2m_client_and_rotate_secret(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        created = service.create_confidential_m2m_client(
            client_id="atm-default-prod",
            name="ATM Default Prod",
            description="M2M integration",
        )
        self.assertTrue(created.created)
        self.assertEqual(created.client.client_id, "atm-default-prod")
        self.assertTrue(created.secret.startswith("secret-"))

        found = service.find_client_by_client_id("atm-default-prod")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, created.client.id)

        rotated = service.rotate_client_secret(client_uuid=created.client.id)
        self.assertNotEqual(rotated, created.secret)
        self.assertTrue(rotated.startswith(f"rotated-{created.client.id}-"))

    def test_create_confidential_m2m_client_is_idempotent(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        first = service.create_confidential_m2m_client(
            client_id="trenord-default-prod"
        )
        second = service.create_confidential_m2m_client(
            client_id="trenord-default-prod"
        )

        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.client.id, second.client.id)
        self.assertEqual(len(session.clients_by_id), 1)

    def test_disable_and_delete_client(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        created = service.create_confidential_m2m_client(
            client_id="atm-lab-default-prod"
        )
        disabled = service.disable_client(client_uuid=created.client.id)
        self.assertFalse(disabled.enabled)

        deleted = service.delete_client(client_uuid=created.client.id)
        self.assertTrue(deleted)
        self.assertIsNone(service.find_client_by_client_id("atm-lab-default-prod"))
        self.assertFalse(service.delete_client(client_uuid=created.client.id))

    def test_get_client_secret_maps_invalid_payload(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        created = service.create_confidential_m2m_client(
            client_id="atm-invalid-secret-prod"
        )
        session.client_secrets_by_id[created.client.id] = ""

        with self.assertRaises(KeycloakAdminAPIError):
            service.get_client_secret(client_uuid=created.client.id)

    def test_token_error_is_mapped(self):
        session = _FakeKeycloakSession(token_error=True)
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="wrong-secret",
            session=session,
        )

        with self.assertRaises(KeycloakAdminAPIError):
            service.ensure_group_path("/rpsd")

    def test_invalid_agency_key_is_rejected(self):
        session = _FakeKeycloakSession()
        service = KeycloakAdminService(
            base_url="http://keycloak:8080",
            realm="rpsd",
            client_id="rpsd-config-admin-api",
            client_secret="secret",
            session=session,
        )

        with self.assertRaises(KeycloakAdminConfigError):
            service.ensure_agency_groups("ATPL Milano")


class KeycloakAdminSettingsDerivationTests(SimpleTestCase):
    def test_derives_admin_base_and_realm_from_discovery(self):
        from rpsd_config.server.settings import ProjectSettings

        cfg = ProjectSettings(
            KEYCLOAK_DISCOVERY_URL=(
                "http://keycloak:8080/realms/rpsd/.well-known/openid-configuration"
            ),
            KEYCLOAK_ADMIN_BASE_URL="",
            KEYCLOAK_ADMIN_REALM="",
        )

        self.assertEqual(cfg.KEYCLOAK_ADMIN_BASE_URL, "http://keycloak:8080")
        self.assertEqual(cfg.KEYCLOAK_ADMIN_REALM, "rpsd")
        self.assertEqual(cfg.KEYCLOAK_ADMIN_GROUP_ROOT, "/rpsd")
