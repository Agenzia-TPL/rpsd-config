# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Admin/web parity, frozen plans, role boundaries and escaped definitions (025)."""

from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase, override_settings
from django.urls import reverse

from rpsd_config.admin_dataset_exchange.validation_admin import IndicatorRuleAdminForm
from rpsd_config.exchange_agreement.models import (
    Authority,
    AuthorityMembership,
    ContractConfigurationRevision,
    IndicatorDimension,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import approve_revision
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    bind_indicator_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.technical_catalog_views import (
    IndicatorRuleCatalogForm,
)

from . import test_indicator_dependencies as dependency_fixtures
from . import test_validation_plan as plan_fixtures


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class ValidationUITests(TestCase):
    def setUp(self):
        plan_fixtures.ValidationPlanTests.setUp(self)
        self.client.force_login(self.admin)

    def detail(self, slug, pk):
        return reverse("exchange_agreement:technical-catalog-detail", args=(slug, pk))

    def revision_path(self):
        return reverse(
            "exchange_agreement:contract-revision-detail",
            args=(self.contract.contract_code, self.revision.pk),
        )

    def binding(self):
        draft = dependency_fixtures.version("ui-draft")
        dataset_binding = self.profile.input_flow_links.get(
            dataset__code="netex"
        ).input_flow_version.dataset_specification.rule_bindings.first()
        dimension, _ = IndicatorDimension.objects.get_or_create(
            code="ui-line", defaults={"name": "Linea UI"}
        )
        return bind_indicator_rule(
            indicator_version=draft,
            specification=(dataset_binding).dataset_specification,
            rule_version=(dataset_binding).rule_version,
            impact="dimension",
            dimensions=[dimension],
            actor=self.admin,
        )

    def form_values(self, binding, impact="calculation", dimensions=()):
        return {
            "indicator_version": binding.indicator_version_id,
            "dataset_specification": binding.dataset_specification_id,
            "rule_version": binding.rule_version_id,
            "impact": impact,
            "dimensions": list(dimensions),
        }

    def test_shared_forms_replace_dimension_impact_with_calculation(self):
        binding = self.binding()
        for form_class in (IndicatorRuleCatalogForm, IndicatorRuleAdminForm):
            form = form_class(self.form_values(binding), instance=binding)
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
            binding.refresh_from_db()
            self.assertEqual(binding.impact, "calculation")
            self.assertFalse(binding.dimension_links.exists())
        invalid = IndicatorRuleCatalogForm(
            self.form_values(binding, "dimension"), instance=binding
        )
        self.assertFalse(invalid.is_valid())

    def test_admin_post_replaces_dimensions_and_published_post_is_forbidden(self):
        binding = self.binding()
        path = reverse(
            "admin:admin_dataset_exchange_indicatorversionruleadminproxy_change",
            args=(binding.pk,),
        )
        response = self.client.post(path, self.form_values(binding) | {"_save": "Save"})
        self.assertEqual(response.status_code, 302, response.content)
        binding.refresh_from_db()
        self.assertEqual(binding.impact, "calculation")
        self.assertFalse(binding.dimension_links.exists())
        publish_indicator_version(binding.indicator_version, actor=self.admin)
        self.assertEqual(
            self.client.post(path, self.form_values(binding)).status_code, 403
        )

    def test_web_post_updates_impact_and_rejects_published_edit(self):
        binding = self.binding()
        path = self.detail("indicator-rule-bindings", binding.pk)
        response = self.client.post(
            path, self.form_values(binding) | {"action": "save"}
        )
        self.assertEqual(response.status_code, 200)
        binding.refresh_from_db()
        self.assertEqual(binding.impact, "calculation")
        publish_indicator_version(binding.indicator_version, actor=self.admin)
        response = self.client.post(
            path, self.form_values(binding, "dimension") | {"action": "save"}
        )
        self.assertContains(response, "immutabile")
        binding.refresh_from_db()
        self.assertEqual(binding.impact, "calculation")

    def test_rule_definition_escaped_clone_and_confirmed_draft_delete(self):
        rule = ValidationRule.objects.create(code="ui-escape", name="Escaped rule")
        definition = "//n:Line[@id='<script>alert(1)</script>']"
        version = ValidationRuleVersion.objects.create(
            rule=rule,
            version="1",
            name="Escaped rule",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition=definition,
            options={"namespaces": {"n": "urn:netex"}},
            execution_reference="validators/default",
        )
        version = transition_validation_rule(
            version, target_status="published", actor=self.admin
        )
        path = self.detail("validation-rule-versions", version.pk)
        response = self.client.get(path)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        response = self.client.post(path, {"action": "new-version", "version": "2"})
        self.assertEqual(response.status_code, 302)
        clone = ValidationRuleVersion.objects.get(rule=rule, version="2")
        self.assertEqual(clone.status, "draft")
        self.assertEqual(clone.definition, definition)
        clone_path = self.detail("validation-rule-versions", clone.pk)
        self.client.post(clone_path, {"action": "delete-draft"})
        self.assertTrue(ValidationRuleVersion.objects.filter(pk=clone.pk).exists())
        self.assertEqual(
            self.client.post(
                clone_path, {"action": "delete-draft", "confirm_delete": "yes"}
            ).status_code,
            302,
        )
        self.client.post(path, {"action": "delete-draft", "confirm_delete": "yes"})
        self.assertTrue(ValidationRuleVersion.objects.filter(pk=version.pk).exists())

    def test_profile_shows_implicit_roles_paths_and_rules(self):
        response = self.client.get(self.detail("processing-profiles", self.profile.pk))
        self.assertContains(response, "dipendenza implicita")
        self.assertContains(response, "demo-journey-count_001")
        self.assertContains(response, "controlli ereditati", status_code=200)

    def test_catalog_denies_non_platform_get_and_post(self):
        reader = get_user_model().objects.create_user(
            username="ui-ordinary", is_staff=True
        )
        self.client.force_login(reader)
        path = self.detail("processing-profiles", self.profile.pk)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(path, {"action": "publish"}).status_code, 403)

    def test_approved_page_renders_frozen_rules_without_live_rule_lookup(self):
        self.revision = approve_revision(self.revision, self.admin)
        with (
            patch(
                "rpsd_config.exchange_agreement.models.ValidationRuleVersion.objects.filter",
                side_effect=AssertionError("Live catalog lookup"),
            ),
            patch(
                "rpsd_config.exchange_agreement.views.resolve_revision_inputs",
                side_effect=AssertionError("Live profile resolution"),
            ),
        ):
            response = self.client.get(self.revision_path())
        self.assertContains(response, "Regole base del dataset")
        self.assertContains(response, "Compatibilità degli indicatori")
        self.assertContains(response, "già approvata")
        self.assertNotContains(response, "pronta per l&#x27;approvazione")
        self.assertNotContains(response, "Salva valori dell’indicatore")

    def test_authority_reader_cannot_edit_or_approve_revision(self):
        authority = Authority.objects.create(name="Region", authority_type="region")
        reader = get_user_model().objects.create_user(username="ui-authority-reader")
        AuthorityMembership.objects.create(
            authority=authority, user=reader, created_by=self.admin
        )
        self.contract.governing_authority = authority
        self.contract.save()
        self.client.force_login(reader)
        path = self.revision_path()
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(
            self.client.post(
                path,
                {
                    "action": "save-indicator-values",
                    "indicator_version_code": "demo-journey-count_001",
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(path, {"action": "approve-contract-revision"}).status_code,
            403,
        )

    def test_global_admin_cannot_edit_contract_values_through_django_admin(self):
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        config = save_revision_indicator_values(
            self.revision,
            version_code="demo-journey-count_001",
            actor=self.admin,
            values={
                "parameters": {},
                "thresholds": {},
                "aggregation": {},
                "penalties": {},
            },
        )
        from django.contrib import admin
        from django.test import RequestFactory

        from rpsd_config.admin_agreements.admin import ContractDependencyValuesInline
        from rpsd_config.admin_agreements.proxies import (
            ContractConfigurationRevisionAdminProxy,
        )

        platform = get_user_model().objects.create_user(
            username="values-platform", is_staff=True
        )
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="values-platform",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        request = RequestFactory().get("/admin/")
        request.user = platform
        inline = ContractDependencyValuesInline(
            ContractConfigurationRevisionAdminProxy, admin.site
        )
        self.assertFalse(inline.has_change_permission(request, self.revision))
        config.refresh_from_db()
        self.assertEqual(config.parameters, {})

    def test_platform_admin_without_business_role_cannot_approve_contract(self):
        platform = get_user_model().objects.create_user(
            username="ui-platform", is_staff=True
        )
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="ui-platform",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.client.force_login(platform)
        self.assertEqual(
            self.client.get(
                self.detail("processing-profiles", self.profile.pk)
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                self.revision_path(), {"action": "approve-contract-revision"}
            ).status_code,
            403,
        )
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.status, "draft")

    def test_corrupt_snapshot_shows_diagnostic_without_fabricating_controls(self):
        self.revision = approve_revision(self.revision, self.admin)
        # Simulate damaged persisted metadata; normal saves forbid this edit.
        models.QuerySet.update(
            ContractConfigurationRevision.objects.filter(pk=self.revision.pk),
            snapshot_checksum="sha256:" + "0" * 64,
        )
        response = self.client.get(self.revision_path())
        self.assertContains(response, "snapshot approvato è incoerente")
        self.assertNotContains(response, "Regole base del dataset")

    def test_draft_selection_change_removes_unused_dependency_values(self):
        from rpsd_config.exchange_agreement.services.contract_revisions import (
            replace_draft_configuration,
        )
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        save_revision_indicator_values(
            self.revision,
            version_code="demo-journey-count_001",
            actor=self.admin,
            values={
                "parameters": {"window": 10},
                "thresholds": {},
                "aggregation": {},
                "penalties": {},
            },
        )
        self.assertTrue(self.revision.dependency_configurations.exists())
        replace_draft_configuration(
            self.revision, selections=[], indicator_configs=[], actor=self.admin
        )
        self.assertFalse(self.revision.dependency_configurations.exists())
