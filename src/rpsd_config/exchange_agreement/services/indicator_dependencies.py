# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Deterministic dependency closure and PostgreSQL transaction serialization."""

from django.core.exceptions import ValidationError
from django.db import connection, transaction

from rpsd_config.exchange_agreement.models import (
    IndicatorVersion,
    IndicatorVersionDependency,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    required_dataset_specifications,
    validate_indicator_bindings,
)

GRAPH_LOCK_KEY = 52505344021


def lock_indicator_graph() -> None:
    """Serialize graph edits/publication before locking individual versions."""
    if not connection.in_atomic_block:
        raise RuntimeError("The graph lock requires an atomic transaction.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [GRAPH_LOCK_KEY])


def would_create_cycle(
    dependent_id: int, prerequisite_id: int, *, exclude_pk=None
) -> bool:
    """Check reachability after replacing one edge; never resolve latest versions."""
    edges = IndicatorVersionDependency.objects.exclude(pk=exclude_pk).values_list(
        "dependent_id", "prerequisite_id"
    )
    graph = {}
    for parent, child in edges:
        graph.setdefault(parent, set()).add(child)
    pending = [prerequisite_id]
    seen = set()
    while pending:
        item = pending.pop()
        if item == dependent_id:
            return True
        if item not in seen:
            seen.add(item)
            pending.extend(graph.get(item, ()))
    return False


def resolve_indicator_closure(roots) -> dict:
    """Return a deterministic AND closure, all paths, edges and required inputs."""
    root_ids = {version.pk for version in roots}
    roots = list(
        IndicatorVersion.objects.filter(pk__in=root_ids)
        .select_related("indicator")
        .order_by("code")
    )
    versions = {}
    paths = {}
    edges = {}
    logical = {}
    specs = {}
    active = set()
    execution_order = []

    def visit(version, path):
        if version.pk in active:
            raise ValidationError(
                "Cyclic indicator dependency: " + " -> ".join(path),
                code="cyclic_indicator_dependency",
            )
        previous = logical.get(version.indicator_id)
        if previous is not None and previous != version.pk:
            raise ValidationError(
                "Conflicting indicator versions.", code="conflicting_indicator_versions"
            )
        logical[version.indicator_id] = version.pk
        if path not in paths.setdefault(version.pk, []):
            paths[version.pk].append(path)
        versions[version.pk] = version
        validate_indicator_bindings(version)
        for spec in required_dataset_specifications(version):
            old = specs.get(spec.dataset.code)
            if old is not None and old.pk != spec.pk:
                raise ValidationError(
                    "Conflicting dataset versions.", code="conflicting_dataset_versions"
                )
            specs[spec.dataset.code] = spec
        active.add(version.pk)
        for edge in (
            version.dependency_links.select_related("prerequisite__indicator")
            .prefetch_related("required_dimensions")
            .order_by("prerequisite__code")
        ):
            if edge.prerequisite.status != "published":
                raise ValidationError(
                    "Unpublished prerequisite: "
                    + " -> ".join(path + [edge.prerequisite.code]),
                    code="unpublished_prerequisite",
                )
            edges[edge.pk] = edge
            visit(edge.prerequisite, path + [edge.prerequisite.code])
        active.remove(version.pk)
        if version.code not in execution_order:
            execution_order.append(version.code)

    for root in roots:
        visit(root, [root.code])
    return {
        "versions": sorted(versions.values(), key=lambda v: v.code),
        "paths": paths,
        "edges": sorted(
            edges.values(), key=lambda e: (e.dependent.code, e.prerequisite.code)
        ),
        "specifications": sorted(specs.values(), key=lambda s: s.code),
        "root_ids": {v.pk for v in roots},
        "execution_order": execution_order,
    }


def dependency_impact_contract(edge) -> dict:
    """Describe propagation requirements; the external runtime maps entities."""
    return {
        "dependent": edge.dependent.code,
        "prerequisite": edge.prerequisite.code,
        "required_dimensions": sorted(
            edge.required_dimensions.values_list("code", flat=True)
        ),
        "calculation_failure": "propagate_for_mapped_entities",
        "dimension_failure": "propagate_only_required_dimensions",
        "missing_entity_mapping": "unknown",
    }


@transaction.atomic
def add_indicator_dependency(
    *, dependent: IndicatorVersion, prerequisite: IndicatorVersion, actor, dimensions=()
) -> IndicatorVersionDependency:
    """Add one prerequisite and its required dimensions under the graph lock."""
    from rpsd_config.exchange_agreement.models import DependencyRequiredDimension
    from rpsd_config.exchange_agreement.services.validation_catalog import (
        require_catalog_admin,
    )

    require_catalog_admin(actor)
    lock_indicator_graph()
    edge = IndicatorVersionDependency.objects.create(
        dependent=dependent, prerequisite=prerequisite
    )
    for dimension in dimensions:
        DependencyRequiredDimension.objects.create(dependency=edge, dimension=dimension)
    resolve_indicator_closure([dependent])
    return edge


def indicator_artifact_inventory() -> dict:
    """Inventory code provenance separately from removable legacy YAML files."""
    from rpsd_config.exchange_agreement.models import ConfigurationAsset

    return {
        "schema_version": "indicator-artifact-inventory-v1",
        "indicator_versions": [
            {
                "code": version.code,
                "indicator_code": version.indicator.code,
                "version": version.version,
                "status": version.status,
                "execution_engine": version.execution_engine,
                "execution_reference": version.execution_reference,
                "artifact_identifier": version.artifact_identifier,
            }
            for version in IndicatorVersion.objects.select_related(
                "indicator"
            ).order_by("code")
        ],
        "legacy_indicator_files": [
            {
                "asset_type": asset.asset_type,
                "code": asset.what,
                "version": asset.version,
                "checksum_sha256": asset.checksum_sha256,
                "status": asset.status,
            }
            for asset in ConfigurationAsset.objects.filter(
                asset_type="indicator_yaml"
            ).order_by("what", "version")
        ],
    }
