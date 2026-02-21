from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from ninja import NinjaAPI, Schema

from .models import ContractInvitation


class InvitationCheckResponse(Schema):
    valid: bool
    status: str
    is_open_invitation: bool
    role_to_assign: str
    contract_code: str
    expires_at: str
    message: str


class InvitationStartResponse(Schema):
    ok: bool
    redirect_url: str
    provider_id: str
    message: str


api = NinjaAPI(title="RPSD Exchange Agreement API", version="1.0")


def _oidc_provider_id() -> str:
    oidc_config = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {})
    apps = oidc_config.get("APPS") or []
    if not apps:
        return "keycloak"
    return apps[0].get("provider_id", "keycloak")


def _build_oidc_login_url(callback_url: str) -> str:
    provider_id = _oidc_provider_id()
    query = urlencode({"process": "login", "next": callback_url})
    return f"/accounts/oidc/{provider_id}/login/?{query}"


@api.get("/invitations/{token}/check", response=InvitationCheckResponse)
def check_invitation(request, token: str):
    try:
        invitation = ContractInvitation.objects.select_related("contract").get(token=token)
    except ContractInvitation.DoesNotExist:
        return InvitationCheckResponse(
            valid=False,
            status="missing",
            is_open_invitation=False,
            role_to_assign="",
            contract_code="",
            expires_at="",
            message="Invitation token not found.",
        )

    now = timezone.now()
    valid = invitation.status == ContractInvitation.Status.PENDING and invitation.expires_at > now
    return InvitationCheckResponse(
        valid=valid,
        status=invitation.status,
        is_open_invitation=not bool(invitation.email),
        role_to_assign=invitation.role_to_assign,
        contract_code=invitation.contract.contract_code,
        expires_at=invitation.expires_at.isoformat(),
        message="Invitation is valid." if valid else "Invitation is not valid anymore.",
    )


@api.post("/invitations/{token}/start", response=InvitationStartResponse)
def start_onboarding(request, token: str):
    try:
        invitation = ContractInvitation.objects.get(token=token)
    except ContractInvitation.DoesNotExist:
        return InvitationStartResponse(
            ok=False,
            redirect_url="",
            provider_id="",
            message="Invitation token not found.",
        )

    if not invitation.is_valid():
        return InvitationStartResponse(
            ok=False,
            redirect_url="",
            provider_id="",
            message="Invitation is not valid anymore.",
        )

    request.session["onboarding_invitation_token"] = token
    callback_url = reverse("exchange_agreement:onboarding-callback")
    redirect_url = _build_oidc_login_url(callback_url)
    return InvitationStartResponse(
        ok=True,
        redirect_url=redirect_url,
        provider_id=_oidc_provider_id(),
        message="Invitation accepted for onboarding. Continue with OIDC login.",
    )
