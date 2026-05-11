# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ConfigurationAssetEvent,
    Dataset,
    IndicatorDef,
    IndicatorProfile,
    NetexValidationProfile,
    SiriValidationProfile,
    Structure,
)


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


class NetexValidationProfileAdminProxy(NetexValidationProfile):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Netex validation profile"
        verbose_name_plural = "Netex validation profiles"


class SiriValidationProfileAdminProxy(SiriValidationProfile):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "SIRI validation profile"
        verbose_name_plural = "SIRI validation profiles"


class IndicatorProfileAdminProxy(IndicatorProfile):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Indicator profile"
        verbose_name_plural = "Indicator profiles"


class ConfigurationAssetAdminProxy(ConfigurationAsset):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Configuration asset"
        verbose_name_plural = "Configuration assets"


class ConfigurationAssetEventAdminProxy(ConfigurationAssetEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Configuration asset event"
        verbose_name_plural = "Configuration asset events"
