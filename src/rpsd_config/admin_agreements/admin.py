from django.contrib import admin, messages

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import Contract
from rpsd_config.exchange_agreement.services.publication import (
    PublishContractError,
    publish_contract,
)

from .proxies import (
    ContractAdminProxy,
    ContractDocumentAdminProxy,
    ContractIndicatorAdminProxy,
    ContractInvitationAdminProxy,
    ContractMembershipAdminProxy,
    ContractPublicationAdminProxy,
    FlowProfileAdminProxy,
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
        "contract_code",
        "client_agency",
        "contractor_company",
        "lot",
        "status",
        "contract_type_label",
        "version",
        "start_date",
        "end_date",
        "is_active_today",
    )
    list_filter = (
        "status",
        "contract_type",
        "client_agency",
        "contractor_company",
        "lot",
        "start_date",
    )
    search_fields = (
        "contract_code",
        "client_agency__name",
        "contractor_company__name",
        "lot__description",
        "tender_id",
    )
    date_hierarchy = "start_date"
    inlines = (
        ContractDocumentInline,
        ContractIndicatorInline,
        ContractMembershipInline,
        ContractInvitationInline,
    )
    autocomplete_fields = (
        "client_agency",
        "contractor_company",
        "lot",
        "replaced_by",
        "flow_profile",
    )
    list_select_related = (
        "client_agency",
        "contractor_company",
        "lot",
        "replaced_by",
        "flow_profile",
    )
    readonly_fields = ("contract_type", "version", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("contract_code", "contract_type", "version")}),
        ("Parties", {"fields": ("client_agency", "contractor_company", "lot")}),
        ("Validity", {"fields": ("start_date", "end_date")}),
        (
            "Lifecycle",
            {"fields": ("status", "closed_at", "closed_reason", "replaced_by")},
        ),
        ("Tender", {"fields": ("tender_id",)}),
        ("Program", {"fields": ("contract_program_file", "flow_profile")}),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )
    actions = ("publish_selected_contracts",)

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
                    "flow_profile",
                    "lot",
                    "status",
                    "closed_at",
                    "closed_reason",
                    "replaced_by",
                ]
            )
        return tuple(readonly)

    @admin.action(description="Publish selected contracts")
    def publish_selected_contracts(self, request, queryset):
        published = 0
        skipped_draft = 0
        skipped_other = 0
        failed = 0

        # Use concrete Contract queryset for locking/publish service.
        contracts = (
            Contract.objects.select_related(
                "lot",
                "client_agency",
                "contractor_company",
                "replaced_by",
                "flow_profile",
            )
            .filter(pk__in=queryset.values_list("pk", flat=True))
            .order_by("contract_code")
        )

        for contract in contracts:
            if contract.status == Contract.ContractStatus.DRAFT:
                skipped_draft += 1
                continue
            if contract.status == Contract.ContractStatus.CLOSED:
                skipped_other += 1
                continue
            try:
                publish_contract(contract=contract, user=request.user)
            except PublishContractError:
                failed += 1
                continue
            published += 1

        if published:
            self.message_user(
                request,
                f"Published {published} contract(s).",
                level=messages.SUCCESS,
            )
        if skipped_draft:
            self.message_user(
                request,
                f"Skipped {skipped_draft} draft contract(s):"
                " drafts are not publishable from this action.",
                level=messages.WARNING,
            )
        if skipped_other:
            self.message_user(
                request,
                f"Skipped {skipped_other} closed contract(s).",
                level=messages.WARNING,
            )
        if failed:
            self.message_user(
                request,
                f"Failed to publish {failed} contract(s)"
                " due to validation/permission errors.",
                level=messages.ERROR,
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
    list_filter = ("indicator__type", "indicator__structures__dataset")
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
    list_display = (
        "contract",
        "email",
        "role_to_assign",
        "status",
        "expires_at",
        "token",
    )
    list_filter = ("status", "role_to_assign", "contract")
    search_fields = ("contract__contract_code", "email", "token")
    autocomplete_fields = ("contract", "invited_by", "accepted_by")
    readonly_fields = ("token", "created_at", "updated_at")


@admin.register(FlowProfileAdminProxy)
class FlowProfileAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "schema_version", "is_active", "updated_at")
    list_filter = ("is_active", "schema_version")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ContractPublicationAdminProxy)
class ContractPublicationAdmin(admin.ModelAdmin):
    list_display = (
        "contract",
        "publication_version",
        "published_at",
        "published_by",
        "snapshot_schema_version",
    )
    list_filter = ("snapshot_schema_version", "published_at")
    search_fields = (
        "contract__contract_code",
        "snapshot_checksum",
        "published_by__username",
        "published_by__email",
    )
    autocomplete_fields = ("contract", "published_by")
    list_select_related = ("contract", "published_by")
    readonly_fields = (
        "contract",
        "publication_version",
        "published_at",
        "published_by",
        "snapshot_schema_version",
        "snapshot_checksum",
        "snapshot",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
