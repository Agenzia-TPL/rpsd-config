# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib import admin
from django.urls import path

from .views import (
    agencies_page,
    agency_contract_detail_page,
    agency_contracts_page,
    agency_detail_page,
    agency_lot_detail_page,
    bootstrap_agency_page,
    bootstrap_agency_result_page,
    company_create_page,
    company_detail_page,
    company_list_page,
    create_agency_contract_page,
    create_agency_invitation_page,
    create_contract_invitation_page,
    invitation_landing,
    onboarding_callback,
    platform_configuration_page,
    received_invitations,
    user_area,
)

app_name = "exchange_agreement"

admin.site.site_header = "Rapsodia Config"
admin.site.site_title = "Rapsodia Config"
admin.site.index_title = "Admin"


urlpatterns = [
    path("invite/<uuid:token>/", invitation_landing, name="invitation-landing"),
    path("onboarding/callback/", onboarding_callback, name="onboarding-callback"),
    path("me/", user_area, name="user-area"),
    path("me/contracts/", user_area, name="user-area-legacy"),
    path("me/agencies/", agencies_page, name="agencies"),
    path("me/companies/", company_list_page, name="company-list"),
    path("me/companies/new/", company_create_page, name="company-create"),
    path(
        "me/companies/<int:company_id>/",
        company_detail_page,
        name="company-detail",
    ),
    path(
        "me/agencies/bootstrap/",
        bootstrap_agency_page,
        name="agency-bootstrap",
    ),
    path(
        "me/agencies/bootstrap/result/",
        bootstrap_agency_result_page,
        name="agency-bootstrap-result",
    ),
    path(
        "me/agencies/<slug:agency_key>/",
        agency_detail_page,
        name="agency-detail",
    ),
    path(
        "me/agencies/<slug:agency_key>/lots/<int:lot_id>/",
        agency_lot_detail_page,
        name="agency-lot-detail",
    ),
    path(
        "me/agencies/<slug:agency_key>/contracts/",
        agency_contracts_page,
        name="agency-contracts",
    ),
    path(
        "me/agencies/<slug:agency_key>/contracts/new/",
        create_agency_contract_page,
        name="agency-contract-create",
    ),
    path(
        "me/agencies/<slug:agency_key>/contracts/<str:contract_code>/",
        agency_contract_detail_page,
        name="agency-contract-detail",
    ),
    path(
        "me/platform-configuration/",
        platform_configuration_page,
        name="platform-configuration",
    ),
    path("me/invitations/", received_invitations, name="received-invitations"),
    path(
        "me/contract-invitations/new/",
        create_contract_invitation_page,
        name="contract-invitation-create",
    ),
    path(
        "me/agency-invitations/new/",
        create_agency_invitation_page,
        name="agency-invitation-create",
    ),
]
