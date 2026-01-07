from django.contrib import admin

#from django.contrib.gis.forms import OSMWidget
from django.contrib.gis.db.models import GeometryField

#from django.urls import reverse
#from django.utils.html import format_html
#import django_filters
from leaflet.admin import LeafletGeoAdmin
from leaflet.forms.widgets import LeafletWidget

from ..admin_service_net.proxies import Route
from .proxies import AgencyAdminProxy, AuthorityAdminProxy, CompanyAdminProxy

# oppure: from leaflet.forms.widgets import LeafletWidget
# e usare formfield_overrides con LeafletWidget

class GeomAdmin(LeafletGeoAdmin):
    #change_form_template = "admin/custom_admin.html"
    formfield_overrides = {
        GeometryField: {"widget": LeafletWidget(attrs={
            "map_height": "600px",   # <- qui la tua altezza
            "map_width": "100%",     # opzionale
        })}
    }


class RouteInline(admin.TabularInline):
    model = Route
    # Campi da mostrare nella tabella inline
    # 'authority' non serve, perché è già l'autorità che stai modificando
    list_display = ('code', 'name', 'lot')
    # Rende i campi non modificabili da qui (opzionale)
    # readonly_fields = ('code', 'name', 'lot')
    # Se hai molti 'Lot', usa l'autocompletamento
    autocomplete_fields = ['lot']
    extra = 0
    # Permette di cercare tra le linee (molto utile se un'autorità ne ha tante)
    search_fields = ('code', 'name')

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
    # ⬇️ CORREZIONE: Usa 'lon', 'lat' e 'zoom'
    #gis_widget_kwargs = {"lon": 0, "lat": 0, "zoom": 2}
    # Se continui ad avere problemi, prova a specificare il widget esplicitamente
    #gis_widget = OSMWidget
    inlines = [RouteInline]
