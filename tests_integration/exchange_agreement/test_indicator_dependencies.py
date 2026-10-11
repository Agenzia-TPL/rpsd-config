# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Version-specific graphs, publication freeze and dependency contracts (021)."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, models, transaction
from django.test import TestCase, TransactionTestCase

from rpsd_config.exchange_agreement.models import (
    DependencyRequiredDimension,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    deprecate_indicator_version,
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    add_indicator_dependency,
    dependency_impact_contract,
    indicator_artifact_inventory,
    resolve_indicator_closure,
)


def version(code, logical=None, number="001"):
    """Create a complete draft without contacting the calculation runtime."""
    logical = logical or Indicator.objects.create(
        code=code, name=code, description=code
    )
    return IndicatorVersion.objects.create(
        indicator=logical,
        code=code + "_" + number,
        version=number,
        description=code,
        formula_description="Count",
        execution_engine="prefect",
        execution_reference="indicators/default",
        artifact_identifier="git:flows@fixture",
    )


class IndicatorDependencyTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(
            username="graph-admin", is_superuser=True
        )

    def test_chain_execution_order_and_roles(self):
        c = publish_indicator_version(version("z-base"), actor=self.actor)
        b = version("m-middle")
        add_indicator_dependency(dependent=b, prerequisite=c, actor=self.actor)
        b = publish_indicator_version(b, actor=self.actor)
        a = version("a-root")
        add_indicator_dependency(dependent=a, prerequisite=b, actor=self.actor)
        closure = resolve_indicator_closure([a, a])
        self.assertEqual(closure["execution_order"], [c.code, b.code, a.code])
        self.assertEqual(closure["paths"][c.pk], [[a.code, b.code, c.code]])
        self.assertEqual(closure["root_ids"], {a.pk})
        self.assertEqual(len(closure["versions"]), 3)

    def test_diamond_deduplicates_execution_and_retains_both_paths(self):
        base = publish_indicator_version(version("base"), actor=self.actor)
        left, right = version("left"), version("right")
        for child in (left, right):
            add_indicator_dependency(
                dependent=child, prerequisite=base, actor=self.actor
            )
            publish_indicator_version(child, actor=self.actor)
        root = version("root")
        for child in (left, right):
            add_indicator_dependency(
                dependent=root, prerequisite=child, actor=self.actor
            )
        closure = resolve_indicator_closure([root])
        self.assertEqual(
            closure["execution_order"], [base.code, left.code, right.code, root.code]
        )
        self.assertEqual(
            closure["paths"][base.pk],
            [[root.code, left.code, base.code], [root.code, right.code, base.code]],
        )
        self.assertEqual(len(closure["versions"]), 4)
        with self.assertRaises(ValidationError):
            add_indicator_dependency(
                dependent=root, prerequisite=left, actor=self.actor
            )
        self.assertEqual(root.dependency_links.count(), 2)

    def test_artifact_inventory_preserves_calculation_provenance(self):
        child = publish_indicator_version(version("inventory"), actor=self.actor)
        inventory = indicator_artifact_inventory()
        self.assertEqual(
            inventory["indicator_versions"][0]["artifact_identifier"],
            child.artifact_identifier,
        )
        self.assertNotIn("legacy_indicator_files", inventory)
        self.assertEqual(inventory["schema_version"], "indicator-artifact-inventory-v2")
        child.refresh_from_db()
        self.assertEqual(child.artifact_identifier, "git:flows@fixture")

    def test_exact_version_conflict_is_atomic(self):
        logical = Indicator.objects.create(code="base", name="Base", description="Base")
        first = publish_indicator_version(version("base", logical), actor=self.actor)
        second = publish_indicator_version(
            version("base", logical, "002"), actor=self.actor
        )
        parent = version("parent")
        add_indicator_dependency(dependent=parent, prerequisite=first, actor=self.actor)
        with self.assertRaises(ValidationError) as error:
            add_indicator_dependency(
                dependent=parent, prerequisite=second, actor=self.actor
            )
        self.assertEqual(error.exception.code, "conflicting_indicator_versions")
        self.assertEqual(parent.dependency_links.count(), 1)

    def test_dimension_contract_total_and_named_dimension(self):
        child = publish_indicator_version(version("child"), actor=self.actor)
        parent = version("parent")
        edge = add_indicator_dependency(
            dependent=parent, prerequisite=child, actor=self.actor
        )
        contract = dependency_impact_contract(edge)
        self.assertEqual(contract["required_dimensions"], [])
        self.assertEqual(contract["missing_entity_mapping"], "unknown")
        self.assertEqual(
            contract["calculation_failure"], "propagate_for_mapped_entities"
        )
        dimension = IndicatorDimension.objects.create(code="line", name="Line")
        DependencyRequiredDimension.objects.create(dependency=edge, dimension=dimension)
        self.assertEqual(
            dependency_impact_contract(edge)["required_dimensions"], ["line"]
        )
        publish_indicator_version(parent, actor=self.actor)
        with self.assertRaises(ValidationError), transaction.atomic():
            edge.required_dimensions.clear()
        with self.assertRaises(ValidationError):
            edge.delete()

    def test_retired_prerequisite_is_read_from_database(self):
        child = publish_indicator_version(version("child"), actor=self.actor)
        deprecate_indicator_version(child, actor=self.actor)
        with self.assertRaises(ValidationError):
            add_indicator_dependency(
                dependent=version("parent"), prerequisite=child, actor=self.actor
            )
        self.assertFalse(IndicatorVersionDependency.objects.exists())

    def test_indirect_cycle_from_legacy_graph_is_rejected(self):
        a = publish_indicator_version(version("a"), actor=self.actor)
        b = version("b")
        add_indicator_dependency(dependent=b, prerequisite=a, actor=self.actor)
        b = publish_indicator_version(b, actor=self.actor)
        # Deliberately simulate a legacy graph imported outside model services.
        models.QuerySet.update(IndicatorVersion.objects.filter(pk=a.pk), status="draft")
        a.refresh_from_db()
        with self.assertRaises(ValidationError):
            add_indicator_dependency(dependent=a, prerequisite=b, actor=self.actor)
        self.assertEqual(IndicatorVersionDependency.objects.count(), 1)

    def test_permissions_and_published_bulk_writes(self):
        actor = get_user_model().objects.create_user(username="graph-editor")
        child = publish_indicator_version(version("child"), actor=self.actor)
        with self.assertRaises(PermissionDenied):
            add_indicator_dependency(
                dependent=version("parent"), prerequisite=child, actor=actor
            )
        for operation in [
            lambda: IndicatorVersion.objects.filter(pk=child.pk).update(
                execution_reference="changed"
            ),
            lambda: IndicatorVersion.objects.filter(pk=child.pk).delete(),
            lambda: IndicatorVersion.objects.bulk_update([child], ["description"]),
        ]:
            with self.assertRaises(ValidationError):
                operation()


class IndicatorGraphConcurrencyTests(TransactionTestCase):
    def test_concurrent_mutual_dependencies_cannot_create_cycle(self):
        actor = get_user_model().objects.create_user(
            username="concurrent-graph-admin", is_superuser=True
        )
        a = version("a")
        b = publish_indicator_version(version("b"), actor=actor)
        barrier = Barrier(2)

        def add(parent_id, child_id):
            close_old_connections()
            try:
                parent = IndicatorVersion.objects.get(pk=parent_id)
                child = IndicatorVersion.objects.get(pk=child_id)
                barrier.wait(timeout=10)
                try:
                    add_indicator_dependency(
                        dependent=parent, prerequisite=child, actor=actor
                    )
                    return "created"
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(add, a.pk, b.pk), pool.submit(add, b.pk, a.pk)]
            self.assertCountEqual(
                [future.result(timeout=20) for future in futures],
                ["created", "rejected"],
            )
        self.assertEqual(IndicatorVersionDependency.objects.count(), 1)
        self.assertEqual(
            resolve_indicator_closure([a])["execution_order"], [b.code, a.code]
        )
