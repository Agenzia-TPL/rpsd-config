# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve, reverse

from rpsd_config.exchange_agreement.rbac import AgencyScope
from rpsd_config.server.context_processors import navigation_context


def _scope(*, platform_admin: bool = True) -> AgencyScope:
    admin_keys = {"agenzia-tpl-davide"} if platform_admin else set()
    return AgencyScope(
        is_platform_admin=platform_admin,
        admin_agency_keys=frozenset(admin_keys),
        editor_agency_keys=frozenset(),
        reader_agency_keys=frozenset(),
    )


class NavigationContextTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, is_superuser=False)

    def _request(self, name: str, *args):
        path = reverse(name, args=args)
        request = self.factory.get(path)
        request.user = self.user
        request.resolver_match = resolve(path)
        return request

    def _context(self, name: str, *args, platform_admin: bool = True):
        request = self._request(name, *args)
        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=platform_admin),
        ):
            return navigation_context(request)["app_navigation"]

    def test_contract_detail_activates_agencies(self):
        nav = self._context(
            "exchange_agreement:agency-contract-detail",
            "agenzia-tpl-davide",
            "mil-1-202605",
        )

        self.assertEqual(nav["active_section"], "agencies")
        self.assertEqual(
            [item["section"] for item in nav["items"] if item["active"]],
            ["agencies"],
        )
        self.assertEqual(nav["context_bar"]["back_label"], "Contratti agenzia")
        self.assertEqual(nav["context_bar"]["breadcrumbs"][0]["label"], "RPSD Config")
        self.assertEqual(
            nav["context_bar"]["breadcrumbs"][-1]["label"],
            "mil-1-202605",
        )

    def test_user_area_has_root_breadcrumb(self):
        nav = self._context("exchange_agreement:user-area")

        self.assertEqual(nav["active_section"], "user")
        self.assertEqual(
            nav["context_bar"]["breadcrumbs"],
            [
                {"label": "RPSD Config", "url": "/", "current": False},
                {"label": "Area utente", "url": "", "current": True},
            ],
        )

    def test_company_list_activates_companies(self):
        nav = self._context("exchange_agreement:company-list")

        self.assertEqual(nav["active_section"], "companies")
        self.assertEqual(
            [item["section"] for item in nav["items"] if item["active"]],
            ["companies"],
        )

    def test_company_create_activates_companies_with_parent_breadcrumb(self):
        nav = self._context("exchange_agreement:company-create")

        self.assertEqual(nav["active_section"], "companies")
        self.assertEqual(nav["context_bar"]["back_label"], "Aziende")
        self.assertEqual(
            [crumb["label"] for crumb in nav["context_bar"]["breadcrumbs"]],
            ["RPSD Config", "Aziende", "Nuova azienda"],
        )

    def test_configuration_activates_configuration(self):
        nav = self._context("exchange_agreement:platform-configuration")

        self.assertEqual(nav["active_section"], "configuration")
        self.assertEqual(
            [item["section"] for item in nav["items"] if item["active"]],
            ["configuration"],
        )

    def test_non_admin_does_not_see_company_or_configuration_items(self):
        nav = self._context("exchange_agreement:user-area", platform_admin=False)

        visible_sections = {
            item["section"] for item in nav["items"] if item["visible"]
        }
        self.assertEqual(visible_sections, {"user", "agencies"})

    def test_user_area_is_last_navigation_item(self):
        nav = self._context("exchange_agreement:user-area")

        self.assertEqual(
            [item["section"] for item in nav["items"]],
            ["agencies", "companies", "configuration", "user"],
        )

    def test_local_icon_sprite_is_discoverable(self):
        self.assertIsNotNone(finders.find("icons/rpsd-icons.svg"))

    def test_home_static_background_assets_are_discoverable(self):
        self.assertIsNotNone(finders.find("images/sfondo.png"))
        self.assertIsNotNone(finders.find("images/card_intro_bgrnd.png"))

    def test_home_template_renders_intro_card_without_user_logout_actions(self):
        request = self.factory.get(reverse("home"))
        request.user = get_user_model()(username="tester", is_staff=False)
        request.resolver_match = resolve(reverse("home"))

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=False),
        ):
            html = render_to_string(
                "home.html",
                {
                    "admin_url": "/admin/",
                    "oidc_login_url": "/accounts/oidc/keycloak/login/",
                },
                request=request,
            )

        self.assertIn("Rapsodia Config", html)
        self.assertIn("Sessione attiva", html)
        self.assertIn("Autenticato", html)
        self.assertNotIn("Stato accesso", html)
        self.assertNotIn("Logout", html)
        self.assertNotIn("Admin Django", html)
        self.assertIn("Agenzie", html)
        self.assertIn("Area utente", html)
        self.assertNotIn("Aziende", html)
        self.assertNotIn("Configurazione", html)
        self.assertIn('class="col-12 col-xl-6"', html)

    def test_home_template_shows_admin_card_only_to_staff(self):
        request = self.factory.get(reverse("home"))
        request.user = get_user_model()(username="staffer", is_staff=True)
        request.resolver_match = resolve(reverse("home"))

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "home.html",
                {
                    "admin_url": "/admin/",
                    "oidc_login_url": "/accounts/oidc/keycloak/login/",
                },
                request=request,
            )

        self.assertIn("Amministrazione Django", html)
        self.assertIn("Admin Django", html)
        self.assertIn("Agenzie", html)
        self.assertIn("Aziende", html)
        self.assertIn("Configurazione", html)
        self.assertIn("Area utente", html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#agency"', html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#company"', html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#settings"', html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#user"', html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#rocket-takeoff"', html)
        self.assertNotIn("Logout", html)

    def test_home_template_hides_admin_card_for_anonymous_user(self):
        request = self.factory.get(reverse("home"))
        request.user = AnonymousUser()
        request.resolver_match = resolve(reverse("home"))

        html = render_to_string(
            "home.html",
            {
                "admin_url": "/admin/",
                "oidc_login_url": "/accounts/oidc/keycloak/login/",
            },
            request=request,
        )

        self.assertIn("Accedi con Keycloak", html)
        self.assertNotIn("Admin Django", html)
        self.assertNotIn("Stato accesso", html)
        self.assertNotIn("Apri sezione", html)

    def test_base_template_renders_navigation_icons(self):
        request = self._request(
            "exchange_agreement:agency-contracts",
            "agenzia-tpl-davide",
        )
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string("base.html", request=request)

        self.assertIn('href="/static/icons/rpsd-icons.svg#agency"', html)
        self.assertIn('aria-current="page"', html)
        self.assertNotIn("icons/rpsd-icons.svg#logout", html)

    def test_agencies_template_places_bootstrap_action_in_list_header(self):
        request = self._request("exchange_agreement:agencies")
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "exchange_agreement/agencies.html",
                {
                    "agency_rows": [],
                    "is_platform_admin": True,
                    "can_bootstrap_agency": True,
                },
                request=request,
            )

        list_header_index = html.index("Lista agenzie")
        action_index = html.index("Bootstrap Nuova Agenzia")
        self.assertLess(list_header_index, action_index)
        self.assertIn('href="/static/icons/rpsd-icons.svg#plus"', html)

    def test_user_area_template_uses_tabs_without_header_actions(self):
        request = self._request("exchange_agreement:user-area")
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "exchange_agreement/user_area.html",
                {
                    "active_tab": "inviti",
                    "agency_memberships": [],
                    "contract_memberships": [],
                    "can_create_contract_invites": True,
                    "identity_privileges": {
                        "auth_source": "LOCAL_DJANGO",
                        "provider": "",
                        "groups": [],
                        "realm_roles": [],
                        "derived_roles": [],
                        "is_staff": False,
                        "is_superuser": True,
                    },
                    "invitation_summary": {
                        "pending": 0,
                        "accepted": 0,
                        "rejected": 0,
                        "revoked": 0,
                    },
                },
                request=request,
            )

        header = html.split("</div>", 1)[0]
        self.assertIn("Utente", html)
        self.assertIn("Inviti", html)
        self.assertIn("Membership", html)
        self.assertNotIn("Vedi Inviti Ricevuti", header)
        self.assertNotIn("Crea Invito Contratto", html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#mail"', html)

    def test_user_area_template_places_logout_in_user_tab(self):
        request = self._request("exchange_agreement:user-area")
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "exchange_agreement/user_area.html",
                {
                    "active_tab": "utente",
                    "agency_memberships": [],
                    "contract_memberships": [],
                    "can_create_contract_invites": True,
                    "identity_privileges": {
                        "auth_source": "LOCAL_DJANGO",
                        "provider": "",
                        "groups": [],
                        "realm_roles": [],
                        "derived_roles": [],
                        "is_staff": False,
                        "is_superuser": True,
                    },
                    "invitation_summary": {
                        "pending": 0,
                        "accepted": 0,
                        "rejected": 0,
                        "revoked": 0,
                    },
                },
                request=request,
            )

        self.assertIn("Privilegi utente", html)
        self.assertIn('href="/accounts/logout/"', html)
        self.assertIn('href="/static/icons/rpsd-icons.svg#logout"', html)
        self.assertLess(html.index("Privilegi utente"), html.index("Logout"))

    def test_companies_template_has_dedicated_create_action_only(self):
        request = self._request("exchange_agreement:company-list")
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "exchange_agreement/companies.html",
                {
                    "companies": [],
                    "can_create_company": True,
                },
                request=request,
            )

        self.assertIn("Elenco aziende", html)
        self.assertIn(reverse("exchange_agreement:company-create"), html)
        self.assertNotIn("<form", html)

    def test_company_create_template_keeps_form_and_success_context(self):
        request = self._request("exchange_agreement:company-create")
        request.user = get_user_model()(username="tester", is_superuser=True)

        with patch(
            "rpsd_config.server.context_processors.resolve_user_agency_scope",
            return_value=_scope(platform_admin=True),
        ):
            html = render_to_string(
                "exchange_agreement/company_create.html",
                {
                    "error_message": "",
                    "success_message": "Azienda creata correttamente.",
                    "created_company": object(),
                    "form_values": {"name": "", "description": ""},
                },
                request=request,
            )

        self.assertIn("Azienda creata correttamente.", html)
        self.assertIn('name="name"', html)
        self.assertIn('value=""', html)
