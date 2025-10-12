from django.contrib import admin

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import DatasetAdminProxy, IndicatorDefAdminProxy, StructureAdminProxy


@admin.register(DatasetAdminProxy)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("slug", "name", "created_at", "updated_at")
    search_fields = ("slug", "name")
    ordering = ("slug",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(StructureAdminProxy)
class StructureAdmin(admin.ModelAdmin):
    list_display = ("dataset", "name", "validation_schema", "created_at", "updated_at")
    list_filter = ("dataset",)
    search_fields = ("name", "dataset__slug", "dataset__name")
    autocomplete_fields = ("dataset",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(IndicatorDefAdminProxy)
class IndicatorDefAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "type", "structure", "created_at", "updated_at")
    list_filter  = ("type", "structure__dataset")
    search_fields = ("code", "name", "description", "structure__name", "structure__dataset__slug")
    autocomplete_fields = ("structure",)
    readonly_fields = ("created_at", "updated_at")
