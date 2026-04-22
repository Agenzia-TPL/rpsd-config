# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import date, timedelta
from unittest.mock import patch

import jwt
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
)


@override_settings(M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=False)
class InternalAuthzCheckEndpointPhase4Tests(TestCase):
    endpoint = "/internal/authz/check"

    def _valid_payload(self) -> dict:
        return {
            "principal_type": "client",
            "principal_id": "atm-default-prod",
            "action": "ingest:write",
            "contract_code": "CTR-123",
            "data_category": "netex",
        }

    def test_rejects_non_post_method(self):
        response = self.client.get(self.endpoint)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "method-not-allowed"},
        )

    def test_rejects_invalid_json(self):
        response = self.client.post(
            self.endpoint,
            data="{invalid",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"allowed": False, "reason": "invalid-json"})

    def test_rejects_non_object_payload(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(["not", "an", "object"]),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["allowed"], False)
        self.assertEqual(payload["reason"], "invalid-request")
        self.assertIn("errors", payload)

    def test_rejects_missing_required_fields(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps({"principal_type": "client"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["allowed"], False)
        self.assertEqual(payload["reason"], "invalid-request")
        self.assertIn("errors", payload)
        self.assertGreaterEqual(len(payload["errors"]), 1)

    def test_returns_canonical_response_for_supported_principal_type(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "allowed": False,
                "reason": "principal-not-found",
            },
        )

    def test_returns_reason_for_unsupported_principal_type(self):
        payload = self._valid_payload()
        payload["principal_type"] = "user"
        response = self.client.post(
            self.endpoint,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "allowed": False,
                "reason": "unsupported-principal-type",
            },
        )


class InternalAuthzServiceAuthGuardPhase4Tests(TestCase):
    endpoint = "/internal/authz/check"

    def _valid_payload(self) -> dict:
        return {
            "principal_type": "client",
            "principal_id": "atm-default-prod",
            "action": "ingest:write",
            "contract_code": "CTR-123",
        }

    @override_settings(M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=True)
    def test_rejects_request_without_bearer_token(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "missing-bearer-token"},
        )

    @override_settings(
        M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=True,
        OIDC_ISSUER_URL="http://localhost:19300/realms/rpsd",
        KEYCLOAK_DISCOVERY_URL="http://keycloak:8080/realms/rpsd/.well-known/openid-configuration",
    )
    @patch(
        "rpsd_config.exchange_agreement.api.jwt.decode",
        side_effect=jwt.InvalidTokenError("bad token"),
    )
    @patch("rpsd_config.exchange_agreement.api.jwtkit.fetch_key", return_value=("RS256", "fake-key"))
    def test_rejects_invalid_bearer_token(self, _fetch_key, _decode):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer invalid-token",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "invalid-bearer-token"},
        )

    @override_settings(
        M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=True,
        OIDC_ISSUER_URL="http://localhost:19300/realms/rpsd",
        KEYCLOAK_DISCOVERY_URL="http://keycloak:8080/realms/rpsd/.well-known/openid-configuration",
    )
    @patch("rpsd_config.exchange_agreement.api.jwt.decode", return_value={"sub": "svc-sub"})
    @patch("rpsd_config.exchange_agreement.api.jwtkit.fetch_key", return_value=("RS256", "fake-key"))
    def test_rejects_token_without_client_identity(self, _fetch_key, _decode):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer valid-no-client",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "principal-id-missing"},
        )

    @override_settings(
        M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=True,
        M2M_INTERNAL_AUTHZ_ALLOWED_CLIENTS_CSV="rpsd-ingest",
        OIDC_ISSUER_URL="http://localhost:19300/realms/rpsd",
        KEYCLOAK_DISCOVERY_URL="http://keycloak:8080/realms/rpsd/.well-known/openid-configuration",
    )
    @patch(
        "rpsd_config.exchange_agreement.api.jwt.decode",
        return_value={"azp": "unexpected-client", "sub": "svc-sub"},
    )
    @patch("rpsd_config.exchange_agreement.api.jwtkit.fetch_key", return_value=("RS256", "fake-key"))
    def test_rejects_client_not_in_allowlist(self, _fetch_key, _decode):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer valid-but-forbidden",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "caller-not-allowed"},
        )

    @override_settings(
        M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=True,
        M2M_INTERNAL_AUTHZ_ALLOWED_CLIENTS_CSV="rpsd-ingest",
        OIDC_ISSUER_URL="http://localhost:19300/realms/rpsd",
        KEYCLOAK_DISCOVERY_URL="http://keycloak:8080/realms/rpsd/.well-known/openid-configuration",
    )
    @patch(
        "rpsd_config.exchange_agreement.api.jwt.decode",
        return_value={"azp": "rpsd-ingest", "sub": "svc-sub"},
    )
    @patch("rpsd_config.exchange_agreement.api.jwtkit.fetch_key", return_value=("RS256", "fake-key"))
    def test_allows_authorized_service_client_to_reach_endpoint_contract(
        self, _fetch_key, _decode
    ):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._valid_payload()),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer valid-and-allowed",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "principal-not-found"},
        )


@override_settings(M2M_INTERNAL_AUTHZ_REQUIRE_BEARER=False)
class InternalAuthzDecisionEnginePhase4Tests(TestCase):
    endpoint = "/internal/authz/check"

    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username="m2m-authz-user",
            email="m2m-authz-user@example.com",
            password="test-pass",
        )
        self.agency = Agency.objects.create(name="ATPL Milano", agency_key="atpl-milano")
        self.company = Company.objects.create(name="ATM")
        self.other_company = Company.objects.create(name="Trenord")
        self.lot = Lot.objects.create(description="Lotto A")
        self.lot_b = Lot.objects.create(description="Lotto B")

        self.active_contract = Contract.objects.create(
            contract_code="CTR-ACTIVE-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            status=Contract.ContractStatus.ACTIVE,
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() + timedelta(days=365),
        )
        self.inactive_contract = Contract.objects.create(
            contract_code="CTR-DRAFT-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            status=Contract.ContractStatus.DRAFT,
            start_date=date.today() + timedelta(days=370),
            end_date=date.today() + timedelta(days=500),
        )
        self.other_company_contract = Contract.objects.create(
            contract_code="CTR-OTHER-001",
            client_agency=self.agency,
            contractor_company=self.other_company,
            lot=self.lot_b,
            status=Contract.ContractStatus.ACTIVE,
            start_date=date.today() - timedelta(days=10),
            end_date=date.today() + timedelta(days=365),
        )
        self.closed_contract = Contract.objects.create(
            contract_code="CTR-CLOSED-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=Lot.objects.create(description="Lotto Closed"),
            status=Contract.ContractStatus.CLOSED,
            start_date=date.today() - timedelta(days=200),
            end_date=date.today() - timedelta(days=1),
            closed_at=timezone.now(),
            closed_reason="Contract terminated",
        )
        self.expired_active_contract = Contract.objects.create(
            contract_code="CTR-EXPIRED-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=Lot.objects.create(description="Lotto Expired"),
            status=Contract.ContractStatus.ACTIVE,
            start_date=date.today() - timedelta(days=365),
            end_date=date.today() - timedelta(days=1),
        )

        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="atm-default-prod",
            status=IntegrationPrincipal.Status.ACTIVE,
            created_by=self.user,
        )

    def _payload(self, **overrides):
        payload = {
            "principal_type": "client",
            "principal_id": self.principal.keycloak_client_id,
            "action": IntegrationGrant.Action.INGEST_WRITE,
            "contract_code": self.active_contract.contract_code,
        }
        payload.update(overrides)
        return payload

    def _create_grant(self, **overrides):
        defaults = {
            "principal": self.principal,
            "contract": self.active_contract,
            "action": IntegrationGrant.Action.INGEST_WRITE,
            "status": IntegrationGrant.Status.ACTIVE,
            "created_by": self.user,
        }
        defaults.update(overrides)
        return IntegrationGrant.objects.create(**defaults)

    def test_allows_active_principal_with_active_grant(self):
        self._create_grant()
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"allowed": True, "reason": "grant-active"})

    def test_denies_suspended_principal(self):
        self.principal.status = IntegrationPrincipal.Status.SUSPENDED
        self.principal.save(update_fields=["status"])

        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "principal-suspended"},
        )

    def test_denies_inactive_contract(self):
        self._create_grant(contract=self.inactive_contract)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.inactive_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "contract-inactive"},
        )

    def test_denies_closed_contract_even_with_active_grant(self):
        self._create_grant(contract=self.closed_contract)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.closed_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "contract-inactive"},
        )

    def test_denies_expired_active_contract_even_with_active_grant(self):
        self._create_grant(contract=self.expired_active_contract)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(
                self._payload(contract_code=self.expired_active_contract.contract_code)
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "contract-inactive"},
        )

    def test_denies_after_contract_closed_lifecycle_transition(self):
        self._create_grant(contract=self.active_contract)
        allow_response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.active_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(allow_response.status_code, 200)
        self.assertEqual(
            allow_response.json(),
            {"allowed": True, "reason": "grant-active"},
        )

        self.active_contract.status = Contract.ContractStatus.CLOSED
        self.active_contract.closed_at = timezone.now()
        self.active_contract.closed_reason = "Lifecycle close test"
        self.active_contract.save(
            update_fields=["status", "closed_at", "closed_reason", "updated_at"]
        )

        deny_response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.active_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(deny_response.status_code, 200)
        self.assertEqual(
            deny_response.json(),
            {"allowed": False, "reason": "contract-inactive"},
        )

    def test_denies_after_contract_expired_lifecycle_transition(self):
        self._create_grant(contract=self.active_contract)
        allow_response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.active_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(allow_response.status_code, 200)
        self.assertEqual(
            allow_response.json(),
            {"allowed": True, "reason": "grant-active"},
        )

        self.active_contract.end_date = date.today() - timedelta(days=1)
        self.active_contract.save(update_fields=["end_date", "updated_at"])

        deny_response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(contract_code=self.active_contract.contract_code)),
            content_type="application/json",
        )
        self.assertEqual(deny_response.status_code, 200)
        self.assertEqual(
            deny_response.json(),
            {"allowed": False, "reason": "contract-inactive"},
        )

    def test_denies_when_grant_missing(self):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "grant-missing"},
        )

    @patch("rpsd_config.exchange_agreement.api.audit_m2m_event")
    def test_denies_when_grant_missing_emits_audit_event(self, audit_mock):
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "grant-missing"},
        )

        audit_mock.assert_called_once()
        self.assertEqual(audit_mock.call_args.args[0], "authz.deny")
        self.assertEqual(audit_mock.call_args.kwargs.get("outcome"), "deny")
        self.assertEqual(audit_mock.call_args.kwargs.get("reason"), "grant-missing")
        extra = audit_mock.call_args.kwargs.get("extra") or {}
        self.assertEqual(extra.get("principal_type"), "client")
        self.assertEqual(extra.get("principal_id"), self.principal.keycloak_client_id)
        self.assertEqual(extra.get("action"), IntegrationGrant.Action.INGEST_WRITE)
        self.assertEqual(extra.get("contract_code"), self.active_contract.contract_code)

    def test_denies_when_data_category_mismatch(self):
        self._create_grant(data_category="siri-pt")
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(data_category="netex")),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "grant-data-category-mismatch"},
        )

    def test_allows_when_wildcard_data_category_grant_exists(self):
        self._create_grant(data_category=None)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(data_category="netex")),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"allowed": True, "reason": "grant-active"})

    def test_denies_when_grant_outside_validity_window(self):
        self._create_grant(valid_from=timezone.now() + timedelta(days=1))
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload()),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "grant-not-in-validity-window"},
        )

    def test_denies_when_principal_company_mismatch(self):
        self._create_grant(contract=self.other_company_contract)
        response = self.client.post(
            self.endpoint,
            data=json.dumps(
                self._payload(contract_code=self.other_company_contract.contract_code)
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "principal-company-mismatch"},
        )

    def test_denies_unsupported_action(self):
        self._create_grant()
        response = self.client.post(
            self.endpoint,
            data=json.dumps(self._payload(action="ingest:delete")),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"allowed": False, "reason": "unsupported-action"},
        )
