# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models.expressions import DatabaseDefault
from django.utils import timezone
from django.utils.formats import date_format

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import DatasetSpecificationAsset
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    DatasetSpecificationTransitionError,
    deprecate_dataset_specification,
    publish_dataset_specification,
    withdraw_dataset_specification,
)

from .proxies import (
    ConfigurationAssetAdminProxy,
    ConfigurationAssetEventAdminProxy,
    DatasetAdminProxy,
    DatasetSpecificationAdminProxy,
    DatasetSpecificationStatusEventAdminProxy,
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


class _PlatformCatalogAdminMixin:
    @staticmethod
    def _can_manage(request):
        user = request.user
        return bool(
            user.is_superuser or resolve_user_agency_scope(user).is_platform_admin
        )

    def has_module_permission(self, request):
        return self._can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_add_permission(self, request):
        return self._can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self._can_manage(request)


@admin.register(DatasetAdminProxy)
class DatasetAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = ("code", "name", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("code", "name")
    ordering = ("code",)
    readonly_fields = ("created_at_human", "updated_at_human")


class DatasetSpecificationAssetInline(admin.TabularInline):
    model = DatasetSpecificationAsset
    extra = 0
    autocomplete_fields = ("configuration_asset",)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


@admin.register(DatasetSpecificationAdminProxy)
class DatasetSpecificationAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = (
        "code",
        "dataset",
        "version",
        "status",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "dataset")
    search_fields = ("code", "version", "description", "dataset__code")
    autocomplete_fields = ("dataset", "published_by")
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (DatasetSpecificationAssetInline,)
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(["dataset", "code", "version", "description", "metadata"])
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for specification in queryset:
            try:
                transition(specification, actor=request.user)
                completed += 1
            except (DatasetSpecificationTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(request, f"Updated specifications: {completed}")

    @admin.action(description="Publish selected specifications")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_dataset_specification)

    @admin.action(description="Deprecate selected specifications")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_dataset_specification)

    @admin.action(description="Withdraw selected specifications")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_dataset_specification)


@admin.register(DatasetSpecificationStatusEventAdminProxy)
class DatasetSpecificationStatusEventAdmin(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "dataset_specification",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("to_status", "changed_at")
    search_fields = ("dataset_specification__code", "changed_by__username")
    readonly_fields = (
        "dataset_specification",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StructureAdminProxy)
class StructureAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("dataset", "name", "created_at", "updated_at")
    list_filter = ("dataset",)
    search_fields = ("name", "dataset__code", "dataset__name")
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
        "structures__dataset__code",
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


@admin.register(ConfigurationAssetAdminProxy)
class ConfigurationAssetAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "asset_type",
        "what",
        "version",
        "label",
        "is_active",
        "status",
        "publish_status",
        "updated_at",
    )
    list_filter = ("asset_type", "what", "status", "is_active", "publish_status")
    search_fields = ("label", "original_filename", "storage_url", "checksum_sha256")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(ConfigurationAssetEventAdminProxy)
class ConfigurationAssetEventAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("event_type", "asset", "status", "attempts", "created_at")
    list_filter = ("event_type", "status")
    search_fields = ("routing_key", "last_error")
    readonly_fields = ("created_at_human", "updated_at_human", "payload")
