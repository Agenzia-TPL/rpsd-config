# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    InputFlowVersion,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.api_usage import (
    api_usage_count,
    reset_api_usage_counts,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_revision,
    create_replacement_revision,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.server.m2m_auth import M2MAuthContext

from .runtime_configuration_fixtures import (
    RuntimeInputFixture,
    install_approved_runtime_configuration,
)


@override_settings(
    ROOT_URLCONF="rpsd_config.server.urls",
    M2M_API_ENABLED=True,
    M2M_API_CLIENT_ID_CLAIM="azp",
)
class M2MApiV1ContractTests(TestCase):
    """Protect the M2M v1 API consumed by the ingest service."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fixture_path = Path(__file__).with_name("fixtures") / "m2m_api_v1_contract.json"
        cls.golden = json.loads(fixture_path.read_text(encoding="utf-8"))

    def setUp(self):
        today = date.today()
        reset_api_usage_counts()
        self.configuration_admin = get_user_model().objects.create_superuser(
            username="golden-configuration-admin",
            password="test-password",
        )
        self.agency = Agency.objects.create(name="Golden Agency")
        self.company = Company.objects.create(name="Golden Company")
        self.lot = Lot.objects.create(
            agency=self.agency,
            short_description="GOLDEN-LOT",
            description="Golden contract lot",
        )
        self.contract = Contract.objects.create(
            contract_code="CTR-GOLDEN-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=30),
            status=Contract.ContractStatus.ACTIVE,
        )
        self.flow_profile, self.revision = install_approved_runtime_configuration(
            contract=self.contract,
            actor=self.configuration_admin,
            profile_code="golden-flow-profile_001",
            profile_version="001",
            profile_name="Golden Flow Profile",
            profile_description="Stable profile used by the M2M v1 contract tests.",
            orchestration_deployment_name="golden-contract-processing/default",
            inputs=(
                RuntimeInputFixture(
                    category="netex",
                    dataset_name="NeTEx",
                    dataset_description="Scheduled public transport data.",
                    specification_code="netex-ita_v001",
                    specification_version="001",
                    flow_code="netex-golden_001",
                    flow_version="001",
                    deployment_name="netex-import/netex-ita-v001",
                    flow_description="NeTEx ingest",
                    selected=True,
                    required=True,
                ),
                RuntimeInputFixture(
                    category="siri",
                    dataset_name="SIRI",
                    dataset_description="Real-time public transport data.",
                    specification_code="siri-vm_v001",
                    specification_version="001",
                    flow_code="siri-golden_001",
                    flow_version="001",
                    deployment_name="siri-import/siri-vm-v001",
                    flow_description="SIRI ingest",
                ),
            ),
        )
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="golden-client",
            environment="prod",
            keycloak_client_id="golden-company-ingest-prod",
            keycloak_client_uuid="golden-client-uuid",
        )
        self.grant = IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        self.client = Client()

    def _auth_context(self) -> M2MAuthContext:
        return M2MAuthContext(
            principal=self.principal,
            client_id=self.principal.keycloak_client_id,
            claims={"azp": self.principal.keycloak_client_id},
        )

    def _get(self, path: str, *, authenticated: bool = True):
        if not authenticated:
            return self.client.get(path)
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token",
            return_value=self._auth_context(),
        ):
            return self.client.get(path, HTTP_AUTHORIZATION="Bearer golden-token")

    def _path(self, suffix: str) -> str:
        return (
            "/exchange_agreement/api/m2m/v1/contracts/"
            f"{self.contract.contract_code}/{suffix}"
        )

    def _public_contract_path(self, suffix: str) -> str:
        return (
            "/exchange_agreement/api/v1/contracts/"
            f"{self.contract.contract_code}/{suffix}"
        )

    def _assert_golden(self, response, expected: dict, *, kind: str) -> None:
        payload = response.json()
        if kind == "required_inputs":
            for item in payload["required_inputs"]:
                for structure in item["structures"]:
                    structure["id"] = "<structure-id>"
        elif kind == "ingest_authorization" and payload.get("grant_id") is not None:
            payload["grant_id"] = "<grant-id>"

        self.assertEqual(response.status_code, expected["status"])
        self.assertEqual(payload, expected["payload"])

    def test_happy_path_matches_versioned_golden_contracts(self):
        cases = {
            "flow_profile": self._path("flow-profile"),
            "required_inputs": self._path("required-inputs"),
            "ingest_authorization": self._path(
                "ingest-authorization?data_category=netex"
            ),
        }

        for kind, path in cases.items():
            with self.subTest(kind=kind):
                response = self._get(path)
                self._assert_golden(
                    response,
                    self.golden["happy_path"][kind],
                    kind=kind,
                )
                self.assertEqual(response.headers["Deprecation"], "true")
                self.assertIn('rel="successor-version"', response.headers["Link"])
                self.assertTrue(response.headers["X-Correlation-ID"])
                self.assertEqual(
                    api_usage_count(
                        version="v1",
                        endpoint=kind.replace("_", "-"),
                        outcome="success",
                    ),
                    1,
                )

    def test_v1_adapters_do_not_query_legacy_configuration_tables(self):
        """The compatibility surface is a projection of target-model data only."""

        m2m_paths = (
            "/exchange_agreement/api/m2m/v1/contracts",
            f"/exchange_agreement/api/m2m/v1/contracts/{self.contract.contract_code}",
            self._path("flow-profile"),
            self._path("required-inputs"),
            self._path("indicators"),
        )
        with CaptureQueriesContext(connection) as captured:
            for path in m2m_paths:
                response = self._get(path)
                self.assertEqual(response.status_code, 200, path)

            self.client.force_login(self.configuration_admin)
            public_paths = (
                "/exchange_agreement/api/v1/contracts",
                f"/exchange_agreement/api/v1/contracts/{self.contract.contract_code}",
                self._public_contract_path("flow-profile"),
                self._public_contract_path("required-inputs"),
                self._public_contract_path("indicators"),
                "/exchange_agreement/api/v1/indicators",
                "/exchange_agreement/api/v1/structures",
                "/exchange_agreement/api/v1/flow-profiles",
            )
            for path in public_paths:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, path)

        legacy_tables = {
            "exchange_agreement_structure",
            "exchange_agreement_indicatordef",
            "exchange_agreement_operationalflow",
            "exchange_agreement_flowprofile",
        }
        executed_sql = "\n".join(query["sql"].lower() for query in captured)
        for table in legacy_tables:
            self.assertNotIn(table, executed_sql)

    def test_legacy_persistence_is_physically_removed(self):
        for model_name in (
            "Structure",
            "IndicatorDef",
            "OperationalFlow",
            "FlowProfile",
        ):
            with self.assertRaises(LookupError):
                apps.get_model("exchange_agreement", model_name)

        tables = set(connection.introspection.table_names())
        self.assertTrue(
            {
                "exchange_agreement_structure",
                "exchange_agreement_indicatordef",
                "exchange_agreement_operationalflow",
                "exchange_agreement_flowprofile",
            }.isdisjoint(tables)
        )
        contract_fields = {field.name for field in Contract._meta.fields}
        self.assertNotIn("flow_profile", contract_fields)

    def test_management_v1_rejects_direct_profile_assignment(self):
        self.client.force_login(self.configuration_admin)

        response = self.client.put(
            self._public_contract_path("flow-profile"),
            data=json.dumps({"flow_profile_code": self.flow_profile.code}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("configuration revision", response.json()["detail"])

    def test_management_v1_contract_create_ignores_compatibility_profile_field(self):
        self.client.force_login(self.configuration_admin)
        lot = Lot.objects.create(
            agency=self.agency,
            short_description="GOLDEN-LOT-2",
            description="Second golden contract lot",
        )

        response = self.client.post(
            "/exchange_agreement/api/v1/contracts",
            data=json.dumps(
                {
                    "contract_code": "CTR-GOLDEN-002",
                    "client_agency_id": self.agency.id,
                    "contractor_company_id": self.company.id,
                    "lot_id": lot.id,
                    "start_date": date.today().isoformat(),
                    "status": Contract.ContractStatus.DRAFT,
                    "flow_profile_code": self.flow_profile.code,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        created = Contract.objects.get(contract_code="CTR-GOLDEN-002")
        self.assertFalse(created.configuration_revisions.exists())

    def test_unauthenticated_request_matches_golden_rejection(self):
        response = self._get(self._path("flow-profile"), authenticated=False)

        self._assert_golden(
            response,
            self.golden["rejections"]["authentication_required"],
            kind="error",
        )

    def test_missing_grant_matches_golden_rejection(self):
        self.grant.delete()

        for suffix in ("flow-profile", "required-inputs"):
            with self.subTest(suffix=suffix):
                response = self._get(self._path(suffix))
                self._assert_golden(
                    response,
                    self.golden["rejections"]["grant_missing"],
                    kind="error",
                )

    def test_unsupported_category_matches_golden_rejection(self):
        response = self._get(self._path("ingest-authorization?data_category=gtfs"))

        self._assert_golden(
            response,
            self.golden["rejections"]["unsupported_data_category"],
            kind="error",
        )

    def test_inactive_category_matches_golden_rejection(self):
        response = self._get(self._path("ingest-authorization?data_category=siri"))

        self._assert_golden(
            response,
            self.golden["rejections"]["inactive_data_category"],
            kind="error",
        )

    def test_legacy_flow_is_deployment_name_not_catalog_code(self):
        response = self._get(self._path("ingest-authorization?data_category=netex"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["flow"], "netex-import/netex-ita-v001")
        self.assertNotEqual(response.json()["flow"], "netex-golden_001")

    def test_v1_and_v2_resolve_the_same_current_deployment(self):
        v1_response = self._get(self._path("ingest-authorization?data_category=netex"))
        v2_response = self._get(
            "/exchange_agreement/api/m2m/v2/contracts/"
            f"{self.contract.contract_code}/ingest-resolution?data_category=netex"
        )

        self.assertEqual(v1_response.status_code, 200)
        self.assertEqual(v2_response.status_code, 200)
        self.assertEqual(
            v1_response.json()["flow"],
            v2_response.json()["input_flow_version"]["deployment_name"],
        )

    def test_v1_selects_revision_from_config_clock_without_request_dates(self):
        current_netex = self.flow_profile.input_flow_links.get(dataset__code="netex")
        replacement_flow = publish_input_flow_version(
            InputFlowVersion.objects.create(
                dataset_specification=(
                    current_netex.input_flow_version.dataset_specification
                ),
                code="netex-golden_002",
                version="002",
                name="Golden NeTEx import v2",
                description="Replacement NeTEx ingest",
                deployment_name="netex-import/netex-ita-v002",
                artifact_identifier="git:rpsd-flows@netex-golden-002",
            ),
            actor=self.configuration_admin,
        )
        replacement_profile = ProcessingProfileVersion.objects.create(
            code="golden-flow-profile_002",
            version="002",
            name="Golden Flow Profile v2",
            description="Future profile used by the M2M v1 boundary test.",
            orchestration_flow_version=(self.flow_profile.orchestration_flow_version),
        )
        for profile_input in self.flow_profile.input_flow_links.select_related(
            "dataset", "input_flow_version"
        ):
            ProcessingProfileInputFlow.objects.create(
                processing_profile_version=replacement_profile,
                dataset=profile_input.dataset,
                input_flow_version=(
                    replacement_flow
                    if profile_input.dataset.code == "netex"
                    else profile_input.input_flow_version
                ),
            )
        for indicator_link in self.flow_profile.indicator_version_links.all():
            ProcessingProfileIndicatorVersion.objects.create(
                processing_profile_version=replacement_profile,
                indicator_version=indicator_link.indicator_version,
                proposed_by_default=indicator_link.proposed_by_default,
            )
        replacement_profile = publish_processing_profile(
            replacement_profile,
            actor=self.configuration_admin,
        )
        future = create_replacement_revision(
            self.revision,
            replacement_profile,
            self.configuration_admin,
            change_reason="Activate the replacement ingest deployment.",
        )
        future.valid_from = timezone.localdate() + timedelta(days=10)
        future.save()
        future = approve_revision(future, self.configuration_admin)

        current_response = self._get(
            self._path("ingest-authorization?data_category=netex")
        )
        self.assertEqual(
            current_response.json()["flow"],
            "netex-import/netex-ita-v001",
        )

        with patch(
            "rpsd_config.exchange_agreement.services.ingest_resolution.timezone.localdate",
            return_value=future.valid_from,
        ):
            future_response = self._get(
                self._path("ingest-authorization?data_category=netex")
            )
        self.assertEqual(future_response.status_code, 200)
        self.assertEqual(
            future_response.json()["flow"],
            "netex-import/netex-ita-v002",
        )

        rejected = self._get(
            self._path(
                "ingest-authorization?data_category=netex&reference_date="
                f"{future.valid_from.isoformat()}"
            )
        )
        self.assertEqual(rejected.status_code, 400)
