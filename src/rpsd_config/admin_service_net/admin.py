# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib import admin

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import LotAdminProxy


@admin.register(LotAdminProxy)
class LotAdmin(admin.ModelAdmin):
    list_display = ("id", "short_description", "description")
    search_fields = ("short_description", "description")
    ordering = ("id",)
