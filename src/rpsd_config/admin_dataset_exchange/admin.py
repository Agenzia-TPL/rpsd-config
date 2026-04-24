# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django.contrib import admin
from django.db.models.expressions import DatabaseDefault
from django.utils import timezone
from django.utils.formats import date_format

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import (
    DatasetAdminProxy,
    IndicatorDefAdminProxy,
    IndicatorProfileAdminProxy,
    NetexValidationProfileAdminProxy,
    SiriValidationProfileAdminProxy,
    StructureAdminProxy,
)


class _HumanReadableTimestampsMixin:
    @staticmethod
    def _format_timestamp(value):
        if value is None or isinstance(value, DatabaseDefault):
            return "-"
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return date_format(timezone.localtime(value), "DATETIME_FORMAT")
        return str(value)

    @admin.display(description="Created at")
    def created_at_human(self, obj):
        if obj is None:
            return "-"
        return self._format_timestamp(getattr(obj, "created_at", None))

    @admin.display(description="Updated at")
    def updated_at_human(self, obj):
        if obj is None:
            return "-"
        return self._format_timestamp(getattr(obj, "updated_at", None))


@admin.register(DatasetAdminProxy)
class DatasetAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("slug", "name", "created_at", "updated_at")
    search_fields = ("slug", "name")
    ordering = ("slug",)
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(StructureAdminProxy)
class StructureAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("dataset", "name", "created_at", "updated_at")
    list_filter = ("dataset",)
    search_fields = ("name", "dataset__slug", "dataset__name")
    autocomplete_fields = ("dataset",)
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(IndicatorDefAdminProxy)
class IndicatorDefAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "type",
        "sql_procedure_name",
        "structures_list",
        "created_at",
        "updated_at",
    )
    list_filter = ("type", "structures__dataset")
    search_fields = (
        "code",
        "name",
        "description",
        "sql_procedure_name",
        "sql_snippet",
        "structures__name",
        "structures__dataset__slug",
    )
    autocomplete_fields = ("structures",)
    readonly_fields = ("created_at_human", "updated_at_human")

    @admin.display(description="Structures")
    def structures_list(self, obj):
        return ", ".join(str(structure) for structure in obj.structures.all())


@admin.register(NetexValidationProfileAdminProxy)
class NetexValidationProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("label", "file", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(SiriValidationProfileAdminProxy)
class SiriValidationProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "profile_type",
        "label",
        "file",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("profile_type", "is_active")
    search_fields = ("profile_type", "label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(IndicatorProfileAdminProxy)
class IndicatorProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("label", "file", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")
