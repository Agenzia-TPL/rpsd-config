# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Verify RenameField preserves JSON and calculation provenance (021)."""

import json

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from rpsd_config.exchange_agreement.models import Indicator, IndicatorVersion


class IndicatorSchemaMigrationTests(TransactionTestCase):
    def test_rename_preserves_existing_json_and_artifact(self):
        logical = Indicator.objects.create(
            code="rename", name="Rename", description="Historical indicator"
        )
        version = IndicatorVersion.objects.create(
            indicator=logical,
            code="rename_001",
            version="001",
            description="Original",
            formula_description="Count",
            artifact_identifier="git:flows@original",
            execution_engine="prefect",
            execution_reference="indicators/default",
        )
        input_schema = {"format": "json", "fields": [{"name": "journey"}]}
        output_schema = {"format": "json", "fields": [{"name": "count"}]}
        # Populate a historical fixture independently of today's schema validator.
        table = connection.ops.quote_name(IndicatorVersion._meta.db_table)
        executor = MigrationExecutor(connection)
        state = executor.loader.project_state(
            [
                ("exchange_agreement", "0042_validation_catalog_proxies"),
                (
                    "admin_dataset_exchange",
                    "0009_delete_indicatordefadminproxy_and_more",
                ),
            ]
        )
        migration = executor.loader.get_migration(
            "exchange_agreement", "0043_indicator_schema_names"
        )
        schema = connection.ops.quote_name("test_indicator_schema_021")
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('search_path')")
            original_path = cursor.fetchone()[0]
            cursor.execute(f"CREATE SCHEMA {schema}")
            cursor.execute(f"CREATE TABLE {schema}.{table} AS SELECT * FROM {table}")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"ALTER TABLE {schema}.{table} DROP COLUMN parameter_schema"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.{table} "
                    "RENAME input_schema TO input_contract"
                )
                cursor.execute(
                    f"ALTER TABLE {schema}.{table} "
                    "RENAME output_schema TO output_contract"
                )

                cursor.execute(
                    f"UPDATE {schema}.{table} SET input_contract = %s::jsonb, "
                    "output_contract = %s::jsonb WHERE id = %s",
                    [json.dumps(input_schema), json.dumps(output_schema), version.pk],
                )
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)",
                    [f"{schema}, {original_path}"],
                )
            with connection.schema_editor() as editor:
                new_state = migration.apply(state, editor)
            model = new_state.apps.get_model("exchange_agreement", "IndicatorVersion")
            migrated = model.objects.get(pk=version.pk)
            self.assertEqual(migrated.input_schema, input_schema)
            self.assertEqual(migrated.output_schema, output_schema)
            self.assertEqual(migrated.parameter_schema, {})
            self.assertEqual(migrated.artifact_identifier, "git:flows@original")
        finally:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('search_path', %s, false)", [original_path]
                )
                cursor.execute(f"DROP SCHEMA {schema} CASCADE")
