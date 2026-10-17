# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.expressions import DatabaseDefault
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.admin_dataset_exchange.validation_admin import (
    IndicatorDependencyInline,
    IndicatorInputInline,
    register_validation_admin,
)
from rpsd_config.admin_guidance import GuidedAdminMixin, GuidedInlineMixin
from rpsd_config.exchange_agreement.asset_forms import ConfigurationAssetUploadForm
from rpsd_config.exchange_agreement.models import (
    BUNDLE_IDENTITY_FIELDS,
    DatasetSpecificationAsset,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope
from rpsd_config.exchange_agreement.services.configuration_assets import (
    activate_configuration_asset,
    archive_configuration_asset,
    store_configuration_asset,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    DatasetSpecificationTransitionError,
    deprecate_dataset_specification,
    publish_dataset_specification,
    withdraw_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    FlowCatalogTransitionError,
    deprecate_input_flow_version,
    deprecate_orchestration_flow_version,
    publish_input_flow_version,
    publish_orchestration_flow_version,
    withdraw_input_flow_version,
    withdraw_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    IndicatorVersionTransitionError,
    deprecate_indicator_version,
    publish_indicator_version,
    withdraw_indicator_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    ProcessingProfileTransitionError,
    deprecate_processing_profile,
    publish_processing_profile,
    withdraw_processing_profile,
)

from .proxies import (
    ConfigurationAssetAdminProxy,
    DatasetAdminProxy,
    DatasetSpecificationAdminProxy,
    IndicatorAdminProxy,
    IndicatorVersionAdminProxy,
    InputFlowVersionAdminProxy,
    OrchestrationFlowVersionAdminProxy,
    ProcessingProfileVersionAdminProxy,
)


class _HumanReadableTimestampsMixin(GuidedAdminMixin):
    @staticmethod
    def _format_timestamp(value):
        if value is None or isinstance(value, DatabaseDefault):
            return "-"
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return date_format(timezone.localtime(value), "DATETIME_FORMAT")
        return str(value)

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


class _PlatformCatalogAdminMixin(GuidedAdminMixin):
    @staticmethod
    def _can_manage(request):
        user = request.user
        return bool(
            user.is_superuser or resolve_user_agency_scope(user).is_platform_admin
        )

    def has_module_permission(self, request):
        return self._can_manage(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_add_permission(self, request):
        return self._can_manage(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage(request)

    def has_delete_permission(self, request, obj=None):
        return self._can_manage(request)


@admin.register(DatasetAdminProxy)
class DatasetAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = ("code", "name", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("code", "name")
    ordering = ("code",)
    readonly_fields = ("created_at_human", "updated_at_human")


class DatasetSpecificationAssetInline(GuidedInlineMixin, admin.TabularInline):
    model = DatasetSpecificationAsset
    extra = 0
    autocomplete_fields = ("configuration_asset",)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


@admin.register(DatasetSpecificationAdminProxy)
class DatasetSpecificationAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = (
        "code",
        "dataset",
        "version",
        "format",
        "status",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "dataset", "format")
    search_fields = ("code", "version", "description", "dataset__code")
    autocomplete_fields = ("dataset", "published_by")
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (DatasetSpecificationAssetInline,)
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                ["dataset", "code", "version", "format", "description", "metadata"]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for specification in queryset:
            try:
                transition(specification, actor=request.user)
                completed += 1
            except (DatasetSpecificationTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(request, f"Specifiche aggiornate: {completed}")

    @admin.action(description="Pubblica le specifiche selezionate")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_dataset_specification)

    @admin.action(description="Depreca le specifiche selezionate")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_dataset_specification)

    @admin.action(description="Ritira le specifiche selezionate")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_dataset_specification)


class DatasetSpecificationStatusEventAdmin(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "dataset_specification",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("to_status", "changed_at")
    search_fields = ("dataset_specification__code", "changed_by__username")
    readonly_fields = (
        "dataset_specification",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IndicatorAdminProxy)
class IndicatorAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = ("code", "name", "status", "created_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(IndicatorVersionAdminProxy)
class IndicatorVersionAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = (
        "code",
        "indicator",
        "version",
        "execution_engine",
        "status",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "execution_engine", "indicator")
    search_fields = ("code", "version", "description", "indicator__code")
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (IndicatorInputInline, IndicatorDependencyInline)
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        labels = {
            "input_schema": "Schema input",
            "output_schema": "Schema output",
            "execution_reference": "Processo di calcolo Prefect",
        }
        for name, label in labels.items():
            if name in form.base_fields:
                form.base_fields[name].label = label
        return form

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                [
                    "indicator",
                    "code",
                    "version",
                    "description",
                    "formula_description",
                    "input_schema",
                    "output_schema",
                    "parameter_schema",
                    "execution_engine",
                    "execution_reference",
                    "artifact_identifier",
                ]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for version in queryset:
            try:
                transition(version, actor=request.user)
                completed += 1
            except (IndicatorVersionTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(
                request, f"Versioni di indicatore aggiornate: {completed}"
            )

    @admin.action(description="Pubblica le versioni di indicatore selezionate")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_indicator_version)

    @admin.action(description="Depreca le versioni di indicatore selezionate")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_indicator_version)

    @admin.action(description="Ritira le versioni di indicatore selezionate")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_indicator_version)


class IndicatorVersionStatusEventAdmin(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "indicator_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("to_status", "changed_at")
    search_fields = ("indicator_version__code", "changed_by__username")
    readonly_fields = (
        "indicator_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class _FlowVersionAdminBase(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_filter = ("status", "engine")
    search_fields = ("code", "version", "name", "deployment_name")
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")
    publish_transition = None
    deprecate_transition = None
    withdraw_transition = None

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                [
                    "code",
                    "version",
                    "name",
                    "description",
                    "engine",
                    "deployment_name",
                    "artifact_identifier",
                ]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for flow in queryset:
            try:
                transition(flow, actor=request.user)
                completed += 1
            except (FlowCatalogTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(request, f"Flussi aggiornati: {completed}")

    @admin.action(description="Pubblica i flussi selezionati")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, self.publish_transition)

    @admin.action(description="Depreca i flussi selezionati")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, self.deprecate_transition)

    @admin.action(description="Ritira i flussi selezionati")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, self.withdraw_transition)


@admin.register(InputFlowVersionAdminProxy)
class InputFlowVersionAdmin(_FlowVersionAdminBase):
    list_display = (
        "code",
        "dataset_specification",
        "version",
        "deployment_name",
        "status",
        "updated_at",
    )
    list_filter = _FlowVersionAdminBase.list_filter + ("dataset_specification",)
    publish_transition = staticmethod(publish_input_flow_version)
    deprecate_transition = staticmethod(deprecate_input_flow_version)
    withdraw_transition = staticmethod(withdraw_input_flow_version)

    readonly_fields = _FlowVersionAdminBase.readonly_fields + ("profile_users",)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("using_profile_versions")

    @admin.display(description="Utilizzato dai profili tecnici")
    def profile_users(self, obj):
        return (
            "; ".join(
                f"{p.code} · {p.name} · {p.version} · {p.get_status_display()}"
                for p in obj.using_profile_versions.all()
            )
            or "Nessun profilo tecnico collegato."
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        if obj:
            target_admin = self.admin_site._registry[ProcessingProfileVersionAdminProxy]
            context["config_profile_links"] = [
                {
                    "label": (
                        f"{p.code} · {p.name} · {p.version} · {p.get_status_display()}"
                    ),
                    "url": reverse(
                        "admin:admin_dataset_exchange_processingprofileversionadminproxy_change",
                        args=[p.pk],
                    ),
                }
                for p in obj.using_profile_versions.all()
                if target_admin.has_view_permission(request, p)
            ]
        return super().render_change_form(request, context, add, change, form_url, obj)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.append("dataset_specification")
        return fields


@admin.register(OrchestrationFlowVersionAdminProxy)
class OrchestrationFlowVersionAdmin(_FlowVersionAdminBase):
    list_display = (
        "code",
        "version",
        "deployment_name",
        "status",
        "updated_at",
    )
    publish_transition = staticmethod(publish_orchestration_flow_version)
    deprecate_transition = staticmethod(deprecate_orchestration_flow_version)
    withdraw_transition = staticmethod(withdraw_orchestration_flow_version)


class _FlowVersionStatusEventAdminBase(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_filter = ("to_status", "changed_at")
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class InputFlowVersionStatusEventAdmin(_FlowVersionStatusEventAdminBase):
    list_display = (
        "input_flow_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    search_fields = ("input_flow_version__code", "changed_by__username")
    readonly_fields = _FlowVersionStatusEventAdminBase.readonly_fields + (
        "input_flow_version",
    )


class OrchestrationFlowVersionStatusEventAdmin(_FlowVersionStatusEventAdminBase):
    list_display = (
        "orchestration_flow_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    search_fields = ("orchestration_flow_version__code", "changed_by__username")
    readonly_fields = _FlowVersionStatusEventAdminBase.readonly_fields + (
        "orchestration_flow_version",
    )


class ProcessingProfileInputFlowInline(GuidedInlineMixin, admin.TabularInline):
    model = ProcessingProfileInputFlow
    extra = 0
    autocomplete_fields = ("dataset",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("dataset", "input_flow_version__dataset_specification")
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "input_flow_version":
            kwargs["queryset"] = InputFlowVersion.objects.filter(
                status=InputFlowVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


class ProcessingProfileIndicatorVersionInline(GuidedInlineMixin, admin.TabularInline):
    model = ProcessingProfileIndicatorVersion
    extra = 0

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "indicator_version":
            kwargs["queryset"] = IndicatorVersion.objects.filter(
                status=IndicatorVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


@admin.register(ProcessingProfileVersionAdminProxy)
class ProcessingProfileVersionAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    list_display = (
        "code",
        "name",
        "version",
        "orchestration_flow_version",
        "status",
        "published_at",
    )
    list_filter = ("status", "orchestration_flow_version")
    search_fields = ("code", "name", "version", "description")
    autocomplete_fields = ("published_by",)
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    inlines = (
        ProcessingProfileInputFlowInline,
        ProcessingProfileIndicatorVersionInline,
    )
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "orchestration_flow_version":
            kwargs["queryset"] = OrchestrationFlowVersion.objects.filter(
                status=OrchestrationFlowVersion.Status.PUBLISHED
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                ["code", "version", "name", "description", "orchestration_flow_version"]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for profile in queryset:
            try:
                transition(profile, actor=request.user)
                completed += 1
            except (ProcessingProfileTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(request, f"Profili tecnici aggiornati: {completed}")

    @admin.action(description="Pubblica i profili tecnici selezionati")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_processing_profile)

    @admin.action(description="Depreca i profili tecnici selezionati")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_processing_profile)

    @admin.action(description="Ritira i profili tecnici selezionati")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_processing_profile)


class ProcessingProfileVersionStatusEventAdmin(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "processing_profile_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("to_status", "changed_at")
    search_fields = ("processing_profile_version__code", "changed_by__username")
    readonly_fields = (
        "processing_profile_version",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ConfigurationAssetAdminProxy)
class ConfigurationAssetAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "asset_type",
        "what",
        "version",
        "label",
        "is_active",
        "status",
        "publish_status",
        "updated_at",
    )
    list_filter = ("asset_type", "what", "status", "is_active", "publish_status")
    search_fields = ("label", "original_filename", "storage_url", "checksum_sha256")
    actions = ("activate_assets", "archive_assets")
    readonly_fields = (
        "created_at_human",
        "updated_at_human",
        "uploaded_by",
        "uploaded_at",
        "activated_by",
        "activated_at",
        "archived_at",
        "publish_status",
        "last_publish_error",
        "status",
        "is_active",
        "new_version",
        "dataset_links",
    ) + tuple(sorted(BUNDLE_IDENTITY_FIELDS))

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Nuova versione")
    def new_version(self, obj):
        return format_html(
            '<a href="{}?asset_type={}&amp;what={}">Carica una nuova versione</a>',
            reverse("admin:admin_dataset_exchange_configurationassetadminproxy_add"),
            obj.asset_type,
            obj.what,
        )

    @admin.display(description="Versioni dataset associate")
    def dataset_links(self, obj):
        return (
            "; ".join(
                f"{link.dataset_specification.code} ({link.get_role_display()})"
                for link in obj.dataset_specification_links.select_related(
                    "dataset_specification"
                )
            )
            or "Nessuna associazione"
        )

    def add_view(self, request, form_url="", extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied
        form = ConfigurationAssetUploadForm(
            request.POST if request.method == "POST" else None,
            request.FILES if request.method == "POST" else None,
            initial={
                "asset_type": request.GET.get("asset_type", "other"),
                "what": request.GET.get("what", ""),
            },
        )
        if request.method == "POST" and form.is_valid():
            try:
                data = form.cleaned_data.copy()
                stored = store_configuration_asset(**data, uploaded_by=request.user)
            except ValidationError as exc:
                form.add_error(None, ValidationError(exc.messages))
            else:
                self.log_addition(request, stored.asset, "Uploaded configuration asset")
                self.message_user(request, "Asset caricato.", messages.SUCCESS)
                return HttpResponseRedirect(
                    reverse(
                        "admin:admin_dataset_exchange_configurationassetadminproxy_change",
                        args=[stored.asset.pk],
                    )
                )
        return TemplateResponse(
            request,
            "admin/config_guidance/asset_upload.html",
            {
                **self.admin_site.each_context(request),
                "opts": self.model._meta,
                "title": "Carica asset tecnico dataset",
                "asset_limits": {
                    key: getattr(settings, key)
                    for key in (
                        "CONFIG_ASSETS_MAX_UPLOAD_BYTES",
                        "CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES",
                        "CONFIG_ASSETS_XSD_MAX_FILE_BYTES",
                        "CONFIG_ASSETS_XSD_MAX_FILES",
                    )
                },
                "form": form,
                **(extra_context or {}),
            },
        )

    @admin.action(description="Attiva la versione selezionata", permissions=["change"])
    def activate_assets(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(
                request, "Seleziona una sola versione da attivare.", messages.ERROR
            )
            return
        activate_configuration_asset(asset=queryset.get(), actor=request.user)

    @admin.action(description="Archivia gli asset selezionati", permissions=["change"])
    def archive_assets(self, request, queryset):
        for asset in queryset:
            archive_configuration_asset(asset=asset)


class ConfigurationAssetEventAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("event_type", "asset", "status", "attempts", "created_at")
    list_filter = ("event_type", "status")
    search_fields = ("routing_key", "last_error")
    readonly_fields = ("created_at_human", "updated_at_human", "payload")


# Additive target catalog; legacy admin remains available during migration.

register_validation_admin(_PlatformCatalogAdminMixin)
