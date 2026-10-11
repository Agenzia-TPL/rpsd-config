# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Fresh schema and bootstrap use only versioned target validation structures."""

from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement.models import ContractConfigurationRevision
from rpsd_config.exchange_agreement.technical_catalog_views import CATALOGS


class TargetSchemaCutoverTests(TestCase):
    def test_retired_tables_models_editors_and_commands_are_absent(self):
        retired = {
            "requirementfragment",
            "fragmentvalidationrule",
            "requirementfragmentstatusevent",
            "legacyvalidationrulemapping",
        }
        self.assertFalse(
            retired & {model._meta.model_name for model in apps.get_models()}
        )
        self.assertFalse(
            {"exchange_agreement_" + name for name in retired}
            & set(connection.introspection.table_names())
        )
        self.assertNotIn(
            "required_fragments",
            {
                field.name
                for field in apps.get_model(
                    "exchange_agreement", "IndicatorVersion"
                )._meta.get_fields()
            },
        )
        self.assertNotIn("fragments", CATALOGS)
        self.assertNotIn("migrate_validation_catalog", get_commands())
        self.assertFalse(
            retired & {model._meta.model_name for model in admin.site._registry}
        )

    @override_settings(DEBUG=False)
    def test_demo_seed_refuses_production_before_creating_users_or_catalogs(self):
        with self.assertRaisesMessage(CommandError, "DEBUG=True"):
            call_command("seed_target_demo")
        self.assertEqual(get_user_model().objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_demo_has_composed_indicator_and_independent_contract_values(self):
        call_command("seed_target_demo", verbosity=0)
        first = ContractConfigurationRevision.objects.get(
            contract__contract_code="DEMO-CONTRACT-001"
        )
        before = (
            first.configuration_snapshot,
            first.snapshot_checksum,
            first.approved_at,
        )
        call_command("seed_target_demo", verbosity=0)
        first.refresh_from_db()
        self.assertEqual(
            before,
            (first.configuration_snapshot, first.snapshot_checksum, first.approved_at),
        )
        self.assertEqual(first.snapshot_schema_version, "canonical-json-v2")
        self.assertEqual(first.processing_profile_version.code, "validation-demo_001")
        configs = {
            c["indicator_version_code"]: c
            for c in first.configuration_snapshot["indicator_configurations"]
        }
        self.assertEqual(
            configs["demo-composed-performance_001"]["parameters"],
            {"sample_window_minutes": 15},
        )
        self.assertEqual(
            configs["demo-journey-count_001"]["parameters"], {"minimum_journeys": 1}
        )
        self.assertEqual(first.dependency_configurations.count(), 1)
