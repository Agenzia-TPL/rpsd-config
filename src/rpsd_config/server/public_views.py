from urllib.parse import urlencode

from allauth.account.internal.decorators import login_not_required
from django.conf import settings
from django.shortcuts import render
from django.urls import reverse


def _oidc_provider_id() -> str:
    oidc_config = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {})
    apps = oidc_config.get("APPS") or []
    if not apps:
        return "keycloak"
    return apps[0].get("provider_id", "keycloak")


def _build_oidc_login_url(next_url: str) -> str:
    provider_id = _oidc_provider_id()
    query = urlencode({"process": "login", "next": next_url})
    return f"/accounts/oidc/{provider_id}/login/?{query}"


@login_not_required
def home(request):
    return render(
        request,
        "home.html",
        {
            "login_page_url": reverse("login-page"),
            "admin_url": "/admin/",
        },
    )


@login_not_required
def login_page(request):
    next_url = request.GET.get("next") or reverse("home")
    return render(
        request,
        "login.html",
        {
            "next_url": next_url,
            "oidc_login_url": _build_oidc_login_url(next_url),
            "home_url": reverse("home"),
        },
    )
