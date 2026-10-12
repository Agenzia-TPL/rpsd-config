# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Exercise the 029 migration on historical tables in an isolated schema."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from rpsd_config.exchange_agreement.models import ContractRevisionIndicator
from tests_integration.exchange_agreement.test_contract_configuration_revisions import (
    _ContractRevisionFixtureMixin,
)


class RevisionIndicatorMigrationTests(
    _ContractRevisionFixtureMixin, TransactionTestCase
):
    def test_audit_and_rename_preserve_selection_and_frozen_snapshot(self):
        revision = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        before = revision.configuration_snapshot
        checksum = revision.snapshot_checksum
        selection = revision.indicator_configurations.get()
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state(
            [
                (
                    "exchange_agreement",
                    "0047_remove_indicatorprofile_configuration_asset_and_more",
                ),
                ("admin_agreements", "0008_delete_contractindicatoradminproxy"),
            ]
        )
        migration = executor.loader.get_migration(
            "exchange_agreement", "0048_contract_revision_indicators"
        )
        old = state.apps.get_model(
            "exchange_agreement", "ContractIndicatorConfiguration"
        )
        link = state.apps.get_model("exchange_agreement", "ContractIndicator")
        quote = connection.ops.quote_name
        schema = quote("test_revision_indicator_029")
        old_table = quote(old._meta.db_table)
        link_table = quote(link._meta.db_table)
        new_table = quote(ContractRevisionIndicator._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('search_path')")
            original_path = cursor.fetchone()[0]
            cursor.execute(f"CREATE SCHEMA {schema}")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE TABLE {schema}.{old_table} AS SELECT * FROM {new_table}"
                )
                cursor.execute(
                    f"CREATE TABLE {schema}.{link_table} "
                    "(id bigint PRIMARY KEY, contract_id bigint, "
                    "logical_indicator_id bigint)"
                )
                cursor.execute(
                    f"INSERT INTO {schema}.{link_table} VALUES (1, %s, %s)",
                    [revision.contract_id, self.logical_indicator.pk],
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.{old_table} "
                    "ADD COLUMN contract_indicator_id "
                    "bigint NOT NULL DEFAULT 1"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.{old_table} ADD CONSTRAINT "
                    "unique_revision_contract_indicator "
                    "UNIQUE (revision_id, contract_indicator_id)"
                )
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)",
                    [f"{schema}, {original_path}"],
                )
                cursor.execute(f"UPDATE {link_table} SET contract_id = 0")
            audit = migration.operations[0].code
            with self.assertRaisesMessage(RuntimeError, "audit failed"):
                audit(state.apps, connection.schema_editor())
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {link_table} SET contract_id = %s", [revision.contract_id]
                )
            with connection.schema_editor() as editor:
                migrated_state = migration.apply(state, editor)
            model = migrated_state.apps.get_model(
                "exchange_agreement", "ContractRevisionIndicator"
            )
            migrated = model.objects.get(pk=selection.pk)
            self.assertEqual(migrated.revision_id, revision.pk)
            self.assertEqual(
                migrated.processing_profile_indicator_version_id,
                selection.processing_profile_indicator_version_id,
            )
            for name in ("parameters", "thresholds", "aggregation", "penalties"):
                self.assertEqual(getattr(migrated, name), getattr(selection, name))
            self.assertNotIn("contract_indicator", {f.name for f in model._meta.fields})
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)", [original_path]
                )
                cursor.execute(f"DROP SCHEMA {schema} CASCADE")
        revision.refresh_from_db()
        self.assertEqual(revision.configuration_snapshot, before)
        self.assertEqual(revision.snapshot_checksum, checksum)
