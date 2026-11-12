# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Draft authoring, consistent exports and unchanged operational boundaries."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.configuration_exports import (
    ConfigurationExportError,
    export_contract_configuration,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionError,
    approve_revision,
    canonical_snapshot_checksum,
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    duplicate_processing_profile,
)
from rpsd_config.exchange_agreement.services.validation_seed import (
    ensure_validation_demo,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class ConfigurationExportTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="export-admin", is_staff=True, is_superuser=True
        )
        self.published = ensure_validation_demo(actor=self.actor)
        self.profile = duplicate_processing_profile(
            self.published, code="preview-profile", version="preview"
        )
        agency = domain.Agency.objects.create(name="Exports", agency_key="exports")
        company = domain.Company.objects.create(name="Operator")
        lot = domain.Lot.objects.create(
            agency=agency, short_description="Exports", description="Exports"
        )
        self.contract = domain.Contract.objects.create(
            contract_code="EXPORT-DEMO",
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=365),
            status="draft",
        )
        self.revision = create_revision_draft(
            self.contract, self.profile, timezone.localdate(), self.actor
        )

    def export(self, **kwargs):
        return export_contract_configuration(
            actor=self.actor,
            contract_code=self.contract.contract_code,
            revision_code=self.revision.code,
            **kwargs,
        )

    def test_draft_preview_is_read_only_deterministic_and_operationally_unapproved(
        self,
    ):
        before = list(domain.ContractConfigurationRevision.objects.values())
        one, two = self.export(), self.export()
        self.assertEqual(one["content_digest"], two["content_digest"])
        self.assertEqual(one["mode"], "draft_preview")
        self.assertTrue(
            any(i["code"] == "component_not_published" for i in one["issues"])
        )
        self.assertEqual(
            before, list(domain.ContractConfigurationRevision.objects.values())
        )
        with self.assertRaises(ContractRevisionError):
            approve_revision(self.revision, self.actor)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.status, "draft")
        with transaction.atomic():
            with self.assertRaises(ConfigurationExportError) as conflict:
                self.export()
            self.assertEqual(conflict.exception.status, 409)

    def test_projection_targets_and_digest_track_saved_values(self):
        full = self.export()
        dataset = full["configuration"]["inputs"][0]["dataset_code"]
        projected = self.export(scope="dataset", dataset_code=dataset)
        self.assertEqual(
            [i["dataset_code"] for i in projected["configuration"]["inputs"]], [dataset]
        )
        root = full["configuration"]["selected_indicators"][0]
        self.assertTrue(
            self.export(scope="indicator", indicator_version_code=root)[
                "configuration"
            ]["inputs"]
        )
        implicit = next(
            v["code"]
            for v in full["configuration"]["effective_indicators"]
            if v["role"] == "dependency"
        )
        subset = self.export(scope="indicator", indicator_version_code=implicit)
        for item in subset["configuration"]["inputs"]:
            for binding in item["rule_bindings"]:
                for consumer in binding["consumers"]:
                    self.assertTrue(
                        all(
                            path[0] == implicit for path in consumer["dependency_paths"]
                        )
                    )
        with self.assertRaises(ConfigurationExportError):
            self.export(scope="dataset", dataset_code="outside")
        config = self.revision.indicator_configurations.get()
        config.aggregation = {"period": "month"}
        config.save()
        self.assertNotEqual(full["content_digest"], self.export()["content_digest"])

    def test_unrelated_reader_denied_and_three_download_channels_agree(self):
        outsider = get_user_model().objects.create_user(username="outsider")
        with self.assertRaises(PermissionDenied):
            export_contract_configuration(
                actor=outsider,
                contract_code=self.contract.contract_code,
                revision_code=self.revision.code,
            )
        self.client.force_login(self.actor)
        api = self.client.get(
            f"/exchange_agreement/api/v1/contracts/{self.contract.contract_code}/configuration-revisions/{self.revision.code}/export"
        )
        self.assertEqual(api.status_code, 200, api.content)
        page = self.client.get(
            f"/exchange_agreement/me/contracts/{self.contract.contract_code}/revisions/{self.revision.pk}/export/"
        )
        self.assertEqual(page.status_code, 200, page.content)
        download = self.client.get(
            f"/admin/admin_agreements/contractconfigurationrevisionadminproxy/{self.revision.pk}/export/?download=1"
        )
        self.assertEqual(download.status_code, 200, download.content)
        self.assertEqual(
            api.json()["content_digest"], download.json()["content_digest"]
        )

    def test_frozen_export_uses_saved_snapshot_after_catalog_change(self):
        self.revision.delete()
        self.revision = create_revision_draft(
            self.contract, self.published, timezone.localdate(), self.actor
        )
        self.revision = approve_revision(self.revision, self.actor)
        source = self.revision.configuration_snapshot
        result = self.export()
        self.assertEqual(result["mode"], "frozen_revision")
        self.assertEqual(result["configuration"], source)
        self.assertEqual(
            result["source"]["snapshot_checksum"], canonical_snapshot_checksum(source)
        )
        self.contract.contractor_company.name = "Changed later"
        self.contract.contractor_company.save()
        self.assertEqual(self.export()["configuration"], source)
        from django.db.models import QuerySet

        legacy = {
            key: source[key]
            for key in (
                "snapshot_schema_version",
                "contract",
                "revision",
                "processing_profile",
                "orchestration_flow",
                "inputs",
                "indicators",
            )
        }
        legacy["snapshot_schema_version"] = "canonical-json-v1"
        QuerySet.update(
            domain.ContractConfigurationRevision.objects.filter(pk=self.revision.pk),
            configuration_snapshot=legacy,
            snapshot_checksum=canonical_snapshot_checksum(legacy),
            snapshot_schema_version="canonical-json-v1",
        )
        code = legacy["indicators"][0]["indicator_version"]["code"]
        historical = self.export(scope="indicator", indicator_version_code=code)
        self.assertEqual(
            historical["configuration"]["indicators"], legacy["indicators"]
        )
        self.assertTrue(
            any(
                issue["code"] == "legacy_indicator_scope_limit"
                for issue in historical["issues"]
            )
        )

    def test_incomplete_draft_graph_can_be_edited_but_not_approved(self):
        from rpsd_config.exchange_agreement.services.contract_revisions import (
            ContractRevisionError,
        )
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )
        from rpsd_config.exchange_agreement.services.validation_catalog import (
            get_validation_type_version,
        )

        self.revision.delete()
        dataset = domain.Dataset.objects.get(code="netex")
        spec = domain.DatasetSpecification.objects.create(
            dataset=dataset,
            code="netex-editable",
            version="editable",
            description="Draft input",
            format="xml",
        )
        identity = domain.ValidationRule.objects.create(
            code="draft-rule", name="Draft rule"
        )
        rule = domain.ValidationRuleVersion.objects.create(
            rule=identity,
            version="draft",
            name="Incomplete rule",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
        )
        identity = domain.Indicator.objects.create(
            code="editable", name="Editable", description="Editable draft indicator"
        )
        version = domain.IndicatorVersion.objects.create(
            indicator=identity,
            code="editable-1",
            version="1",
            description="Draft",
            formula_description="External implementation",
            parameter_schema={
                "schema_version": 2,
                "allow_extra": False,
                "required": ["lines"],
                "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
            },
        )
        domain.IndicatorVersionInput.objects.create(
            indicator_version=version, dataset_specification=spec
        )
        domain.IndicatorVersionRule.objects.create(
            indicator_version=version,
            dataset_specification=spec,
            rule_version=rule,
            impact="calculation",
        )
        flow = domain.InputFlowVersion.objects.create(
            dataset_specification=spec,
            code="editable-flow",
            version="1",
            name="Editable",
            description="No runtime yet",
            engine="prefect",
        )
        self.profile.indicator_version_links.all().delete()
        self.profile.input_flow_links.all().delete()
        domain.ProcessingProfileInputFlow.objects.create(
            processing_profile_version=self.profile,
            dataset=dataset,
            input_flow_version=flow,
        )
        domain.ProcessingProfileIndicatorVersion.objects.create(
            processing_profile_version=self.profile,
            indicator_version=version,
            proposed_by_default=True,
        )
        self.revision = create_revision_draft(
            self.contract, self.profile, timezone.localdate(), self.actor
        )
        first = self.export()
        codes = {i["code"] for i in first["issues"]}
        self.assertIn("invalid_indicator_parameters", codes)
        self.assertIn("incomplete_rule_definition", codes)
        count = domain.IndicatorVersion.objects.count()
        for lines in ([], ["2"], ["2", "3", "4"]):
            save_revision_indicator_values(
                self.revision,
                version_code=version.code,
                values={"parameters": {"lines": lines}, "aggregation": {}},
                actor=self.actor,
            )
        self.assertEqual(count, domain.IndicatorVersion.objects.count())
        with self.assertRaises(ValidationError):
            save_revision_indicator_values(
                self.revision,
                version_code=version.code,
                values={"parameters": {"lines": [42]}, "aggregation": {}},
                actor=self.actor,
            )
        self.assertNotEqual(first["content_digest"], self.export()["content_digest"])
        with self.assertRaises(ContractRevisionError):
            approve_revision(self.revision, self.actor)

    def test_contract_author_cannot_select_catalog_drafts_without_catalog_permission(
        self,
    ):
        from django.core.exceptions import PermissionDenied

        from rpsd_config.exchange_agreement.services import (
            contract_revision_permissions as revision_permissions,
        )

        user = get_user_model().objects.create_user(username="contract-only")
        domain.ContractMembership.objects.create(
            contract=self.contract, user=user, role="contract_admin"
        )
        self.assertTrue(
            revision_permissions.can_prepare_contract_revision(
                user=user, contract=self.contract
            )
        )
        with self.assertRaises(PermissionDenied):
            create_revision_draft(
                self.contract, self.profile, timezone.localdate(), user
            )
        export_contract_configuration(
            actor=user,
            contract_code=self.contract.contract_code,
            revision_code=self.revision.code,
        )

    def test_export_keeps_a_single_database_snapshot_during_concurrent_edit(self):
        from threading import Thread

        from django.db import connection, connections

        original = self.profile.name
        edited = []

        def edit():
            try:
                profile = domain.ProcessingProfileVersion.objects.get(
                    pk=self.profile.pk
                )
                profile.name = "Concurrent change"
                profile.save()
                edited.append(True)
            finally:
                connections.close_all()

        triggered = []

        def intercept(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if (
                not triggered
                and sql.startswith("SELECT")
                and '"exchange_agreement_contractconfigurationrevision"' in sql
            ):
                triggered.append(True)
                worker = Thread(target=edit)
                worker.start()
                worker.join(timeout=10)
                self.assertFalse(worker.is_alive())
            return result

        with connection.execute_wrapper(intercept):
            result = self.export()
        self.assertTrue(edited)
        self.assertEqual(
            result["configuration"]["processing_profile"]["name"], original
        )
        self.assertEqual(
            self.export()["configuration"]["processing_profile"]["name"],
            "Concurrent change",
        )

    def test_schema_cli_and_admin_read_saved_data_and_protect_external_links(self):
        import io
        import json
        from pathlib import Path

        from django.core.management import call_command

        from rpsd_config.exchange_agreement.services.draft_cleanup import (
            delete_draft,
            draft_deletion_plan,
        )

        output = io.StringIO()
        call_command(
            "export_contract_configuration",
            actor=self.actor.username,
            contract_code=self.contract.contract_code,
            revision_code=self.revision.code,
            stdout=output,
        )
        payload = json.loads(output.getvalue())
        schema = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "src/rpsd_config/exchange_agreement/contracts/"
                "contract-configuration-export-v1.schema.json"
            ).read_text()
        )
        self.assertEqual(set(payload), set(schema["required"]))
        self.assertEqual(
            set(payload["source"]), set(schema["properties"]["source"]["required"])
        )
        self.assertEqual(
            payload["schema_version"], schema["properties"]["schema_version"]["const"]
        )
        self.assertRegex(
            payload["content_digest"], schema["$defs"]["digest"]["pattern"]
        )
        self.assertEqual(payload["content_digest"], self.export()["content_digest"])
        own, blockers = draft_deletion_plan(self.profile, actor=self.actor)
        self.assertTrue(blockers)
        with self.assertRaises(ValidationError):
            delete_draft(self.profile, actor=self.actor)
        from rpsd_config.admin_dataset_exchange.proxies import (
            ProcessingProfileVersionAdminProxy,
        )

        delete_draft(self.revision, actor=self.actor)
        delete_draft(
            ProcessingProfileVersionAdminProxy.objects.get(pk=self.profile.pk),
            actor=self.actor,
        )
        self.assertFalse(
            domain.ProcessingProfileVersion.objects.filter(pk=self.profile.pk).exists()
        )
        self.assertTrue(domain.IndicatorVersion.objects.exists())
