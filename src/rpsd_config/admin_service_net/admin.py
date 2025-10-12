from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import (
    TripStop,  # real through model for inline
)

from .proxies import LineAdminProxy, LotAdminProxy, StopAdminProxy, TripAdminProxy


class LineInline(admin.TabularInline):
    model = LineAdminProxy
    extra = 0
    fields = ("code", "name", "authority")
    autocomplete_fields = ("authority",)

@admin.register(LotAdminProxy)
class LotAdmin(admin.ModelAdmin):
    list_display = ("id", "description")
    search_fields = ("description",)
    inlines = (LineInline,)
    ordering = ("id",)

@admin.register(LineAdminProxy)
class LineAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "lot", "authority")
    list_filter  = ("lot",)
    search_fields = ("code", "name", "lot__description", "authority__name")
    autocomplete_fields = ("lot", "authority")
    list_select_related = ("lot", "authority")

@admin.register(StopAdminProxy)
class StopAdmin(GISModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    gis_widget_kwargs = {"default_lon": 0, "default_lat": 0, "default_zoom": 2}

class TripStopInline(admin.TabularInline):
    model = TripStop
    extra = 0
    fields = ("stop", "sequence")
    autocomplete_fields = ("stop",)
    ordering = ("sequence",)

@admin.register(TripAdminProxy)
class TripAdmin(GISModelAdmin):
    list_display = ("code", "name", "line")
    list_filter  = ("line",)
    search_fields = ("code", "name", "line__code", "line__name")
    autocomplete_fields = ("line",)
    list_select_related = ("line",)
    inlines = (TripStopInline,)
    gis_widget_kwargs = {"default_lon": 0, "default_lat": 0, "default_zoom": 2}
