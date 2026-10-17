# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Rule lifecycle, immutable bulk writes and authorization on an isolated test DB."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from rpsd_config.exchange_agreement.models import ValidationRule, ValidationRuleVersion
from rpsd_config.exchange_agreement.services.validation_catalog import (
    delete_validation_rule_version,
    get_validation_type_version,
    save_validation_rule,
    save_validation_rule_version,
    transition_validation_rule,
    validation_execution_manifest,
)


class ValidationCatalogTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="rule-admin", is_superuser=True
        )
        self.editor = get_user_model().objects.create_user(username="rule-editor")
        self.rule = ValidationRule.objects.create(
            code="daytype-reference", name="DayType reference"
        )
        self.version = ValidationRuleVersion(
            rule=self.rule,
            version="001",
            name="DayType reference",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition="//n:DayTypeRef[not(@ref = //n:DayType/@id)]",
            options={"namespaces": {"n": "http://www.netex.org.uk/netex"}},
            execution_reference="validators/netex-default",
        )
        save_validation_rule_version(self.version, actor=self.admin)

    def publish(self):
        self.version = transition_validation_rule(
            self.version, target_status="published", actor=self.admin
        )

    def test_transition_audit_and_manifest(self):
        self.publish()
        self.assertEqual(self.version.status_events.count(), 1)
        report = validation_execution_manifest()
        self.assertEqual(report["rules"][0]["rule_code"], self.rule.code)
        self.assertNotIn("id", report["rules"][0])
        transition_validation_rule(
            self.version,
            target_status="deprecated",
            actor=self.admin,
            reason="New version",
        )
        self.assertEqual(validation_execution_manifest()["rules"], [])
        self.assertEqual(self.version.status_events.count(), 2)

    def test_editor_is_denied(self):
        with self.assertRaises(PermissionDenied):
            transition_validation_rule(
                self.version, target_status="published", actor=self.editor
            )
        self.assertFalse(self.version.status_events.exists())

    def test_incomplete_publication_is_atomic(self):
        self.version.execution_reference = ""
        self.version.save()
        with self.assertRaises(ValidationError):
            self.publish()
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "draft")
        self.assertFalse(self.version.status_events.exists())

    def test_published_versions_cannot_mutate_or_delete(self):
        self.publish()
        self.version.definition = "//n:Line"
        with self.assertRaises(ValidationError):
            self.version.save()
        with self.assertRaises(ValidationError):
            ValidationRuleVersion.objects.filter(pk=self.version.pk).update(
                definition="unsafe"
            )
        with self.assertRaises(ValidationError):
            ValidationRuleVersion.objects.filter(pk=self.version.pk).delete()
        with self.assertRaises(ValidationError):
            self.version.delete()
        event = self.version.status_events.get()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_new_versions_and_duplicate_identity(self):
        self.version.pk = None
        self.version._state.adding = True
        self.version.version = "002"
        self.version.save()
        self.assertEqual(self.rule.versions.count(), 2)
        self.version.pk = None
        with self.assertRaises(ValidationError):
            self.version.save()

    def test_draft_bulk_create_is_not_a_validation_bypass(self):
        with self.assertRaises(ValidationError):
            ValidationRuleVersion.objects.bulk_create([self.version])
        self.version.delete()
        self.assertFalse(ValidationRuleVersion.objects.exists())

    def test_stable_identity_cannot_be_renamed(self):
        self.rule.code = "changed"
        with self.assertRaises(ValidationError):
            self.rule.save()
        with self.assertRaises(ValidationError):
            ValidationRule.objects.filter(pk=self.rule.pk).update(code="changed")
        with self.assertRaises(ValidationError):
            ValidationRule.objects.bulk_update([self.rule], ["code"])
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.code, "daytype-reference")

    def test_initial_publication_metadata_cannot_be_forged(self):
        self.version.pk = None
        self.version.version = "002"
        self.version.published_by = self.admin
        with self.assertRaises(ValidationError):
            self.version.save()
        self.assertEqual(self.rule.versions.count(), 1)

    def test_stale_draft_cannot_overwrite_publication(self):
        stale = ValidationRuleVersion.objects.get(pk=self.version.pk)
        self.publish()
        stale.definition = "//n:Line"
        with self.assertRaises(ValidationError):
            stale.save()
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")
        self.assertIn("DayTypeRef", self.version.definition)

    def test_audit_and_lifecycle_are_protected(self):
        self.publish()
        with self.assertRaises(ValidationError):
            self.version.status_events.update(reason="tampered")
        with self.assertRaises(ValidationError):
            self.version.status_events.all().delete()
        with self.assertRaises(ValidationError):
            transition_validation_rule(
                self.version, target_status="deprecated", actor=self.admin
            )
        self.assertEqual(self.version.status_events.count(), 1)
        transition_validation_rule(
            self.version, target_status="withdrawn", actor=self.admin, reason="Retired"
        )
        with self.assertRaises(ValidationError):
            transition_validation_rule(
                self.version, target_status="published", actor=self.admin
            )

    def test_manifest_command_is_deterministic(self):
        import json
        from io import StringIO

        from django.core.management import call_command

        self.publish()
        first, second = StringIO(), StringIO()
        call_command("validation_execution_manifest", stdout=first)
        call_command("validation_execution_manifest", stdout=second)
        self.assertEqual(first.getvalue(), second.getvalue())
        self.assertEqual(json.loads(first.getvalue()), validation_execution_manifest())

    def test_catalog_services_deny_all_editor_writes(self):
        self.version.definition = "//n:Line"
        with self.assertRaises(PermissionDenied):
            save_validation_rule_version(self.version, actor=self.editor)
        with self.assertRaises(PermissionDenied):
            save_validation_rule_version(self.version, actor=None)
        with self.assertRaises(PermissionDenied):
            save_validation_rule(self.rule, actor=self.editor)
        with self.assertRaises(PermissionDenied):
            delete_validation_rule_version(self.version, actor=self.editor)
        self.version.refresh_from_db()
        self.assertIn("DayTypeRef", self.version.definition)

    def test_authorized_draft_deletion_and_frozen_bulk_update(self):
        from django.db.models.deletion import ProtectedError

        self.publish()
        with self.assertRaises(ProtectedError):
            self.rule.delete()
        with self.assertRaises(ValidationError):
            ValidationRuleVersion.objects.bulk_update([self.version], ["definition"])
        with self.assertRaises(ValidationError):
            delete_validation_rule_version(self.version, actor=self.admin)
        draft = ValidationRuleVersion.objects.create(
            rule=self.rule,
            version="002",
            name="Incomplete draft",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
        )
        delete_validation_rule_version(draft, actor=self.admin)
        self.assertEqual(self.rule.versions.count(), 1)
