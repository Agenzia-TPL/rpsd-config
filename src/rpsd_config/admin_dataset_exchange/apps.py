# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.apps import AppConfig


class AdminDatasetExchangeConfig(AppConfig):
    name = "rpsd_config.admin_dataset_exchange"
    label = "admin_dataset_exchange"  # app_label usato dall'admin
    verbose_name = "DatasetExchange"  # intestazione nel menu admin
