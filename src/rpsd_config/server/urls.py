# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""
URL configuration for rpsd_config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from rpsd_config.exchange_agreement.api import api
from rpsd_config.exchange_agreement.views import invitation_landing
from rpsd_config.server.oidc_views import oidc_callback, oidc_login
from rpsd_config.server.public_views import bootstrap_smoke, home, login_page

urlpatterns = [
    path(
        "favicon.ico",
        RedirectView.as_view(url=f"{settings.STATIC_URL}favicon.ico", permanent=False),
    ),
    path("", home, name="home"),
    path("login/", login_page, name="login-page"),
    path("ui/bootstrap-smoke/", bootstrap_smoke, name="bootstrap-smoke"),
    path("admin/", admin.site.urls),
    path("exchange_agreement/api/", api.urls),
    path(
        "accounts/oidc/<str:provider_id>/login/",
        oidc_login,
        name="openid_connect_login",
    ),
    path(
        "accounts/oidc/<str:provider_id>/login/callback/",
        oidc_callback,
        name="openid_connect_callback",
    ),
    path("accounts/", include("allauth.urls")),
    path("invite/<uuid:token>/", invitation_landing, name="invitation-landing-root"),
]

urlpatterns += [
    path("app1/", include("rpsd_config.app1.urls", namespace="app1")),
    path(
        "exchange_agreement/",
        include("rpsd_config.exchange_agreement.urls", namespace="exchange_agreement"),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
