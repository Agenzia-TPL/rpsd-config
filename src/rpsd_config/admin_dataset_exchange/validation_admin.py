# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Recovery admin for the versioned validation configuration."""

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.admin_dataset_exchange import proxies
from rpsd_config.exchange_agreement.services.validation_bindings import (
    save_dataset_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    delete_validation_rule_version,
    save_validation_rule,
    save_validation_rule_version,
    transition_validation_rule,
)
from rpsd_config.exchange_agreement.validation_forms import (
    DatasetRuleForm,
    IndicatorRuleForm,
)
from rpsd_config.exchange_agreement.validation_models import FrozenComposition


class RuleIdentityAdmin(admin.ModelAdmin):
    """Allow metadata changes while keeping the external rule code stable."""

    list_display = ("code", "name")
    search_fields = ("code", "name")

    def get_readonly_fields(self, request, obj=None):
        return ("code", "created_at", "updated_at") if obj else ()

    def save_model(self, request, obj, form, change):
        save_validation_rule(obj, actor=request.user)


class CompositionAdminForm(forms.ModelForm):
    """Report frozen composition edits during form validation, before saving."""

    def _post_clean(self):
        super()._post_clean()
        if not self.errors:
            try:
                with transaction.atomic():
                    self.instance.check_editable()
            except ValidationError as exc:
                self.add_error(None, exc)


class FrozenCompositionAdmin(admin.ModelAdmin):
    """Expose published composition as read-only, including forged admin POSTs."""

    form = CompositionAdminForm

    def _editable(self, obj):
        if obj is None:
            return True
        try:
            with transaction.atomic():
                obj.check_editable()
        except ValidationError:
            return False
        return True

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self._editable(obj)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self._editable(obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class DatasetRuleAdminForm(DatasetRuleForm, CompositionAdminForm):
    """Policy explanation with admin composition freeze validation."""


class DatasetRuleAdmin(FrozenCompositionAdmin):
    """Record the authenticated creator of append-only dataset applicability."""

    form = DatasetRuleAdminForm
    readonly_fields = ("created_by", "created_at")
    list_display = (
        "dataset_specification",
        "rule_version",
        "import_policy",
        "created_by",
    )
    list_filter = ("import_policy", "dataset_specification")
    search_fields = (
        "dataset_specification__code",
        "dataset_specification__version",
        "rule_version__rule__code",
        "rule_version__version",
    )
    list_select_related = (
        "dataset_specification__dataset",
        "rule_version__rule",
        "created_by",
    )

    def save_model(self, request, obj, form, change):
        save_dataset_rule(obj, actor=request.user)


class IndicatorRuleAdminForm(IndicatorRuleForm):
    """Use the same replacement semantics as the web catalog."""


class RuleVersionAdmin(admin.ModelAdmin):
    fieldsets = (
        ("Identità e versione", {"fields": ("rule", "version", "name", "description")}),
        (
            "Tipo di validazione",
            {"fields": ("validation_type", "language_version", "result_contract")},
        ),
        ("Definizione completa", {"fields": ("definition", "options")}),
        ("Processo di validazione Prefect", {"fields": ("execution_reference",)}),
        (
            "Stato e audit",
            {
                "fields": (
                    "status",
                    "published_by",
                    "published_at",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    list_display = (
        "rule",
        "version",
        "validation_type",
        "status",
        "execution_reference",
    )
    list_filter = ("status", "validation_type")
    search_fields = ("rule__code", "name", "definition")
    actions = ("publish_rules", "deprecate_rules", "withdraw_rules")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "execution_reference" in form.base_fields:
            form.base_fields[
                "execution_reference"
            ].label = "Processo di validazione Prefect"
        return form

    def get_readonly_fields(self, request, obj=None):
        base = ("status", "published_by", "published_at", "created_at", "updated_at")
        if obj is not None and obj.status != "draft":
            return tuple(field.name for field in obj._meta.fields)
        return base

    def save_model(self, request, obj, form, change):
        save_validation_rule_version(obj, actor=request.user)

    def delete_model(self, request, obj):
        delete_validation_rule_version(obj, actor=request.user)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or obj.status == "draft"
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Django's generic collector cannot turn a frozen selection into a
        # form error. Draft deletion remains available on the object page.
        actions.pop("delete_selected", None)
        return actions

    def transition(self, request, queryset, status):
        for obj in queryset:
            try:
                transition_validation_rule(
                    obj,
                    target_status=status,
                    actor=request.user,
                    reason="Administrator lifecycle action",
                )
            except ValidationError as exc:
                self.message_user(request, "; ".join(exc.messages), messages.ERROR)

    @admin.action(description="Pubblica le regole selezionate")
    def publish_rules(self, request, queryset):
        self.transition(request, queryset, "published")

    @admin.action(description="Depreca le regole selezionate")
    def deprecate_rules(self, request, queryset):
        self.transition(request, queryset, "deprecated")

    @admin.action(description="Ritira le regole selezionate")
    def withdraw_rules(self, request, queryset):
        self.transition(request, queryset, "withdrawn")


class IndicatorRuleAdmin(FrozenCompositionAdmin):
    form = IndicatorRuleAdminForm
    list_display = ("indicator_version", "dataset_version_rule", "impact")
    list_filter = ("impact", "dataset_version_rule__import_policy")
    search_fields = (
        "indicator_version__code",
        "indicator_version__version",
        "dataset_version_rule__dataset_specification__code",
        "dataset_version_rule__rule_version__rule__code",
        "dataset_version_rule__rule_version__version",
    )
    list_select_related = (
        "indicator_version__indicator",
        "dataset_version_rule__dataset_specification__dataset",
        "dataset_version_rule__rule_version__rule",
    )

    @admin.display(description="Dimensioni interessate")
    def dimensions(self, obj):
        """Expose frozen dimension selections without enabling a write widget."""
        return (
            ", ".join(str(dimension) for dimension in obj.affected_dimensions.all())
            or "—"
        )

    def save_model(self, request, obj, form, change):
        obj.check_editable()
        if obj.pk:
            obj.dimension_links.all().delete()
        obj.save()

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.save_dimensions()


class ReadOnlyContractValuesAdmin(admin.ModelAdmin):
    """Contract values are edited through the scoped revision workflow."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReadOnlyRuleAuditAdmin(admin.ModelAdmin):
    list_display = (
        "rule_version",
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


def register_validation_admin(permission_mixin) -> None:
    """Register proxies using the existing platform-admin boundary."""
    specialized = {
        "ValidationRule": RuleIdentityAdmin,
        "ValidationRuleVersion": RuleVersionAdmin,
        "ValidationRuleStatusEvent": ReadOnlyRuleAuditAdmin,
        "IndicatorVersionRule": IndicatorRuleAdmin,
        "DatasetVersionRule": DatasetRuleAdmin,
        "ContractDependencyConfiguration": ReadOnlyContractValuesAdmin,
    }
    presentation = {
        "IndicatorDimension": {
            "list_display": ("code", "name", "description"),
            "search_fields": ("code", "name"),
        },
        "IndicatorVersionInput": {
            "list_display": ("indicator_version", "dataset_specification"),
            "search_fields": (
                "indicator_version__code",
                "indicator_version__version",
                "dataset_specification__code",
                "dataset_specification__version",
            ),
            "list_select_related": (
                "indicator_version__indicator",
                "dataset_specification__dataset",
            ),
        },
        "IndicatorVersionDependency": {
            "list_display": ("dependent", "prerequisite"),
            "search_fields": (
                "dependent__code",
                "dependent__version",
                "prerequisite__code",
                "prerequisite__version",
            ),
            "list_select_related": ("dependent__indicator", "prerequisite__indicator"),
        },
        "DependencyRequiredDimension": {
            "list_display": ("dependency", "dimension"),
            "search_fields": (
                "dependency__dependent__code",
                "dependency__prerequisite__code",
                "dimension__code",
                "dimension__name",
            ),
            "list_select_related": (
                "dependency__dependent__indicator",
                "dependency__prerequisite__indicator",
                "dimension",
            ),
        },
        "ContractDependencyConfiguration": {
            "list_display": ("revision", "indicator_version"),
            "search_fields": (
                "revision__code",
                "revision__contract__contract_code",
                "indicator_version__code",
                "indicator_version__version",
            ),
            "list_select_related": (
                "revision__contract",
                "indicator_version__indicator",
            ),
        },
        "ValidationRuleStatusEvent": {
            "list_select_related": ("rule_version__rule", "changed_by"),
            "search_fields": (
                "rule_version__rule__code",
                "rule_version__version",
                "reason",
            ),
        },
    }
    for name in (
        "ValidationRule",
        "ValidationRuleVersion",
        "ValidationRuleStatusEvent",
        "DatasetVersionRule",
        "IndicatorDimension",
        "IndicatorVersionRule",
        "IndicatorVersionInput",
        "IndicatorVersionDependency",
        "DependencyRequiredDimension",
        "ContractDependencyConfiguration",
    ):
        proxy = getattr(proxies, f"{name}AdminProxy")
        default = (
            FrozenCompositionAdmin
            if issubclass(proxy, FrozenComposition)
            else admin.ModelAdmin
        )
        base = specialized.get(name, default)
        # Specialized restrictions must precede platform permissions in the MRO.
        # An intermediate class keeps ModelAdmin's default permissions behind
        # the platform mixin, including for non-superuser platform admins.
        scoped_base = type(
            f"{name}ScopedAdmin", (permission_mixin, admin.ModelAdmin), {}
        )
        bases = (scoped_base,) if base is admin.ModelAdmin else (base, scoped_base)
        admin_class = type(f"{name}CatalogAdmin", bases, presentation.get(name, {}))
        admin.site.register(getattr(proxies, f"{name}AdminProxy"), admin_class)
