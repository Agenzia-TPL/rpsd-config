# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import timedelta
from unittest.mock import patch

from django.db import OperationalError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement.api import m2m_api
from rpsd_config.exchange_agreement.models import (
    Contract,
    InputFlowVersion,
    IntegrationGrant,
    IntegrationPrincipal,
)
from rpsd_config.exchange_agreement.services.api_usage import (
    api_usage_count,
    reset_api_usage_counts,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_revision,
)
from rpsd_config.server.m2m_auth import (
    M2MAuthContext,
    M2MTokenValidationError,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


@override_settings(
    ROOT_URLCONF="rpsd_config.server.urls",
    M2M_API_ENABLED=True,
    M2M_API_CLIENT_ID_CLAIM="azp",
)
class IngestResolutionApiV2Tests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        reset_api_usage_counts()
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="runtime-ingest-client",
            environment="prod",
            keycloak_client_id="runtime-ingest-client-prod",
            keycloak_client_uuid="runtime-ingest-client-uuid",
        )
        self.grant = IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        self.client = Client()

    def _auth_context(self):
        return M2MAuthContext(
            principal=self.principal,
            client_id=self.principal.keycloak_client_id,
            claims={"azp": self.principal.keycloak_client_id},
        )

    def _path(self, query="?data_category=netex"):
        return (
            "/exchange_agreement/api/m2m/v2/contracts/"
            f"{self.contract.contract_code}/ingest-resolution{query}"
        )

    def _get(self, path=None, *, authenticated=True):
        path = path or self._path()
        if not authenticated:
            return self.client.get(path)
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token",
            return_value=self._auth_context(),
        ):
            return self.client.get(
                path,
                HTTP_AUTHORIZATION="Bearer runtime-token",
                HTTP_X_CORRELATION_ID="test-correlation-id",
            )

    def _approve_current(self):
        return self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )

    def assert_error(self, response, *, status, code):
        self.assertEqual(response.status_code, status)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], code)
        self.assertTrue(payload["error"]["message"])
        self.assertTrue(payload["error"]["correlation_id"])
        self.assertNotIn("token", response.content.decode().lower())

    def test_happy_path_reads_complete_resolution_from_approved_snapshot(self):
        revision = self._approve_current()

        response = self._get()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "ingest-resolution/v2")
        self.assertEqual(payload["contract_code"], self.contract.contract_code)
        self.assertEqual(payload["configuration_revision_code"], revision.code)
        self.assertEqual(payload["data_category"], "netex")
        self.assertEqual(
            payload["dataset_specification"],
            {"code": "netex-ita_v001", "version": "001"},
        )
        self.assertEqual(
            payload["input_flow_version"],
            {
                "code": "netex-import_002",
                "version": "002",
                "engine": "prefect",
                "deployment_name": "validators/netex-default",
                "artifact_identifier": "git:rpsd-flows@netex-import-002",
            },
        )
        self.assertEqual(
            payload["orchestration_flow_version"]["deployment_name"],
            "contract-processing/default",
        )
        self.assertEqual(
            payload["snapshot_schema_version"],
            "canonical-json-v2",
        )
        self.assertEqual(payload["snapshot_checksum"], revision.snapshot_checksum)
        self.assertNotIn("fragments", payload)
        self.assertNotIn("valid_from", payload)
        self.assertEqual(
            api_usage_count(
                version="v2",
                endpoint="ingest-resolution",
                outcome="success",
            ),
            1,
        )

    def test_openapi_contract_has_no_dates_or_validation_context(self):
        schema = m2m_api.get_openapi_schema()
        operation = schema["paths"][
            "/exchange_agreement/api/m2m/v2/contracts/{contract_code}/ingest-resolution"
        ]["get"]
        query_parameters = {
            parameter["name"]
            for parameter in operation["parameters"]
            if parameter["in"] == "query"
        }
        self.assertEqual(query_parameters, {"data_category"})
        response_schema = schema["components"]["schemas"]["IngestResolutionV2"]
        serialized_schema = str(response_schema).lower()
        for excluded in (
            "reference_date",
            "service_day",
            "valid_from",
            "fragment",
            "validation_rule",
        ):
            self.assertNotIn(excluded, serialized_schema)

    def test_runtime_values_remain_frozen_when_catalog_rows_change(self):
        self._approve_current()
        InputFlowVersion.objects.filter(
            pk=self.profile_input.input_flow_version_id
        ).update(
            deployment_name="mutated-after-approval",
            artifact_identifier="git:mutated-after-approval",
        )

        response = self._get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["input_flow_version"]["deployment_name"],
            "validators/netex-default",
        )
        self.assertEqual(
            response.json()["input_flow_version"]["artifact_identifier"],
            "git:rpsd-flows@netex-import-002",
        )

    def test_request_rejects_dates_unknown_parameters_and_duplicate_category(self):
        for query in (
            "?data_category=netex&reference_date=2026-01-01",
            "?data_category=netex&service_day=2026-01-01",
            "?data_category=netex&data_category=siri-vm",
            "",
        ):
            with self.subTest(query=query):
                self.assert_error(
                    self._get(self._path(query)),
                    status=422,
                    code="invalid_request",
                )

    def test_authentication_authorization_and_visibility_are_fail_closed(self):
        self.assert_error(
            self._get(authenticated=False),
            status=401,
            code="authentication_failed",
        )

        self.grant.delete()
        self.assert_error(
            self._get(),
            status=403,
            code="ingest_not_authorized",
        )

        self.assert_error(
            self._get(
                self._path().replace(
                    self.contract.contract_code,
                    "UNKNOWN-CONTRACT",
                )
            ),
            status=404,
            code="contract_not_found",
        )

    def test_inactive_principal_uses_403_error_envelope(self):
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token",
            side_effect=M2MTokenValidationError("principal-suspended"),
        ):
            response = self.client.get(
                self._path(),
                HTTP_AUTHORIZATION="Bearer runtime-token",
            )
        self.assert_error(
            response,
            status=403,
            code="ingest_not_authorized",
        )

    def test_runtime_conflict_codes_distinguish_not_ready_category_and_integrity(self):
        self.assert_error(
            self._get(),
            status=409,
            code="configuration_not_ready",
        )

        revision = self._approve_current()
        self.assert_error(
            self._get(self._path("?data_category=gtfs")),
            status=409,
            code="data_category_not_configured",
        )

        type(revision).objects.filter(pk=revision.pk).update(
            snapshot_checksum="sha256:" + ("0" * 64)
        )
        self.assert_error(
            self._get(),
            status=409,
            code="configuration_invariant_violation",
        )

    def test_contract_effectiveness_and_database_availability_have_stable_errors(self):
        Contract.objects.filter(pk=self.contract.pk).update(
            status=Contract.ContractStatus.DRAFT
        )
        self.assert_error(
            self._get(),
            status=409,
            code="contract_not_effective",
        )

        Contract.objects.filter(pk=self.contract.pk).update(
            status=Contract.ContractStatus.ACTIVE
        )
        with patch(
            "rpsd_config.exchange_agreement.api.resolve_current_ingest_configuration",
            side_effect=OperationalError("database unavailable"),
        ):
            self.assert_error(
                self._get(),
                status=503,
                code="configuration_service_unavailable",
            )

    def test_future_revision_cannot_be_selected_by_request(self):
        current = self._approve_current()
        future = self._revision(
            number=2,
            valid_from=timezone.localdate() + timedelta(days=10),
            replaces=current,
        )
        approve_revision(future, self.user)

        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["configuration_revision_code"],
            current.code,
        )

        with patch(
            "rpsd_config.exchange_agreement.services.ingest_resolution.timezone.localdate",
            return_value=future.valid_from,
        ):
            response_after_clock_change = self._get()
        self.assertEqual(response_after_clock_change.status_code, 200)
        self.assertEqual(
            response_after_clock_change.json()["configuration_revision_code"],
            future.code,
        )
