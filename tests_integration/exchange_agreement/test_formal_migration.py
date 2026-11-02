# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""The additive migration preserves published definitions from the baseline."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class FormalMigrationTests(TransactionTestCase):
    def test_legacy_published_version_gets_no_invented_formula_or_evidence(self):
        previous = (
            "exchange_agreement",
            "0056_indicatorpenalty_penalty_positive_period_days_and_more",
        )
        target = ("exchange_agreement", "0057_formal_indicator_definitions")
        executor = MigrationExecutor(connection)
        executor.migrate([previous])
        try:
            apps = executor.loader.project_state([previous]).apps
            identity = apps.get_model("exchange_agreement", "Indicator").objects.create(
                code="legacy-indicator", name="Legacy", description="Existing identity"
            )
            item = apps.get_model(
                "exchange_agreement", "IndicatorVersion"
            ).objects.create(
                indicator=identity,
                code="legacy-indicator_001",
                version="001",
                description="Existing definition",
                formula_description="Existing prose",
                status="published",
                execution_engine="prefect",
                execution_reference="indicators/legacy",
                artifact_identifier="git:calculations@legacy",
            )
            executor = MigrationExecutor(connection)
            executor.migrate([target])
            apps = executor.loader.project_state([target]).apps
            migrated = apps.get_model(
                "exchange_agreement", "IndicatorVersion"
            ).objects.get(pk=item.pk)
            self.assertEqual(migrated.status, "published")
            self.assertEqual(migrated.formula_description, "Existing prose")
            self.assertEqual(migrated.definition_kind, "")
            self.assertEqual(migrated.formal_verification, {})
            self.assertIsNone(
                apps.get_model("exchange_agreement", "Indicator")
                .objects.get(pk=identity.pk)
                .formula_symbol
            )
            self.assertFalse(
                apps.get_model(
                    "exchange_agreement", "IndicatorVersionDimension"
                ).objects.exists()
            )
        finally:
            MigrationExecutor(connection).migrate([target])
