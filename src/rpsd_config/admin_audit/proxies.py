# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement import models


class ConfigurationAssetEventAdminProxy(models.ConfigurationAssetEvent):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Notifiche asset"
        verbose_name_plural = "Notifiche asset"
        permissions = [
            ("retry_configurationassetevent", "Can retry asset notifications")
        ]


class DatasetSpecificationStatusEventAdminProxy(models.DatasetSpecificationStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico specifiche dataset"
        verbose_name_plural = "Storico specifiche dataset"


class IndicatorVersionStatusEventAdminProxy(models.IndicatorVersionStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico versioni indicatore"
        verbose_name_plural = "Storico versioni indicatore"


class InputFlowVersionStatusEventAdminProxy(models.InputFlowVersionStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico processi di input"
        verbose_name_plural = "Storico processi di input"


class OrchestrationFlowVersionStatusEventAdminProxy(
    models.OrchestrationFlowVersionStatusEvent
):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico orchestratori"
        verbose_name_plural = "Storico orchestratori"


class ProcessingProfileVersionStatusEventAdminProxy(
    models.ProcessingProfileVersionStatusEvent
):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico profili tecnici"
        verbose_name_plural = "Storico profili tecnici"


class ValidationRuleStatusEventAdminProxy(models.ValidationRuleStatusEvent):
    class Meta:
        proxy = True
        app_label = "admin_audit"
        verbose_name = "Storico regole di validazione"
        verbose_name_plural = "Storico regole di validazione"
