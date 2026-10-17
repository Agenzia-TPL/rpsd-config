# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Scoped admin adapters; domain fields and permission methods remain untouched."""

from copy import copy, deepcopy

from django import forms
from django.contrib import admin
from django.contrib.admin.utils import flatten_fieldsets, lookup_field
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.forms.models import BaseInlineFormSet
from django.http import HttpRequest
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from rpsd_config.admin_examples import field_examples
from rpsd_config.exchange_agreement.field_guidance import field_guide
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    can_prepare_contract_revision,
)

CHOICE_LABELS = {
    "draft": _("Bozza"),
    "published": _("Pubblicata"),
    "deprecated": _("Deprecata"),
    "withdrawn": _("Ritirata"),
    "approved": _("Approvata"),
    "active": _("Attivo"),
    "archived": _("Archiviato"),
    "stored": _("Conservato"),
    "closed": _("Chiuso"),
    "pending": _("In attesa"),
    "accepted": _("Accettato"),
    "rejected": _("Rifiutato"),
    "expired": _("Scaduto"),
    "failed": _("Fallito"),
    "start": _("Iniziale"),
    "renewal": _("Rinnovo"),
    "region": _("Regione"),
    "municipality": _("Comune"),
    "other": _("Altro"),
    "validation_schema": _("Schema di validazione"),
    "constraint": _("Vincolo"),
    "documentation": _("Documentazione"),
    "example": _("Esempio"),
    "contract_reader": _("Lettore del contratto"),
    "contract_editor": _("Editor del contratto"),
    "contract_admin": _("Amministratore del contratto"),
    "reject_import": _("Blocco dell’import: sempre per questo dataset"),
    "warn": _("Avviso dataset: sempre per questo dataset"),
    "indicator_only": _("Compatibilità: se richiesta dagli indicatori effettivi"),
    "calculation": _("Calcolo delle entità conformi"),
    "dimension": _("Disaggregazione nelle dimensioni indicate"),
    "violating_entities": _("Entità non conformi (vuoto = pass)"),
    "structured_report": _("Report strutturato"),
    "boolean_assertion": _("Asserzione booleana (non supportata dal registro)"),
}

SECTION_LABELS = {
    "Parties": _("Parti e perimetro"),
    "Validity": _("Stato e validità"),
    "Lifecycle": _("Ciclo di vita"),
    "Tender": _("Gara"),
    "Program": _("Programma contrattuale"),
    "Audit": _("Audit e provenienza"),
}


LABEL_RELATIONS = {
    "ValidationRuleVersion": ("rule",),
    "DatasetVersionRule": ("dataset_specification", "rule_version__rule"),
    "IndicatorVersionRule": (
        "indicator_version",
        "dataset_specification",
        "rule_version__rule",
    ),
    "IndicatorVersionInput": ("indicator_version", "dataset_specification"),
    "IndicatorVersionDependency": ("dependent", "prerequisite"),
    "DependencyRequiredDimension": (
        "dependency__dependent",
        "dependency__prerequisite",
        "dimension",
    ),
    "ProcessingProfileInputFlow": (
        "processing_profile_version",
        "dataset",
        "input_flow_version",
    ),
    "ProcessingProfileIndicatorVersion": (
        "processing_profile_version",
        "indicator_version",
    ),
    "ContractDependencyConfiguration": ("revision", "indicator_version"),
}


def relation_label(obj: models.Model) -> str:
    """Describe association endpoints locally instead of changing model __str__."""
    model_name = obj._meta.concrete_model.__name__
    if model_name == "ContractRevisionIndicator":
        version_code = obj.processing_profile_indicator_version.indicator_version.code
        return f"{obj.revision.code}: {version_code}"
    if model_name == "DatasetVersionRule":
        return (
            f"{obj.dataset_specification.code} → {obj.rule_version} "
            f"[{obj.failure_policy}]"
        )
    if model_name == "IndicatorVersionDependency":
        return f"{obj.dependent.code} → {obj.prerequisite.code}"
    if model_name == "ProcessingProfileInputFlow":
        return (
            f"{obj.processing_profile_version.code}: {obj.dataset.code} → "
            f"{obj.input_flow_version.code}"
        )
    if model_name == "ProcessingProfileIndicatorVersion":
        return f"{obj.processing_profile_version.code}: {obj.indicator_version.code}"
    return str(obj)


def guided_form(
    form: type[forms.ModelForm],
    model: type[models.Model],
    *,
    extra_fields: tuple[str, ...] = (),
) -> type[forms.ModelForm]:
    """Populate Meta as well as fields: Django reads Meta for readonly rendering."""
    form._meta = copy(form._meta)
    form._meta.labels = dict(form._meta.labels or {})
    form._meta.help_texts = dict(form._meta.help_texts or {})
    # Declared extra fields may be inherited from a shared web ModelForm.
    form.base_fields = deepcopy(form.base_fields)
    for field in form.base_fields.values():
        if hasattr(field, "queryset"):
            paths = LABEL_RELATIONS.get(
                field.queryset.model._meta.concrete_model.__name__, ()
            )
            if paths:
                field.queryset = field.queryset.select_related(*paths)
                field.label_from_instance = relation_label
    names = {f.name for f in model._meta.fields} | set(form.base_fields)
    names |= {"created_at_human", "updated_at_human", "dimensions"} | set(extra_fields)
    for name in names:
        info = field_guide(model, name)
        if info is None:
            continue
        help_text = format_html("{}{}", info.help, field_examples(model, name))
        form._meta.labels[name] = info.label
        form._meta.help_texts[name] = help_text
        if name in form.base_fields:
            field = form.base_fields[name]
            field.label = info.label
            field.help_text = help_text
            if not hasattr(field, "queryset") and getattr(field, "choices", None):
                field.choices = [
                    (key, CHOICE_LABELS.get(key, label)) for key, label in field.choices
                ]
    return form


class GuidedFieldListFilter(admin.FieldListFilter):
    """Keep Django's filter implementation while supplying a translated title."""

    def __new__(
        cls,
        field: models.Field,
        request: HttpRequest,
        params: dict,
        model: type[models.Model],
        model_admin: admin.ModelAdmin,
        field_path: str,
    ) -> admin.FieldListFilter:
        instance = admin.FieldListFilter.create(
            field, request, params, model, model_admin, field_path
        )
        info = field_guide(field.model, field.name)
        if info:
            instance.title = info.label
        return instance


class GuidanceMixin:
    """Apply shared copy to forms, readonly fields, sections and list columns."""

    class Media:
        css = {"all": ("admin/config-guidance.css",)}

    def get_fieldsets(
        self, request: HttpRequest, obj: models.Model | None = None
    ) -> list[tuple]:
        """Group default editors without exposing excluded or hidden fields."""
        fieldsets = super().get_fieldsets(request, obj)
        if self.fieldsets:
            return [
                (
                    SECTION_LABELS.get(title, title)
                    if title
                    else _("Identità e versione"),
                    options,
                )
                for title, options in fieldsets
            ]
        if isinstance(self, admin.options.InlineModelAdmin):
            return fieldsets
        grouped = {}
        for name in flatten_fieldsets(fieldsets):
            info = field_guide(self.model, name)
            group = info.group if info else _("Configurazione")
            grouped.setdefault(group, []).append(name)
        return [(group, {"fields": names}) for group, names in grouped.items()]


class GuidedAdminMixin(GuidanceMixin):
    """ModelAdmin-only adapter; specialized save/freeze/RBAC stay in the MRO."""

    change_form_template = "admin/config_guidance/change_form.html"

    def get_readonly_fields(
        self, request: HttpRequest, obj: models.Model | None = None
    ) -> tuple[str, ...]:
        """Keep system-produced provenance consultable rather than manually editable."""
        readonly = list(super().get_readonly_fields(request, obj))
        automatic = {
            "published_by",
            "published_at",
            "approved_by",
            "approved_at",
            "withdrawn_by",
            "withdrawn_at",
            "withdrawal_reason",
            "uploaded_by",
            "uploaded_at",
            "activated_by",
            "activated_at",
            "archived_at",
            "accepted_by",
            "accepted_at",
            "rejected_by",
            "rejected_at",
        }
        readonly.extend(
            field.name for field in self.model._meta.fields if field.name in automatic
        )
        if (
            obj is not None
            and self.model._meta.concrete_model.__name__ == "ConfigurationAsset"
        ):
            from rpsd_config.exchange_agreement.models import BUNDLE_IDENTITY_FIELDS

            readonly.extend(sorted(BUNDLE_IDENTITY_FIELDS))
        return tuple(dict.fromkeys(readonly))

    def get_form(
        self, request: HttpRequest, obj: models.Model | None = None, **kwargs
    ) -> type[forms.ModelForm]:
        """Supply labels and help even for fields omitted from the editable form."""
        return guided_form(
            super().get_form(request, obj, **kwargs),
            self.model,
            extra_fields=self.get_readonly_fields(request, obj),
        )

    def get_list_display(self, request: HttpRequest) -> tuple:
        """Translate headers without mutating Django's global model metadata."""
        columns = []
        for column in super().get_list_display(request):
            info = field_guide(self.model, column) if isinstance(column, str) else None
            if info is None:
                columns.append(column)
                continue
            try:
                field = self.model._meta.get_field(column)
            except FieldDoesNotExist:
                field = None

            def display(obj, name=column, model_field=field):
                value = lookup_field(name, obj, self)[2]
                if model_field and model_field.choices:
                    return CHOICE_LABELS.get(
                        value, getattr(obj, f"get_{name}_display")()
                    )
                if value is not None and hasattr(value, "_meta"):
                    return relation_label(value)
                return value

            display.__name__ = f"guided_{column}"
            display.short_description = info.label
            if field:
                display.admin_order_field = column
                display.boolean = field.get_internal_type() == "BooleanField"
            else:
                original = getattr(self, column, None) or getattr(
                    self.model, column, None
                )
                for attr in ("boolean", "admin_order_field", "empty_value_display"):
                    if hasattr(original, attr):
                        setattr(display, attr, getattr(original, attr))
            columns.append(display)
        return tuple(columns)

    def get_list_filter(self, request: HttpRequest) -> tuple:
        """Preserve filters, including relation paths, with localized headings."""
        return tuple(
            (field, GuidedFieldListFilter) if isinstance(field, str) else field
            for field in super().get_list_filter(request)
        )

    def get_queryset(self, request: HttpRequest) -> models.QuerySet:
        """Preload foreign-key labels; nested paths belong to specialized admins."""
        queryset = super().get_queryset(request)
        relations = [
            f.name for f in self.model._meta.fields if f.many_to_one or f.one_to_one
        ]
        configured = self.get_list_select_related(request)
        if isinstance(configured, (list, tuple)):
            relations.extend(configured)
        return queryset.select_related(*relations) if relations else queryset

    def render_change_form(
        self,
        request: HttpRequest,
        context: dict,
        add: bool = False,
        change: bool = False,
        form_url: str = "",
        obj: models.Model | None = None,
    ) -> TemplateResponse:
        """Link to the existing revision workflow only inside its authorized scope."""
        model_name = self.model._meta.concrete_model.__name__
        if obj:
            from rpsd_config.admin_audit import proxies as audit

            event_name = (
                "ConfigurationAssetEvent"
                if model_name == "ConfigurationAsset"
                else model_name + "StatusEvent"
            )
            proxy = getattr(audit, event_name + "AdminProxy", None)
            event_admin = self.admin_site._registry.get(proxy)
            if event_admin and event_admin.has_view_permission(request):
                from django.utils.text import camel_case_to_spaces

                owner = (
                    "asset"
                    if model_name == "ConfigurationAsset"
                    else camel_case_to_spaces(model_name).replace(" ", "_")
                )
                if model_name == "ValidationRuleVersion":
                    owner = "rule_version"
                context["config_history_url"] = (
                    reverse(f"admin:admin_audit_{proxy._meta.model_name}_changelist")
                    + f"?{owner}__id__exact={obj.pk}"
                )
        revision = None
        if obj is not None:
            if model_name == "ContractConfigurationRevision":
                revision = obj
            elif model_name == "ContractDependencyConfiguration":
                revision = obj.revision
        if revision and can_prepare_contract_revision(
            user=request.user, contract=revision.contract
        ):
            context["config_revision_workflow"] = reverse(
                "exchange_agreement:contract-revision-detail",
                args=[revision.contract.contract_code, revision.pk],
            )
        if (
            model_name
            in {
                "ValidationRuleVersion",
                "DatasetSpecification",
                "IndicatorVersion",
                "InputFlowVersion",
                "OrchestrationFlowVersion",
                "ProcessingProfileVersion",
                "ContractConfigurationRevision",
                "Contract",
            }
            and obj is not None
            and getattr(obj, "status", "draft")
            in {
                "published",
                "deprecated",
                "withdrawn",
                "approved",
                "closed",
            }
        ):
            context["config_freeze_guidance"] = _(
                "Configurazione congelata: consultare i valori e gli aiuti. Per "
                "variare una configurazione tecnica creare una nuova versione; per i "
                "valori contrattuali creare una nuova revisione in bozza. Le "
                "transizioni consentite restano disponibili nel workflow autorizzato."
            )
        return super().render_change_form(request, context, add, change, form_url, obj)


class GuidedInlineMixin(GuidanceMixin):
    """Keep inline permissions and formsets intact, including fully readonly rows."""

    template = "admin/config_guidance/tabular.html"

    def get_formset(
        self, request: HttpRequest, obj: models.Model | None = None, **kwargs
    ) -> type[BaseInlineFormSet]:
        """Supply Meta labels/help for readonly inline headers as well as inputs."""
        formset = super().get_formset(request, obj, **kwargs)
        formset.form = guided_form(
            formset.form,
            self.model,
            extra_fields=self.get_readonly_fields(request, obj),
        )
        return formset
