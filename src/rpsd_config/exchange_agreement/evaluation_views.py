# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Contract-scoped evaluation configuration, without triggering external jobs."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from rpsd_config.exchange_agreement.evaluation_forms import (
    EvaluationThresholdForm,
    IndicatorParametersForm,
    IndicatorPenaltyForm,
)
from rpsd_config.exchange_agreement.models import (
    ContractRevisionIndicator,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    can_prepare_contract_revision,
    require_revision_preparer,
)
from rpsd_config.exchange_agreement.services.indicator_evaluations import (
    delete_evaluation,
    save_evaluation,
)
from rpsd_config.exchange_agreement.services.revision_indicator_values import (
    save_revision_indicator_values,
)


@login_required
@require_http_methods(["GET", "POST"])
def indicator_evaluations_page(request, contract_code, revision_id, owner_id):
    """Use the same model forms and authorized services as Django admin."""
    from rpsd_config.exchange_agreement.views import (
        _can_view_contract_via_membership_or_agency,
    )

    owner = get_object_or_404(
        ContractRevisionIndicator.objects.select_related(
            "revision__contract__client_agency",
            "processing_profile_indicator_version__indicator_version",
        ),
        pk=owner_id,
        revision_id=revision_id,
        revision__contract__contract_code=contract_code,
    )
    revision, contract = owner.revision, owner.revision.contract
    if not _can_view_contract_via_membership_or_agency(
        user=request.user, contract=contract
    ):
        raise PermissionDenied("Non hai accesso a questo contratto.")
    editable = revision.status == "draft" and can_prepare_contract_revision(
        user=request.user, contract=contract
    )
    kind = (
        request.POST.get("kind", "")
        if request.method == "POST"
        else request.GET.get("kind", "")
    )
    if kind and kind not in {"threshold", "penalty"}:
        raise Http404
    kind = kind or "threshold"
    form_class = IndicatorPenaltyForm if kind == "penalty" else EvaluationThresholdForm
    queryset = (
        owner.evaluation_penalties if kind == "penalty" else owner.evaluation_thresholds
    )
    target_id = (
        request.POST.get("target_id")
        if request.method == "POST"
        else request.GET.get("target_id")
    )
    if target_id and not str(target_id).isdecimal():
        raise Http404
    target = get_object_or_404(queryset, pk=target_id) if target_id else None
    form = form_class(owner=owner, instance=target)
    parameter_form = IndicatorParametersForm(owner=owner)
    error = ""
    if request.method == "POST":
        if not editable:
            raise PermissionDenied("Solo una bozza nel tuo perimetro è modificabile.")
        require_revision_preparer(user=request.user, contract=contract)
        action = request.POST.get("action", "")
        try:
            if action == "save-evaluation":
                form = form_class(request.POST, owner=owner, instance=target)
                if form.is_valid():
                    save_evaluation(
                        form.save(commit=False),
                        dimensions=form.cleaned_data["group_by_dimensions"],
                        actor=request.user,
                    )
                    return redirect(request.path)
            elif action == "delete-evaluation" and target is not None:
                delete_evaluation(target, actor=request.user)
                return redirect(request.path)
            elif action == "save-parameters":
                parameter_form = IndicatorParametersForm(request.POST, owner=owner)
                if parameter_form.is_valid():
                    save_revision_indicator_values(
                        revision,
                        version_code=owner.processing_profile_indicator_version.indicator_version.code,
                        values={
                            "parameters": parameter_form.cleaned_data,
                            "aggregation": owner.aggregation,
                            "thresholds": owner.thresholds,
                            "penalties": owner.penalties,
                        },
                        actor=request.user,
                    )
                    return redirect(request.path)
        except (ValidationError, ProtectedError) as exc:
            error = (
                " ".join(exc.messages)
                if isinstance(exc, ValidationError)
                else (
                    "La soglia è utilizzata da una penale: prima modifica"
                    " o rimuovi la penale."
                )
            )
    return render(
        request,
        "exchange_agreement/indicator_evaluations.html",
        {
            "owner": owner,
            "revision": revision,
            "contract": contract,
            "form": form,
            "parameter_form": parameter_form,
            "kind": kind,
            "target": target,
            "editable": editable,
            "error_message": error,
            "thresholds": owner.evaluation_thresholds.all(),
            "penalties": owner.evaluation_penalties.all(),
            "preview": json.dumps(form.context_preview(), ensure_ascii=False, indent=2),
            "back_url": reverse(
                "exchange_agreement:contract-revision-detail",
                args=[contract_code, revision_id],
            ),
        },
    )
