from django.contrib import admin
from django.urls import path

from .views import (
    invitation_landing,
    onboarding_callback,
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
    path("me/contracts/", user_area, name="user-area"),
    path("me/invitations/", received_invitations, name="received-invitations"),
]
