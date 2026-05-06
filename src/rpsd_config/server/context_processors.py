# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from django.urls import NoReverseMatch, reverse

from rpsd_config.exchange_agreement.models import ContractMembership
from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope


_ACTIVE_SECTION_BY_URL_NAME = {
    "user-area": "user",
    "user-area-legacy": "user",
    "received-invitations": "user",
    "contract-invitation-create": "user",
    "user-contracts": "contracts",
    "user-contract-detail": "contracts",
    "agencies": "agencies",
    "agency-bootstrap": "agencies",
    "agency-detail": "agencies",
    "agency-lot-detail": "agencies",
    "agency-contracts": "agencies",
    "agency-contract-create": "agencies",
    "agency-contract-detail": "agencies",
    "agency-invitation-create": "agencies",
    "company-list": "companies",
    "company-create": "companies",
    "company-detail": "companies",
    "platform-configuration": "configuration",
}


def _reverse_url(name: str, *args) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


def _crumb(label: str, url: str = "", *, current: bool = False) -> dict:
    return {
        "label": label,
        "url": url,
        "current": current,
    }


def _context_bar_for_request(request) -> dict:
    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    kwargs = getattr(resolver_match, "kwargs", {}) or {}

    platform_url = _reverse_url("home")
    user_area_url = _reverse_url("exchange_agreement:user-area")
    user_contracts_url = _reverse_url("exchange_agreement:user-contracts")
    agencies_url = _reverse_url("exchange_agreement:agencies")
    companies_url = _reverse_url("exchange_agreement:company-list")
    agency_key = kwargs.get("agency_key", "")
    contract_code = kwargs.get("contract_code", "")
    lot_id = kwargs.get("lot_id", "")

    agency_url = (
        _reverse_url("exchange_agreement:agency-detail", agency_key)
        if agency_key
        else ""
    )
    agency_contracts_url = (
        _reverse_url("exchange_agreement:agency-contracts", agency_key)
        if agency_key
        else ""
    )

    base = [_crumb("RPSD Config", platform_url)]

    if url_name in {"user-area", "user-area-legacy"}:
        return {
            "breadcrumbs": [*base, _crumb("Area utente", current=True)],
            "back_url": "",
            "back_label": "",
        }
    if url_name == "received-invitations":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Area utente", user_area_url),
                _crumb("Inviti ricevuti", current=True),
            ],
            "back_url": user_area_url,
            "back_label": "Area utente",
        }
    if url_name == "contract-invitation-create":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Area utente", user_area_url),
                _crumb("Nuovo invito contratto", current=True),
            ],
            "back_url": user_area_url,
            "back_label": "Area utente",
        }
    if url_name == "user-contracts":
        return {
            "breadcrumbs": [*base, _crumb("Contratti", current=True)],
            "back_url": "",
            "back_label": "",
        }
    if url_name == "user-contract-detail":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Contratti", user_contracts_url),
                _crumb(str(contract_code), current=True),
            ],
            "back_url": user_contracts_url,
            "back_label": "Contratti",
        }
    if url_name == "agencies":
        return {
            "breadcrumbs": [*base, _crumb("Agenzie", current=True)],
            "back_url": "",
            "back_label": "",
        }
    if url_name == "agency-bootstrap":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb("Bootstrap nuova agenzia", current=True),
            ],
            "back_url": agencies_url,
            "back_label": "Agenzie",
        }
    if url_name == "agency-detail":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb(str(agency_key), current=True),
            ],
            "back_url": agencies_url,
            "back_label": "Agenzie",
        }
    if url_name == "agency-lot-detail":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb(str(agency_key), agency_url),
                _crumb(f"Lotto {lot_id}", current=True),
            ],
            "back_url": agency_url,
            "back_label": "Dettaglio agenzia",
        }
    if url_name == "agency-contracts":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb(str(agency_key), agency_url),
                _crumb("Contratti", current=True),
            ],
            "back_url": agency_url,
            "back_label": "Dettaglio agenzia",
        }
    if url_name == "agency-contract-create":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb(str(agency_key), agency_url),
                _crumb("Contratti", agency_contracts_url),
                _crumb("Nuovo contratto", current=True),
            ],
            "back_url": agency_contracts_url,
            "back_label": "Contratti agenzia",
        }
    if url_name == "agency-contract-detail":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb(str(agency_key), agency_url),
                _crumb("Contratti", agency_contracts_url),
                _crumb(str(contract_code), current=True),
            ],
            "back_url": agency_contracts_url,
            "back_label": "Contratti agenzia",
        }
    if url_name == "agency-invitation-create":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Agenzie", agencies_url),
                _crumb("Nuovo invito agenzia", current=True),
            ],
            "back_url": agencies_url,
            "back_label": "Agenzie",
        }
    if url_name == "company-list":
        return {
            "breadcrumbs": [*base, _crumb("Aziende", current=True)],
            "back_url": "",
            "back_label": "",
        }
    if url_name == "company-create":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Aziende", companies_url),
                _crumb("Nuova azienda", current=True),
            ],
            "back_url": companies_url,
            "back_label": "Aziende",
        }
    if url_name == "company-detail":
        return {
            "breadcrumbs": [
                *base,
                _crumb("Aziende", companies_url),
                _crumb(f"Azienda {kwargs.get('company_id', '')}", current=True),
            ],
            "back_url": companies_url,
            "back_label": "Aziende",
        }
    if url_name == "platform-configuration":
        return {
            "breadcrumbs": [*base, _crumb("Configurazione", current=True)],
            "back_url": "",
            "back_label": "",
        }

    return {"breadcrumbs": [], "back_url": "", "back_label": ""}


def navigation_context(request):
    user = getattr(request, "user", None)
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    can_view_configuration = False
    can_view_companies = False
    has_contract_memberships = False
    resolver_match = getattr(request, "resolver_match", None)
    url_name = getattr(resolver_match, "url_name", "") or ""
    active_section = _ACTIVE_SECTION_BY_URL_NAME.get(url_name, "")

    if is_authenticated and user is not None:
        agency_scope = resolve_user_agency_scope(user)
        can_view_configuration = agency_scope.is_platform_admin or user.is_superuser
        can_view_companies = (
            agency_scope.is_platform_admin
            or user.is_superuser
            or bool(agency_scope.admin_agency_keys)
        )
        has_contract_memberships = ContractMembership.objects.filter(
            user=user
        ).exists()

    nav_items = [
        {
            "section": "agencies",
            "label": "Agenzie",
            "url": _reverse_url("exchange_agreement:agencies"),
            "icon": "agency",
            "visible": is_authenticated,
            "active": active_section == "agencies",
        },
        {
            "section": "contracts",
            "label": "Contratti",
            "url": _reverse_url("exchange_agreement:user-contracts"),
            "icon": "file-text",
            "visible": has_contract_memberships,
            "active": active_section == "contracts",
        },
        {
            "section": "companies",
            "label": "Aziende",
            "url": _reverse_url("exchange_agreement:company-list"),
            "icon": "company",
            "visible": can_view_companies,
            "active": active_section == "companies",
        },
        {
            "section": "configuration",
            "label": "Configurazione",
            "url": _reverse_url("exchange_agreement:platform-configuration"),
            "icon": "settings",
            "visible": can_view_configuration,
            "active": active_section == "configuration",
        },
        {
            "section": "user",
            "label": "Area utente",
            "url": _reverse_url("exchange_agreement:user-area"),
            "icon": "user",
            "visible": is_authenticated,
            "active": active_section == "user",
        },
    ]

    return {
        "app_navigation": {
            "is_authenticated": is_authenticated,
            "can_view_user_area": is_authenticated,
            "can_view_agencies": is_authenticated,
            "can_view_configuration": can_view_configuration,
            "can_view_companies": can_view_companies,
            "can_view_contracts": has_contract_memberships,
            "active_section": active_section,
            "items": nav_items,
            "context_bar": _context_bar_for_request(request),
        }
    }
