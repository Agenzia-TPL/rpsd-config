# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Contextual, scope-checked contractual evaluation administration."""

from django.contrib import admin
from django.shortcuts import get_object_or_404

from rpsd_config.admin_agreements.proxies import (
    IndicatorEvaluationThresholdAdminProxy,
    IndicatorPenaltyAdminProxy,
)
from rpsd_config.admin_guidance import GuidedAdminMixin, guided_form
from rpsd_config.exchange_agreement.evaluation_forms import (
    EvaluationThresholdForm,
    IndicatorPenaltyForm,
)
from rpsd_config.exchange_agreement.models import ContractRevisionIndicator
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
        owner = self.contextual_owner(request, obj)
        return bool(
            owner
            and owner.revision.status == "draft"
            and super().has_change_permission(request, obj)
            and can_prepare_contract_revision(
                user=request.user, contract=owner.revision.contract
            )
        )

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
