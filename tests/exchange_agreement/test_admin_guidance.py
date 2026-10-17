# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Check the complete registered presentation surface without database access."""

from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase

from rpsd_config.admin_examples import (
    CORSE_BUNDLE_MANIFEST,
    JSON_EXAMPLES,
    PARAMETER_SCHEMA,
    RULE_EXAMPLES,
    example_block,
)
from rpsd_config.admin_guidance import GuidedAdminMixin, GuidedInlineMixin
from rpsd_config.exchange_agreement.field_guidance import field_guide
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
    validate_parameter_schema,
)
from rpsd_config.exchange_agreement.services.revision_registry import (
    validate_business_configuration,
)
from rpsd_config.exchange_agreement.services.schema_bundles import (
    validate_bundle_manifest,
)
from rpsd_config.exchange_agreement.services.validation_registry import (
    CAPABILITIES,
    validate_rule_definition,
)

CONFIG_APPS = {
    "admin_dataset_exchange",
    "admin_audit",
    "admin_agreements",
    "admin_stakeholders",
    "admin_service_net",
}


class AdminGuidanceInventoryTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/admin/")
        self.request.user = get_user_model()(
            is_superuser=True, is_staff=True, is_active=True
        )

    def test_every_registered_field_inline_and_display_has_explicit_guidance(self):
        for model, model_admin in admin.site._registry.items():
            if model._meta.app_label not in CONFIG_APPS:
                continue
            self.assertIsInstance(model_admin, GuidedAdminMixin)
            for editor in (
                model_admin,
                *model_admin.get_inline_instances(self.request),
            ):
                names = flatten_fieldsets(editor.get_fieldsets(self.request))
                names += [
                    name
                    for name in getattr(editor, "list_display", ())
                    if name != "__str__"
                ]
                for name in names:
                    with self.subTest(model=editor.model.__name__, field=name):
                        info = field_guide(editor.model, name)
                        self.assertIsNotNone(info)
                        self.assertTrue(info.label)
                        self.assertGreater(len(str(info.help)), len(str(info.label)))
                if editor is not model_admin:
                    self.assertIsInstance(editor, GuidedInlineMixin)
                form = (
                    editor.get_form(self.request)
                    if editor is model_admin
                    else editor.get_formset(self.request).form
                )
                for name in flatten_fieldsets(editor.get_fieldsets(self.request)):
                    with self.subTest(
                        model=editor.model.__name__, field=name, mode="Meta"
                    ):
                        self.assertIn(name, form._meta.labels)
                        self.assertIn(name, form._meta.help_texts)

    def test_all_registry_types_have_locally_valid_examples(self):
        self.assertEqual(
            {example["validation_type"] for example in RULE_EXAMPLES}, set(CAPABILITIES)
        )
        for example in RULE_EXAMPLES:
            with self.subTest(type=example["validation_type"]):
                validate_rule_definition(**example)

    def test_parameter_and_business_examples_use_existing_contracts(self):
        validate_parameter_schema(PARAMETER_SCHEMA)
        validate_indicator_parameters(PARAMETER_SCHEMA, JSON_EXAMPLES["parameters"])
        for name in ("thresholds", "aggregation", "penalties"):
            validate_business_configuration(JSON_EXAMPLES[name], field_name=name)
        validate_bundle_manifest(CORSE_BUNDLE_MANIFEST)

    def test_example_renderer_escapes_html_in_headings_and_data(self):
        html = example_block(
            "<script>heading</script>", {"value": "<img src=x onerror=alert(1)>"}
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img ", html)
        self.assertIn("&lt;img", html)
        self.assertIn('tabindex="0"', html)

    def test_technical_model_labels_and_shared_forms_remain_unmodified(self):
        from rpsd_config.admin_dataset_exchange.proxies import (
            IndicatorVersionRuleAdminProxy,
        )
        from rpsd_config.exchange_agreement.validation_forms import IndicatorRuleForm

        original = IndicatorRuleForm.base_fields["dimensions"].help_text
        editor = admin.site._registry[IndicatorVersionRuleAdminProxy]
        editor.get_form(self.request)
        self.assertEqual(
            original, IndicatorRuleForm.base_fields["dimensions"].help_text
        )
        self.assertEqual(
            str(IndicatorVersionRuleAdminProxy._meta.get_field("impact").verbose_name),
            "impact",
        )
