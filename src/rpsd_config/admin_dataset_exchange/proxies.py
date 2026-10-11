# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ConfigurationAssetEvent,
    ContractDependencyConfiguration,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationStatusEvent,
    DatasetVersionRule,
    DependencyRequiredDimension,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
    IndicatorVersionInput,
    IndicatorVersionRule,
    IndicatorVersionStatusEvent,
    InputFlowVersion,
    InputFlowVersionStatusEvent,
    NetexValidationProfile,
    OrchestrationFlowVersion,
    OrchestrationFlowVersionStatusEvent,
    ProcessingProfileVersion,
    ProcessingProfileVersionStatusEvent,
    SiriValidationProfile,
    ValidationRule,
    ValidationRuleStatusEvent,
    ValidationRuleVersion,
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


class ValidationRuleAdminProxy(ValidationRule):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "ValidationRule"


class ValidationRuleVersionAdminProxy(ValidationRuleVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "ValidationRuleVersion"


class ValidationRuleStatusEventAdminProxy(ValidationRuleStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "ValidationRuleStatusEvent"


class DatasetVersionRuleAdminProxy(DatasetVersionRule):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "DatasetVersionRule"


class IndicatorDimensionAdminProxy(IndicatorDimension):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "IndicatorDimension"


class IndicatorVersionRuleAdminProxy(IndicatorVersionRule):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "IndicatorVersionRule"


class IndicatorVersionInputAdminProxy(IndicatorVersionInput):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "IndicatorVersionInput"


class IndicatorVersionDependencyAdminProxy(IndicatorVersionDependency):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "IndicatorVersionDependency"


class DependencyRequiredDimensionAdminProxy(DependencyRequiredDimension):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "DependencyRequiredDimension"


class ContractDependencyConfigurationAdminProxy(ContractDependencyConfiguration):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "ContractDependencyConfiguration"
