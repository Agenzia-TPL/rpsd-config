# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""The packaged pilot is offline, draft-only and shares exact schema bundles."""

import io
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from rpsd_config.exchange_agreement import models
from rpsd_config.exchange_agreement.services.catalog_contract import load_package
from rpsd_config.exchange_agreement.services.formal_definitions import (
    verification_state,
)
from rpsd_config.exchange_agreement.services.netex_profile_seed import (
    ensure_netex_italian_profile,
)
from rpsd_config.exchange_agreement.services.siri_profile_seed import (
    ensure_siri_schema_asset,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    ensure_validation_type_catalog,
)


class ToolsCatalogSeedTests(TestCase):
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
            username="tools-seed-admin", is_superuser=True, is_staff=True
        )
        ensure_validation_type_catalog()
        self.legacy = ensure_netex_italian_profile(actor=self.actor)
        self.siri = ensure_siri_schema_asset(actor=self.actor)

    def test_packaged_pilot_previews_applies_and_reuses_without_runtime_or_contracts(
        self,
    ):
        before = list(models.DatasetSpecification.objects.values())
        before_rules = models.ValidationRuleVersion.objects.count()
        before_bindings = models.DatasetVersionRule.objects.count()
        output = io.StringIO()
        call_command("seed_tools_catalog", actor=self.actor.username, stdout=output)
        self.assertFalse(models.IndicatorVersion.objects.exists())
        self.assertEqual(list(models.DatasetSpecification.objects.values()), before)
        call_command(
            "seed_tools_catalog", actor=self.actor.username, apply=True, stdout=output
        )
        counts = (
            models.IndicatorVersion.objects.count(),
            models.ValidationRuleVersion.objects.count(),
            models.ConfigurationAsset.objects.count(),
        )
        self.assertEqual(counts[0], 14)
        self.assertEqual(counts[1] - before_rules, 67)
        self.assertEqual(
            models.DatasetVersionRule.objects.count() - before_bindings, 57
        )
        self.assertEqual(models.IndicatorVersionRule.objects.count(), 111)
        python_rule = models.ValidationRuleVersion.objects.get(
            validation_type_version__validation_type="python"
        )
        self.assertEqual(python_rule.language_version, "0.3.0")
        self.assertEqual(python_rule.options, {"python_version": "3.13"})
        self.assertEqual(python_rule.version, "1")
        self.assertEqual(
            models.ValidationRuleVersion.objects.filter(version="2").count(), 5
        )
        line_rules = models.IndicatorVersionRule.objects.filter(impact="dimension")
        self.assertEqual(line_rules.count(), 3)
        self.assertEqual(
            set(line_rules.values_list("affected_dimensions__code", flat=True)),
            {"linea"},
        )
        self.assertFalse(
            models.IndicatorVersion.objects.exclude(status="draft").exists()
        )
        fid = models.IndicatorVersion.objects.get(indicator__formula_symbol="FID")
        self.assertEqual(fid.definition_kind, "composite")
        self.assertEqual(fid.formula_value_kind, "number")
        self.assertEqual(verification_state(fid), "current")
        self.assertFalse(fid.formal_verification["limitations"])
        self.assertEqual(
            set(
                fid.dependency_links.values_list(
                    "prerequisite__indicator__formula_symbol", flat=True
                )
            ),
            {"CORSE_CONF", "CORSE_PDE", "CORSE_PS"},
        )
        confirmed = models.IndicatorVersion.objects.get(
            indicator__formula_symbol="CORSE_CONF"
        )
        self.assertEqual(confirmed.formula_value_kind, "set")
        self.assertFalse(
            confirmed.dependency_links.filter(
                prerequisite__indicator__formula_symbol="CORSE_PDE"
            ).exists()
        )
        self.assertIn("CORSE_PDE", confirmed.formal_verification["context_bindings"])
        self.assertEqual(verification_state(confirmed), "current")
        for code in ("siri-pt_v004", "siri-et_v004"):
            spec = models.DatasetSpecification.objects.get(code=code)
            self.assertEqual(
                spec.asset_links.get().configuration_asset_id, self.siri.pk
            )
            self.assertEqual(
                spec.rule_bindings.count(), 12 if spec.dataset.code == "siri-pt" else 18
            )
        call_command(
            "seed_tools_catalog", actor=self.actor.username, apply=True, stdout=output
        )
        self.assertEqual(
            counts,
            (
                models.IndicatorVersion.objects.count(),
                models.ValidationRuleVersion.objects.count(),
                models.ConfigurationAsset.objects.count(),
            ),
        )
        self.assertEqual(
            models.DatasetSpecification.objects.filter(pk=self.legacy.pk)
            .values()
            .get(),
            before[0],
        )
        self.assertFalse(models.ProcessingProfileVersion.objects.exists())
        self.assertFalse(models.Contract.objects.exists())

    def test_packaged_schema_matches_the_validated_contract(self):
        import json

        from rpsd_config.exchange_agreement.services.catalog_contract import (
            CatalogPackage,
        )

        directory = (
            Path(__file__).resolve().parents[2] / "src/rpsd_config/exchange_agreement"
        )
        package = load_package((directory / "seed_data/tools/catalog.json").read_text())
        self.assertEqual(len(package.selection.exclusions), 0)
        schema = json.loads(
            (directory / "contracts/config-catalog-import-v2.schema.json").read_text()
        )
        for key in ("$schema", "$id"):
            schema.pop(key)
        self.assertEqual(schema, CatalogPackage.model_json_schema())
