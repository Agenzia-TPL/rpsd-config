from allauth.account.internal.decorators import login_not_required
from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.oauth2.views import (
    OAuth2CallbackView,
    OAuth2LoginView,
)
from django.http import Http404

from rpsd_config.server.oidc_adapter import RpsdOpenIDConnectOAuth2Adapter


@login_not_required
def oidc_login(request, provider_id):
    try:
        view = OAuth2LoginView.adapter_view(
            RpsdOpenIDConnectOAuth2Adapter(request, provider_id)
        )
        return view(request)
    except SocialApp.DoesNotExist:
        raise Http404


@login_not_required
def oidc_callback(request, provider_id):
    try:
        view = OAuth2CallbackView.adapter_view(
            RpsdOpenIDConnectOAuth2Adapter(request, provider_id)
        )
        return view(request)
    except SocialApp.DoesNotExist:
        raise Http404
