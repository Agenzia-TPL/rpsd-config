# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent bootstrap for the initial dataset catalog."""

from dataclasses import dataclass

from django.db import transaction

from rpsd_config.exchange_agreement.models import Dataset, DatasetSpecification
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)


@dataclass(frozen=True)
class InitialDatasetSpecification:
    dataset_code: str
    dataset_name: str
    specification_code: str
    version: str = "001"


INITIAL_DATASET_SPECIFICATIONS = (
    InitialDatasetSpecification("netex", "NeTEx", "netex-ita_v001"),
    InitialDatasetSpecification("siri-pt", "SIRI PT", "siri-pt_v001"),
    InitialDatasetSpecification("siri-et", "SIRI ET", "siri-et_v001"),
    InitialDatasetSpecification("siri-st", "SIRI ST", "siri-st_v001"),
    InitialDatasetSpecification("siri-sm", "SIRI SM", "siri-sm_v001"),
    InitialDatasetSpecification("siri-vm", "SIRI VM", "siri-vm_v001"),
    InitialDatasetSpecification("siri-ct", "SIRI CT", "siri-ct_v001"),
    InitialDatasetSpecification("siri-cm", "SIRI CM", "siri-cm_v001"),
    InitialDatasetSpecification("siri-gm", "SIRI GM", "siri-gm_v001"),
    InitialDatasetSpecification("siri-fm", "SIRI FM", "siri-fm_v001"),
    InitialDatasetSpecification("siri-sx", "SIRI SX", "siri-sx_v001"),
)


@transaction.atomic
def ensure_initial_dataset_catalog() -> list[DatasetSpecification]:
    """Create missing initial datasets and specifications without rewriting them."""

    specifications = []
    for initial in INITIAL_DATASET_SPECIFICATIONS:
        dataset, _created = Dataset.objects.update_or_create(
            code=initial.dataset_code,
            defaults={
                "name": initial.dataset_name,
                "description": f"Logical {initial.dataset_name} dataset.",
                "status": Dataset.Status.ACTIVE,
            },
        )
        specification, created = DatasetSpecification.objects.get_or_create(
            code=initial.specification_code,
            defaults={
                "dataset": dataset,
                "version": initial.version,
                "description": (
                    f"Initial {initial.dataset_name} technical specification."
                ),
                "metadata": {},
            },
        )
        if created:
            specification = publish_dataset_specification(specification)
        specifications.append(specification)
    return specifications
