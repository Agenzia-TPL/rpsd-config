# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Configure the standard admin before autodiscovering Config's applications."""

from django.contrib.admin.apps import AdminConfig


class RpsdAdminConfig(AdminConfig):
    default_site = "rpsd_config.admin_site.RpsdAdminSite"

    def ready(self):
        super().ready()
        from django.contrib import admin

        from rpsd_config.admin_relations import register_related_admins

        register_related_admins(admin.site)
