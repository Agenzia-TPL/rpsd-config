from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from .proxies import AgencyAdminProxy, AuthorityAdminProxy, CompanyAdminProxy


@admin.register(AgencyAdminProxy)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(CompanyAdminProxy)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(AuthorityAdminProxy)
class AuthorityAdmin(GISModelAdmin):
    list_display = ("name", "authority_type", "created_at", "updated_at")
    list_filter = ("authority_type",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    gis_widget_kwargs = {"default_lon": 0, "default_lat": 0, "default_zoom": 2}
