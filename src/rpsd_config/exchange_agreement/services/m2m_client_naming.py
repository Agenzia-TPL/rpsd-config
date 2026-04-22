# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import hashlib

from django.conf import settings
from django.utils.text import slugify

from ..models import Company, IntegrationPrincipal

DEFAULT_M2M_INTEGRATION_NAME = "default"
DEFAULT_M2M_ENVIRONMENT = IntegrationPrincipal.Environment.PROD
MAX_KEYCLOAK_CLIENT_ID_LENGTH = 255


def _normalize_slug(value: str, *, fallback: str) -> str:
    normalized = slugify((value or "").strip(), allow_unicode=False).strip("-")
    return normalized or fallback


def _normalize_client_suffix(suffix: str | None = None) -> str:
    configured = suffix or getattr(settings, "M2M_CLIENT_ID_SUFFIX", "default-prod")
    return _normalize_slug(configured, fallback="default-prod")


def _append_tail(base: str, tail: str) -> str:
    clean_base = (base or "").strip("-")
    clean_tail = (tail or "").strip("-")
    if not clean_tail:
        candidate = clean_base[:MAX_KEYCLOAK_CLIENT_ID_LENGTH]
        return candidate.strip("-") or "m2m-client"

    max_base_length = MAX_KEYCLOAK_CLIENT_ID_LENGTH - len(clean_tail) - 1
    if max_base_length < 1:
        return clean_tail[:MAX_KEYCLOAK_CLIENT_ID_LENGTH]

    trimmed_base = clean_base[:max_base_length].rstrip("-")
    if not trimmed_base:
        trimmed_base = "m2m"
    return f"{trimmed_base}-{clean_tail}"


def _build_company_slug(company: Company) -> str:
    base = company.name or f"company-{company.pk or ''}".strip("-")
    return _normalize_slug(base, fallback="company")


def _build_collision_marker(company: Company) -> str:
    if company.pk:
        return f"c{company.pk}"
    digest = hashlib.sha1((company.name or "").encode("utf-8")).hexdigest()[:8]
    return f"h{digest}"


def _client_id_conflict(client_id: str) -> IntegrationPrincipal | None:
    return (
        IntegrationPrincipal.objects.filter(keycloak_client_id=client_id)
        .order_by("id")
        .first()
    )


def resolve_default_m2m_client_id(
    *, company: Company, suffix: str | None = None
) -> str:
    """Return deterministic client_id for the company's default M2M principal.

    Behaviour:
    1. If a default/prod IntegrationPrincipal already exists for company, reuse it.
    2. Otherwise derive `<company-slug>-<suffix>` (default suffix from settings).
    3. On conflict with another company, derive deterministic collision-safe fallback.
    """

    existing = (
        IntegrationPrincipal.objects.filter(
            company=company,
            name=DEFAULT_M2M_INTEGRATION_NAME,
            environment=DEFAULT_M2M_ENVIRONMENT,
        )
        .order_by("id")
        .first()
    )
    if existing is not None:
        return existing.keycloak_client_id

    company_slug = _build_company_slug(company)
    normalized_suffix = _normalize_client_suffix(suffix)
    canonical = _append_tail(company_slug, normalized_suffix)

    conflict = _client_id_conflict(canonical)
    if conflict is None or conflict.company_id == company.id:
        return canonical

    collision_marker = _build_collision_marker(company)
    fallback = _append_tail(canonical, collision_marker)
    conflict = _client_id_conflict(fallback)
    if conflict is None or conflict.company_id == company.id:
        return fallback

    attempt = 2
    while True:
        candidate = _append_tail(canonical, f"{collision_marker}-{attempt}")
        conflict = _client_id_conflict(candidate)
        if conflict is None or conflict.company_id == company.id:
            return candidate
        attempt += 1
