# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Apply 0040 in an isolated PostgreSQL schema alongside existing legacy data."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from rpsd_config.exchange_agreement.models import Dataset


class ValidationCatalogMigrationTests(TransactionTestCase):
    def test_additive_catalog_migration_preserves_existing_dataset(self):
        # Apply exactly 0040 without reversing unrelated historical migrations.
        # Existing tables are visible through the original search_path; new
        # catalog tables are created in a disposable schema in the test DB.
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state(
            [
                ("exchange_agreement", "0039_remove_flow_protocol_json"),
                (
                    "admin_dataset_exchange",
                    "0009_delete_indicatordefadminproxy_and_more",
                ),
            ]
        )
        migration = executor.loader.get_migration(
            "exchange_agreement", "0040_validation_rule_catalog"
        )
        dataset = Dataset.objects.create(
            code="legacy-preserved", name="Legacy", description="Original metadata"
        )
        schema = "test_validation_019"
        quoted_schema = connection.ops.quote_name(schema)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('search_path')")
            original_path = cursor.fetchone()[0]
            cursor.execute(f"CREATE SCHEMA {quoted_schema}")
            cursor.execute(
                "SELECT set_config('search_path', %s, false)",
                [f"{quoted_schema}, {original_path}"],
            )
        try:
            with connection.schema_editor() as editor:
                new_state = migration.apply(state, editor)
            versions = new_state.apps.get_model(
                "exchange_agreement", "ValidationRuleVersion"
            )
            self.assertEqual(versions.objects.count(), 0)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = %s",
                    [schema],
                )
                self.assertEqual(cursor.fetchone()[0], 3)
            preserved = Dataset.objects.get(pk=dataset.pk)
            self.assertEqual(preserved.code, "legacy-preserved")
            self.assertEqual(preserved.description, "Original metadata")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)", [original_path]
                )
                cursor.execute(f"DROP SCHEMA {quoted_schema} CASCADE")
