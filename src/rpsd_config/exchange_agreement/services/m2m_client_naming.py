# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import hashlib

from django.conf import settings
from django.utils.text import slugify

from ..models import Company, IntegrationPrincipal


def resolve_default_m2m_client_id(
    company: Company,
    *,
    environment: str | None = None,
) -> str:
    env = (
        environment or getattr(settings, "M2M_DEFAULT_ENVIRONMENT", "prod")
    ).strip().lower()
    existing = (
        IntegrationPrincipal.objects.filter(company=company, environment=env)
        .order_by("id")
        .first()
    )
    if existing is not None:
        return existing.keycloak_client_id

    base = slugify(company.name or f"company-{company.pk}", allow_unicode=False)
    base = base.strip("-") or f"company-{company.pk}"
    suffix = getattr(settings, "M2M_DEFAULT_CLIENT_SUFFIX", "default-prod")
    candidate = f"{base}-{suffix}".lower()
    if not IntegrationPrincipal.objects.filter(keycloak_client_id=candidate).exists():
        return candidate

    digest = hashlib.sha1(
        f"{company.pk}:{company.name}:{env}".encode("utf-8")
    ).hexdigest()[:8]
    return f"{base}-{suffix}-{digest}".lower()
