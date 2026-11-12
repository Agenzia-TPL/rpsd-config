# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Independent seeds, exact ownership, shared reuse and development retirement."""

import json
from copy import deepcopy

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from rpsd_config.exchange_agreement import models
from rpsd_config.exchange_agreement.services.catalog_contract import (
    analyze_package,
    package_payload,
    seal_package,
)
from rpsd_config.exchange_agreement.services.catalog_import import (
    CatalogImportError,
    apply_catalog,
)
from rpsd_config.exchange_agreement.services.seed_cleanup import (
    cleanup_seed,
    inventory_seed,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    ensure_validation_type_catalog,
    transition_validation_rule,
)


def scenario_package(name):
    payload = {
        "sources": [],
        "selection": {"roots": []},
        "dimensions": [],
        "indicator_versions": [],
        "dependencies": [],
        "analysis": {},
        "dataset_bindings": [
            {
                "source_dataset": code,
                "source_schema": "schema-1",
                "dataset_code": code,
                "dataset_name": code,
                "code": code + "-" + name,
                "version": name,
                "create": True,
                "format": "xml",
            }
            for code in ("shared", "only-" + name)
        ],
        "rule_versions": [
            {
                "code": "shared-check",
                "version": "1",
                "name": "Shared check",
                "description": "Identifier required",
                "validation_type": "xpath",
                "language_version": "1.0",
                "definition": "//*[not(@id)]",
            }
        ],
        "rule_sources": [
            {"rule_code": "shared-check", "rule_version": "1", "origin": "config"}
        ],
        "dataset_rules": [
            {
                "specification": "shared-" + name,
                "rule_code": "shared-check",
                "rule_version": "1",
                "failure_policy": "warn",
            }
        ],
    }
    first = seal_package(payload)
    return seal_package({**package_payload(first), "analysis": analyze_package(first)})


class ToolsSeedScenariosTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="scenario-admin", is_staff=True, is_superuser=True
        )
        ensure_validation_type_catalog()
        self.package = scenario_package("a")

    def test_inventory_closes_manually_added_owned_bindings(self):
        original = apply_catalog(self.package, actor=self.actor)
        child = models.DatasetVersionRule.objects.create(
            dataset_specification=models.DatasetSpecification.objects.get(
                code="only-a-a"
            ),
            rule_version=models.ValidationRuleVersion.objects.get(),
            failure_policy="warn",
            created_by=self.actor,
        )
        self.assertTrue(cleanup_seed(original, actor=self.actor)["preserved_shared"])
        fresh = inventory_seed(
            [self.package.package_digest], actor=self.actor, scenario="complete-a"
        )
        owned = next(
            row
            for row in fresh["created"]
            if row["model"] == "exchange_agreement.datasetversionrule"
            and row["pk"] == child.pk
        )
        self.assertIn("owned_by", owned)
        cleanup_seed(fresh, actor=self.actor, apply=True)
        self.assertFalse(models.DatasetVersionRule.objects.exists())
        self.assertFalse(models.DatasetSpecification.objects.exists())

    def test_published_python_rule_is_readable_in_native_admin(self):
        rule = models.ValidationRule.objects.create(code="python-manual", name="Python")
        version = models.ValidationRuleVersion.objects.create(
            rule=rule,
            version="1",
            name="Python",
            description="Registered function",
            validation_type_version=models.ValidationTypeVersion.objects.get(
                validation_type="python", language_version="0.3.0"
            ),
            definition=json.dumps(
                {
                    "function": "netex_passing_times_increasing",
                    "paths": ["//netex:ServiceJourney"],
                    "namespaces": {"netex": "http://www.netex.org.uk/netex"},
                    "definition_sha256": "a" * 64,
                }
            ),
            options={"python_version": "3.13"},
        )
        transition_validation_rule(version, target_status="published", actor=self.actor)
        self.client.force_login(self.actor)
        response = self.client.get(
            reverse(
                "admin:admin_dataset_exchange_validationruleversionadminproxy_change",
                args=[version.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "netex_passing_times_increasing")

    def test_repeat_preserves_initial_ownership_and_second_seed_coexists(self):
        first = apply_catalog(self.package, actor=self.actor, scenario="a")
        repeat = apply_catalog(
            self.package, actor=self.actor, scenario="a", previous_manifest=first
        )
        self.assertEqual(first["created"], repeat["created"])
        self.assertEqual(repeat["created_this_run"], 0)
        second = apply_catalog(scenario_package("b"), actor=self.actor, scenario="b")
        self.assertTrue(second["reused"])
        self.assertEqual(models.DatasetSpecification.objects.count(), 4)
        self.assertEqual(models.ValidationRuleVersion.objects.count(), 1)
        before_b = models.DatasetSpecification.objects.filter(
            code__in=["shared-b", "only-b-b"]
        ).count()
        plan = cleanup_seed(repeat, actor=self.actor)
        self.assertFalse(plan["applied"])
        self.assertTrue(plan["preserved_shared"])
        cleanup_seed(repeat, actor=self.actor, apply=True)
        self.assertFalse(
            models.DatasetSpecification.objects.filter(code="shared-a").exists()
        )
        self.assertEqual(
            models.DatasetSpecification.objects.filter(
                code__in=["shared-b", "only-b-b"]
            ).count(),
            before_b,
        )
        self.assertTrue(models.Dataset.objects.filter(code="shared").exists())
        self.assertTrue(
            models.ValidationRuleVersion.objects.filter(
                rule__code="shared-check"
            ).exists()
        )
        # B never owned the shared rule, so removing B must not appropriate it.
        cleanup_seed(second, actor=self.actor, apply=True)
        self.assertTrue(
            models.ValidationRuleVersion.objects.filter(
                rule__code="shared-check"
            ).exists()
        )

    def test_conflict_is_atomic_and_operator_changes_block_stale_manifest(self):
        report = apply_catalog(self.package, actor=self.actor)
        rule = models.ValidationRuleVersion.objects.get()
        rule.description = "Operator revision"
        rule.save()
        before = models.DatasetSpecification.objects.count(), LogEntry.objects.count()
        with self.assertRaises(CatalogImportError):
            apply_catalog(self.package, actor=self.actor)
        self.assertEqual(
            before,
            (models.DatasetSpecification.objects.count(), LogEntry.objects.count()),
        )
        with self.assertRaisesMessage(ValidationError, "modificato"):
            cleanup_seed(report, actor=self.actor, apply=True)
        self.assertTrue(models.DatasetSpecification.objects.exists())

    @override_settings(DEBUG=True)
    def test_retirement_preserves_full_audit_and_keeps_ordinary_delete_frozen(self):
        apply_catalog(self.package, actor=self.actor)
        rule = transition_validation_rule(
            models.ValidationRuleVersion.objects.get(),
            target_status="published",
            actor=self.actor,
        )
        event = rule.status_events.get()
        event_pk = event.pk
        with self.assertRaises(ValidationError):
            rule.delete()
        manifest = inventory_seed(
            [self.package.package_digest], actor=self.actor, scenario="retire"
        )
        plan = cleanup_seed(manifest, actor=self.actor)
        self.assertTrue(plan["blockers"])
        with self.assertRaises(ValidationError):
            cleanup_seed(
                manifest,
                actor=self.actor,
                apply=True,
                retire_published=True,
                confirm_database="wrong",
            )
        plan = cleanup_seed(manifest, actor=self.actor, retire_published=True)
        self.assertTrue(plan["audit_events_transferred"])
        cleanup_seed(
            manifest,
            actor=self.actor,
            apply=True,
            retire_published=True,
            confirm_database=connection.settings_dict["NAME"],
        )
        self.assertFalse(models.ValidationRuleVersion.objects.exists())
        saved = LogEntry.objects.get(change_message__contains='"retired_status_event"')
        archived = json.loads(saved.change_message)["retired_status_event"]
        self.assertEqual(archived["pk"], event_pk)
        self.assertEqual(archived["fields"]["rule_version_id"], rule.pk)
        self.assertEqual(archived["fields"]["to_status"], "published")
        self.assertEqual(archived["fields"]["changed_by_id"], self.actor.pk)

    @override_settings(DEBUG=False)
    def test_production_retirement_and_unauthorized_cleanup_are_denied(self):
        report = apply_catalog(self.package, actor=self.actor)
        with self.assertRaises(ValidationError):
            cleanup_seed(report, actor=self.actor, retire_published=True)
        ordinary = get_user_model().objects.create_user(username="ordinary")
        with self.assertRaises(PermissionDenied):
            cleanup_seed(report, actor=ordinary)
        bad = deepcopy(report)
        bad["created"][0]["model"] = "auth.user"
        with self.assertRaises(ValidationError):
            cleanup_seed(bad, actor=self.actor, apply=True)
        self.assertTrue(models.DatasetSpecification.objects.exists())
