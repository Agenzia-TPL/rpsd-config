# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Documented AdminSite extension for constrained native autocomplete."""

from django.apps import apps
from django.contrib.admin import AdminSite
from django.contrib.admin.views.autocomplete import AutocompleteJsonView

from rpsd_config.admin_relations import requires_published_choice


class CatalogAutocompleteJsonView(AutocompleteJsonView):
    """Retain the source relation's catalog and lifecycle constraints."""

    def get_queryset(self):
        queryset = super().get_queryset()
        field = self.source_field
        source = field.model._meta.concrete_model.__name__
        if requires_published_choice(field):
            queryset = queryset.filter(status="published")
        if (
            source in {"DatasetVersionRule", "IndicatorVersionRule"}
            and field.name == "rule_version"
        ):
            queryset = queryset.exclude(validation_type_version__validation_type="dbt")
        if source in {
            "IndicatorVersionInput",
            "IndicatorVersionDependency",
            "IndicatorVersionRule",
            "DatasetVersionRule",
        }:
            if hasattr(queryset.model, "status"):
                allowed = ["published"]
                if self._draft_composition_allowed():
                    allowed.append("draft")
                queryset = queryset.filter(status__in=allowed)
        return queryset

    def _draft_composition_allowed(self):
        label = self.request.GET.get("owner_model", "")
        pk = self.request.GET.get("owner_pk", "")
        if not label or not pk:
            return True  # An unsaved formal definition may compose draft versions.
        if not pk.isdecimal():
            return False
        try:
            model = apps.get_model(label)
        except (LookupError, ValueError):
            return False
        owner_fields = {
            "IndicatorVersionRule": "indicator_version",
            "IndicatorVersionInput": "indicator_version",
            "IndicatorVersionDependency": "dependent",
            "DatasetVersionRule": "dataset_specification",
        }
        if model.__name__ not in {
            "IndicatorVersion",
            "DatasetSpecification",
            *owner_fields,
        }:
            return False
        # The destination's ModelAdmin permissions/queryset remain authoritative.
        owner_admin = self.admin_site._registry.get(model)
        if owner_admin is None or not owner_admin.has_view_permission(self.request):
            return False
        owner = owner_admin.get_queryset(self.request).filter(pk=pk).first()
        if owner is not None and model.__name__ in owner_fields:
            owner = getattr(owner, owner_fields[model.__name__])
        if owner is None or owner.status != "draft":
            return False
        return owner._meta.concrete_model.__name__ == "DatasetSpecification" or bool(
            owner.definition_kind
        )


class RpsdAdminSite(AdminSite):
    """Use native admin URLs, with a constrained autocomplete implementation."""

    def autocomplete_view(self, request):
        return CatalogAutocompleteJsonView.as_view(admin_site=self)(request)
