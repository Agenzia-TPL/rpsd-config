# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import Dataset, IndicatorDef, Structure


class DatasetAdminProxy(Dataset):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"


class StructureAdminProxy(Structure):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Structure"
        verbose_name_plural = "Structures"


class IndicatorDefAdminProxy(IndicatorDef):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Indicator definition"
        verbose_name_plural = "Indicator definitions"
