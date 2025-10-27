from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from ..admin_service_net.proxies import Line
from .proxies import AgencyAdminProxy, AuthorityAdminProxy, CompanyAdminProxy


class LineInline(admin.TabularInline):
    model = Line
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
class AuthorityAdmin(GISModelAdmin):
    list_display = ("name", "authority_type", "created_at", "updated_at")
    list_filter = ("authority_type",)
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    # ⬇️ CORREZIONE: Usa 'lon', 'lat' e 'zoom'
    #gis_widget_kwargs = {"lon": 0, "lat": 0, "zoom": 2}
    # Se continui ad avere problemi, prova a specificare il widget esplicitamente
    #gis_widget = OSMWidget
    inlines = [LineInline]

