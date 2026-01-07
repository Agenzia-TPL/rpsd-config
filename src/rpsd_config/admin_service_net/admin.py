from django.contrib import admin
from django.contrib.gis.db.models import GeometryField
from leaflet.admin import LeafletGeoAdmin
from leaflet.forms.widgets import LeafletWidget

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import (
    TripStop,  # real through model for inline
)

from .proxies import LotAdminProxy, RouteAdminProxy, StopAdminProxy, TripAdminProxy


class GeomAdmin(LeafletGeoAdmin):
    formfield_overrides = {
        GeometryField: {
            "widget": LeafletWidget(
                attrs={
                    "map_height": "600px",
                    "map_width": "100%",
                }
            )
        }
    }


class RouteInline(admin.TabularInline):
    model = RouteAdminProxy
    extra = 0
    fields = ("code", "name", "authority")
    autocomplete_fields = ("authority",)

@admin.register(LotAdminProxy)
class LotAdmin(admin.ModelAdmin):
    list_display = ("id", "description")
    search_fields = ("description",)
    inlines = (RouteInline,)
    ordering = ("id",)

@admin.register(RouteAdminProxy)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "lot", "authority")
    list_filter  = ("lot",)
    search_fields = ("code", "name", "lot__description", "authority__name")
    autocomplete_fields = ("lot", "authority")
    list_select_related = ("lot", "authority")

@admin.register(StopAdminProxy)
class StopAdmin(GeomAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")

class TripStopInline(admin.TabularInline):
    model = TripStop
    extra = 0
    fields = ("stop", "sequence")
    autocomplete_fields = ("stop",)
    ordering = ("sequence",)

@admin.register(TripAdminProxy)
class TripAdmin(GeomAdmin):
    list_display = ("code", "name", "route")
    list_filter  = ("route",)
    search_fields = ("code", "name", "route__code", "route__name")
    autocomplete_fields = ("route",)
    list_select_related = ("route",)
    inlines = (TripStopInline,)
