# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Native relation controls preserve popup permissions, filters and through data."""

import json

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets
from django.contrib.admin.widgets import (
    FilteredSelectMultiple,
    RelatedFieldWidgetWrapper,
)
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from rpsd_config.admin_agreements.proxies import IndicatorEvaluationThresholdAdminProxy
from rpsd_config.admin_dataset_exchange.proxies import IndicatorVersionRuleAdminProxy
from rpsd_config.admin_guidance import GuidedAdminMixin, GuidedInlineMixin
from rpsd_config.exchange_agreement import models
from rpsd_config.exchange_agreement.field_guidance import field_guide
from rpsd_config.exchange_agreement.services.catalog_import import apply_catalog
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.formal_definitions import verify_definition
from rpsd_config.exchange_agreement.services.validation_catalog import (
    ensure_validation_type_catalog,
    get_validation_type_version,
)

from .test_formal_indicators import generic_package


class AdminRelatedCatalogTests(TestCase):
    def setUp(self):
        self.platform = get_user_model().objects.create_user(
            username="relations-platform", is_staff=True
        )
        SocialAccount.objects.create(
            user=self.platform,
            provider="openid_connect",
            uid="relations-platform",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.staff = get_user_model().objects.create_user(
            username="relations-staff", is_staff=True
        )
        self.client.force_login(self.platform)
        ensure_validation_type_catalog()

    def test_concrete_popup_uses_platform_permissions_and_guided_form(self):
        path = reverse("admin:exchange_agreement_indicatordimension_add")
        response = self.client.get(path, {"_popup": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "config-guidance.css")
        response = self.client.post(
            path + "?_popup=1",
            {
                "code": "popup-dimension",
                "name": "Dimensione popup",
                "description": "Contesto",
                "allowed_values": "null",
                "_popup": "1",
                "_save": "Salva",
            },
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(
            models.IndicatorDimension.objects.filter(code="popup-dimension").exists()
        )
        self.assertContains(response, "data-popup-response")
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(path).status_code, 403)

    def test_autocomplete_allows_authorized_drafts_and_denies_ordinary_staff(self):
        flows = []
        for index in range(2):
            flow = models.OrchestrationFlowVersion.objects.create(
                code=f"admin-search-{index}",
                version=str(index),
                name="Admin search",
                description="Test",
                engine="prefect",
                deployment_name="contracts/test",
                artifact_identifier="git:rpsd-flows@test",
            )
            flows.append(flow)
        published = publish_orchestration_flow_version(flows[1], actor=self.platform)
        query = {
            "app_label": "exchange_agreement",
            "model_name": "processingprofileversion",
            "field_name": "orchestration_flow_version",
            "term": "admin-search",
        }
        response = self.client.get(reverse("admin:autocomplete"), query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [r["id"] for r in response.json()["results"]],
            [str(flows[0].pk), str(published.pk)],
        )
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("admin:autocomplete"), query).status_code, 403
        )

    def test_dbt_context_is_not_offered_as_an_operational_rule(self):
        from tests.exchange_agreement.test_dbt_contexts import context_document

        doc = models.ValidationRuleVersion.objects.create(
            rule=models.ValidationRule.objects.create(
                code="dbt-context-test", name="Document"
            ),
            version="1",
            name="Document",
            description="Document",
            validation_type_version=get_validation_type_version("dbt", "1"),
            definition=json.dumps(context_document()),
            result_contract="structured_report",
        )
        response = self.client.get(
            reverse("admin:autocomplete"),
            {
                "app_label": "exchange_agreement",
                "model_name": "indicatorversionrule",
                "field_name": "rule_version",
                "term": "dbt-context-test",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(str(doc.pk), [r["id"] for r in response.json()["results"]])

    def test_declared_multi_selection_uses_native_widget_and_related_links(self):
        request = RequestFactory().get("/admin/")
        request.user = self.platform
        form = admin.site._registry[IndicatorVersionRuleAdminProxy].get_form(request)()
        widget = form.fields["dimensions"].widget
        self.assertIsInstance(widget, RelatedFieldWidgetWrapper)
        self.assertIsInstance(widget.widget, FilteredSelectMultiple)
        threshold_form = admin.site._registry[
            IndicatorEvaluationThresholdAdminProxy
        ].get_form(request)()
        threshold_widget = threshold_form.fields["group_by_dimensions"].widget
        self.assertIsInstance(threshold_widget.widget, FilteredSelectMultiple)
        self.assertFalse(threshold_widget.can_add_related)
        self.assertTrue(widget.can_add_related)
        self.assertIn("SelectFilter2.js", str(form.media))

    def test_draft_rule_binding_retains_its_formal_owner_context_in_search(self):
        apply_catalog(generic_package(), actor=self.platform)
        owner = models.IndicatorVersion.objects.get(code="base_001")
        dataset = models.Dataset.objects.create(
            code="draft-context", name="Draft context"
        )
        spec = models.DatasetSpecification.objects.create(
            dataset=dataset,
            code="draft-context_001",
            version="001",
            description="Draft",
            format="xml",
        )
        rule = models.ValidationRuleVersion.objects.create(
            rule=models.ValidationRule.objects.create(
                code="draft-reference", name="Draft reference"
            ),
            version="1",
            name="Draft reference",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition="//Line",
        )
        binding = models.IndicatorVersionRule.objects.create(
            indicator_version=owner,
            dataset_specification=spec,
            rule_version=rule,
            impact="calculation",
        )
        response = self.client.get(
            reverse("admin:autocomplete"),
            {
                "app_label": "exchange_agreement",
                "model_name": "indicatorversionrule",
                "field_name": "rule_version",
                "owner_model": "exchange_agreement.indicatorversionrule",
                "owner_pk": str(binding.pk),
                "term": "draft-reference",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r["id"] for r in response.json()["results"]], [str(rule.pk)])

    def test_batch_publication_identifies_failures_and_escapes_limitations(self):
        apply_catalog(generic_package(), actor=self.platform)
        base = models.IndicatorVersion.objects.get(code="base_001")
        subset = models.IndicatorVersion.objects.get(code="subset_001")
        verify_definition(
            subset,
            actor=self.platform,
            limitations=[
                {
                    "code": "review",
                    "rule": "CHECK_REQUIRED",
                    "reason": "Da rivedere <script>alert(1)</script>",
                }
            ],
        )
        path = reverse(
            "admin:admin_dataset_exchange_indicatorversionadminproxy_changelist"
        )
        response = self.client.post(
            path,
            {
                "action": "publish_selected",
                "_selected_action": [str(base.pk), str(subset.pk)],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        base.refresh_from_db()
        subset.refresh_from_db()
        self.assertEqual(base.status, "published")
        self.assertEqual(subset.status, "draft")
        self.assertContains(response, "subset_001")
        self.assertContains(response, "CHECK_REQUIRED")
        self.assertContains(response, "Apri il record")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, "['Requisiti")
        self.assertContains(response, "Versioni di indicatore aggiornate: 1")


class AdminThroughSelectionTests(TestCase):
    def setUp(self):
        from .test_validation_plan import ValidationPlanTests

        ValidationPlanTests.setUp(self)

    def test_dependency_inline_saves_native_multi_selection_and_metadata(self):
        from rpsd_config.admin_dataset_exchange.proxies import (
            IndicatorVersionAdminProxy,
        )
        from rpsd_config.exchange_agreement.services.indicator_catalog import (
            clone_indicator_version,
        )

        original = self.profile.indicator_version_links.get().indicator_version
        draft = clone_indicator_version(
            original, code="inline-draft", version="inline-draft", actor=self.admin
        )
        edge = draft.dependency_links.get()
        dimension = models.IndicatorDimension.objects.get(code="line")
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        editor = admin.site._registry[IndicatorVersionAdminProxy]
        inline = next(
            i
            for i in editor.get_inline_instances(request, draft)
            if i.model._meta.concrete_model is models.IndicatorVersionDependency
        )
        formclass = inline.get_formset(request, draft).form
        form = formclass(
            {
                "prerequisite": str(edge.prerequisite_id),
                "origin": "technical",
                "technical_reason": "Disaggregazione richiesta",
                "dimensions": [str(dimension.pk)],
            },
            instance=edge,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        edge.refresh_from_db()
        self.assertEqual(
            list(edge.required_dimensions.values_list("code", flat=True)), ["line"]
        )
        self.assertEqual(edge.technical_reason, "Disaggregazione richiesta")


CONFIG_APPS = {
    "admin_dataset_exchange",
    "admin_audit",
    "admin_agreements",
    "admin_stakeholders",
    "admin_service_net",
}


class AdminGuidanceInventoryTests(TestCase):
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
