# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Native admin relation controls sharing the visible catalog's permissions."""

from urllib.parse import urlencode

from django import forms
from django.contrib.admin.widgets import AutocompleteSelect, RelatedFieldWidgetWrapper
from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from django.utils.html import format_html

CATALOG_TARGETS = {
    "Dataset",
    "DatasetSpecification",
    "Indicator",
    "IndicatorVersion",
    "IndicatorDimension",
    "InputFlowVersion",
    "OrchestrationFlowVersion",
    "ProcessingProfileVersion",
    "ValidationRule",
    "ValidationRuleVersion",
}
PUBLISHED_CHOICES = {
    ("ProcessingProfileInputFlow", "input_flow_version"),
    ("ProcessingProfileIndicatorVersion", "indicator_version"),
    ("ProcessingProfileVersion", "orchestration_flow_version"),
    ("ContractConfigurationRevision", "processing_profile_version"),
}


def requires_published_choice(field):
    """A newly created draft cannot be selected by these composition fields."""
    return (field.model._meta.concrete_model.__name__, field.name) in PUBLISHED_CHOICES


class CatalogAutocompleteSelect(AutocompleteSelect):
    """Pass the editing owner as context, never arbitrary query expressions."""

    def __init__(self, field, admin_site, *, owner_model=None, owner_pk=None):
        super().__init__(field, admin_site)
        self.owner_model = owner_model
        self.owner_pk = owner_pk

    def get_url(self):
        url = super().get_url()
        if self.owner_model and self.owner_pk:
            url += "?" + urlencode(
                {"owner_model": self.owner_model, "owner_pk": self.owner_pk}
            )
        return url


def relation_formfield(admin_object, field, request, kwargs):
    """Choose a native searchable FK widget without replacing its queryset."""
    target = field.remote_field.model
    if target.__name__ not in CATALOG_TARGETS or "widget" in kwargs:
        return
    related_admin = admin_object.admin_site._registry.get(target)
    if related_admin is None or not related_admin.search_fields:
        return
    match = getattr(request, "resolver_match", None)
    owner_pk = match.kwargs.get("object_id") if match else None
    owner = getattr(admin_object, "parent_model", admin_object.model)
    kwargs["widget"] = CatalogAutocompleteSelect(
        field,
        admin_object.admin_site,
        owner_model=owner._meta.concrete_model._meta.label_lower,
        owner_pk=owner_pk,
    )


def apply_related_controls(field, formfield, request, site=None):
    """Avoid offering a popup that only creates an ineligible draft."""
    if formfield is None or not getattr(field, "remote_field", None):
        return formfield
    if requires_published_choice(field) and hasattr(
        formfield.widget, "can_add_related"
    ):
        formfield.widget.can_add_related = False
        if "Selezionare una versione pubblicata." not in str(formfield.help_text):
            formfield.help_text = format_html(
                "{} {}",
                formfield.help_text or "",
                "Selezionare una versione pubblicata. Una nuova bozza deve essere "
                "completata e pubblicata dal catalogo prima dell’associazione.",
            )
        if site is not None:
            target = field.remote_field.model._meta.concrete_model
            proxy = next(
                (
                    m
                    for m in site._registry
                    if m._meta.proxy and m._meta.concrete_model is target
                ),
                target,
            )
            url = reverse(
                f"{site.name}:{proxy._meta.app_label}_{proxy._meta.model_name}_changelist"
            )
            formfield.help_text = format_html(
                '{} <a href="{}">Apri il catalogo</a>', formfield.help_text, url
            )
    if field.remote_field.model.__name__ == "IndicatorEvaluationThreshold" and hasattr(
        formfield.widget, "can_add_related"
    ):
        formfield.widget.can_add_related = False
        formfield.help_text = str(formfield.help_text or "") + (
            " Creare le soglie dal medesimo indicatore della revisione contrattuale."
        )
    if field.name == "group_by_dimensions" and hasattr(
        formfield.widget, "can_add_related"
    ):
        formfield.widget.can_add_related = False
        formfield.help_text = str(formfield.help_text or "") + (
            " Le dimensioni disponibili provengono dall’output dell’indicatore: "
            "un nuovo elemento del catalogo non le estende."
        )
    return formfield


def wrap_declared_relations(form, admin_object, request):
    """Custom through selectors also get Django's permission-aware related links."""
    for name, field in form.base_fields.items():
        try:
            model_field = admin_object.model._meta.get_field(name)
        except FieldDoesNotExist:
            model_field = None
        if model_field is not None and getattr(model_field, "remote_field", None):
            apply_related_controls(model_field, field, request, admin_object.admin_site)
        if not isinstance(field, forms.ModelMultipleChoiceField) or isinstance(
            field.widget, RelatedFieldWidgetWrapper
        ):
            continue
        target = field.queryset.model._meta.concrete_model
        related = admin_object.admin_site._registry.get(target)
        relation = next(
            (
                f.remote_field
                for f in admin_object.model._meta.many_to_many
                if f.remote_field.model._meta.concrete_model is target
            ),
            None,
        )
        if related is None or relation is None:
            continue
        field.widget = RelatedFieldWidgetWrapper(
            field.widget,
            relation,
            admin_object.admin_site,
            can_add_related=related.has_add_permission(request),
            can_change_related=related.has_change_permission(request),
            can_delete_related=related.has_delete_permission(request),
            can_view_related=related.has_view_permission(request),
        )
        if model_field is not None:
            apply_related_controls(model_field, field, request, admin_object.admin_site)
    return form


def _delegate_permission(name):
    def delegated(self, request, obj=None):
        method = getattr(self.visible_admin, name)
        if name in {"has_module_permission", "has_add_permission"}:
            return method(request)
        return method(request, obj)

    return delegated


def register_related_admins(site):
    """Register hidden concrete destinations using the complete visible admin."""
    for proxy, visible in list(site._registry.items()):
        if not proxy._meta.proxy or not proxy._meta.app_label.startswith("admin_"):
            continue
        concrete = proxy._meta.concrete_model
        existing = site._registry.get(concrete)
        if existing and existing.__class__.__module__ != "rpsd_config.admin_hidden":
            continue
        attributes = {
            "visible_admin": visible,
            "__module__": __name__,
            "get_model_perms": lambda self, request: {},
            **{
                name: _delegate_permission(name)
                for name in (
                    "has_module_permission",
                    "has_view_permission",
                    "has_add_permission",
                    "has_change_permission",
                    "has_delete_permission",
                )
            },
        }
        if existing:
            site.unregister(concrete)
        site.register(
            concrete,
            type(f"Related{concrete.__name__}Admin", (type(visible),), attributes),
        )


def admin_change_url(site, obj):
    """Prefer the public proxy over its hidden concrete counterpart."""
    concrete = obj._meta.concrete_model
    target = next(
        (
            m
            for m in site._registry
            if m._meta.proxy and m._meta.concrete_model is concrete
        ),
        concrete,
    )
    return reverse(
        f"{site.name}:{target._meta.app_label}_{target._meta.model_name}_change",
        args=(obj.pk,),
    )
