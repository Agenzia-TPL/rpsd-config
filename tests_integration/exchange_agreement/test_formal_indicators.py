# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Formal authoring, version-owned domains, graph evidence and atomic imports."""

from unittest.mock import patch

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from rpsd_config.exchange_agreement.models import (
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
    IndicatorVersionDimension,
)
from rpsd_config.exchange_agreement.services.catalog_contract import seal_package
from rpsd_config.exchange_agreement.services.catalog_import import (
    CatalogImportError,
    analyze_package,
    apply_catalog,
    plan_catalog,
)
from rpsd_config.exchange_agreement.services.formal_definitions import (
    LANGUAGE_VERSION,
    verification_state,
    verify_definition,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    resolve_indicator_closure,
)


def generic_package():
    """No pilot symbols: the importer must work without FID-specific branches."""
    payload = {
        "sources": [{"repository": "fixture", "commit": "a" * 40, "files": {}}],
        "selection": {"roots": ["SUBSET"], "exclusions": []},
        "dimensions": [
            {"code": "state", "name": "Stato", "allowed_values": ["YES", "NO"]}
        ],
        "indicator_versions": [
            {
                "symbol": "BASE",
                "indicator_code": "base",
                "name": "Base",
                "code": "base_001",
                "version": "001",
                "description": "Universo delle entità",
                "formula_description": "Entità ricostruite dal processo esterno",
                "definition_kind": "base",
                "dimensions": [
                    {
                        "code": "state",
                        "allowed_values": ["YES", "NO"],
                        "is_carried": True,
                    }
                ],
            },
            {
                "symbol": "SUBSET",
                "indicator_code": "subset",
                "name": "Sottoinsieme",
                "code": "subset_001",
                "version": "001",
                "description": "Entità selezionate",
                "formula_description": "Solo entità YES",
                "definition_kind": "projection",
                "formula_definition": "BASE[state = YES]",
            },
        ],
        "dependencies": [
            {
                "dependent": "subset_001",
                "prerequisite": "base_001",
                "origin": "formula",
                "required_dimensions": ["state"],
            }
        ],
        "analysis": {},
    }
    package = seal_package(payload)
    payload["analysis"] = analyze_package(package)
    return seal_package(payload)


class FormalIndicatorTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="formal-admin", is_superuser=True, is_staff=True
        )
        self.package = generic_package()

    def test_supported_previous_core_provenance_preserves_semantic_freshness(self):
        from django.db import models as orm

        from rpsd_config.exchange_agreement.services.formal_definitions import (
            CORE_RELEASES,
        )

        apply_catalog(self.package, actor=self.actor)
        version = IndicatorVersion.objects.get(code="base_001")
        proof = dict(version.formal_verification)
        proof.update(core_version="0.2.0", core_commit=CORE_RELEASES["0.2.0"])
        orm.QuerySet.update(
            IndicatorVersion.objects.filter(pk=version.pk), formal_verification=proof
        )
        version.refresh_from_db()
        self.assertEqual(verification_state(version), "current")
        proof["core_commit"] = "0" * 40
        orm.QuerySet.update(
            IndicatorVersion.objects.filter(pk=version.pk), formal_verification=proof
        )
        version.refresh_from_db()
        self.assertEqual(verification_state(version), "stale")

    def test_dry_run_is_read_only_then_two_imports_reuse_exact_objects(self):
        before = (
            Indicator.objects.count(),
            IndicatorVersion.objects.count(),
            LogEntry.objects.count(),
        )
        report = plan_catalog(self.package, actor=self.actor).report
        self.assertFalse(report["applied"])
        self.assertEqual(
            before,
            (
                Indicator.objects.count(),
                IndicatorVersion.objects.count(),
                LogEntry.objects.count(),
            ),
        )
        first = apply_catalog(self.package, actor=self.actor)
        self.assertTrue(first["applied"])
        selected = IndicatorVersion.objects.get(code="subset_001")
        self.assertEqual(selected.formula_value_kind, "set")
        self.assertEqual(verification_state(selected), "current")
        self.assertEqual(selected.status, "draft")
        self.assertEqual(selected.execution_reference, "")
        audit = LogEntry.objects.count()
        second = apply_catalog(self.package, actor=self.actor)
        self.assertNotIn("create", second["counts"])
        self.assertEqual(LogEntry.objects.count(), audit)
        self.assertEqual(IndicatorVersion.objects.count(), 2)

    def test_defaults_do_not_mutate_version_domains_but_draft_changes_stale_dependents(
        self,
    ):
        apply_catalog(self.package, actor=self.actor)
        selected = IndicatorVersion.objects.get(code="subset_001")
        dimension = IndicatorDimension.objects.get(code="state")
        dimension.allowed_values = ["OTHER"]
        dimension.save()
        self.assertEqual(verification_state(selected), "current")
        link = IndicatorVersionDimension.objects.get(dimension=dimension)
        self.assertEqual(link.allowed_values, ["YES", "NO"])
        link.allowed_values = ["YES", "NO", "MAYBE"]
        link.save()
        self.assertEqual(verification_state(selected), "stale")

    def test_draft_graph_is_authorable_but_operational_resolution_requires_publication(
        self,
    ):
        apply_catalog(self.package, actor=self.actor)
        selected = IndicatorVersion.objects.get(code="subset_001")
        self.assertEqual(
            len(resolve_indicator_closure([selected], allow_drafts=True)["versions"]), 2
        )
        with self.assertRaises(ValidationError):
            resolve_indicator_closure([selected])
        with self.assertRaises(ValidationError):
            publish_indicator_version(selected, actor=self.actor)

    def test_publication_freezes_symbol_domains_and_evidence_without_invoking_workflow(
        self,
    ):
        apply_catalog(self.package, actor=self.actor)
        base = IndicatorVersion.objects.get(code="base_001")
        base.execution_engine = "prefect"
        base.execution_reference = "indicators/base"
        base.artifact_identifier = "git:rpsd-calculations@v1"
        base.save()
        self.assertEqual(verification_state(base), "stale")
        base = verify_definition(base, actor=self.actor)
        publish_indicator_version(base, actor=self.actor)
        base.refresh_from_db()
        self.assertEqual(verification_state(base), "current")
        link = base.dimension_links.get()
        link.allowed_values = None
        with self.assertRaises(ValidationError):
            link.save()
        with self.assertRaises(ValidationError):
            base.dimension_links.all().update(is_carried=False)
        identity = base.indicator
        identity.formula_symbol = "RENAMED"
        with self.assertRaises(ValidationError):
            identity.save()

    def test_tampered_analysis_conflicts_and_late_failure_rolls_back_every_row(self):
        tampered = self.package.model_copy(deep=True)
        tampered.analysis["indicators"]["subset_001"]["value_kind"] = "number"
        with self.assertRaises(CatalogImportError):
            plan_catalog(tampered, actor=self.actor)
        original = IndicatorVersion.save

        def fail_last(instance, *args, **kwargs):
            if instance.code == "subset_001":
                raise ValidationError("Injected final write failure")
            return original(instance, *args, **kwargs)

        with patch.object(IndicatorVersion, "save", fail_last):
            with self.assertRaises(ValidationError):
                apply_catalog(self.package, actor=self.actor)
        self.assertFalse(Indicator.objects.exists())
        self.assertFalse(IndicatorDimension.objects.exists())
        self.assertFalse(LogEntry.objects.exists())
        apply_catalog(self.package, actor=self.actor)
        conflict = self.package.model_copy(deep=True)
        conflict.indicator_versions[0].description = "Un'altra definizione"
        with self.assertRaises(CatalogImportError):
            apply_catalog(conflict, actor=self.actor)

    def test_manual_evidence_and_bulk_symbol_changes_are_rejected(self):
        apply_catalog(self.package, actor=self.actor)
        version = IndicatorVersion.objects.get(code="base_001")
        version.formal_verification = {"verified": True}
        with self.assertRaises(ValidationError):
            version.save()
        with self.assertRaises(ValidationError):
            Indicator.objects.filter(pk=version.indicator_id).update(
                formula_symbol="CHANGED"
            )
        with self.assertRaises(ValidationError):
            IndicatorVersionDimension.objects.all().bulk_update([], ["allowed_values"])
        reader = get_user_model().objects.create_user(username="formal-reader")
        with self.assertRaises(PermissionDenied):
            apply_catalog(self.package, actor=reader)

    def test_technical_cycles_and_missing_filter_dimensions_are_rejected(self):
        missing = self.package.model_copy(deep=True)
        missing.dependencies[0].required_dimensions = []
        with self.assertRaises(ValidationError):
            analyze_package(missing)
        apply_catalog(self.package, actor=self.actor)
        base = IndicatorVersion.objects.get(code="base_001")
        selected = IndicatorVersion.objects.get(code="subset_001")
        with self.assertRaises(ValidationError):
            IndicatorVersionDependency.objects.create(
                dependent=base,
                prerequisite=selected,
                origin="technical",
                technical_reason="Ciclo tecnico",
            )
        with self.assertRaises(ValidationError):
            IndicatorVersionDependency.objects.create(
                dependent=base, prerequisite=base, origin="formula"
            )

    def test_own_evidence_cannot_bypass_unresolved_source_requirements(self):
        package = self.package.model_copy(deep=True)
        package.indicator_versions[0].limitations = [
            {"code": "missing_rule", "reason": "Source requirement not implemented"}
        ]
        package = seal_package(package.model_dump(exclude={"package_digest"}))
        apply_catalog(package, actor=self.actor)
        base = IndicatorVersion.objects.get(code="base_001")
        base.execution_engine = "prefect"
        base.execution_reference = "indicators/base"
        base.artifact_identifier = "git:rpsd-calculations@v1"
        base.save()
        base = verify_definition(base, actor=self.actor)
        with self.assertRaisesMessage(ValidationError, "Requisiti esclusi"):
            publish_indicator_version(base, actor=self.actor)

    def test_generic_composite_and_consistency_context_do_not_add_execution_edges(self):
        payload = self.package.model_dump(exclude={"package_digest"})
        payload["indicator_versions"].append(
            {
                "symbol": "RATIO",
                "indicator_code": "ratio",
                "name": "Rapporto",
                "code": "ratio_001",
                "version": "001",
                "description": "Quota del sottoinsieme",
                "formula_description": "Rapporto fra cardinalità",
                "definition_kind": "composite",
                "formula_definition": "SUBSET / BASE",
            }
        )
        payload["indicator_versions"][0]["consistency_checks"] = (
            "BASE = SUBSET ∪ BASE[state = NO]"
        )
        payload["dependencies"].extend(
            [
                {
                    "dependent": "ratio_001",
                    "prerequisite": "base_001",
                    "origin": "formula",
                },
                {
                    "dependent": "ratio_001",
                    "prerequisite": "subset_001",
                    "origin": "formula",
                },
            ]
        )
        package = seal_package(payload)
        payload["analysis"] = analyze_package(package)
        package = seal_package(payload)
        apply_catalog(package, actor=self.actor)
        ratio = IndicatorVersion.objects.get(code="ratio_001")
        self.assertEqual(ratio.formula_value_kind, "number")
        base = IndicatorVersion.objects.get(code="base_001")
        self.assertFalse(base.dependency_links.exists())
        self.assertEqual(verification_state(base), "current")
        from rpsd_config.exchange_agreement.services.indicator_catalog import (
            clone_indicator_version,
        )

        clone = clone_indicator_version(
            base, code="base_002", version="002", actor=self.actor
        )
        self.assertEqual(clone.dimension_links.get().allowed_values, ["YES", "NO"])
        self.assertFalse(clone.formal_verification)
        self.assertEqual(verification_state(clone), "not_verified")

    def test_admin_and_web_expose_formal_fields_and_version_owned_domains(self):
        from django.urls import reverse

        from rpsd_config.exchange_agreement.formal_forms import IndicatorDimensionForm

        apply_catalog(self.package, actor=self.actor)
        base = IndicatorVersion.objects.get(code="base_001")
        self.client.force_login(self.actor)
        path = reverse(
            "admin:admin_dataset_exchange_indicatorversionadminproxy_change",
            args=[base.pk],
        )
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dimensioni proprie e vocabolari della versione")
        self.assertContains(response, "rpsd-formula-v1")
        self.assertContains(response, "Evidenza di verifica statica")
        from allauth.socialaccount.models import SocialAccount

        operator = get_user_model().objects.create_user(
            username="formal-platform", is_staff=True
        )
        SocialAccount.objects.create(
            user=operator,
            provider="openid_connect",
            uid="formal-platform-keycloak",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        self.client.force_login(operator)
        self.assertContains(self.client.get(path), "dimension_links-TOTAL_FORMS")
        self.client.force_login(self.actor)

        web = reverse(
            "exchange_agreement:technical-catalog-detail",
            args=["indicator-versions", base.pk],
        )
        self.assertContains(self.client.get(web), "BASE")
        dimension = IndicatorDimension.objects.create(
            code="empty", name="Vuoto", allowed_values=[]
        )
        form = IndicatorDimensionForm(
            data={
                "dimension": dimension.pk,
                "is_carried": "on",
                "copy_catalog_values": "on",
                "allowed_values": "null",
            },
            owner=base,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().allowed_values, [])
        with self.assertRaises(ValidationError):
            dimension.allowed_values = [True]
            dimension.save()

    def test_a_legacy_identity_can_receive_its_first_symbol_for_a_new_formal_version(
        self,
    ):
        identity = Indicator.objects.create(
            code="legacy", name="Legacy", description="Existing"
        )
        version = IndicatorVersion.objects.create(
            indicator=identity,
            code="legacy_001",
            version="001",
            description="Existing",
            formula_description="Existing prose",
            execution_engine="prefect",
            execution_reference="indicators/legacy",
            artifact_identifier="git:calculation@legacy",
        )
        publish_indicator_version(version, actor=self.actor)
        identity.formula_symbol = "LEGACY"
        identity.save()
        version.refresh_from_db()
        self.assertEqual(version.definition_kind, "")
        self.assertFalse(version.formal_verification)
        current = IndicatorVersion.objects.create(
            indicator=identity,
            code="legacy_002",
            version="002",
            description="Formalized",
            formula_description="External base",
            definition_kind="base",
            formula_language_version=LANGUAGE_VERSION,
        )
        self.assertEqual(
            verify_definition(current, actor=self.actor).formula_value_kind, "set"
        )
