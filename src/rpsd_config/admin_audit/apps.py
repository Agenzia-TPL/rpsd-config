# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.apps import AppConfig


class AdminAuditConfig(AppConfig):
    name = "rpsd_config.admin_audit"
    verbose_name = "Storico e notifiche"
