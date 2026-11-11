# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Independent documentary catalog, lifecycle and offline repeatable seed."""

import io
import json

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement import models
from rpsd_config.exchange_agreement.services.validation_catalog import (
    ensure_validation_type_catalog,
    get_validation_type_version,
    transition_validation_rule,
    validation_execution_manifest,
)
from rpsd_config.exchange_agreement.validation_forms import ValidationRuleVersionForm


class DbtContextCatalogTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="dbt-admin", is_staff=True, is_superuser=True
        )
        ensure_validation_type_catalog()

    def seed(self, **kwargs):
        output = io.StringIO()
        call_command(
            "seed_tools_catalog",
            actor=self.actor.username,
            dbt_contexts_only=True,
            stdout=output,
            **kwargs,
        )
        return json.loads(output.getvalue())

    def test_seed_is_independent_read_only_then_idempotent(self):
        models.ValidationTypeVersion.objects.filter(validation_type="dbt").delete()
        preview = self.seed()
        self.assertFalse(preview["applied"])
        self.assertFalse(models.ValidationRuleVersion.objects.exists())
        self.assertFalse(LogEntry.objects.exists())
        self.assertFalse(
            models.ValidationTypeVersion.objects.filter(validation_type="dbt").exists()
        )
        result = self.seed(apply=True)
        self.assertTrue(result["applied"])
        self.assertEqual(models.ValidationRuleVersion.objects.count(), 11)
        self.assertFalse(
            models.ValidationRuleVersion.objects.exclude(status="draft").exists()
        )
        self.assertFalse(models.IndicatorVersion.objects.exists())
        self.assertFalse(models.DatasetSpecification.objects.exists())
        self.assertFalse(models.DatasetVersionRule.objects.exists())
        self.assertFalse(models.IndicatorVersionRule.objects.exists())
        self.assertFalse(models.ProcessingProfileVersion.objects.exists())
        self.assertEqual(self.seed(apply=True)["counts"], {"reuse": 22})

    def test_publication_is_documentary_and_immutable(self):
        self.seed(apply=True)
        v = models.ValidationRuleVersion.objects.get(rule__code="siri-pt-covers-pde")
        document = json.loads(v.definition)
        self.assertEqual(document["requirement"]["kind"], "coverage")
        self.assertIn("Cancellation=true", document["rule"]["description"])
        self.assertEqual(document["relations"][0]["code"], "SIRI_PT_DVJ_TO_SJ")
        v = transition_validation_rule(v, target_status="published", actor=self.actor)
        self.assertFalse(v.execution_reference)
        self.assertEqual(v.status_events.count(), 1)
        self.assertEqual(validation_execution_manifest()["rules"], [])
        v.description = "Changed"
        with self.assertRaises(ValidationError):
            v.save()

    def test_binding_checks_cannot_use_a_document_as_a_validator(self):
        self.seed(apply=True)
        v = models.ValidationRuleVersion.objects.first()
        dataset = models.Dataset.objects.create(
            code="context-test", name="Context test"
        )
        spec = models.DatasetSpecification.objects.create(
            dataset=dataset,
            code="context-test_001",
            version="001",
            description="Only a test",
            format="xml",
        )
        with self.assertRaises(ValidationError):
            models.DatasetVersionRule.objects.create(
                dataset_specification=spec,
                rule_version=v,
                failure_policy="warn",
                created_by=self.actor,
            )
        indicator = models.Indicator.objects.create(
            code="context-indicator",
            name="Context indicator",
            description="Test",
            formula_symbol="CTX",
        )
        owner = models.IndicatorVersion.objects.create(
            indicator=indicator,
            code="context-indicator_001",
            version="001",
            description="Test",
            formula_description="Test",
            definition_kind="base",
            formula_language_version="rpsd-formula-v1",
        )
        with self.assertRaises(ValidationError):
            models.IndicatorVersionRule.objects.bulk_create(
                [
                    models.IndicatorVersionRule(
                        indicator_version=owner,
                        dataset_specification=spec,
                        rule_version=v,
                        impact="calculation",
                    )
                ]
            )
        self.assertFalse(models.IndicatorVersionRule.objects.exists())

    def test_form_does_not_request_execution_metadata(self):
        self.seed(apply=True)
        v = models.ValidationRuleVersion.objects.first()
        form = ValidationRuleVersionForm(instance=v)
        for field in ("options", "result_contract", "execution_reference"):
            self.assertTrue(form.fields[field].disabled)
        self.assertIn("non genera", form.fields["definition"].help_text)
        pair = get_validation_type_version("dbt", "1")
        self.assertEqual(pair.validation_type, "dbt")

    def test_context_is_editable_in_admin_without_execution_metadata(self):
        self.seed(apply=True)
        self.client.force_login(self.actor)
        source = models.ValidationRuleVersion.objects.first()
        path = reverse(
            "admin:admin_dataset_exchange_validationruleversionadminproxy_add"
        )
        response = self.client.post(
            path,
            {
                "rule": str(source.rule_id),
                "version": "manual-002",
                "name": "Document",
                "description": "Requisito documentale",
                "validation_type_version": str(source.validation_type_version_id),
                "definition": source.definition,
                "options": "{}",
                "result_contract": "violating_entities",
                "execution_reference": "not-an-execution-reference",
                "_save": "Salva",
            },
        )
        self.assertEqual(response.status_code, 302, response.content)
        created = models.ValidationRuleVersion.objects.get(
            rule=source.rule, version="manual-002"
        )
        self.assertEqual(created.result_contract, "structured_report")
        self.assertFalse(created.execution_reference)
        response = self.client.get(
            reverse(
                "admin:admin_dataset_exchange_validationruleversionadminproxy_change",
                args=[created.pk],
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "execution_reference", response.context["adminform"].form.fields
        )
        self.assertContains(response, "Contesto documentale dbt")

    def test_conflict_does_not_rewrite_or_partially_apply_catalog(self):
        self.seed(apply=True)
        version = models.ValidationRuleVersion.objects.first()
        version.description = "Revisione locale da preservare"
        version.save()
        entries = LogEntry.objects.count()
        with self.assertRaises(CommandError):
            self.seed(apply=True)
        self.assertEqual(LogEntry.objects.count(), entries)
        version.refresh_from_db()
        self.assertEqual(version.description, "Revisione locale da preservare")
