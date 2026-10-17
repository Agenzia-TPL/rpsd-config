# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Config-only target plan, API authorization and immutable revision evidence."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    ContractDependencyConfiguration,
    IndicatorVersion,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_revision,
    canonical_snapshot_checksum,
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.ingest_resolution import (
    IngestResolutionError,
    resolve_current_ingest_configuration,
)
from rpsd_config.exchange_agreement.services.revision_indicator_values import (
    save_revision_indicator_values,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
)
from rpsd_config.exchange_agreement.services.validation_plans import (
    validation_plan_from_resolution,
)
from rpsd_config.exchange_agreement.services.validation_seed import (
    ensure_validation_demo,
)


@override_settings(
    ROOT_URLCONF="rpsd_config.server.urls",
    VALIDATION_M2M_ALLOWED_CLIENT_IDS="test-validator",
)
class ValidationPlanTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="plan-admin", is_superuser=True, is_staff=True
        )
        self.profile = ensure_validation_demo(actor=self.admin)
        agency = Agency.objects.create(name="Test agency", agency_key="plan-agency")
        company = Company.objects.create(name="Test company")
        lot = Lot.objects.create(
            agency=agency, short_description="PLAN", description="Plan fixture"
        )
        self.contract = Contract.objects.create(
            contract_code="VALIDATION-PLAN-001",
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=365),
            status="active",
        )
        self.revision = create_revision_draft(
            self.contract,
            self.profile,
            timezone.localdate(),
            self.admin,
            change_reason="Target plan fixture",
        )

    def approve(self):
        self.revision = approve_revision(self.revision, self.admin)
        return self.revision

    def get_api(self, query="?data_category=netex", client_id="test-validator"):
        with (
            patch(
                "rpsd_config.exchange_agreement.api.M2MClientTokenAuth.authenticate",
                return_value=None,
            ),
            patch(
                "rpsd_config.exchange_agreement.api.validate_m2m_token",
                return_value={"azp": client_id},
            ),
        ):
            return self.client.get(
                f"/exchange_agreement/api/m2m/v3/contracts/{self.contract.contract_code}/validation-plan"
                + query,
                HTTP_AUTHORIZATION="Bearer test-token",
            )

    def test_seed_is_idempotent_without_mutating_published_catalog(self):
        before = (
            ValidationRuleVersion.objects.count(),
            IndicatorVersion.objects.count(),
        )
        again = ensure_validation_demo(actor=self.admin)
        self.assertEqual(again.pk, self.profile.pk)
        self.assertEqual(
            before,
            (ValidationRuleVersion.objects.count(), IndicatorVersion.objects.count()),
        )

    def test_plan_filters_dataset_and_keeps_dependency_provenance(self):
        revision = self.approve()
        self.assertEqual(revision.snapshot_schema_version, "canonical-json-v2")
        self.assertEqual(len(revision.input_selections.all()), 2)
        resolution = resolve_current_ingest_configuration(self.contract, "netex")
        plan = validation_plan_from_resolution(resolution)
        self.assertEqual(plan["scope"], "transfer")
        self.assertEqual(len(plan["validation_rules"]), 2)
        self.assertFalse(
            any(
                rule["rule_code"].startswith("siri")
                for rule in plan["validation_rules"]
            )
        )
        bindings = plan["input"]["rule_bindings"]
        dimension = next(b for b in bindings if b["import_policy"] == "indicator_only")
        self.assertEqual(dimension["consumers"][0]["impact"], "dimension")
        self.assertEqual(len(dimension["consumers"][0]["dependency_paths"][0]), 2)
        digest = plan.pop("plan_digest")
        self.assertEqual(digest, canonical_snapshot_checksum(plan))
        self.assertNotEqual(digest, revision.snapshot_checksum)

    def test_api_allows_explicit_service_and_rejects_extra_query_or_unknown_client(
        self,
    ):
        self.approve()
        response = self.get_api()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["schema_version"], "validation-plan-v1")
        self.assertEqual(
            self.get_api(query="?data_category=netex&date=2020-01-01").status_code, 422
        )
        self.assertEqual(self.get_api(client_id="unlisted-client").status_code, 401)

    def test_values_belong_to_dependency_and_freeze_with_revision(self):
        values = dict(
            parameters={"window_minutes": 30},
            thresholds={},
            aggregation={},
            penalties={},
        )
        config = save_revision_indicator_values(
            self.revision,
            version_code="demo-journey-count_001",
            values=values,
            actor=self.admin,
        )
        self.assertIsInstance(config, ContractDependencyConfiguration)
        self.assertEqual(self.revision.indicator_configurations.get().parameters, {})
        self.approve()
        with self.assertRaises(ValidationError):
            save_revision_indicator_values(
                self.revision,
                version_code="demo-journey-count_001",
                values=values,
                actor=self.admin,
            )
        snapshot = self.revision.configuration_snapshot
        result = next(
            c
            for c in snapshot["indicator_configurations"]
            if c["indicator_version_code"] == "demo-journey-count_001"
        )
        self.assertEqual(result["parameters"], values["parameters"])

    def test_published_plan_does_not_query_live_rules(self):
        self.approve()
        resolution = resolve_current_ingest_configuration(self.contract, "netex")
        with patch(
            "rpsd_config.exchange_agreement.models.ValidationRuleVersion.objects.filter",
            side_effect=AssertionError("Live rule query"),
        ):
            plan = validation_plan_from_resolution(resolution)
        self.assertEqual(len(plan["validation_rules"]), 2)

    def test_append_only_applicability_preserves_approved_snapshot_and_plan(self):
        from copy import deepcopy

        from rpsd_config.exchange_agreement.models import ValidationRule
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            bind_dataset_rule,
        )
        from rpsd_config.exchange_agreement.services.validation_catalog import (
            transition_validation_rule,
        )

        self.approve()
        before_snapshot = deepcopy(self.revision.configuration_snapshot)
        before_checksum = self.revision.snapshot_checksum
        before_plan = validation_plan_from_resolution(
            resolve_current_ingest_configuration(self.contract, "netex")
        )
        specification = self.profile.input_flow_links.get(
            dataset__code="netex"
        ).input_flow_version.dataset_specification
        version = ValidationRuleVersion.objects.create(
            rule=ValidationRule.objects.create(
                code="later-optional-rule", name="Later optional rule"
            ),
            version="001",
            name="Later optional rule",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition="//n:Line[not(@id)]",
            options={"namespaces": {"n": "urn:netex"}},
            execution_reference="validators/default",
        )
        rule = transition_validation_rule(
            version, target_status="published", actor=self.admin
        )
        with self.assertRaises(ValidationError):
            bind_dataset_rule(
                specification=specification,
                rule_version=rule,
                failure_policy="warn",
                actor=self.admin,
            )
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.configuration_snapshot, before_snapshot)
        self.assertEqual(self.revision.snapshot_checksum, before_checksum)
        after_plan = validation_plan_from_resolution(
            resolve_current_ingest_configuration(self.contract, "netex")
        )
        self.assertEqual(before_plan, after_plan)

    def test_dependency_required_parameters_are_not_inherited_from_parent(self):
        from django.db import models

        from rpsd_config.exchange_agreement.services.contract_revisions import (
            build_revision_snapshot,
            validate_revision_for_approval,
        )

        dependency = IndicatorVersion.objects.get(code="demo-journey-count_001")
        # Fixture for a published catalog imported before schema enforcement.
        models.QuerySet.update(
            IndicatorVersion.objects.filter(pk=dependency.pk),
            parameter_schema={
                "schema_version": 1,
                "properties": {"window": {"type": "integer"}},
                "required": ["window"],
            },
        )
        root_config = self.revision.indicator_configurations.get()
        root_config.parameters = {"window": 20}
        root_config.save()
        issues = validate_revision_for_approval(self.revision)
        issue = next(
            item for item in issues if item.code == "missing_dependency_parameters"
        )
        self.assertEqual(issue.details["indicator_version_code"], dependency.code)
        self.assertIn(dependency.code, issue.message)
        save_revision_indicator_values(
            self.revision,
            version_code=dependency.code,
            values={
                "parameters": {"window": 10},
                "thresholds": {},
                "aggregation": {},
                "penalties": {},
            },
            actor=self.admin,
        )
        snapshot = build_revision_snapshot(self.revision)
        values = {
            item["indicator_version_code"]: item["parameters"]
            for item in snapshot["indicator_configurations"]
        }
        self.assertEqual(values[dependency.code], {"window": 10})
        self.assertIn(
            "propagate_only_required_dimensions", str(snapshot["dependency_edges"])
        )

    def test_selected_indicator_cannot_have_implicit_configuration(self):
        from rpsd_config.exchange_agreement.models import (
            ContractDependencyConfiguration,
        )

        configuration = self.revision.indicator_configurations.get()
        link = configuration.processing_profile_indicator_version
        root = link.indicator_version
        with self.assertRaises(ValidationError):
            ContractDependencyConfiguration.objects.create(
                revision=self.revision, indicator_version=root
            )

    def test_reader_rejects_corrupt_frozen_structures_without_live_queries(self):
        self.approve()
        resolution = resolve_current_ingest_configuration(self.contract, "netex")
        for mutation in (
            lambda s: s["validation_rules"].append(deepcopy(s["validation_rules"][0])),
            lambda s: s["effective_indicators"].clear(),
            lambda s: s["indicator_configurations"].clear(),
            lambda s: s["indicator_execution_order"].reverse(),
            lambda s: s["inputs"][0].update(rule_bindings=[None]),
            lambda s: s["inputs"][0]["rule_bindings"][0].update(rule_code="missing"),
        ):
            snapshot = deepcopy(resolution.snapshot)
            mutation(snapshot)
            with self.subTest(mutation=mutation), self.assertNumQueries(0):
                with self.assertRaises(IngestResolutionError) as error:
                    validation_plan_from_resolution(
                        replace(resolution, snapshot=snapshot)
                    )
                self.assertEqual(
                    error.exception.code, "configuration_invariant_violation"
                )

    def test_legacy_plan_is_not_synthesized(self):
        self.approve()
        resolution = resolve_current_ingest_configuration(self.contract, "netex")
        with (
            self.assertNumQueries(0),
            self.assertRaises(IngestResolutionError) as error,
        ):
            validation_plan_from_resolution(
                replace(resolution, snapshot_schema_version="canonical-json-v1")
            )
        self.assertEqual(error.exception.code, "validation_plan_not_available")

    def test_acquired_plan_remains_pinned_after_new_revision(self):
        self.approve()
        resolution = resolve_current_ingest_configuration(self.contract, "netex")
        old_plan = validation_plan_from_resolution(resolution)
        tomorrow = timezone.localdate() + timedelta(days=1)
        new_revision = create_revision_draft(
            self.contract,
            self.profile,
            tomorrow,
            self.admin,
            change_reason="Next revision",
        )
        approve_revision(new_revision, self.admin)
        with patch(
            "rpsd_config.exchange_agreement.services.ingest_resolution.timezone.localdate",
            return_value=tomorrow,
        ):
            current = resolve_current_ingest_configuration(self.contract, "netex")
        new_plan = validation_plan_from_resolution(current)
        self.assertNotEqual(old_plan["plan_digest"], new_plan["plan_digest"])
        with self.assertNumQueries(0):
            self.assertEqual(validation_plan_from_resolution(resolution), old_plan)
        # Consumers persist this content/digest; Config does not create ingest jobs.

    def test_invalid_query_and_unavailable_database_have_stable_envelopes(self):
        self.approve()
        for query in (
            "",
            "?data_category=netex&data_category=siri-vm",
            "?data_category=netex&extra=1",
        ):
            response = self.get_api(query=query)
            self.assertEqual(response.status_code, 422)
        with patch(
            "rpsd_config.exchange_agreement.api.resolve_current_ingest_configuration",
            side_effect=OperationalError("Unavailable"),
        ):
            response = self.get_api()
        self.assertEqual(response.status_code, 503)
        self.assertIn("configuration_service_unavailable", response.content.decode())

    def test_complete_snapshot_matches_golden_fixture(self):
        self.approve()
        actual = deepcopy(self.revision.configuration_snapshot)
        actual["revision"]["valid_from"] = "2026-10-11"
        expected = json.loads(
            (
                Path(__file__).parent / "fixtures" / "validation_snapshot_v2.json"
            ).read_text()
        )
        self.assertEqual(actual, expected)
        self.assertEqual(
            canonical_snapshot_checksum(actual), canonical_snapshot_checksum(expected)
        )
        # Golden contains stable catalog codes, never local IDs or storage secrets.
        self.assertNotIn('"pk":', json.dumps(actual))

    def test_company_grant_and_tenant_scope_for_v3(self):
        from rpsd_config.server.m2m_auth import M2MAuthContext

        self.approve()
        principal = IntegrationPrincipal.objects.create(
            company=self.contract.contractor_company,
            name="Company client",
            environment="prod",
            keycloak_client_id="plan-company-client",
            keycloak_client_uuid="plan-company-uuid",
        )
        path = (
            "/exchange_agreement/api/m2m/v3/contracts/"
            f"{self.contract.contract_code}/validation-plan?data_category=netex"
        )
        context = M2MAuthContext(
            principal=principal,
            client_id=principal.keycloak_client_id,
            claims={"azp": principal.keycloak_client_id},
        )
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token", return_value=context
        ):
            denied = self.client.get(path, HTTP_AUTHORIZATION="Bearer company-token")
            self.assertEqual(denied.status_code, 403)
            grant = IntegrationGrant.objects.create(
                principal=principal,
                contract=self.contract,
                action=IntegrationGrant.Action.INGEST_WRITE,
            )
            allowed = self.client.get(path, HTTP_AUTHORIZATION="Bearer company-token")
            self.assertEqual(allowed.status_code, 200, allowed.content)
            grant.data_category = "siri-vm"
            grant.save()
            self.assertEqual(
                self.client.get(
                    path, HTTP_AUTHORIZATION="Bearer company-token"
                ).status_code,
                403,
            )
            principal.company = Company.objects.create(name="Another company")
            principal.save()
            self.assertEqual(
                self.client.get(
                    path, HTTP_AUTHORIZATION="Bearer company-token"
                ).status_code,
                404,
            )
