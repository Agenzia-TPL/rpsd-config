# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ContractDependencyConfiguration,
    Dataset,
    DatasetSpecification,
    DatasetVersionRule,
    DependencyRequiredDimension,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
    IndicatorVersionInput,
    IndicatorVersionRule,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileVersion,
    ValidationRule,
    ValidationRuleVersion,
    ValidationTypeVersion,
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


class InputFlowVersionAdminProxy(InputFlowVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Input flow version"
        verbose_name_plural = "Input flow versions"


class OrchestrationFlowVersionAdminProxy(OrchestrationFlowVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Orchestration flow version"
        verbose_name_plural = "Orchestration flow versions"


class ProcessingProfileVersionAdminProxy(ProcessingProfileVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Processing profile version"
        verbose_name_plural = "Processing profile versions"


class ConfigurationAssetAdminProxy(ConfigurationAsset):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Configuration asset"
        verbose_name_plural = "Configuration assets"


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


class ValidationTypeVersionAdminProxy(ValidationTypeVersion):
    class Meta:
        proxy = True
        app_label = "admin_dataset_exchange"
        verbose_name = "Tipo e versione del linguaggio"
        verbose_name_plural = "Tipi e versioni dei linguaggi"


from rpsd_config.admin_audit.proxies import (  # noqa: E402, F401
    ConfigurationAssetEventAdminProxy,
    DatasetSpecificationStatusEventAdminProxy,
    IndicatorVersionStatusEventAdminProxy,
    InputFlowVersionStatusEventAdminProxy,
    OrchestrationFlowVersionStatusEventAdminProxy,
    ProcessingProfileVersionStatusEventAdminProxy,
    ValidationRuleStatusEventAdminProxy,
)
