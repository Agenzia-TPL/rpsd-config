# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope


def navigation_context(request):
    user = getattr(request, "user", None)
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    can_view_configuration = False

    if is_authenticated and user is not None:
        agency_scope = resolve_user_agency_scope(user)
        can_view_configuration = agency_scope.is_platform_admin

    return {
        "app_navigation": {
            "is_authenticated": is_authenticated,
            "can_view_user_area": is_authenticated,
            "can_view_agencies": is_authenticated,
            "can_view_configuration": can_view_configuration,
        }
    }

