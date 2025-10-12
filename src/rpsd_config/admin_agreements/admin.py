from django.contrib import admin

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import (
    ContractAdminProxy,
    ContractDocumentAdminProxy,
    ContractIndicatorAdminProxy,
)


class ContractDocumentInline(admin.TabularInline):
    model = ContractDocumentAdminProxy
    extra = 0
    fields = ("name", "file")
    show_change_link = True

class ContractIndicatorInline(admin.TabularInline):
    model = ContractIndicatorAdminProxy
    extra = 0
    fields = ("indicator", "params")
    autocomplete_fields = ("indicator",)
    show_change_link = True

@admin.register(ContractAdminProxy)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "contract_code", "client_agency", "contractor_company", "lot",
        "contract_type_label", "version", "start_date", "end_date", "is_active_today",
    )
    list_filter = ("contract_type", "client_agency", "contractor_company", "lot", "start_date")
    search_fields = ("contract_code", "client_agency__name", "contractor_company__name",
                     "lot__description", "tender_id")
    date_hierarchy = "start_date"
    inlines = (ContractDocumentInline, ContractIndicatorInline)
    autocomplete_fields = ("client_agency", "contractor_company", "lot")
    list_select_related = ("client_agency", "contractor_company", "lot")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("contract_code", "contract_type", "version")}),
        ("Parties", {"fields": ("client_agency", "contractor_company", "lot")}),
        ("Validity", {"fields": ("start_date", "end_date")}),
        ("Tender", {"fields": ("tender_id",)}),
        ("Program", {"fields": ("contract_program_file",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

@admin.register(ContractDocumentAdminProxy)
class ContractDocumentAdmin(admin.ModelAdmin):
    list_display = ("contract", "name", "file", "created_at")
    search_fields = ("contract__contract_code", "name", "file")
    autocomplete_fields = ("contract",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(ContractIndicatorAdminProxy)
class ContractIndicatorAdmin(admin.ModelAdmin):
    list_display = ("contract", "indicator")
    list_filter  = ("indicator__type", "indicator__structure__dataset")
    search_fields = ("contract__contract_code", "indicator__code", "indicator__name")
    autocomplete_fields = ("contract", "indicator")
