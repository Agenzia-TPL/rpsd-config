# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.expressions import DatabaseDefault
from django.forms.models import BaseInlineFormSet
from django.utils import timezone
from django.utils.formats import date_format

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.admin_guidance import GuidedAdminMixin, GuidedInlineMixin
from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevisionStatusEvent,
    ContractDependencyConfiguration,
    ContractInputSelection,
    ContractRevisionIndicator,
    IndicatorVersion,
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
    ContractInvitationAdminProxy,
    ContractMembershipAdminProxy,
    ContractPublicationAdminProxy,
)


class ContractDocumentInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractDocumentAdminProxy
    extra = 0
    fields = ("name", "file")
    show_change_link = True


class ContractMembershipInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractMembershipAdminProxy
    extra = 0
    fields = ("user", "role", "created_by")
    autocomplete_fields = ("user", "created_by")
    show_change_link = True


class ContractInvitationInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractInvitationAdminProxy
    extra = 0
    fields = ("email", "role_to_assign", "token", "status", "expires_at", "invited_by")
    readonly_fields = ("token",)
    autocomplete_fields = ("invited_by",)
    show_change_link = True


class ContractConfigurationRevisionInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractConfigurationRevisionAdminProxy
    extra = 0
    fields = ("code", "revision_number", "valid_from", "status")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _HumanReadableTimestampsMixin(GuidedAdminMixin):
    @staticmethod
    def _format_timestamp(value):
        if value is None or isinstance(value, DatabaseDefault):
            return "-"
        if not isinstance(value, datetime):
            return str(value)
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return date_format(timezone.localtime(value), "DATETIME_FORMAT")

    @admin.display(description="Creazione")
    def created_at_human(self, obj):
        if obj is None:
            return "-"
        return self._format_timestamp(getattr(obj, "created_at", None))

    @admin.display(description="Ultimo aggiornamento")
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
    )
    list_select_related = (
        "client_agency",
        "contractor_company",
        "governing_authority",
        "lot",
        "replaced_by",
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
        ("Program", {"fields": ("contract_program_file",)}),
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
                    "lot",
                    "status",
                    "closed_at",
                    "closed_reason",
                    "replaced_by",
                ]
            )
        return tuple(readonly)

    @admin.action(description="Pubblica i contratti selezionati")
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
                f"Contratti pubblicati: {published}.",
                level=messages.SUCCESS,
            )
        if skipped_draft:
            self.message_user(
                request,
                f"Contratti in bozza ignorati: {skipped_draft}."
                " Le bozze non sono pubblicabili con questa azione.",
                level=messages.WARNING,
            )
        if skipped_other:
            self.message_user(
                request,
                f"Contratti chiusi ignorati: {skipped_other}.",
                level=messages.WARNING,
            )
        if failed:
            self.message_user(
                request,
                f"Pubblicazione non riuscita per {failed} contratti"
                " per errori di validazione o permessi.",
                level=messages.ERROR,
            )


@admin.register(ContractDocumentAdminProxy)
class ContractDocumentAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("contract", "name", "file", "created_at")
    search_fields = ("contract__contract_code", "name", "file")
    autocomplete_fields = ("contract",)
    readonly_fields = ("created_at_human", "updated_at_human")


class ContractInputSelectionInline(GuidedInlineMixin, admin.TabularInline):
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


class ContractRevisionIndicatorInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractRevisionIndicator
    extra = 0
    exclude = ("thresholds", "penalties")
    readonly_fields = ("evaluation_links",)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj and obj.status != "draft":
            return (*fields, "thresholds", "penalties")
        return fields

    @admin.display(description="Soglie e penali")
    def evaluation_links(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html

        if not obj.pk:
            return "Salva prima la selezione dell'indicatore."
        return format_html(
            '<a href="{}?owner_id={}">Nuova soglia</a> · '
            '<a href="{}?owner_id={}">Nuova penale</a> · '
            '<a href="{}">Configurazione completa</a>',
            reverse(
                "admin:admin_agreements_indicatorevaluationthresholdadminproxy_add"
            ),
            obj.pk,
            reverse("admin:admin_agreements_indicatorpenaltyadminproxy_add"),
            obj.pk,
            reverse(
                "exchange_agreement:indicator-evaluations",
                args=[obj.revision.contract.contract_code, obj.revision_id, obj.pk],
            ),
        )

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        name = "processing_profile_indicator_version"
        if name in formset.form.base_fields:
            formset.form.base_fields[
                name
            ].queryset = ProcessingProfileIndicatorVersion.objects.filter(
                processing_profile_version_id=obj.processing_profile_version_id
                if obj
                else None
            )
        return formset

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


class DependencyValuesForm(forms.ModelForm):
    """Validate the same parameter schema as the web value editor."""

    class Meta:
        model = ContractDependencyConfiguration
        fields = (
            "indicator_version",
            "parameters",
            "aggregation",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and "indicator_version" in self.fields:
            self.fields["indicator_version"].disabled = True

    def clean(self):
        values = super().clean()
        version = values.get("indicator_version")
        if version and "parameters" in values:
            from rpsd_config.exchange_agreement.services.parameter_schema import (
                validate_indicator_parameters,
            )

            validate_indicator_parameters(
                version.parameter_schema, values["parameters"]
            )
        return values


class DependencyValuesFormSet(BaseInlineFormSet):
    """Delegate each write to the existing authorized domain service."""

    def save(self, commit=True):
        from rpsd_config.exchange_agreement.services import (
            contract_revision_permissions,
        )
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        with transaction.atomic():
            revision = (
                type(self.instance).objects.select_for_update().get(pk=self.instance.pk)
            )
            contract_revision_permissions.require_revision_preparer(
                user=self.actor, contract=revision.contract
            )
            if revision.status != "draft":
                raise ValidationError("Approved revision values are immutable.")
            saved = []
            self.new_objects, self.changed_objects, self.deleted_objects = [], [], []
            for form in self.forms:
                if not form.cleaned_data or not form.has_changed():
                    continue
                if form.cleaned_data.get("DELETE"):
                    if form.instance.pk:
                        self.deleted_objects.append(form.instance)
                        form.instance.delete()
                    continue
                config = save_revision_indicator_values(
                    revision,
                    version_code=form.cleaned_data["indicator_version"].code,
                    values={
                        field: form.cleaned_data[field]
                        for field in (
                            "parameters",
                            "aggregation",
                        )
                    },
                    actor=self.actor,
                )
                if form.instance.pk:
                    self.changed_objects.append((config, form.changed_data))
                else:
                    self.new_objects.append(config)
                saved.append(config)
            return saved


class ContractDependencyValuesInline(GuidedInlineMixin, admin.TabularInline):
    model = ContractDependencyConfiguration
    form = DependencyValuesForm
    formset = DependencyValuesFormSet
    verbose_name_plural = "Valori degli indicatori prerequisiti"
    extra = 0

    def _editable(self, request, obj):
        from rpsd_config.exchange_agreement.services import (
            contract_revision_permissions,
        )

        return bool(
            obj
            and obj.status == "draft"
            and contract_revision_permissions.can_prepare_contract_revision(
                user=request.user, contract=obj.contract
            )
        )

    def has_add_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._editable(request, obj)

    def has_view_permission(self, request, obj=None):
        from rpsd_config.exchange_agreement.services import (
            contract_revision_permissions,
        )

        return bool(
            obj
            and contract_revision_permissions.can_prepare_contract_revision(
                user=request.user, contract=obj.contract
            )
        )

    def get_readonly_fields(self, request, obj=None):
        return () if self._editable(request, obj) else self.form.Meta.fields

    def get_formset(self, request, obj=None, **kwargs):
        from rpsd_config.exchange_agreement.services.indicator_dependencies import (
            resolve_indicator_closure,
        )

        formset = super().get_formset(request, obj, **kwargs)

        class ScopedFormSet(formset):
            actor = request.user

        if obj and "indicator_version" in ScopedFormSet.form.base_fields:
            roots = [
                c.processing_profile_indicator_version.indicator_version
                for c in obj.indicator_configurations.select_related(
                    "processing_profile_indicator_version__indicator_version"
                )
            ]
            closure = resolve_indicator_closure(roots)
            ids = {v.pk for v in closure["versions"]} - closure["root_ids"]
            ScopedFormSet.form.base_fields[
                "indicator_version"
            ].queryset = IndicatorVersion.objects.filter(pk__in=ids)
        return ScopedFormSet


class ContractConfigurationRevisionStatusEventInline(
    GuidedInlineMixin, admin.TabularInline
):
    model = ContractConfigurationRevisionStatusEvent
    extra = 0
    can_delete = False
    fields = (
        "from_status",
        "to_status",
        "changed_by",
        "reason",
        "snapshot_checksum",
        "changed_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


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
        "withdrawal_reason",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (
        ContractInputSelectionInline,
        ContractRevisionIndicatorInline,
        ContractDependencyValuesInline,
        ContractConfigurationRevisionStatusEventInline,
    )
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
                f"Revisioni aggiornate: {completed}",
                level=messages.SUCCESS,
            )

    @admin.action(description="Approva le revisioni selezionate")
    def approve_selected(self, request, queryset):
        self._transition_selected(request, queryset, approve_contract_revision)

    @admin.action(description="Ritira le revisioni selezionate")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(
            request,
            queryset,
            lambda revision, *, actor: withdraw_contract_revision(
                revision,
                actor=actor,
                reason="Withdrawn through Django admin action.",
            ),
        )


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


@admin.register(ContractPublicationAdminProxy)
class ContractPublicationAdmin(GuidedAdminMixin, admin.ModelAdmin):
    list_display = (
        "contract",
        "configuration_revision",
        "publication_version",
        "published_at",
        "published_by",
        "snapshot_schema_version",
    )
    list_filter = ("snapshot_schema_version", "published_at")
    search_fields = (
        "contract__contract_code",
        "configuration_revision__code",
        "snapshot_checksum",
        "published_by__username",
        "published_by__email",
    )
    autocomplete_fields = ("contract", "published_by")
    list_select_related = ("contract", "configuration_revision", "published_by")
    readonly_fields = (
        "contract",
        "configuration_revision",
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


from rpsd_config.admin_agreements import evaluation_admin  # noqa: E402, F401
