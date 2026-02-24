from django.contrib import admin

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import LotAdminProxy

@admin.register(LotAdminProxy)
class LotAdmin(admin.ModelAdmin):
    list_display = ("id", "short_description", "description")
    search_fields = ("short_description", "description")
    ordering = ("id",)
