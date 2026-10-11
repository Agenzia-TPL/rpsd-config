# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Per-revision values for selected and implicitly required indicators."""

from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    ContractDependencyConfiguration,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    require_revision_preparer,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    resolve_indicator_closure,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)
from rpsd_config.exchange_agreement.services.revision_registry import (
    validate_business_configuration,
)


@transaction.atomic
def save_revision_indicator_values(revision, *, version_code: str, values: dict, actor):
    """Store only this indicator's values, with contract scope and draft locking."""
    locked = (
        ContractConfigurationRevision.objects.select_for_update()
        .select_related("contract")
        .get(pk=revision.pk)
    )
    require_revision_preparer(user=actor, contract=locked.contract)
    if locked.status != "draft":
        raise ValidationError("Approved revision values are immutable.")
    selected = {
        c.processing_profile_indicator_version.indicator_version_id: c
        for c in locked.indicator_configurations.select_related(
            "processing_profile_indicator_version__indicator_version"
        )
    }
    closure = resolve_indicator_closure(
        [
            c.processing_profile_indicator_version.indicator_version
            for c in selected.values()
        ]
    )
    version = next((v for v in closure["versions"] if v.code == version_code), None)
    if version is None:
        raise ValidationError(
            "The indicator does not belong to the effective revision."
        )
    fields = ("parameters", "thresholds", "aggregation", "penalties")
    if not isinstance(values, dict) or set(values) != set(fields):
        raise ValidationError("Provide all four configuration objects.")
    for field in fields:
        validate_business_configuration(values[field], field_name=field)
    validate_indicator_parameters(version.parameter_schema, values["parameters"])
    config = selected.get(version.pk)
    if config is None:
        config = ContractDependencyConfiguration.objects.filter(
            revision=locked, indicator_version=version
        ).first() or ContractDependencyConfiguration(
            revision=locked, indicator_version=version
        )
    for field in fields:
        setattr(config, field, values[field])
    config.save()
    return config


def revision_indicator_value_rows(revision) -> list[dict]:
    """Show independent values and their role without implying execution results."""
    import json

    selected = {
        c.processing_profile_indicator_version.indicator_version_id: c
        for c in revision.indicator_configurations.select_related(
            "processing_profile_indicator_version__indicator_version"
        )
    }
    implicit = {
        c.indicator_version_id: c for c in revision.dependency_configurations.all()
    }
    closure = resolve_indicator_closure(
        [
            c.processing_profile_indicator_version.indicator_version
            for c in selected.values()
        ]
    )
    rows = []
    for version in closure["versions"]:
        config = selected.get(version.pk) or implicit.get(version.pk)
        rows.append(
            {
                "code": version.code,
                "role": "selezionato" if version.pk in selected else "dipendenza",
                "values": [
                    {
                        "name": field,
                        "json": json.dumps(
                            getattr(config, field) if config else {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                    for field in (
                        "parameters",
                        "thresholds",
                        "aggregation",
                        "penalties",
                    )
                ],
            }
        )
    return rows
