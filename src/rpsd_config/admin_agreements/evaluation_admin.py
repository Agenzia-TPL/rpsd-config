# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Contextual, scope-checked contractual evaluation administration."""

from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse

from rpsd_config.admin_agreements.proxies import (
    ContractRevisionIndicatorAdminProxy,
    IndicatorEvaluationThresholdAdminProxy,
    IndicatorPenaltyAdminProxy,
)
from rpsd_config.admin_guidance import GuidedAdminMixin, GuidedInlineMixin, guided_form
from rpsd_config.exchange_agreement.evaluation_forms import (
    EvaluationThresholdForm,
    IndicatorPenaltyForm,
)
from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    ContractRevisionIndicator,
    IndicatorEvaluationThreshold,
    IndicatorPenalty,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    can_prepare_contract_revision,
)
from rpsd_config.exchange_agreement.services.indicator_evaluations import (
    delete_evaluation,
    save_evaluation,
)


def may_view(user, owner):
    from rpsd_config.exchange_agreement.views import (
        _can_view_contract_via_membership_or_agency,
    )

    return _can_view_contract_via_membership_or_agency(
        user=user, contract=owner.revision.contract
    )


class EvaluationAdmin(GuidedAdminMixin, admin.ModelAdmin):
    list_display = ("code", "name", "contract_revision_indicator")
    search_fields = (
        "code",
        "name",
        "contract_revision_indicator__revision__contract__contract_code",
    )
    readonly_fields = ("created_at", "updated_at")
    actions = None

    def eligible_owners(self, request):
        rows = ContractRevisionIndicatorAdminProxy.objects.filter(
            revision__status="draft"
        ).select_related(
            "revision__contract",
            "processing_profile_indicator_version__indicator_version",
        )
        return rows.filter(
            pk__in=[
                row.pk
                for row in rows
                if may_view(request.user, row)
                and can_prepare_contract_revision(
                    user=request.user, contract=row.revision.contract
                )
            ]
        )

    def contextual_owner(self, request, obj=None):
        if obj is not None:
            return obj.contract_revision_indicator
        value = request.GET.get("owner_id")
        if value is None or not value.isdecimal():
            return None
        owner = get_object_or_404(
            ContractRevisionIndicator.objects.select_related("revision__contract"),
            pk=value,
        )
        return owner if may_view(request.user, owner) else None

    def get_queryset(self, request):
        rows = (
            super()
            .get_queryset(request)
            .select_related("contract_revision_indicator__revision__contract")
        )
        ids = [
            row.pk
            for row in rows
            if may_view(request.user, row.contract_revision_indicator)
        ]
        return rows.filter(pk__in=ids)

    def has_add_permission(self, request):
        if not super().has_add_permission(request):
            return False
        if "owner_id" not in request.GET:
            return self.eligible_owners(request).exists()
        owner = self.contextual_owner(request)
        return bool(
            owner
            and owner.revision.status == "draft"
            and super().has_add_permission(request)
            and can_prepare_contract_revision(
                user=request.user, contract=owner.revision.contract
            )
        )

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            obj is None or may_view(request.user, obj.contract_revision_indicator)
        )

    def has_change_permission(self, request, obj=None):
        if obj is None:
            return super().has_change_permission(request, obj)
        owner = self.contextual_owner(request, obj)
        return bool(
            owner
            and owner.revision.status == "draft"
            and super().has_change_permission(request, obj)
            and can_prepare_contract_revision(
                user=request.user, contract=owner.revision.contract
            )
        )

    def add_view(self, request, form_url="", extra_context=None):
        if "owner_id" in request.GET:
            return super().add_view(request, form_url, extra_context)
        if request.method != "GET" or not self.has_add_permission(request):
            raise PermissionDenied
        selection_form = forms.Form()
        selection_form.fields["owner_id"] = forms.ModelChoiceField(
            queryset=self.eligible_owners(request),
            label="Indicatore della revisione contrattuale",
            help_text=(
                "Scegli l'indicatore in una revisione in bozza. "
                "Il modulo successivo mostrerà le metriche e le dimensioni disponibili."
            ),
        )
        context = {
            **self.admin_site.each_context(request),
            **(extra_context or {}),
            "title": f"Aggiungi {self.opts.verbose_name}",
            "opts": self.opts,
            "selection_form": selection_form,
        }
        return TemplateResponse(request, "admin/evaluations/select_owner.html", context)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "group_by_dimensions":
            return db_field.formfield(**kwargs)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(
            request, obj
        ) and self.has_change_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.contract_revision_indicator.revision.status != "draft":
            return tuple(
                field.name for field in self.model._meta.fields if not field.primary_key
            ) + ("group_by_dimensions",)
        return self.readonly_fields

    def get_form(self, request, obj=None, **kwargs):
        owner = self.contextual_owner(request, obj)
        base_form = super().get_form(request, obj, **kwargs)

        class ContextualForm(base_form):
            def __init__(self, *args, **form_kwargs):
                form_kwargs["owner"] = owner
                super().__init__(*args, **form_kwargs)

        return guided_form(
            ContextualForm,
            self.model,
            extra_fields=self.get_readonly_fields(request, obj),
        )

    def save_model(self, request, obj, form, change):
        save_evaluation(
            obj,
            dimensions=form.cleaned_data.get("group_by_dimensions", []),
            actor=request.user,
        )

    def save_related(self, request, form, formsets, change):
        # The shared service writes guarded through rows inside the admin transaction.
        return None

    def delete_model(self, request, obj):
        delete_evaluation(obj, actor=request.user)


@admin.register(IndicatorEvaluationThresholdAdminProxy)
class ThresholdAdmin(EvaluationAdmin):
    form = EvaluationThresholdForm
    exclude = ("contract_revision_indicator",)


@admin.register(IndicatorPenaltyAdminProxy)
class PenaltyAdmin(EvaluationAdmin):
    form = IndicatorPenaltyForm
    exclude = ("contract_revision_indicator",)


class EvaluationInline(GuidedInlineMixin, admin.StackedInline):
    """Native inline with the same contextual forms and writes as the web UI."""

    extra = 0
    template = "admin/edit_inline/stacked.html"
    readonly_fields = ("created_at", "updated_at")

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "group_by_dimensions":
            # Explicit through models are written by save_evaluation, not save_m2m.
            return db_field.formfield(**kwargs)
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def editable(self, request, obj):
        return bool(
            obj
            and obj.revision.status == "draft"
            and may_view(request.user, obj)
            and can_prepare_contract_revision(
                user=request.user, contract=obj.revision.contract
            )
        )

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and self.editable(request, obj)

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and self.editable(
            request, obj
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and self.editable(
            request, obj
        )

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        base_form = formset.form

        class ContextualForm(base_form):
            def __init__(self, *args, **form_kwargs):
                form_kwargs["owner"] = obj
                super().__init__(*args, **form_kwargs)

        formset.form = ContextualForm
        return formset


class ThresholdInline(EvaluationInline):
    model = IndicatorEvaluationThreshold
    form = EvaluationThresholdForm
    verbose_name = "Soglia"
    verbose_name_plural = "Soglie di valutazione"


class PenaltyInline(EvaluationInline):
    model = IndicatorPenalty
    form = IndicatorPenaltyForm
    verbose_name = "Penale"
    verbose_name_plural = "Penali cumulative"


@admin.register(ContractRevisionIndicatorAdminProxy)
class RevisionIndicatorAdmin(admin.ModelAdmin):
    """Edit contractual values and child evaluations without nested inlines."""

    list_display = ("__str__", "revision_status")
    search_fields = (
        "revision__code",
        "revision__contract__contract_code",
        "processing_profile_indicator_version__indicator_version__code",
    )
    fields = (
        "revision",
        "processing_profile_indicator_version",
        "parameters",
        "aggregation",
    )
    readonly_fields = ("revision", "processing_profile_indicator_version")
    inlines = (ThresholdInline, PenaltyInline)
    actions = None

    @admin.display(description="Stato revisione")
    def revision_status(self, obj):
        return obj.revision.get_status_display()

    def get_queryset(self, request):
        rows = (
            super()
            .get_queryset(request)
            .select_related(
                "revision__contract",
                "processing_profile_indicator_version__indicator_version",
            )
        )
        return rows.filter(
            pk__in=[row.pk for row in rows if may_view(request.user, row)]
        )

    def has_add_permission(self, request):
        return False  # Selections are made in the contract revision.

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and (
            obj is None or may_view(request.user, obj)
        )

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and (
            obj is None
            or (
                obj.revision.status == "draft"
                and may_view(request.user, obj)
                and can_prepare_contract_revision(
                    user=request.user, contract=obj.revision.contract
                )
            )
        )

    def save_model(self, request, obj, form, change):
        revision = ContractConfigurationRevision.objects.select_for_update().get(
            pk=obj.revision_id
        )
        if revision.status != "draft" or not self.has_change_permission(request, obj):
            raise PermissionDenied
        obj.full_clean()
        obj.save()

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for target in formset.deleted_objects:
            delete_evaluation(target, actor=request.user)
        for target in instances:
            bound_form = next(f for f in formset.forms if f.instance is target)
            save_evaluation(
                target,
                dimensions=bound_form.cleaned_data.get("group_by_dimensions", []),
                actor=request.user,
            )
