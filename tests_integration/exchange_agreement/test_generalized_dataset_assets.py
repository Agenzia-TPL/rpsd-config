# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Generalized asset identity, storage, frozen composition, UI and seed (030)."""

import hashlib
import importlib
import io
import json
import tempfile
import zipfile
from pathlib import Path
from threading import Barrier, Thread
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    activate_configuration_asset,
    archive_configuration_asset,
    load_configuration_asset_content,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.dataset_asset_seed import (
    ensure_dataset_asset_examples,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.schema_bundles import (
    validate_bundle_rule_asset,
)
from tests_integration.exchange_agreement.test_contract_configuration_revisions import (
    _ContractRevisionFixtureMixin,
)


class GeneralizedDatasetAssetTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        overrides = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=self.directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.actor = get_user_model().objects.create_user(
            username="generic-asset-admin",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(self.actor)
        self.page = reverse("exchange_agreement:platform-configuration")
        self.spec = DatasetSpecification.objects.create(
            format="xml",
            dataset=Dataset.objects.create(code="netex", name="NeTEx"),
            code="netex_generic_001",
            version="001",
        )

    def upload(
        self,
        *,
        code="independent-code",
        asset_type="document",
        name="manuale.pdf",
        content=b"example",
        **kwargs,
    ):
        return store_configuration_asset(
            uploaded_file=SimpleUploadedFile(name, content),
            asset_type=asset_type,
            what=code,
            uploaded_by=self.actor,
            **kwargs,
        ).asset

    @staticmethod
    def bundle():
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr(
                "schema.xsd", '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'
            )
        return content.getvalue()

    def link(self, asset, **kwargs):
        return DatasetSpecificationAsset.objects.create(
            dataset_specification=self.spec,
            configuration_asset=asset,
            role="validation_schema",
            required=False,
            **kwargs,
        )

    def test_named_files_and_formats_have_independent_identity(self):
        cases = [
            ("document", "manuale.pdf", b"pdf"),
            ("other", "colonne.csv", b"id,type"),
            ("other", "config.xlsx", b"opaque"),
            ("other", "README", b"text"),
            ("json_schema", "schema.json", b'{"type":"object"}'),
            ("xsd_schema", "lev5.xsd", b"<schema/>"),
            ("netex_xsd", "nome-libero.xsd", b"<schema/>"),
        ]
        for index, (asset_type, name, content) in enumerate(cases):
            asset = self.upload(
                code=f"resource-{index}",
                asset_type=asset_type,
                name=name,
                content=content,
            )
            self.assertEqual(asset.what, f"resource-{index}")
            self.assertEqual(load_configuration_asset_content(asset), content)
            self.assertEqual(asset.checksum_sha256, hashlib.sha256(content).hexdigest())
            self.link(asset)

    def test_same_asset_can_be_shared_by_different_dataset_versions(self):
        asset = self.upload()
        self.link(asset)
        second = DatasetSpecification.objects.create(
            format="xml",
            dataset=Dataset.objects.create(code="csv-demo", name="CSV"),
            code="csv-demo_001",
            version="001",
        )
        DatasetSpecificationAsset.objects.create(
            dataset_specification=second,
            configuration_asset=asset,
            role="documentation",
            required=False,
        )
        self.assertEqual(asset.dataset_specification_links.count(), 2)

    def test_generic_zip_is_not_inspected_as_xsd(self):
        asset = self.upload(
            asset_type="archive", name="files.zip", content=b"opaque ZIP"
        )
        self.assertEqual(asset.bundle_manifest, {})
        self.assertEqual(load_configuration_asset_content(asset), b"opaque ZIP")
        with self.assertRaises(ValidationError):
            self.upload(
                asset_type="xsd_bundle", name="files.zip", content=b"opaque ZIP"
            )

    def test_bad_identity_json_or_empty_file_never_contacts_storage(self):
        for kwargs in (
            {"code": ""},
            {"code": "../unsafe"},
            {"name": "unsafe\\name"},
            {"content": b""},
            {"asset_type": "json_schema", "name": "x.json", "content": b"{"},
        ):
            with patch(
                "rpsd_config.exchange_agreement.services.configuration_assets._storage_provider"
            ) as provider:
                with self.assertRaises(ValidationError):
                    self.upload(**kwargs)
                provider.assert_not_called()

    def test_metadata_of_every_file_is_immutable(self):
        asset = self.upload()
        for field, value in (
            ("what", "changed"),
            ("original_filename", "new.pdf"),
            ("checksum_sha256", "a" * 64),
            ("content_type", "new/type"),
        ):
            setattr(asset, field, value)
            with self.assertRaises(ValidationError), transaction.atomic():
                asset.save()
            asset.refresh_from_db()
            with self.assertRaises(ValidationError):
                ConfigurationAsset.objects.filter(pk=asset.pk).update(**{field: value})
        with self.assertRaises(ValidationError):
            ConfigurationAsset.objects.bulk_update([asset], ["what"])
        with self.assertRaises(ValidationError):
            ConfigurationAsset.objects.bulk_create([asset])
        asset.label = "New label"
        asset.save()

    def test_published_links_are_frozen_and_cannot_move_or_bulk_write(self):
        link = self.link(self.upload())
        publish_dataset_specification(self.spec, actor=self.actor)
        with self.assertRaises(ValidationError), transaction.atomic():
            link.delete()
        with self.assertRaises(ValidationError), transaction.atomic():
            self.spec.asset_links.all().delete()
        with self.assertRaises(ValidationError):
            self.spec.asset_links.update(required=True)
        with self.assertRaises(ValidationError):
            DatasetSpecificationAsset.objects.bulk_create([link])
        second = DatasetSpecification.objects.create(
            format="xml",
            dataset=self.spec.dataset,
            code="netex_generic_002",
            version="002",
        )
        link.dataset_specification = second
        with self.assertRaises(ValidationError), transaction.atomic():
            link.save()

    def test_activation_preserves_exact_association_and_historic_download(self):
        old = self.upload(activate=True)
        link = self.link(old)
        publish_dataset_specification(self.spec, actor=self.actor)
        new = self.upload(content=b"second", activate=True)
        old.refresh_from_db()
        self.assertEqual(new.version, old.version + 1)
        self.assertFalse(old.is_active)
        self.assertEqual(self.spec.asset_links.get().pk, link.pk)
        self.assertEqual(load_configuration_asset_content(old), b"example")
        archive_configuration_asset(asset=new)
        activate_configuration_asset(asset=old, actor=self.actor)
        self.assertEqual(ConfigurationAsset.objects.filter(is_active=True).count(), 1)

    def test_xsd_bundle_binding_uses_code_and_rejects_ambiguity(self):
        content = self.bundle()
        asset = self.upload(
            asset_type="xsd_bundle", name="italian-lev5.zip", content=content
        )
        self.link(asset)
        rule = SimpleNamespace(
            definition=json.dumps(
                {
                    "asset_code": asset.what,
                    "asset_version": str(asset.version),
                    "entrypoint": "schema.xsd",
                    "bundle_sha256": asset.checksum_sha256,
                }
            )
        )
        validate_bundle_rule_asset(self.spec, rule)
        second = self.upload(
            asset_type="netex_xsd", name="other-name.zip", content=content
        )
        self.link(second)
        with self.assertRaises(ValidationError) as error:
            validate_bundle_rule_asset(self.spec, rule)
        self.assertEqual(error.exception.code, "ambiguous_asset")

    def test_storage_rollback_cleans_only_attempted_object(self):
        old = self.upload()
        before = set(Path(self.directory.name).rglob("*"))
        with patch(
            "rpsd_config.exchange_agreement.services.configuration_assets.create_asset_event",
            side_effect=ValidationError("Intentional write failure"),
        ):
            with self.assertRaises(ValidationError):
                self.upload(content=b"new")
        self.assertEqual(ConfigurationAsset.objects.count(), 1)
        self.assertEqual(load_configuration_asset_content(old), b"example")
        self.assertFalse(
            [
                p
                for p in set(Path(self.directory.name).rglob("*")) - before
                if p.is_file()
            ]
        )

    def test_broker_failure_is_recorded_without_losing_upload(self):
        with (
            override_settings(CONFIG_ASSETS_RABBITMQ_ENABLED=True),
            patch(
                "rpsd_transport.get_carrier",
                side_effect=RuntimeError("Unavailable broker"),
            ),
        ):
            asset = self.upload()
        self.assertEqual(asset.publish_status, "failed")
        self.assertEqual(asset.events.count(), 1)
        self.assertEqual(load_configuration_asset_content(asset), b"example")

    def test_admin_upload_guidance_and_readonly_metadata(self):
        add = reverse("admin:admin_dataset_exchange_configurationassetadminproxy_add")
        response = self.client.get(add)
        self.assertContains(response, "Codice asset")
        self.assertNotContains(response, 'name="storage_url"')
        response = self.client.post(
            add,
            {
                "asset_type": "other",
                "what": "admin-file",
                "uploaded_file": SimpleUploadedFile("data.txt", b"text"),
                "label": "Example",
            },
        )
        self.assertEqual(response.status_code, 302)
        asset = ConfigurationAsset.objects.get(what="admin-file")
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        for field in ("what", "storage_url", "checksum_sha256", "status"):
            self.assertNotIn(field, response.context["adminform"].form.fields)
        self.assertContains(response, "Carica una nuova versione")
        self.assertEqual(asset.uploaded_by, self.actor)

    def test_admin_invalid_bundle_stays_on_form(self):
        response = self.client.post(
            reverse("admin:admin_dataset_exchange_configurationassetadminproxy_add"),
            {
                "asset_type": "xsd_bundle",
                "what": "invalid",
                "uploaded_file": SimpleUploadedFile("bad.zip", b"bad"),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ConfigurationAsset.objects.exists())

    def test_admin_service_errors_are_nonfield_errors_without_metadata_editor(self):
        with patch(
            "rpsd_config.admin_dataset_exchange.admin.store_configuration_asset",
            side_effect=ValidationError({"storage_provider": ["Storage unavailable"]}),
        ):
            response = self.client.post(
                reverse(
                    "admin:admin_dataset_exchange_configurationassetadminproxy_add"
                ),
                {
                    "asset_type": "other",
                    "what": "preserved-code",
                    "uploaded_file": SimpleUploadedFile("data.txt", b"text"),
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Storage unavailable")
        self.assertContains(response, 'value="preserved-code"')
        self.assertFalse(ConfigurationAsset.objects.exists())

    def test_web_upload_download_details_filters_and_draft_selection(self):
        response = self.client.post(
            self.page,
            {
                "tab": "asset",
                "action": "upload-config-asset",
                "asset_type": "other",
                "what": "web-columns",
                "uploaded_file": SimpleUploadedFile("columns.csv", b"id,type"),
            },
        )
        self.assertContains(response, "Asset tecnico caricato.")
        asset = ConfigurationAsset.objects.get(what="web-columns")
        response = self.client.get(self.page + "?tab=asset&asset_code=web-columns")
        self.assertContains(response, "columns.csv")
        download = self.client.get(
            reverse("exchange_agreement:configuration-asset-download", args=[asset.pk])
        )
        self.assertEqual(b"".join(download.streaming_content), b"id,type")
        detail = reverse(
            "exchange_agreement:technical-catalog-detail",
            args=["dataset-specifications", self.spec.pk],
        )
        self.assertContains(self.client.get(detail), "web-columns")
        response = self.client.post(
            detail,
            {"action": "add-asset", "asset_id": asset.pk, "role": "documentation"},
        )
        self.assertIn(response.status_code, [200, 302])
        self.assertEqual(self.spec.asset_links.get().configuration_asset, asset)

    def test_web_invalid_upload_preserves_identity_and_permissions(self):
        response = self.client.post(
            self.page,
            {
                "tab": "asset",
                "action": "upload-config-asset",
                "asset_type": "xsd_bundle",
                "what": "keep-code",
                "label": "Keep label",
                "uploaded_file": SimpleUploadedFile("invalid.zip", b"bad"),
            },
        )
        self.assertContains(response, 'value="keep-code"')
        self.assertContains(response, 'value="Keep label"')
        user = get_user_model().objects.create_user(username="not-platform")
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.page + "?tab=asset").status_code, 403)
        self.assertEqual(
            self.client.post(
                self.page, {"tab": "asset", "action": "upload-config-asset"}
            ).status_code,
            403,
        )

    @override_settings(VALIDATION_M2M_ALLOWED_CLIENT_IDS="test-validator")
    def test_generic_download_api_has_same_pinned_identity_and_integrity_contract(self):
        asset = self.upload(code="docs-ref")
        path = (
            "/exchange_agreement/api/m2m/v3/validation-assets/document/docs-ref/"
            f"{asset.version}/download"
        )
        with (
            patch(
                "rpsd_config.exchange_agreement.api.M2MClientTokenAuth.authenticate",
                return_value=None,
            ),
            patch(
                "rpsd_config.exchange_agreement.api.validate_m2m_token",
                return_value={"azp": "test-validator"},
            ),
        ):
            response = self.client.get(path, HTTP_AUTHORIZATION="Bearer test")
            self.assertEqual(response.content, b"example")
            self.assertEqual(response.status_code, 200)
            with patch(
                "rpsd_config.exchange_agreement.api.load_configuration_asset_content",
                side_effect=ValidationError("Corrupt"),
            ):
                self.assertEqual(
                    self.client.get(path, HTTP_AUTHORIZATION="Bearer test").status_code,
                    409,
                )
            self.assertEqual(
                self.client.get(
                    path.replace("docs-ref", "missing"),
                    HTTP_AUTHORIZATION="Bearer test",
                ).status_code,
                404,
            )

    def test_seed_is_idempotent_shared_and_reports_content_conflicts(self):
        first = ensure_dataset_asset_examples(actor=self.actor)
        paths = {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        second = ensure_dataset_asset_examples(actor=self.actor)
        self.assertEqual([a.pk for a in first], [a.pk for a in second])
        self.assertEqual(
            paths, {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        )
        for asset in first:
            self.assertEqual(asset.dataset_specification_links.count(), 2)
        self.upload(code="demo-colonne", asset_type="other", name="changed.txt")
        with self.assertRaises(ValidationError):
            ensure_dataset_asset_examples(actor=self.actor)

    def test_netex_profile_seed_loads_pinned_assets_without_duplicates(self):
        import json

        from rpsd_config.exchange_agreement.models import ValidationRuleVersion
        from rpsd_config.exchange_agreement.services.netex_profile_seed import (
            ensure_netex_italian_profile,
        )

        spec = ensure_netex_italian_profile(actor=self.actor)
        links = list(spec.asset_links.select_related("configuration_asset"))
        self.assertEqual(len(links), 3)
        schema = next(link for link in links if link.role == "validation_schema")
        self.assertTrue(schema.required)
        self.assertTrue(schema.configuration_asset.is_active)
        self.assertEqual(len(schema.configuration_asset.bundle_manifest["files"]), 8)
        self.assertTrue(all(not link.required for link in links if link != schema))
        self.assertEqual(spec.status, "draft")
        self.assertEqual(spec.rule_bindings.count(), 0)
        rule = ValidationRuleVersion.objects.get(rule__code="netex-it-lev5-xsd")
        self.assertEqual(rule.status, "draft")
        self.assertEqual(rule.execution_reference, "")
        self.assertEqual(
            json.loads(rule.definition)["bundle_sha256"],
            schema.configuration_asset.checksum_sha256,
        )
        paths = {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        repeated = ensure_netex_italian_profile(actor=self.actor)
        self.assertEqual(repeated.pk, spec.pk)
        self.assertEqual(
            list(repeated.asset_links.values_list("pk", flat=True)),
            [link.pk for link in links],
        )
        self.assertEqual(
            paths, {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        )
        self.upload(
            code="netex-it-guidelines", asset_type="document", name="changed.txt"
        )
        with self.assertRaises(ValidationError):
            ensure_netex_italian_profile(actor=self.actor)

    def test_siri_seed_shares_bundle_and_preserves_published_versions(self):
        from rpsd_config.exchange_agreement.services.dataset_catalog import (
            publish_dataset_specification,
        )
        from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
            INITIAL_DATASET_SPECIFICATIONS,
        )
        from rpsd_config.exchange_agreement.services.siri_profile_seed import (
            ensure_siri_italian_profile,
        )

        originals = []
        for initial in INITIAL_DATASET_SPECIFICATIONS:
            if not initial.dataset_code.startswith("siri-"):
                continue
            dataset = Dataset.objects.create(
                code=initial.dataset_code, name=initial.dataset_name
            )
            spec = DatasetSpecification.objects.create(
                dataset=dataset,
                code=initial.specification_code,
                version=initial.version,
                format="xml",
            )
            originals.append(publish_dataset_specification(spec, actor=self.actor))
        result = ensure_siri_italian_profile(actor=self.actor)
        self.assertEqual(len(result), 10)
        self.assertTrue(all(s.code.endswith("_v002") for s in result))
        schema_ids = set()
        for spec in result:
            schema = spec.asset_links.get(role="validation_schema")
            schema_ids.add(schema.configuration_asset_id)
            self.assertTrue(schema.required)
            self.assertEqual(spec.status, "draft")
            self.assertEqual(spec.format, "xml")
            self.assertEqual(spec.metadata["standard_version"], "2.1")
            self.assertEqual(
                len(schema.configuration_asset.bundle_manifest["files"]), 73
            )
            self.assertEqual(spec.asset_links.filter(role="documentation").count(), 1)
        self.assertEqual(len(schema_ids), 1)
        self.assertEqual(ConfigurationAsset.objects.count(), 7)
        self.assertEqual(
            sum(spec.asset_links.filter(role="example").count() for spec in result), 5
        )
        for spec in originals:
            spec.refresh_from_db()
            self.assertEqual(spec.status, "published")
            self.assertEqual(spec.asset_links.count(), 0)
        paths = {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        repeated = ensure_siri_italian_profile(actor=self.actor)
        self.assertEqual([s.pk for s in repeated], [s.pk for s in result])
        self.assertEqual(ConfigurationAsset.objects.count(), 7)
        self.assertEqual(
            paths, {p for p in Path(self.directory.name).rglob("*") if p.is_file()}
        )
        self.upload(code="siri-2-1-schema", asset_type="other", name="changed.txt")
        with self.assertRaises(ValidationError):
            ensure_siri_italian_profile(actor=self.actor)

    def test_siri_seed_fresh_catalog_keeps_same_versions_after_publication(self):
        from rpsd_config.exchange_agreement.services.dataset_catalog import (
            publish_dataset_specification,
        )
        from rpsd_config.exchange_agreement.services.siri_profile_seed import (
            ensure_siri_italian_profile,
        )

        result = ensure_siri_italian_profile(actor=self.actor)
        self.assertTrue(all(s.code.endswith("_v001") for s in result))
        publish_dataset_specification(result[0], actor=self.actor)
        repeated = ensure_siri_italian_profile(actor=self.actor)
        self.assertEqual([s.pk for s in result], [s.pk for s in repeated])

    def test_migration_audit_rejects_invalid_existing_code(self):
        asset = self.upload()
        migration = importlib.import_module(
            "rpsd_config.exchange_agreement.migrations.0049_generalize_configuration_assets"
        )
        from django.apps import apps

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE exchange_agreement_configurationasset "
                "SET what = '' WHERE id = %s",
                [asset.pk],
            )
        with self.assertRaises(RuntimeError):
            migration.audit_asset_codes(apps, SimpleNamespace(connection=connection))


class ConcurrentAssetUploadTests(TransactionTestCase):
    def test_first_uploads_allocate_distinct_versions_and_one_active_object(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            override_settings(
                CONFIG_ASSETS_STORAGE_PROVIDER="fs",
                CONFIG_ASSETS_STORAGE_FS_BASE_PATH=directory,
                CONFIG_ASSETS_RABBITMQ_ENABLED=False,
            ),
        ):
            barrier = Barrier(2)
            publication_barrier = Barrier(2)
            results = []
            errors = []

            def upload(index):
                close_old_connections()
                try:
                    barrier.wait(timeout=10)
                    asset = store_configuration_asset(
                        uploaded_file=SimpleUploadedFile(
                            "config.txt", str(index).encode()
                        ),
                        asset_type="other",
                        what="concurrent",
                        activate=True,
                    ).asset
                    results.append((asset.pk, asset.version, asset.storage_url))
                except Exception as exc:
                    errors.append(exc)
                finally:
                    close_old_connections()

            def delayed_publication(event):
                publication_barrier.wait(timeout=10)
                return event

            with patch(
                "rpsd_config.exchange_agreement.services.configuration_assets.publish_asset_event",
                side_effect=delayed_publication,
            ):
                threads = [Thread(target=upload, args=[index]) for index in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=20)
                    self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual({row[1] for row in results}, {1, 2})
            self.assertEqual(len({row[2] for row in results}), 2)
            self.assertEqual(
                ConfigurationAsset.objects.filter(is_active=True).count(), 1
            )
            for asset in ConfigurationAsset.objects.all():
                self.assertIn(load_configuration_asset_content(asset), [b"0", b"1"])


class GeneralizedAssetMigrationTests(
    _ContractRevisionFixtureMixin, TransactionTestCase
):
    def test_upgrade_from_029_preserves_asset_identity_and_frozen_snapshot(self):
        revision = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        before = revision.configuration_snapshot
        checksum = revision.snapshot_checksum
        asset = self.netex_asset
        values = ConfigurationAsset.objects.filter(pk=asset.pk).values().get()
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state(
            [
                ("exchange_agreement", "0048_contract_revision_indicators"),
                ("admin_agreements", "0008_delete_contractindicatoradminproxy"),
            ]
        )
        migration = executor.loader.get_migration(
            "exchange_agreement", "0049_generalize_configuration_assets"
        )
        quote = connection.ops.quote_name
        schema = quote("test_generalized_asset_030")
        table = quote(ConfigurationAsset._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('search_path')")
            original_path = cursor.fetchone()[0]
            cursor.execute(f"CREATE SCHEMA {schema}")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE {schema}.{table} AS SELECT * FROM {table}"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.{table} ADD CONSTRAINT "
                    "config_asset_supported_dataset_type CHECK "
                    "(asset_type IN ('netex_xsd', 'siri_profile'))"
                )
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)",
                    [f"{schema}, {original_path}"],
                )
            with connection.schema_editor() as editor:
                migrated_state = migration.apply(state, editor)
            model = migrated_state.apps.get_model(
                "exchange_agreement", "ConfigurationAsset"
            )
            self.assertEqual(model.objects.filter(pk=asset.pk).values().get(), values)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)", [original_path]
                )
                cursor.execute(f"DROP SCHEMA {schema} CASCADE")
        activate_configuration_asset(asset=asset, actor=self.user)
        revision.refresh_from_db()
        self.assertEqual(revision.configuration_snapshot, before)
        self.assertEqual(revision.snapshot_checksum, checksum)


class GenericAssetSnapshotTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        overrides = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=self.directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        overrides.enable()
        self.addCleanup(overrides.disable)

        def publish_with_generic_resource(specification, *, actor):
            if specification.dataset.code == "netex":
                self.resource = store_configuration_asset(
                    uploaded_file=SimpleUploadedFile("istruzioni.csv", b"id,type"),
                    asset_type="other",
                    what="independent-columns",
                    uploaded_by=actor,
                ).asset
                DatasetSpecificationAsset.objects.create(
                    dataset_specification=specification,
                    configuration_asset=self.resource,
                    role="documentation",
                    required=False,
                )
            return publish_dataset_specification(specification, actor=actor)

        with patch(
            "tests_integration.exchange_agreement.test_contract_configuration_revisions.publish_dataset_specification",
            side_effect=publish_with_generic_resource,
        ):
            super().setUp()

    def test_generic_identity_is_frozen_in_snapshot_and_survives_new_activation(self):
        revision = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        before = revision.configuration_snapshot
        checksum = revision.snapshot_checksum
        asset = next(
            asset
            for item in before["inputs"]
            for asset in item["assets"]
            if asset["code"] == "independent-columns"
        )
        self.assertEqual(asset["asset_type"], "other")
        self.assertEqual(asset["version"], self.resource.version)
        self.assertIn("/other/independent-columns/", asset["download_path"])
        store_configuration_asset(
            uploaded_file=SimpleUploadedFile("nuove-istruzioni.csv", b"id,type,new"),
            asset_type="other",
            what="independent-columns",
            activate=True,
        )
        revision.refresh_from_db()
        self.assertEqual(revision.configuration_snapshot, before)
        self.assertEqual(revision.snapshot_checksum, checksum)
        self.assertEqual(load_configuration_asset_content(self.resource), b"id,type")
