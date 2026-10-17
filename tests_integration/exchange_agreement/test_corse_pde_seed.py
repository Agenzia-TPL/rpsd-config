# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""CORSE_PDE definitions, policies, immutability and exact schema linkage."""

import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    Company,
    Contract,
    DatasetSpecification,
    IndicatorVersion,
    Lot,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    archive_configuration_asset,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_revision,
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.corse_pde_seed import (
    ensure_corse_pde_demo,
    load_corse_pde_corpus,
)
from rpsd_config.exchange_agreement.services.ingest_resolution import (
    resolve_current_ingest_configuration,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.services.validation_plans import (
    validation_plan_from_resolution,
)


class CorsePdeSeedTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = get_user_model().objects.create_user(
            username="corse-pde-admin", is_superuser=True
        )
        bundle = Path(__file__).parent / "fixtures/corse_pde/upstream/netex.zip"
        self.asset = store_configuration_asset(
            uploaded_file=SimpleUploadedFile("netex.zip", bundle.read_bytes()),
            asset_type="netex_xsd",
            what="netex",
            activate=True,
            uploaded_by=self.actor,
        ).asset

    def test_seed_preserves_xpath_versions_policies_and_dimensions(self):
        profile = ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        self.assertEqual(profile.status, "published")
        spec = DatasetSpecification.objects.get(code="netex-corse-pde_001")
        indicator = IndicatorVersion.objects.get(code="corse-pde-file-checks_001")
        self.assertEqual(spec.rule_bindings.count(), 1)
        self.assertEqual(indicator.rule_bindings.count(), 13)
        self.assertEqual(spec.metadata["excluded_requirements"], ["WF-001"])
        self.assertFalse(
            ValidationRule.objects.filter(code__contains="wf-001").exists()
        )
        for row in load_corse_pde_corpus()["rules"]:
            if row["requirement_type"] == "STATO":
                continue
            code = "corse-pde-" + row["code"].lower()
            if row["requirement_type"] == "XSD":
                binding = spec.rule_bindings.get(rule_version__rule__code=code)
            else:
                binding = indicator.rule_bindings.get(rule_version__rule__code=code)
            version = binding.rule_version
            with self.subTest(rule=row["code"]):
                if row["requirement_type"] == "XSD":
                    self.assertEqual(binding.failure_policy, "reject_import")
                    self.assertEqual(version.validation_type, "xsd_bundle")
                    continue
                self.assertEqual(version.definition, row["definition"])
                self.assertEqual(version.language_version, row["language_version"])
                consumer = binding
                self.assertEqual(
                    consumer.impact,
                    "calculation" if row["blocking"] == "sì" else "dimension",
                )
                self.assertEqual(
                    set(consumer.affected_dimensions.values_list("name", flat=True)),
                    set(
                        filter(None, (s.strip() for s in row["dimensions"].split(",")))
                    ),
                )
                if row["code"] == "NX-006":
                    self.assertIn("xs", version.options["namespaces"])

    def test_second_seed_is_read_only_for_published_definitions_and_bindings(self):
        ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        before = list(ValidationRuleVersion.objects.values())
        call_command(
            "seed_corse_pde_catalog",
            actor=self.actor.username,
            schema_asset_id=self.asset.pk,
            verbosity=0,
        )
        self.assertEqual(before, list(ValidationRuleVersion.objects.values()))
        self.assertEqual(ValidationRule.objects.count(), 14)
        self.assertEqual(DatasetSpecification.objects.get().rule_bindings.count(), 1)
        self.assertEqual(IndicatorVersion.objects.get().rule_bindings.count(), 13)

    def test_non_admin_is_rejected_before_creating_catalogs(self):
        actor = get_user_model().objects.create_user(username="corse-pde-reader")
        with self.assertRaises(PermissionDenied):
            ensure_corse_pde_demo(actor=actor, schema_asset=self.asset)
        self.assertFalse(DatasetSpecification.objects.exists())
        self.assertFalse(ValidationRule.objects.exists())

    def test_inactive_bundle_is_rejected_before_creating_catalogs(self):
        archive_configuration_asset(asset=self.asset)
        with self.assertRaises(ValidationError):
            ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        self.assertFalse(ValidationRule.objects.exists())

    def test_retired_rule_is_not_silently_reused(self):
        ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        rule = ValidationRuleVersion.objects.get(rule__code="corse-pde-nx-005")
        transition_validation_rule(
            rule,
            target_status="withdrawn",
            actor=self.actor,
            reason="Fixture retirement",
        )
        before = list(ValidationRuleVersion.objects.values())
        with self.assertRaisesMessage(ValidationError, "retired rule"):
            ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        self.assertEqual(before, list(ValidationRuleVersion.objects.values()))

    def test_single_xsd_is_not_accepted_as_the_lev5_bundle(self):
        asset = store_configuration_asset(
            uploaded_file=SimpleUploadedFile(
                "netex.xsd", b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
            ),
            asset_type="netex_xsd",
            what="netex",
            activate=True,
            uploaded_by=self.actor,
        ).asset
        with self.assertRaises(ValidationError) as error:
            ensure_corse_pde_demo(actor=self.actor, schema_asset=asset)
        self.assertEqual(error.exception.code, "corse_pde_bundle_mismatch")
        self.assertFalse(ValidationRule.objects.exists())

    def test_seed_refuses_changed_bundle_identity_in_an_existing_composition(self):
        ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        second = store_configuration_asset(
            uploaded_file=SimpleUploadedFile(
                "netex.zip",
                (
                    Path(__file__).parent / "fixtures/corse_pde/upstream/netex.zip"
                ).read_bytes(),
            ),
            asset_type="netex_xsd",
            what="netex",
            activate=True,
            uploaded_by=self.actor,
        ).asset
        before = list(ValidationRuleVersion.objects.values())
        with self.assertRaisesMessage(ValidationError, "schema association conflicts"):
            ensure_corse_pde_demo(actor=self.actor, schema_asset=second)
        self.assertEqual(before, list(ValidationRuleVersion.objects.values()))

    def test_approved_revision_freezes_all_rules_and_exact_bundle_for_the_transfer(
        self,
    ):
        profile = ensure_corse_pde_demo(actor=self.actor, schema_asset=self.asset)
        agency = Agency.objects.create(name="CORSE agency", agency_key="corse")
        company = Company.objects.create(name="CORSE company")
        lot = Lot.objects.create(agency=agency, short_description="CORSE")
        contract = Contract.objects.create(
            contract_code="CORSE-PLAN-001",
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=365),
            status="active",
        )
        revision = create_revision_draft(
            contract,
            profile,
            timezone.localdate(),
            self.actor,
            change_reason="CORSE_PDE file-only fixture",
        )
        revision = approve_revision(revision, self.actor)
        plan = validation_plan_from_resolution(
            resolve_current_ingest_configuration(
                contract=contract, data_category="netex"
            )
        )
        self.assertEqual(revision.snapshot_schema_version, "canonical-json-v2")
        self.assertEqual(len(revision.configuration_snapshot["validation_rules"]), 14)
        self.assertEqual(plan["scope"], "transfer")
        self.assertEqual(len(plan["validation_rules"]), 14)
        self.assertIn(self.asset.checksum_sha256, str(plan))
        self.assertIn("corse-pde-nx-005", str(plan))
        self.assertNotIn("corse-pde-wf-001", str(plan))
