# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Real offline pilot: draft seed, handoff, conflicts and safe cleanup."""

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings

from rpsd_config.exchange_agreement import models as domain
from rpsd_config.exchange_agreement.services.configuration_exports import (
    ConfigurationExportError,
    export_contract_configuration,
)
from rpsd_config.exchange_agreement.services.configuration_handoff import (
    write_configuration_handoff,
)
from rpsd_config.exchange_agreement.services.contract_demo import seed_contract_demo
from rpsd_config.exchange_agreement.services.draft_cleanup import cleanup_demo
from rpsd_config.exchange_agreement.services.netex_profile_seed import (
    ensure_netex_italian_profile,
)
from rpsd_config.exchange_agreement.services.siri_profile_seed import (
    ensure_siri_schema_asset,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    ensure_validation_type_catalog,
)


class ContractDemoTests(TransactionTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        settings = override_settings(
            CONFIG_ASSETS_STORAGE_PROVIDER="fs",
            CONFIG_ASSETS_STORAGE_FS_BASE_PATH=directory.name,
            CONFIG_ASSETS_RABBITMQ_ENABLED=False,
        )
        settings.enable()
        self.addCleanup(settings.disable)
        self.actor = get_user_model().objects.create_user(
            username="demo-author", is_superuser=True, is_staff=True
        )
        ensure_validation_type_catalog()
        ensure_netex_italian_profile(actor=self.actor)
        ensure_siri_schema_asset(actor=self.actor)

    def seed(self, **kwargs):
        return seed_contract_demo(namespace="trial", actor=self.actor, **kwargs)

    def test_offline_seed_reuses_exports_and_cleans_its_own_drafts(self):
        before = list(domain.DatasetSpecification.objects.values())
        assets = list(domain.ConfigurationAsset.objects.values())
        plan = self.seed()
        self.assertFalse(plan["applied"])
        self.assertEqual(before, list(domain.DatasetSpecification.objects.values()))
        self.assertFalse(domain.IndicatorVersion.objects.exists())
        report = self.seed(apply=True)
        counts = (
            domain.IndicatorVersion.objects.count(),
            domain.ValidationRuleVersion.objects.count(),
        )
        repeat = self.seed(apply=True, previous_manifest=report)
        self.assertEqual(
            counts,
            (
                domain.IndicatorVersion.objects.count(),
                domain.ValidationRuleVersion.objects.count(),
            ),
        )
        self.assertEqual(len(report["created"]), len(repeat["created"]))
        self.assertFalse(
            domain.IndicatorVersion.objects.exclude(status="draft").exists()
        )
        scenario = report["scenario"]
        payload = export_contract_configuration(
            actor=self.actor,
            contract_code=scenario["contract_code"],
            revision_code=scenario["revision_code"],
        )
        cfg = payload["configuration"]
        self.assertEqual(len(cfg["effective_indicators"]), 6)
        self.assertEqual(
            {i["dataset_code"]: len(i["rule_bindings"]) for i in cfg["inputs"]},
            {"netex": 27, "siri-et": 18},
        )
        self.assertEqual(len(cfg["validation_rules"]), 45)
        handoff = write_configuration_handoff(
            actor=self.actor,
            **{k: scenario[k] for k in ("contract_code", "revision_code")},
            directory=self.directory / "handoff",
            include_assets=True,
            seed_manifest=report,
        )
        self.assertTrue(handoff["complete"], handoff)
        self.assertEqual(len(handoff["files"]), 4)
        self.assertEqual(len(handoff["assets"]), 2)
        from rpsd_config.exchange_agreement.services.draft_cleanup import delete_draft
        from rpsd_config.exchange_agreement.services.formal_definitions import (
            verify_definition,
        )

        source = domain.IndicatorVersion.objects.get(code="trial-corse-pde-tools_004")
        identity = domain.Indicator.objects.create(
            code="outside",
            name="Outside",
            description="Outside context",
            formula_symbol="OUT",
        )
        outside = domain.IndicatorVersion.objects.create(
            indicator=identity,
            code="outside-1",
            version="1",
            description="Formal context only",
            formula_description="External base",
            definition_kind="base",
            formula_language_version="rpsd-formula-v1",
            consistency_checks="OUT = CORSE_PDE",
        )
        for link in source.dimension_links.all():
            domain.IndicatorVersionDimension.objects.create(
                indicator_version=outside,
                dimension=link.dimension,
                allowed_values=link.allowed_values,
                is_carried=link.is_carried,
                is_monitoring=link.is_monitoring,
                is_contractual=link.is_contractual,
            )
        verify_definition(
            outside, actor=self.actor, context_bindings={"CORSE_PDE": source.code}
        )
        self.assertTrue(
            any(
                "Contesto formale" in b
                for b in cleanup_demo(repeat, actor=self.actor)["blockers"]
            )
        )
        with self.assertRaises(ValidationError):
            cleanup_demo(repeat, actor=self.actor, apply=True)
        delete_draft(outside, actor=self.actor)
        identity.delete()
        cleanup = cleanup_demo(repeat, actor=self.actor)
        self.assertFalse(cleanup["blockers"], cleanup)
        cleanup_demo(repeat, actor=self.actor, apply=True)
        self.assertFalse(domain.Contract.objects.exists())
        self.assertFalse(domain.IndicatorVersion.objects.exists())
        self.assertEqual(before, list(domain.DatasetSpecification.objects.values()))
        self.assertEqual(assets, list(domain.ConfigurationAsset.objects.values()))

    def test_operator_changes_prevent_overwrite_or_cleanup(
        self,
    ):
        report = self.seed(apply=True)
        fid = domain.IndicatorVersion.objects.get(code="trial-fid-tools_004")
        fid.description += " revised"
        fid.save()
        with self.assertRaises(ValidationError):
            self.seed(apply=True)
        with self.assertRaises(ValidationError):
            cleanup_demo(report, actor=self.actor, apply=True)
        fid.refresh_from_db()
        self.assertTrue(fid.description.endswith(" revised"))
        rule = domain.ValidationRuleVersion.objects.get(
            rule__code="tools-netex-day-type-assigned", version="trial-1"
        )
        rule.description += " revised rule"
        rule.save()
        with self.assertRaisesMessage(ConfigurationExportError, "regole sono cambiate"):
            write_configuration_handoff(
                actor=self.actor,
                contract_code=report["scenario"]["contract_code"],
                revision_code=report["scenario"]["revision_code"],
                directory=self.directory / "stale-provenance",
                seed_manifest=report,
            )
