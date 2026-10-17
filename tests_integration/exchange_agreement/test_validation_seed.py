# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Target seeding refuses semantic conflicts without changing published data."""

import csv
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from rpsd_config.exchange_agreement.models import (
    DatasetVersionRule,
    IndicatorVersionRule,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.csv_validation_seed import (
    ensure_csv_validation_demo,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.services.validation_seed import (
    ensure_validation_demo,
)


class ValidationSeedConflictTests(TestCase):
    def test_seed_rejects_different_published_definition_without_mutation(self):
        actor = get_user_model().objects.create_user(
            username="seed-conflict-admin", is_superuser=True, is_staff=True
        )
        rule = ValidationRule.objects.create(
            code="netex-demo-presence", name="Required netex entities"
        )
        version = ValidationRuleVersion.objects.create(
            rule=rule,
            version="001",
            name=rule.name,
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition="/*[not(//n:Different)]",
            options={"namespaces": {"n": "http://www.netex.org.uk/netex"}},
            execution_reference="validators/netex-demo",
        )
        transition_validation_rule(version, target_status="published", actor=actor)
        before = list(ValidationRuleVersion.objects.values())
        with self.assertRaisesMessage(ValidationError, "Seed conflict"):
            ensure_validation_demo(actor=actor)
        self.assertEqual(before, list(ValidationRuleVersion.objects.values()))
        self.assertEqual(ValidationRule.objects.count(), 1)

    def test_csv_seed_is_idempotent_and_declares_policies_and_dimension(self):
        actor = get_user_model().objects.create_user(
            username="csv-seed-admin", is_superuser=True, is_staff=True
        )
        profile = ensure_csv_validation_demo(actor=actor)
        before = list(ValidationRuleVersion.objects.values())
        self.assertEqual(ensure_csv_validation_demo(actor=actor).pk, profile.pk)
        self.assertEqual(before, list(ValidationRuleVersion.objects.values()))
        self.assertEqual(profile.status, "published")
        bindings = {
            binding.rule_version.rule.code: binding
            for binding in DatasetVersionRule.objects.select_related(
                "rule_version__rule"
            )
        }
        self.assertEqual(
            {code: binding.failure_policy for code, binding in bindings.items()},
            {
                "demo-csv-identity": "reject_import",
                "demo-csv-timestamp": "warn",
            },
        )
        indicator_binding = IndicatorVersionRule.objects.get()
        self.assertEqual(indicator_binding.impact, "dimension")
        self.assertEqual(
            list(indicator_binding.affected_dimensions.values_list("code", flat=True)),
            ["line"],
        )
        self.assertEqual(indicator_binding.rule_version.rule.code, "demo-csv-line")
        bindings["demo-csv-line"] = indicator_binding
        # Check fixture/config consistency, without executing an external validator.
        fixtures = Path(__file__).parent / "fixtures"
        for case, missing in (
            ("valid", set()),
            ("missing_identity", {"demo-csv-identity"}),
            ("missing_timestamp", {"demo-csv-timestamp"}),
            ("missing_line", {"demo-csv-line"}),
        ):
            with self.subTest(case=case):
                with (fixtures / f"validation_csv_{case}.csv").open() as stream:
                    header = next(csv.reader(stream, delimiter=";"))
                absent = {
                    code
                    for code, binding in bindings.items()
                    if not set(json.loads(binding.rule_version.definition)["columns"])
                    <= set(header)
                }
                self.assertEqual(absent, missing)
