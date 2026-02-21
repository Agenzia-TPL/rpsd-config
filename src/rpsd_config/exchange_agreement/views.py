from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import ContractInvitation, ContractMembership


@transaction.atomic
def accept_invitation_for_user(*, token: str, user) -> tuple[ContractInvitation, ContractMembership]:
    invitation = (
        ContractInvitation.objects.select_for_update()
        .select_related("contract")
        .get(token=token)
    )

    if invitation.status != ContractInvitation.Status.PENDING:
        raise ValueError("Invitation is not pending.")

    if invitation.expires_at <= timezone.now():
        invitation.status = ContractInvitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        raise ValueError("Invitation has expired.")

    if invitation.email:
        user_email = (user.email or "").lower()
        if user_email != invitation.email.lower():
            raise ValueError("Authenticated user email does not match invitation target.")

    membership, _ = ContractMembership.objects.get_or_create(
        contract=invitation.contract,
        user=user,
        defaults={
            "role": invitation.role_to_assign,
            "created_by": invitation.invited_by,
        },
    )

    if (
        membership.role != ContractMembership.Role.CONTRACT_ADMIN
        and invitation.role_to_assign == ContractMembership.Role.CONTRACT_ADMIN
    ):
        membership.role = ContractMembership.Role.CONTRACT_ADMIN
        membership.save(update_fields=["role", "updated_at"])

    invitation.status = ContractInvitation.Status.ACCEPTED
    invitation.accepted_by = user
    invitation.accepted_at = timezone.now()
    invitation.save(
        update_fields=["status", "accepted_by", "accepted_at", "updated_at"]
    )
    return invitation, membership


@login_required
def onboarding_callback(request: HttpRequest) -> HttpResponse:
    try:
        user_area_url = reverse("exchange_agreement:user-area")
    except NoReverseMatch:
        user_area_url = getattr(settings, "LOGIN_REDIRECT_URL", "/")

    token = request.session.get("onboarding_invitation_token")
    if not token:
        return render(
            request,
            "exchange_agreement/onboarding_result.html",
            {
                "success": False,
                "title": "Onboarding non avviato",
                "message": (
                    "Sessione onboarding non trovata. Apri di nuovo il link invito "
                    "e riprova."
                ),
                "invite_url": "",
                "home_url": user_area_url,
            },
            status=400,
        )

    try:
        invitation, membership = accept_invitation_for_user(token=token, user=request.user)
    except ContractInvitation.DoesNotExist:
        return render(
            request,
            "exchange_agreement/onboarding_result.html",
            {
                "success": False,
                "title": "Invito non trovato",
                "message": "Il token invito non esiste oppure non e' piu' disponibile.",
                "invite_url": "",
                "home_url": user_area_url,
            },
            status=400,
        )
    except ValueError as exc:
        invite_url = ""
        try:
            invite_url = reverse("invitation-landing-root", kwargs={"token": token})
        except NoReverseMatch:
            pass

        return render(
            request,
            "exchange_agreement/onboarding_result.html",
            {
                "success": False,
                "title": "Onboarding non completato",
                "message": str(exc),
                "invite_url": invite_url,
                "home_url": user_area_url,
            },
            status=400,
        )
    finally:
        request.session.pop("onboarding_invitation_token", None)

    return render(
        request,
        "exchange_agreement/onboarding_result.html",
        {
            "success": True,
            "title": "Onboarding completato",
            "message": (
                "Accesso attivato con successo. Il tuo account e' stato associato al "
                "contratto invitato."
            ),
            "contract_code": invitation.contract.contract_code,
            "role": membership.get_role_display(),
            "home_url": user_area_url,
            "invite_url": "",
        },
    )


@login_required
def user_area(request: HttpRequest) -> HttpResponse:
    memberships = (
        ContractMembership.objects.select_related("contract")
        .filter(user=request.user)
        .order_by("contract__contract_code")
    )
    return render(
        request,
        "exchange_agreement/user_area.html",
        {
            "memberships": memberships,
        },
    )


@login_required
def received_invitations(request: HttpRequest) -> HttpResponse:
    user_email = (request.user.email or "").strip().lower()
    base_query = Q(accepted_by=request.user)
    if user_email:
        base_query = base_query | Q(email__iexact=user_email)

    invitations = (
        ContractInvitation.objects.select_related("contract", "invited_by", "accepted_by")
        .filter(base_query)
        .order_by("-created_at")
    )
    return render(
        request,
        "exchange_agreement/received_invitations.html",
        {
            "invitations": invitations,
        },
    )


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


@require_http_methods(["GET", "POST"])
def invitation_landing(request: HttpRequest, token: str) -> HttpResponse:
    now = timezone.now()
    context = {
        "token": token,
        "state": "missing",
        "can_continue": False,
        "submission_error": "",
    }

    invitation = (
        ContractInvitation.objects.select_related("contract")
        .filter(token=token)
        .first()
    )
    if invitation is None:
        return render(request, "exchange_agreement/invitation_landing.html", context)

    if invitation.status == ContractInvitation.Status.PENDING and invitation.expires_at > now:
        state = "valid"
        can_continue = True
    elif invitation.status == ContractInvitation.Status.ACCEPTED:
        state = "accepted"
        can_continue = False
    elif invitation.status == ContractInvitation.Status.REVOKED:
        state = "revoked"
        can_continue = False
    else:
        state = "expired"
        can_continue = False

    context.update(
        {
            "invitation": invitation,
            "state": state,
            "can_continue": can_continue,
        }
    )

    if request.method == "POST":
        if not can_continue:
            context["submission_error"] = (
                "Questo invito non e' piu' utilizzabile."
            )
            return render(request, "exchange_agreement/invitation_landing.html", context)

        request.session["onboarding_invitation_token"] = str(invitation.token)
        callback_url = reverse("exchange_agreement:onboarding-callback")
        return redirect(_build_oidc_login_url(callback_url))

    return render(request, "exchange_agreement/invitation_landing.html", context)
