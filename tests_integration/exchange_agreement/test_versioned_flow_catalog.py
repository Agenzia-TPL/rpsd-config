# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from rpsd_config.admin_dataset_exchange.proxies import InputFlowVersionAdminProxy
from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    InputFlowVersion,
    InputFlowVersionStatusEvent,
    OrchestrationFlowVersion,
    OrchestrationFlowVersionStatusEvent,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    FlowCatalogTransitionError,
    deprecate_input_flow_version,
    deprecate_orchestration_flow_version,
    input_flow_runtime_projection,
    orchestration_flow_runtime_projection,
    publish_input_flow_version,
    publish_orchestration_flow_version,
    withdraw_input_flow_version,
    withdraw_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.flow_catalog_bootstrap import (
    ensure_standard_flow_catalog,
)
from rpsd_config.exchange_agreement.services.flow_catalog_registry import (
    transport_message_invocation_contract,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class VersionedFlowCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="flow-catalog-admin",
            password="test-password",
        )
        self.dataset = Dataset.objects.create(code="netex", name="NeTEx")
        self.specification = DatasetSpecification.objects.create(
            dataset=self.dataset,
            code="netex-ita_v001",
            version="001",
            description="NeTEx Italia v1",
        )
        self.specification = publish_dataset_specification(
            self.specification,
            actor=self.user,
        )

    def _input_flow(self, *, code="netex-import_001", version="001", **kwargs):
        values = {
            "code": code,
            "version": version,
            "name": "NeTEx import",
            "description": "Validate and import NeTEx data.",
            "dataset_specification": self.specification,
            "deployment_name": "validators/netex-default",
            "artifact_identifier": "git:rpsd-flows@netex-import-001",
            "invocation_contract": transport_message_invocation_contract(),
            "compatibility": {"schema_version": 1, "what": "netex"},
        }
        values.update(kwargs)
        return InputFlowVersion.objects.create(**values)

    def _orchestration_flow(
        self,
        *,
        code="contract-processing_001",
        version="001",
        **kwargs,
    ):
        values = {
            "code": code,
            "version": version,
            "name": "Contract processing",
            "description": "Coordinate the configured contract processing.",
            "deployment_name": "rpsd-contract-processing/default",
            "artifact_identifier": "git:rpsd-flows@contract-processing-001",
            "invocation_contract": transport_message_invocation_contract(),
        }
        values.update(kwargs)
        return OrchestrationFlowVersion.objects.create(**values)

    def test_input_flow_has_distinct_catalog_and_deployment_identity(self):
        flow = self._input_flow()
        self.assertNotEqual(flow.code, flow.deployment_name)
        self.assertEqual(flow.dataset_specification, self.specification)
        self.assertEqual(flow.compatibility["what"], self.dataset.code)

        with self.assertRaises(ValidationError):
            self._input_flow(code="netex-alias_001")
        with self.assertRaises(ValidationError):
            self._input_flow(
                code="netex-import_002",
                version="002",
                compatibility={"schema_version": 1, "what": "siri-vm"},
            )

    def test_closed_invocation_contract_adds_no_runtime_parameters(self):
        flow = self._input_flow()
        self.assertEqual(
            flow.invocation_contract,
            {"schema_version": 1, "message_type": "TransportMessage"},
        )
        self.assertNotIn("date", flow.invocation_contract)
        self.assertNotIn("revision_id", flow.invocation_contract)

        with self.assertRaises(ValidationError):
            self._input_flow(
                code="netex-import_002",
                version="002",
                invocation_contract={
                    "schema_version": 1,
                    "message_type": "TransportMessage",
                    "revision_id": "required",
                },
            )

    def test_publication_requires_published_specification_and_executable_references(
        self,
    ):
        incomplete = self._input_flow(
            deployment_name="",
            artifact_identifier="",
        )
        with self.assertRaises(ValidationError):
            publish_input_flow_version(incomplete, actor=self.user)

        draft_specification = DatasetSpecification.objects.create(
            dataset=self.dataset,
            code="netex-ita_v002",
            version="002",
            description="Draft NeTEx specification",
        )
        draft_flow = self._input_flow(
            code="netex-import_002",
            version="002",
            dataset_specification=draft_specification,
        )
        with self.assertRaises(FlowCatalogTransitionError):
            publish_input_flow_version(draft_flow, actor=self.user)

        with self.assertRaises(ValidationError):
            self._orchestration_flow(
                artifact_identifier="artifact with spaces",
            )

    def test_input_lifecycle_is_audited_and_immutable(self):
        flow = publish_input_flow_version(self._input_flow(), actor=self.user)
        event = InputFlowVersionStatusEvent.objects.get(input_flow_version=flow)
        self.assertEqual(event.changed_by, self.user)
        self.assertEqual(event.to_status, InputFlowVersion.Status.PUBLISHED)

        flow.deployment_name = "different/deployment"
        with self.assertRaises(ValidationError):
            flow.save()
        with self.assertRaises(ValidationError):
            flow.delete()

        flow = deprecate_input_flow_version(flow, actor=self.user)
        flow = withdraw_input_flow_version(flow, actor=self.user)
        self.assertEqual(flow.status, InputFlowVersion.Status.WITHDRAWN)
        self.assertEqual(flow.status_events.count(), 3)

    def test_orchestration_catalog_is_separate_and_audited(self):
        flow = publish_orchestration_flow_version(
            self._orchestration_flow(),
            actor=self.user,
        )
        self.assertFalse(hasattr(flow, "dataset_specification"))
        event = OrchestrationFlowVersionStatusEvent.objects.get(
            orchestration_flow_version=flow
        )
        self.assertEqual(event.changed_by, self.user)

        flow = deprecate_orchestration_flow_version(flow, actor=self.user)
        flow = withdraw_orchestration_flow_version(flow, actor=self.user)
        self.assertEqual(flow.status, OrchestrationFlowVersion.Status.WITHDRAWN)

    def test_runtime_projection_and_api_use_deployment_not_code(self):
        input_flow = publish_input_flow_version(self._input_flow(), actor=self.user)
        orchestration = publish_orchestration_flow_version(
            self._orchestration_flow(),
            actor=self.user,
        )
        input_projection = input_flow_runtime_projection(input_flow)
        orchestration_projection = orchestration_flow_runtime_projection(orchestration)
        self.assertEqual(
            input_projection["deployment_name"],
            "validators/netex-default",
        )
        self.assertNotEqual(
            input_projection["deployment_name"], input_projection["code"]
        )
        self.assertEqual(
            orchestration_projection["deployment_name"],
            "rpsd-contract-processing/default",
        )

        self.client.force_login(self.user)
        input_response = self.client.get(
            "/exchange_agreement/api/v1/flow-catalog/input/netex-import_001"
        )
        orchestration_response = self.client.get(
            "/exchange_agreement/api/v1/flow-catalog/orchestration/"
            "contract-processing_001"
        )
        self.assertEqual(input_response.status_code, 200)
        self.assertEqual(orchestration_response.status_code, 200)
        self.assertEqual(
            input_response.json()["deployment_name"],
            input_flow.deployment_name,
        )
        self.assertEqual(
            orchestration_response.json()["artifact_identifier"],
            orchestration.artifact_identifier,
        )

    def test_bootstrap_is_idempotent_and_registers_standard_catalog(self):
        first_inputs, first_orchestration = ensure_standard_flow_catalog()
        second_inputs, second_orchestration = ensure_standard_flow_catalog()

        self.assertEqual(len(first_inputs), 11)
        self.assertEqual(
            [flow.pk for flow in first_inputs],
            [flow.pk for flow in second_inputs],
        )
        self.assertEqual(first_orchestration.pk, second_orchestration.pk)
        self.assertFalse(
            InputFlowVersion.objects.exclude(
                status=InputFlowVersion.Status.PUBLISHED
            ).exists()
        )
        self.assertEqual(
            first_orchestration.status,
            OrchestrationFlowVersion.Status.PUBLISHED,
        )

    def test_catalog_contains_no_dag_or_scheduling_configuration(self):
        forbidden = {
            "cron",
            "frequency",
            "interval",
            "trigger_mode",
            "retry",
            "nodes",
            "dependencies",
            "fan_in",
        }
        input_fields = {field.name for field in InputFlowVersion._meta.get_fields()}
        orchestration_fields = {
            field.name for field in OrchestrationFlowVersion._meta.get_fields()
        }
        self.assertFalse(input_fields & forbidden)
        self.assertFalse(orchestration_fields & forbidden)

    def test_admin_permissions_are_limited_to_platform_roles(self):
        regular = get_user_model().objects.create_user(username="flow-regular")
        platform = get_user_model().objects.create_user(username="flow-platform")
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="flow-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        model_admin = admin.site._registry[InputFlowVersionAdminProxy]
        request = RequestFactory().get("/")
        request.user = regular
        self.assertFalse(model_admin.has_add_permission(request))
        request.user = platform
        self.assertTrue(model_admin.has_add_permission(request))
