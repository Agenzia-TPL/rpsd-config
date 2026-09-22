# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import datetime

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.models.expressions import DatabaseDefault
from django.utils import timezone
from django.utils.formats import date_format

from rpsd_config import admin_hidden  # noqa: F401
from rpsd_config.exchange_agreement.models import (
    DatasetSpecificationAsset,
    FragmentValidationRule,
    IndicatorVersion,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
)
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope
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
from rpsd_config.exchange_agreement.services.requirement_fragments import (
    RequirementFragmentTransitionError,
    deprecate_requirement_fragment,
    publish_requirement_fragment,
    withdraw_requirement_fragment,
)

from .forms import (
    FragmentValidationRuleAdminForm,
    RequirementFragmentAdminForm,
)
from .proxies import (
    ConfigurationAssetAdminProxy,
    ConfigurationAssetEventAdminProxy,
    DatasetAdminProxy,
    DatasetSpecificationAdminProxy,
    DatasetSpecificationStatusEventAdminProxy,
    IndicatorAdminProxy,
    IndicatorDefAdminProxy,
    IndicatorProfileAdminProxy,
    IndicatorVersionAdminProxy,
    IndicatorVersionStatusEventAdminProxy,
    InputFlowVersionAdminProxy,
    InputFlowVersionStatusEventAdminProxy,
    NetexValidationProfileAdminProxy,
    OrchestrationFlowVersionAdminProxy,
    OrchestrationFlowVersionStatusEventAdminProxy,
    ProcessingProfileVersionAdminProxy,
    ProcessingProfileVersionStatusEventAdminProxy,
    RequirementFragmentAdminProxy,
    RequirementFragmentStatusEventAdminProxy,
    SiriValidationProfileAdminProxy,
    StructureAdminProxy,
)


class _HumanReadableTimestampsMixin:
    @staticmethod
    def _format_timestamp(value):
        if value is None or isinstance(value, DatabaseDefault):
            return "-"
        if isinstance(value, datetime):
            if timezone.is_naive(value):
                value = timezone.make_aware(value, timezone.get_current_timezone())
            return date_format(timezone.localtime(value), "DATETIME_FORMAT")
        return str(value)

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


class _PlatformCatalogAdminMixin:
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


class DatasetSpecificationAssetInline(admin.TabularInline):
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
        "status",
        "published_at",
        "updated_at",
    )
    list_filter = ("status", "dataset")
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
            fields.extend(["dataset", "code", "version", "description", "metadata"])
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
            self.message_user(request, f"Updated specifications: {completed}")

    @admin.action(description="Publish selected specifications")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_dataset_specification)

    @admin.action(description="Deprecate selected specifications")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_dataset_specification)

    @admin.action(description="Withdraw selected specifications")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_dataset_specification)


@admin.register(DatasetSpecificationStatusEventAdminProxy)
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


class FragmentValidationRuleInline(admin.StackedInline):
    model = FragmentValidationRule
    form = FragmentValidationRuleAdminForm
    extra = 0

    def has_add_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_change_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)

    def has_delete_permission(self, request, obj=None):
        return bool(obj is None or obj.status == obj.Status.DRAFT)


@admin.register(RequirementFragmentAdminProxy)
class RequirementFragmentAdmin(
    _PlatformCatalogAdminMixin,
    _HumanReadableTimestampsMixin,
    admin.ModelAdmin,
):
    form = RequirementFragmentAdminForm
    list_display = (
        "code",
        "dataset_specification",
        "locator_type",
        "result_kind",
        "status",
        "updated_at",
    )
    list_filter = ("status", "locator_type", "result_kind")
    search_fields = (
        "code",
        "name",
        "description",
        "dataset_specification__code",
    )
    readonly_fields = ("status", "created_at_human", "updated_at_human")
    inlines = (FragmentValidationRuleInline,)
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(
                [
                    "dataset_specification",
                    "code",
                    "name",
                    "description",
                    "locator_type",
                    "result_kind",
                    "locator_definition",
                ]
            )
        return fields

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != obj.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)

    def _transition_selected(self, request, queryset, transition):
        completed = 0
        for fragment in queryset:
            try:
                transition(fragment, actor=request.user)
                completed += 1
            except (RequirementFragmentTransitionError, ValidationError) as exc:
                self.message_user(request, str(exc), level="ERROR")
        if completed:
            self.message_user(request, f"Updated fragments: {completed}")

    @admin.action(description="Publish selected requirement fragments")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_requirement_fragment)

    @admin.action(description="Deprecate selected requirement fragments")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_requirement_fragment)

    @admin.action(description="Withdraw selected requirement fragments")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_requirement_fragment)


@admin.register(RequirementFragmentStatusEventAdminProxy)
class RequirementFragmentStatusEventAdmin(
    _PlatformCatalogAdminMixin,
    admin.ModelAdmin,
):
    list_display = (
        "requirement_fragment",
        "from_status",
        "to_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("to_status", "changed_at")
    search_fields = ("requirement_fragment__code", "changed_by__username")
    readonly_fields = (
        "requirement_fragment",
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
    filter_horizontal = ("required_fragments",)
    readonly_fields = (
        "status",
        "published_by",
        "published_at",
        "created_at_human",
        "updated_at_human",
    )
    actions = ("publish_selected", "deprecate_selected", "withdraw_selected")

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
                    "input_contract",
                    "output_contract",
                    "execution_engine",
                    "execution_reference",
                    "artifact_identifier",
                    "required_fragments",
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
            self.message_user(request, f"Updated indicator versions: {completed}")

    @admin.action(description="Publish selected indicator versions")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_indicator_version)

    @admin.action(description="Deprecate selected indicator versions")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_indicator_version)

    @admin.action(description="Withdraw selected indicator versions")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_indicator_version)


@admin.register(IndicatorVersionStatusEventAdminProxy)
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
                    "invocation_contract",
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
            self.message_user(request, f"Updated flow versions: {completed}")

    @admin.action(description="Publish selected flow versions")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, self.publish_transition)

    @admin.action(description="Deprecate selected flow versions")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, self.deprecate_transition)

    @admin.action(description="Withdraw selected flow versions")
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

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None and obj.status != obj.Status.DRAFT:
            fields.extend(["dataset_specification", "compatibility"])
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


@admin.register(InputFlowVersionStatusEventAdminProxy)
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


@admin.register(OrchestrationFlowVersionStatusEventAdminProxy)
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


class ProcessingProfileInputFlowInline(admin.TabularInline):
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


class ProcessingProfileIndicatorVersionInline(admin.TabularInline):
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
            self.message_user(request, f"Updated processing profiles: {completed}")

    @admin.action(description="Publish selected processing profiles")
    def publish_selected(self, request, queryset):
        self._transition_selected(request, queryset, publish_processing_profile)

    @admin.action(description="Deprecate selected processing profiles")
    def deprecate_selected(self, request, queryset):
        self._transition_selected(request, queryset, deprecate_processing_profile)

    @admin.action(description="Withdraw selected processing profiles")
    def withdraw_selected(self, request, queryset):
        self._transition_selected(request, queryset, withdraw_processing_profile)


@admin.register(ProcessingProfileVersionStatusEventAdminProxy)
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


@admin.register(StructureAdminProxy)
class StructureAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("dataset", "name", "created_at", "updated_at")
    list_filter = ("dataset",)
    search_fields = ("name", "dataset__code", "dataset__name")
    autocomplete_fields = ("dataset",)
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(IndicatorDefAdminProxy)
class IndicatorDefAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "type",
        "sql_procedure_name",
        "structures_list",
        "created_at",
        "updated_at",
    )
    list_filter = ("type", "structures__dataset")
    search_fields = (
        "code",
        "name",
        "description",
        "sql_procedure_name",
        "sql_snippet",
        "structures__name",
        "structures__dataset__code",
    )
    autocomplete_fields = ("structures",)
    readonly_fields = ("created_at_human", "updated_at_human")

    @admin.display(description="Structures")
    def structures_list(self, obj):
        return ", ".join(str(structure) for structure in obj.structures.all())


@admin.register(NetexValidationProfileAdminProxy)
class NetexValidationProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("label", "file", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(SiriValidationProfileAdminProxy)
class SiriValidationProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = (
        "profile_type",
        "label",
        "file",
        "is_active",
        "created_at",
        "updated_at",
    )
    list_filter = ("profile_type", "is_active")
    search_fields = ("profile_type", "label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(IndicatorProfileAdminProxy)
class IndicatorProfileAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("label", "file", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("label", "file")
    readonly_fields = ("created_at_human", "updated_at_human")


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
    readonly_fields = ("created_at_human", "updated_at_human")


@admin.register(ConfigurationAssetEventAdminProxy)
class ConfigurationAssetEventAdmin(_HumanReadableTimestampsMixin, admin.ModelAdmin):
    list_display = ("event_type", "asset", "status", "attempts", "created_at")
    list_filter = ("event_type", "status")
    search_fields = ("routing_key", "last_error")
    readonly_fields = ("created_at_human", "updated_at_human", "payload")
