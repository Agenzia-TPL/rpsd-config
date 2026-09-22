# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db.models.expressions import DatabaseDefault
from django.utils import timezone
from django.utils.formats import date_format

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractIndicatorConfiguration,
    ContractInputSelection,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionError,
    approve_contract_revision,
    withdraw_contract_revision,
)
from rpsd_config.exchange_agreement.services.publication import (
    PublishContractError,
    publish_contract,
)

from .proxies import (
    ContractAdminProxy,
    ContractConfigurationRevisionAdminProxy,
    ContractDocumentAdminProxy,
    ContractIndicatorAdminProxy,
    ContractInvitationAdminProxy,
    ContractMembershipAdminProxy,
    ContractPublicationAdminProxy,
    FlowProfileAdminProxy,
    OperationalFlowAdminProxy,
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


class ContractConfigurationRevisionInline(admin.TabularInline):
    model = ContractConfigurationRevisionAdminProxy
    extra = 0
    fields = ("code", "revision_number", "valid_from", "status")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _HumanReadableTimestampsMixin:
    @staticmethod
    def _format_timestamp(value):
        if value is None or isinstance(value, DatabaseDefault):
            return "-"
        if not isinstance(value, datetime):
            return str(value)
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return date_format(timezone.localtime(value), "DATETIME_FORMAT")

    @admin.display(description="Created at")
    def created_at_human(self, obj):
        if obj is None:
            return "-"
        return self._format_timestamp(getattr(obj, "created_at", None))

    @admin.display(description="Updated at")
    def updated_at_human(self, obj):
        if obj is None:
            return "-"
        return self._format_timestamp(getattr(obj, "updated_at", None))


@admin.register(ContractAdminProxy)
class ContractAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
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
        ContractConfigurationRevisionInline,
    )
    autocomplete_fields = (
        "client_agency",
        "contractor_company",
        "governing_authority",
        "lot",
        "replaced_by",
        "flow_profile",
    )
    list_select_related = (
        "client_agency",
        "contractor_company",
        "governing_authority",
        "lot",
        "replaced_by",
        "flow_profile",
    )
    readonly_fields = (
        "contract_type",
        "version",
        "created_at_human",
        "updated_at_human",
    )
    fieldsets = (
        (None, {"fields": ("contract_code", "contract_type", "version")}),
        (
            "Parties",
            {
                "fields": (
                    "client_agency",
                    "contractor_company",
                    "governing_authority",
                    "lot",
                )
            },
        ),
        ("Validity", {"fields": ("start_date", "end_date")}),
        (
            "Lifecycle",
            {"fields": ("status", "closed_at", "closed_reason", "replaced_by")},
        ),
        ("Tender", {"fields": ("tender_id",)}),
        ("Program", {"fields": ("contract_program_file", "flow_profile")}),
        ("Audit", {"fields": ("created_at_human", "updated_at_human")}),
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
                    "governing_authority",
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
class ContractDocumentAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("contract", "name", "file", "created_at")
    search_fields = ("contract__contract_code", "name", "file")
    autocomplete_fields = ("contract",)
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(ContractIndicatorAdminProxy)
class ContractIndicatorAdmin(admin.ModelAdmin):
    list_display = ("contract", "logical_indicator", "indicator")
    list_filter = ("indicator__type", "indicator__structures__dataset")
    search_fields = ("contract__contract_code", "indicator__code", "indicator__name")
    autocomplete_fields = ("contract", "indicator")


class ContractInputSelectionInline(admin.TabularInline):
    model = ContractInputSelection
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "processing_profile_input_flow":
            kwargs["queryset"] = ProcessingProfileInputFlow.objects.filter(
                processing_profile_version__status=ProcessingProfileVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


class ContractIndicatorConfigurationInline(admin.TabularInline):
    model = ContractIndicatorConfiguration
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "processing_profile_indicator_version":
            kwargs["queryset"] = ProcessingProfileIndicatorVersion.objects.filter(
                processing_profile_version__status=ProcessingProfileVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


@admin.register(ContractConfigurationRevisionAdminProxy)
class ContractConfigurationRevisionAdmin(
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = (
        "code",
        "contract",
        "revision_number",
        "processing_profile_version",
        "valid_from",
        "status",
        "approved_at",
    )
    list_filter = ("status", "valid_from", "processing_profile_version")
    search_fields = ("code", "contract__contract_code", "change_reason")
    autocomplete_fields = (
        "contract",
        "created_by",
        "approved_by",
        "withdrawn_by",
    )
    readonly_fields = (
        "status",
        "snapshot_schema_version",
        "configuration_snapshot",
        "snapshot_checksum",
        "approved_by",
        "approved_at",
        "withdrawn_by",
        "withdrawn_at",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (ContractInputSelectionInline, ContractIndicatorConfigurationInline)
    actions = ("approve_selected", "withdraw_selected")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "processing_profile_version":
            kwargs["queryset"] = ProcessingProfileVersion.objects.filter(
                status=ProcessingProfileVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                [
                    "contract",
                    "revision_number",
                    "code",
                    "processing_profile_version",
                    "valid_from",
                    "change_reason",
                    "replaces_revision",
                ]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for revision in queryset:
            try:
                transition(revision, actor=request.user)
                completed += 1
            except (ContractRevisionError, ValidationError) as exc:
                self.message_user(request, str(exc), level=messages.ERROR)
        if completed:
            self.message_user(
                request,
                f"Updated contract revisions: {completed}",
                level=messages.SUCCESS,
            )

    @admin.action(description="Approve selected contract revisions")
    def approve_selected(self, request, queryset):
        self._transition_selected(request, queryset, approve_contract_revision)

    @admin.action(description="Withdraw selected contract revisions")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_contract_revision)


@admin.register(ContractMembershipAdminProxy)
class ContractMembershipAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("contract", "user", "role", "created_at")
    list_filter = ("role",)
    search_fields = ("contract__contract_code", "user__username", "user__email")
    autocomplete_fields = ("contract", "user", "created_by")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(ContractInvitationAdminProxy)
class ContractInvitationAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
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
    readonly_fields = ("token", "created_at_human", "updated_at_human")


@admin.register(FlowProfileAdminProxy)
class FlowProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "schema_version",
        "is_active",
        "contract_count",
        "updated_at",
    )
    list_filter = ("is_active", "schema_version")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at_human", "updated_at_human")

    def contract_count(self, obj):
        return obj.contracts.count()

    contract_count.short_description = "Contracts"

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.contracts.exists():
            fields.extend(["code", "schema_version", "options"])
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.contracts.exists():
            return False
        return super().has_delete_permission(request, obj)


@admin.register(OperationalFlowAdminProxy)
class OperationalFlowAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "engine",
        "supported_what",
        "deployment_name",
        "status",
        "version",
        "updated_at",
    )
    list_filter = ("engine", "status", "supported_what")
    search_fields = ("code", "deployment_name", "supported_what", "description")
    readonly_fields = ("created_at_human", "updated_at_human")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.is_referenced_by_flow_profiles():
            fields.extend(["code", "engine", "deployment_name", "supported_what"])
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_referenced_by_flow_profiles():
            return False
        return super().has_delete_permission(request, obj)


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
