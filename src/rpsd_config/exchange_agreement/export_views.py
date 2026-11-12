# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""User/admin downloads of saved revisions, distinct from operational APIs."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from rpsd_config.exchange_agreement.models import ContractConfigurationRevision
from rpsd_config.exchange_agreement.services.configuration_exports import (
    ConfigurationExportError,
    export_contract_configuration,
    load_revision_asset,
)


def export_arguments(query):
    return {
        name: query.get(name) or None
        for name in ("dataset_code", "indicator_version_code")
    } | {"scope": query.get("scope") or "revision"}


def export_response(payload):
    response = JsonResponse(
        payload, json_dumps_params={"ensure_ascii": False, "indent": 2}
    )
    response["Content-Disposition"] = (
        'attachment; filename="contract-configuration.json"'
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def configuration_export_page(
    request, contract_code, revision_id, *, admin_context=None
):
    revision = get_object_or_404(
        ContractConfigurationRevision,
        pk=revision_id,
        contract__contract_code=contract_code,
    )
    try:
        kwargs = export_arguments(request.GET) if "download" in request.GET else {}
        payload = export_contract_configuration(
            actor=request.user,
            contract_code=contract_code,
            revision_code=revision.code,
            **kwargs,
        )
    except ConfigurationExportError as exc:
        return JsonResponse({"code": exc.code, "message": str(exc)}, status=exc.status)
    if "download" in request.GET:
        return export_response(payload)
    context = {
        **(admin_context or {}),
        "revision": revision,
        "preview": payload,
        "title": "Esporta configurazione salvata",
        "is_admin": admin_context is not None,
        "base_template": "admin/base_site.html"
        if admin_context is not None
        else "base.html",
    }
    response = render(request, "exchange_agreement/configuration_export.html", context)
    response["Cache-Control"] = "private, no-store"
    return response


configuration_export_page = login_required(require_GET(configuration_export_page))


@login_required
@require_GET
def revision_asset_download(request, contract_code, revision_id, asset_id):
    revision = get_object_or_404(
        ContractConfigurationRevision,
        pk=revision_id,
        contract__contract_code=contract_code,
    )
    try:
        asset, content = load_revision_asset(
            actor=request.user,
            contract_code=contract_code,
            revision_code=revision.code,
            asset_id=asset_id,
        )
    except ConfigurationExportError as exc:
        return JsonResponse({"code": exc.code, "message": str(exc)}, status=exc.status)
    except ValidationError as exc:
        return JsonResponse(
            {"code": "asset_integrity_error", "message": " ".join(exc.messages)},
            status=409,
        )
    except Http404:
        raise
    response = HttpResponse(
        content, content_type=asset.content_type or "application/octet-stream"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="asset-{asset.checksum_sha256}.bin"'
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
