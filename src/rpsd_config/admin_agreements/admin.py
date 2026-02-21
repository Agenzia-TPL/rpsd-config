from django.contrib import admin

from rpsd_config import admin_hidden  # noqa: F401

from .proxies import (
    ContractAdminProxy,
    ContractDocumentAdminProxy,
    ContractInvitationAdminProxy,
    ContractIndicatorAdminProxy,
    ContractMembershipAdminProxy,
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


class ContractMembershipInline(admin.TabularInline):
    model = ContractMembershipAdminProxy
    extra = 0
    fields = ("user", "role", "created_by")
    autocomplete_fields = ("user", "created_by")
    show_change_link = True


class ContractInvitationInline(admin.TabularInline):
    model = ContractInvitationAdminProxy
    extra = 0
    fields = ("email", "role_to_assign", "token", "status", "expires_at", "invited_by")
    readonly_fields = ("token",)
    autocomplete_fields = ("invited_by",)
    show_change_link = True

@admin.register(ContractAdminProxy)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "contract_code", "client_agency", "contractor_company", "lot",
        "status", "contract_type_label", "version", "start_date", "end_date", "is_active_today",
    )
    list_filter = (
        "status",
        "contract_type",
        "client_agency",
        "contractor_company",
        "lot",
        "start_date",
    )
    search_fields = ("contract_code", "client_agency__name", "contractor_company__name",
                     "lot__description", "tender_id")
    date_hierarchy = "start_date"
    inlines = (
        ContractDocumentInline,
        ContractIndicatorInline,
        ContractMembershipInline,
        ContractInvitationInline,
    )
    autocomplete_fields = ("client_agency", "contractor_company", "lot", "replaced_by")
    list_select_related = ("client_agency", "contractor_company", "lot", "replaced_by")
    readonly_fields = ("contract_type", "version", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("contract_code", "contract_type", "version")}),
        ("Parties", {"fields": ("client_agency", "contractor_company", "lot")}),
        ("Validity", {"fields": ("start_date", "end_date")}),
        ("Lifecycle", {"fields": ("status", "closed_at", "closed_reason", "replaced_by")}),
        ("Tender", {"fields": ("tender_id",)}),
        ("Program", {"fields": ("contract_program_file",)}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.status == obj.ContractStatus.CLOSED:
            readonly.extend(
                [
                    "contract_code",
                    "client_agency",
                    "contractor_company",
                    "start_date",
                    "end_date",
                    "tender_id",
                    "contract_type",
                    "version",
                    "contract_program_file",
                    "lot",
                    "status",
                    "closed_at",
                    "closed_reason",
                    "replaced_by",
                ]
            )
        return tuple(readonly)

@admin.register(ContractDocumentAdminProxy)
class ContractDocumentAdmin(admin.ModelAdmin):
    list_display = ("contract", "name", "file", "created_at")
    search_fields = ("contract__contract_code", "name", "file")
    autocomplete_fields = ("contract",)
    readonly_fields = ("created_at", "updated_at")

@admin.register(ContractIndicatorAdminProxy)
class ContractIndicatorAdmin(admin.ModelAdmin):
    list_display = ("contract", "indicator")
    list_filter  = ("indicator__type", "indicator__structures__dataset")
    search_fields = ("contract__contract_code", "indicator__code", "indicator__name")
    autocomplete_fields = ("contract", "indicator")


@admin.register(ContractMembershipAdminProxy)
class ContractMembershipAdmin(admin.ModelAdmin):
    list_display = ("contract", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("contract__contract_code", "user__username", "user__email")
    autocomplete_fields = ("contract", "user", "created_by")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ContractInvitationAdminProxy)
class ContractInvitationAdmin(admin.ModelAdmin):
    list_display = ("contract", "email", "role_to_assign", "status", "expires_at", "token")
    list_filter = ("status", "role_to_assign", "contract")
    search_fields = ("contract__contract_code", "email", "token")
    autocomplete_fields = ("contract", "invited_by", "accepted_by")
    readonly_fields = ("token", "created_at", "updated_at")
