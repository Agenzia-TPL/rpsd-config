# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from django.http import HttpRequest

from ..models import Company, IntegrationPrincipal

logger = logging.getLogger(__name__)


def resolve_request_id(request: HttpRequest | None) -> str:
    if request is None:
        return uuid.uuid4().hex

    for key in ("HTTP_X_REQUEST_ID", "HTTP_X_CORRELATION_ID"):
        value = (request.META.get(key) or "").strip()
        if value:
            return value[:128]

    meta_request_id = (
        (request.META.get("REQUEST_ID") or "").strip()
        or (request.META.get("request_id") or "").strip()
    )
    if meta_request_id:
        return meta_request_id[:128]

    return uuid.uuid4().hex


def audit_m2m_event(
    event_name: str,
    *,
    request_id: str | None = None,
    outcome: str = "success",
    actor=None,
    company: Company | None = None,
    principal: IntegrationPrincipal | None = None,
    reason: str = "",
    extra: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "request_id": request_id or uuid.uuid4().hex,
        "outcome": outcome,
    }
    if actor is not None and getattr(actor, "pk", None) is not None:
        payload["actor_user_id"] = actor.pk
        payload["actor_username"] = getattr(actor, "username", "")
    if company is not None:
        payload["company_id"] = company.id
        payload["company_name"] = company.name
    if principal is not None:
        payload["integration_principal_id"] = principal.id
        payload["keycloak_client_id"] = principal.keycloak_client_id
        payload["keycloak_client_uuid"] = principal.keycloak_client_uuid
        payload["principal_status"] = principal.status
    if reason:
        payload["reason"] = reason
    if extra:
        payload.update(dict(extra))

    log_method = logger.info if outcome == "success" else logger.warning
    log_method(f"m2m.audit.{event_name}", extra=payload)
