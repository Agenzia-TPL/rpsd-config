from django.contrib import admin

#from django.contrib.gis.forms import OSMWidget
from django.contrib.gis.db.models import GeometryField

#from django.urls import reverse
#from django.utils.html import format_html
#import django_filters
from leaflet.admin import LeafletGeoAdmin
from leaflet.forms.widgets import LeafletWidget

from .proxies import AgencyAdminProxy, AuthorityAdminProxy, CompanyAdminProxy

# Alternative setup: import `LeafletWidget` and configure it via `formfield_overrides`.

class GeomAdmin(LeafletGeoAdmin):
    #change_form_template = "admin/custom_admin.html"
    formfield_overrides = {
        GeometryField: {"widget": LeafletWidget(attrs={
            "map_height": "600px",   # adjust as needed
            "map_width": "100%",     # optional
        })}
    }


@admin.register(AgencyAdminProxy)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at", "updated_at")
#    list_display = ("name", "description")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(CompanyAdminProxy)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_at", "updated_at")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(AuthorityAdminProxy)
class AuthorityAdmin(GeomAdmin):
    list_display = ("name", "authority_type", "created_at", "updated_at")
    list_filter = ("authority_type",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    # Use 'lon', 'lat' and 'zoom' if you enable widget kwargs explicitly.
    #gis_widget_kwargs = {"lon": 0, "lat": 0, "zoom": 2}
    # If rendering issues persist, try setting the widget explicitly.
    #gis_widget = OSMWidget
