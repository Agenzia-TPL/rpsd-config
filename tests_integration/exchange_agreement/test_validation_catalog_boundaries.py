# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Real PostgreSQL locks and HTTP permissions for feature 019."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from rpsd_config.admin_dataset_exchange.proxies import (
    ValidationRuleStatusEventAdminProxy,
    ValidationRuleVersionAdminProxy,
)
from rpsd_config.exchange_agreement.models import ValidationRule, ValidationRuleVersion
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
    save_validation_rule_version,
    transition_validation_rule,
)


def make_rule_version() -> ValidationRuleVersion:
    """Create a locally publishable definition, without a provisioned runtime."""
    rule = ValidationRule.objects.create(code="reference-check", name="Reference check")
    return ValidationRuleVersion.objects.create(
        rule=rule,
        version="001",
        name="Reference check",
        validation_type_version=get_validation_type_version("xpath", "1.0"),
        definition="//n:DayTypeRef[not(@ref = //n:DayType/@id)]",
        options={"namespaces": {"n": "urn:netex"}},
        execution_reference="validators/netex-default",
    )


class RuleCatalogBoundaryTests(TestCase):
    def setUp(self):
        self.platform_admin = get_user_model().objects.create_user(
            username="platform-rule-admin",
            is_staff=True,
        )
        SocialAccount.objects.create(
            user=self.platform_admin,
            provider="openid_connect",
            uid="rule-admin-oidc",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.editor = get_user_model().objects.create_user(
            username="agency-rule-editor", is_staff=True
        )
        SocialAccount.objects.create(
            user=self.editor,
            provider="openid_connect",
            uid="rule-editor-oidc",
            extra_data={"id_token": {"groups": ["/rpsd/test-agency/editor"]}},
        )
        self.version = make_rule_version()
        self.url = reverse(
            "exchange_agreement:technical-catalog-detail",
            kwargs={
                "catalog_slug": "validation-rule-versions",
                "object_id": self.version.pk,
            },
        )

    def test_platform_admin_without_superuser_can_publish(self):
        save_validation_rule_version(self.version, actor=self.platform_admin)
        self.client.force_login(self.platform_admin)
        response = self.client.post(self.url, {"action": "publish"})
        self.assertEqual(response.status_code, 200)
        self.version.refresh_from_db()
        self.assertEqual(self.version.status, "published")
        self.assertEqual(
            self.version.status_events.get().changed_by, self.platform_admin
        )

    def test_agency_editor_gets_403_for_both_http_boundaries(self):
        self.client.force_login(self.editor)
        self.assertEqual(
            self.client.post(self.url, {"action": "publish"}).status_code, 403
        )
        admin_url = reverse(
            "admin:admin_dataset_exchange_validationruleversionadminproxy_change",
            args=[self.version.pk],
        )
        self.assertEqual(
            self.client.post(admin_url, {"definition": "changed"}).status_code, 403
        )
        self.assertFalse(self.version.status_events.exists())

    def test_forged_web_save_cannot_change_published_rule(self):
        transition_validation_rule(
            self.version, target_status="published", actor=self.platform_admin
        )
        self.client.force_login(self.platform_admin)
        self.assertEqual(
            self.client.post(
                self.url, {"action": "save", "definition": "changed"}
            ).status_code,
            200,
        )
        self.version.refresh_from_db()
        self.assertIn("DayTypeRef", self.version.definition)

    def test_recovery_admin_preserves_specialized_permissions(self):
        request = RequestFactory().get("/admin/")
        request.user = self.platform_admin
        rule_admin = admin.site._registry[ValidationRuleVersionAdminProxy]
        self.assertTrue(rule_admin.has_add_permission(request))
        self.assertTrue(rule_admin.has_delete_permission(request, self.version))
        transition_validation_rule(
            self.version, target_status="published", actor=self.platform_admin
        )
        self.version.refresh_from_db()
        self.assertFalse(rule_admin.has_delete_permission(request, self.version))
        self.assertNotIn("delete_selected", rule_admin.get_actions(request))
        audit_admin = admin.site._registry[ValidationRuleStatusEventAdminProxy]
        self.assertTrue(audit_admin.has_view_permission(request))
        self.assertFalse(audit_admin.has_add_permission(request))
        self.assertFalse(audit_admin.has_change_permission(request))
        self.assertFalse(audit_admin.has_delete_permission(request))


class RulePublicationConcurrencyTests(TransactionTestCase):
    def test_concurrent_publish_has_one_audit_event(self):
        actor = get_user_model().objects.create_user(
            username="concurrent-rule-admin", is_superuser=True
        )
        version = make_rule_version()
        barrier = Barrier(2)

        def publish() -> str:
            close_old_connections()
            try:
                local_actor = get_user_model().objects.get(pk=actor.pk)
                local_version = ValidationRuleVersion.objects.get(pk=version.pk)
                barrier.wait(timeout=10)
                try:
                    transition_validation_rule(
                        local_version, target_status="published", actor=local_actor
                    )
                    return "published"
                except ValidationError as exc:
                    return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(publish) for _ in range(2)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertCountEqual(outcomes, ["published", "invalid_rule_transition"])
        version.refresh_from_db()
        self.assertEqual(version.status, "published")
        self.assertEqual(version.status_events.count(), 1)

    def test_dataset_publication_serializes_base_rule_creation(self):
        from rpsd_config.exchange_agreement.models import Dataset, DatasetSpecification
        from rpsd_config.exchange_agreement.services.dataset_catalog import (
            publish_dataset_specification,
        )
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            bind_dataset_rule,
        )

        actor = get_user_model().objects.create_user(
            username="dataset-binding-admin", is_superuser=True
        )
        rule = transition_validation_rule(
            make_rule_version(), target_status="published", actor=actor
        )
        spec = DatasetSpecification.objects.create(
            dataset=Dataset.objects.create(code="netex", name="NeTEx"),
            code="concurrent-netex_001",
            version="001",
            format="xml",
        )
        barrier = Barrier(2)

        def action(publish: bool) -> str:
            close_old_connections()
            try:
                local_spec = DatasetSpecification.objects.get(pk=spec.pk)
                local_actor = get_user_model().objects.get(pk=actor.pk)
                local_rule = ValidationRuleVersion.objects.get(pk=rule.pk)
                barrier.wait(timeout=10)
                if publish:
                    publish_dataset_specification(local_spec, actor=local_actor)
                    return "published"
                try:
                    bind_dataset_rule(
                        specification=local_spec,
                        rule_version=local_rule,
                        failure_policy="reject_import",
                        actor=local_actor,
                    )
                    return "created"
                except ValidationError as exc:
                    return exc.code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(action, publish) for publish in (True, False)]
            outcomes = [future.result(timeout=20) for future in futures]
        self.assertEqual(outcomes[0], "published")
        self.assertIn(outcomes[1], ("created", "immutable_binding"))
        spec.refresh_from_db()
        self.assertEqual(spec.status, "published")
        self.assertEqual(
            spec.rule_bindings.count(), 1 if outcomes[1] == "created" else 0
        )
        self.assertEqual(spec.status_events.count(), 1)
