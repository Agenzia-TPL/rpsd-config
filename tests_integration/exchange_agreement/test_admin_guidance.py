# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Test rendered guidance, frozen values and unchanged access boundaries."""

from pathlib import Path
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase
from django.urls import reverse

from rpsd_config.admin_dataset_exchange.proxies import DatasetVersionRuleAdminProxy
from rpsd_config.admin_examples import CORSE_BUNDLE_MANIFEST
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    DatasetVersionRule,
    IndicatorVersionDependency,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import approve_revision
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.schema_bundles import verify_schema_bundle
from rpsd_config.exchange_agreement.services.validation_catalog import (
    get_validation_type_version,
    transition_validation_rule,
)

from . import test_validation_plan as plan_fixtures
from . import test_validation_ui as ui_fixtures


def admin_path(model: str, pk: int) -> str:
    """Build an existing catalog object's change/view path."""
    return reverse(
        f"admin:admin_dataset_exchange_{model.lower()}adminproxy_change", args=[pk]
    )


class AdminGuidanceRenderingTests(TestCase):
    def setUp(self):
        ContentType.objects.clear_cache()
        plan_fixtures.ValidationPlanTests.setUp(self)
        self.client.force_login(self.admin)

    def tearDown(self):
        # Some proxy content types are created lazily on a reused test database.
        # Their cache must not outlive the enclosing TestCase rollback.
        ContentType.objects.clear_cache()
        super().tearDown()

    def test_all_config_changelists_and_authorized_add_pages_render(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        for model, editor in admin.site._registry.items():
            if not model._meta.app_label.startswith("admin_"):
                continue
            with self.subTest(model=model.__name__):
                name = f"admin:{model._meta.app_label}_{model._meta.model_name}"
                self.assertEqual(
                    self.client.get(reverse(name + "_changelist")).status_code, 200
                )
                if editor.has_add_permission(request):
                    response = self.client.get(reverse(name + "_add"))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, "config-guidance.css")

    def test_rule_draft_published_and_withdrawn_keep_help_and_escape_data(self):
        version = ValidationRuleVersion.objects.create(
            rule=ValidationRule.objects.create(code="guide-escape", name="Guide"),
            version="1",
            name="Guide",
            validation_type_version=get_validation_type_version("xpath", "1.0"),
            definition="//n:Line[@id='<script>alert(1)</script>']",
            options={"namespaces": {"n": "urn:netex"}},
            execution_reference="validators/default",
        )
        path = admin_path("ValidationRuleVersion", version.pk)
        for status in ("draft", "published", "withdrawn"):
            if status != "draft":
                version = transition_validation_rule(
                    version,
                    target_status=status,
                    actor=self.admin,
                    reason="Guidance test",
                )
            before = dict(
                ValidationRuleVersion.objects.filter(pk=version.pk).values().get()
            )
            with patch(
                "requests.sessions.Session.request",
                side_effect=AssertionError("Unexpected external request"),
            ):
                response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            for text in (
                "Definizione della regola",
                "Processo di validazione Prefect",
                "empty_context",
                "Esempio xsd_bundle",
                "Errori tecnici e violazioni",
            ):
                self.assertContains(response, text)
            self.assertContains(response, "&lt;script&gt;")
            self.assertNotContains(response, "<script>alert(1)</script>")
            if status != "draft":
                self.assertNotIn(
                    "definition", response.context["adminform"].form.fields
                )
                self.assertContains(response, "Configurazione congelata")
            self.assertEqual(
                before,
                ValidationRuleVersion.objects.filter(pk=version.pk).values().get(),
            )

    def test_frozen_indicator_binding_retains_dimension_values_and_guidance(self):
        binding = ui_fixtures.ValidationUITests.binding(self)
        publish_indicator_version(binding.indicator_version, actor=self.admin)
        path = admin_path("IndicatorVersionRule", binding.pk)
        response = self.client.get(path)
        self.assertContains(response, "Linea UI")
        self.assertContains(response, "Dimensioni interessate")
        self.assertContains(response, "disaggregazioni perse")
        self.assertContains(response, "L’impatto non cambia la politica di import")
        self.assertEqual(
            self.client.post(path, {"impact": "calculation"}).status_code, 403
        )
        binding.refresh_from_db()
        self.assertEqual(binding.impact, "dimension")

    def test_dataset_binding_and_dependency_lists_show_endpoints_and_policy(self):
        binding = DatasetVersionRule.objects.select_related(
            "rule_version__rule", "dataset_specification"
        ).first()
        response = self.client.get(admin_path("DatasetVersionRule", binding.pk))
        self.assertContains(response, "Politica di import")
        self.assertContains(response, "regole indicatore si associano separatamente")
        dependency = IndicatorVersionDependency.objects.first()
        response = self.client.get(
            admin_path("IndicatorVersionDependency", dependency.pk)
        )
        self.assertContains(response, "Indicatore dipendente (A)")
        self.assertContains(response, "Indicatore prerequisito (B)")
        self.assertContains(response, "Vietati autoriferimenti e cicli")

    def test_published_profile_inline_help_is_textual_and_keyboard_accessible(self):
        response = self.client.get(
            admin_path("ProcessingProfileVersion", self.profile.pk)
        )
        self.assertContains(response, 'class="config-inline-guidance"')
        self.assertContains(
            response, "<summary>Proposto per default</summary>", html=True
        )
        self.assertContains(response, "Non lo rende obbligatorio")
        for inline in response.context["inline_admin_formsets"]:
            self.assertFalse(inline.has_add_permission)
            self.assertFalse(inline.has_change_permission)

    def test_approved_revision_keeps_values_help_link_and_payload_unchanged(self):
        self.revision = approve_revision(self.revision, self.admin)
        before = self.revision.configuration_snapshot
        checksum = self.revision.snapshot_checksum
        path = reverse(
            "admin:admin_agreements_contractconfigurationrevisionadminproxy_change",
            args=[self.revision.pk],
        )
        response = self.client.get(path)
        self.assertContains(response, "Decorrenza della revisione")
        self.assertContains(response, "L’approvazione è immediata")
        self.assertContains(response, "Soglie della revisione")
        self.assertContains(response, "Parametri della revisione")
        self.assertContains(response, "Apri il workflow web della revisione")
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.configuration_snapshot, before)
        self.assertEqual(self.revision.snapshot_checksum, checksum)

    def test_dependency_values_link_requires_contract_preparer_scope(self):
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        values = save_revision_indicator_values(
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
        path = reverse(
            "admin:admin_agreements_contractconfigurationrevisionadminproxy_change",
            args=[self.revision.pk],
        )
        self.assertContains(
            self.client.get(path), "Valori degli indicatori prerequisiti"
        )
        from rpsd_config.admin_agreements.admin import ContractDependencyValuesInline
        from rpsd_config.admin_agreements.proxies import (
            ContractConfigurationRevisionAdminProxy,
        )

        inline = ContractDependencyValuesInline(
            ContractConfigurationRevisionAdminProxy, admin.site
        )
        actor = get_user_model().objects.create_user(
            username="guide-platform", is_staff=True
        )
        SocialAccount.objects.create(
            user=actor,
            provider="openid_connect",
            uid="guide-platform-uid",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        request = RequestFactory().get("/admin/")
        request.user = actor
        self.assertFalse(inline.has_change_permission(request, self.revision))
        values.refresh_from_db()
        self.assertEqual(values.parameters, {})

    def test_binding_columns_do_not_add_per_row_relation_queries(self):
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        editor = admin.site._registry[DatasetVersionRuleAdminProxy]
        with self.assertNumQueries(1):
            rows = list(editor.get_queryset(request))
            for row in rows:
                for column in editor.get_list_display(request):
                    column(row)
        self.assertGreater(len(rows), 1)

    def test_deprecated_logical_identity_is_not_described_as_frozen_version(self):
        for model_name, identity in (
            ("Dataset", self.profile.input_flow_links.first().dataset),
            (
                "Indicator",
                self.profile.indicator_version_links.first().indicator_version.indicator,
            ),
        ):
            with self.subTest(model=model_name):
                identity.status = "deprecated"
                identity.save()
                response = self.client.get(admin_path(model_name, identity.pk))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "active o deprecated")
                self.assertNotContains(response, "Configurazione congelata")
                self.assertIn("name", response.context["adminform"].form.fields)

    def test_bundle_asset_identity_is_readonly_and_keeps_manifest_guidance(self):
        asset = ConfigurationAsset.objects.create(
            asset_type="netex_xsd",
            original_filename="netex.zip",
            what="netex",
            storage_provider="local",
            storage_url="local://fixture/netex.zip",
            checksum_sha256=CORSE_BUNDLE_MANIFEST["bundle_sha256"],
            bundle_manifest=CORSE_BUNDLE_MANIFEST,
        )
        before = ConfigurationAsset.objects.filter(pk=asset.pk).values().get()
        response = self.client.get(admin_path("ConfigurationAsset", asset.pk))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("bundle_manifest", response.context["adminform"].form.fields)
        self.assertContains(response, "Manifest del bundle XSD")
        self.assertContains(response, "Manifest della fixture CORSE_PDE")
        self.assertContains(response, "NeTEx_publication_Lev5.xsd")
        self.assertEqual(
            before, ConfigurationAsset.objects.filter(pk=asset.pk).values().get()
        )

    def test_bundle_example_matches_the_actual_pinned_fixture(self):
        archive = Path(__file__).parent / "fixtures/corse_pde/upstream/netex.zip"
        verify_schema_bundle(archive.read_bytes(), CORSE_BUNDLE_MANIFEST)
