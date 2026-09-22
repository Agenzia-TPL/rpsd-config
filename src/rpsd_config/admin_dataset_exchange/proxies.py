# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ConfigurationAssetEvent,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationStatusEvent,
    Indicator,
    IndicatorDef,
    IndicatorProfile,
    IndicatorVersion,
    IndicatorVersionStatusEvent,
    InputFlowVersion,
    InputFlowVersionStatusEvent,
    NetexValidationProfile,
    OrchestrationFlowVersion,
    OrchestrationFlowVersionStatusEvent,
    ProcessingProfileVersion,
    ProcessingProfileVersionStatusEvent,
    RequirementFragment,
    RequirementFragmentStatusEvent,
    SiriValidationProfile,
    Structure,
)


class DatasetAdminProxy(Dataset):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"


class DatasetSpecificationAdminProxy(DatasetSpecification):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Dataset specification"
        verbose_name_plural = "Dataset specifications"


class DatasetSpecificationStatusEventAdminProxy(DatasetSpecificationStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Dataset specification status event"
        verbose_name_plural = "Dataset specification status events"


class RequirementFragmentAdminProxy(RequirementFragment):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Requirement fragment"
        verbose_name_plural = "Requirement fragments"


class RequirementFragmentStatusEventAdminProxy(RequirementFragmentStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Requirement fragment status event"
        verbose_name_plural = "Requirement fragment status events"


class IndicatorAdminProxy(Indicator):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Indicator"
        verbose_name_plural = "Indicators"


class IndicatorVersionAdminProxy(IndicatorVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Indicator version"
        verbose_name_plural = "Indicator versions"


class IndicatorVersionStatusEventAdminProxy(IndicatorVersionStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Indicator version status event"
        verbose_name_plural = "Indicator version status events"


class InputFlowVersionAdminProxy(InputFlowVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Input flow version"
        verbose_name_plural = "Input flow versions"


class InputFlowVersionStatusEventAdminProxy(InputFlowVersionStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Input flow version status event"
        verbose_name_plural = "Input flow version status events"


class OrchestrationFlowVersionAdminProxy(OrchestrationFlowVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Orchestration flow version"
        verbose_name_plural = "Orchestration flow versions"


class OrchestrationFlowVersionStatusEventAdminProxy(
    OrchestrationFlowVersionStatusEvent
):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Orchestration flow version status event"
        verbose_name_plural = "Orchestration flow version status events"


class ProcessingProfileVersionAdminProxy(ProcessingProfileVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Processing profile version"
        verbose_name_plural = "Processing profile versions"


class ProcessingProfileVersionStatusEventAdminProxy(
    ProcessingProfileVersionStatusEvent
):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Processing profile version status event"
        verbose_name_plural = "Processing profile version status events"


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
