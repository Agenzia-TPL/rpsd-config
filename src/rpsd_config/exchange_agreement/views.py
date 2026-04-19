# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import base64
import json
from datetime import date
from urllib.parse import urlencode

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from rpsd_config.server.keycloak_admin import (
    KeycloakAdminAPIError,
    KeycloakAdminConfigError,
    KeycloakAdminService,
)

from .models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    Company,
    Contract,
    ContractInvitation,
    ContractMembership,
    Lot,
)
from .rbac import resolve_user_agency_scope
from .services.agency_invitations import (
    AgencyInvitationPermissionError,
    AgencyInvitationProvisioningError,
    AgencyInvitationValidationError,
    accept_agency_invitation_for_user,
    create_agency_invitation,
)
from .services.invitation_rejections import (
    InvitationRejectValidationError,
    reject_agency_invitation_for_user,
    reject_contract_invitation_for_user,
)
from .services.agency_bootstrap import (
    AgencyBootstrapPermissionError,
    AgencyBootstrapProvisioningError,
    AgencyBootstrapValidationError,
    bootstrap_agency_with_admin_invitation,
)


def _cache_group_membership_for_current_session(*, user, group_path: str) -> None:
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )
    if social is None or not isinstance(group_path, str) or not group_path:
        return

    extra_data = social.extra_data if isinstance(social.extra_data, dict) else {}
    changed = False

    cached_groups = extra_data.get("groups")
    if isinstance(cached_groups, list):
        groups = [group for group in cached_groups if isinstance(group, str)]
    else:
        groups = []
    if group_path not in groups:
        groups.append(group_path)
        extra_data["groups"] = groups
        changed = True

    id_token = extra_data.get("id_token")
    if isinstance(id_token, dict):
        token_groups = id_token.get("groups")
        if isinstance(token_groups, list):
            token_groups_list = [group for group in token_groups if isinstance(group, str)]
        else:
            token_groups_list = []
        if group_path not in token_groups_list:
            token_groups_list.append(group_path)
            id_token["groups"] = token_groups_list
            extra_data["id_token"] = id_token
            changed = True

    if changed:
        social.extra_data = extra_data
        social.save(update_fields=["extra_data"])


def _prepare_invitation_credentials(*, invitation, email: str, password: str) -> str:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValueError("Email obbligatoria.")
    if invitation.email and normalized_email != invitation.email.lower():
        raise ValueError("Email non coerente con l'invito.")
    if len(password or "") < 8:
        raise ValueError("La password deve contenere almeno 8 caratteri.")

    keycloak = KeycloakAdminService.from_settings()
    keycloak_user = keycloak.ensure_user(
        username=normalized_email,
        email=normalized_email,
    )
    keycloak.set_user_password(user_id=keycloak_user.id, password=password)
    return keycloak_user.username


@transaction.atomic
def accept_invitation_for_user(
    *, token: str, user
) -> tuple[ContractInvitation, ContractMembership]:
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
            raise ValueError(
                "Authenticated user email does not match invitation target."
            )

    membership, _ = ContractMembership.objects.get_or_create(
        contract=invitation.contract,
        user=user,
        defaults={
            "role": invitation.role_to_assign,
            "created_by": invitation.invited_by,
        },
    )

    if ContractMembership.role_rank(
        invitation.role_to_assign
    ) > ContractMembership.role_rank(membership.role):
        membership.role = invitation.role_to_assign
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
    invitation_kind = request.session.get("onboarding_invitation_kind")
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
                "show_sidebar": False,
            },
            status=400,
        )

    try:
        scope, result = _accept_onboarding_token(
            token=token,
            user=request.user,
            invitation_kind=invitation_kind,
        )
    except (ContractInvitation.DoesNotExist, AgencyInvitation.DoesNotExist):
        return render(
            request,
            "exchange_agreement/onboarding_result.html",
            {
                "success": False,
                "title": "Invito non trovato",
                "message": "Il token invito non esiste oppure non e' piu' disponibile.",
                "invite_url": "",
                "home_url": user_area_url,
                "show_sidebar": False,
            },
            status=400,
        )
    except (
        ValueError,
        AgencyInvitationValidationError,
        AgencyInvitationProvisioningError,
    ) as exc:
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
                "show_sidebar": False,
            },
            status=400,
        )
    finally:
        request.session.pop("onboarding_invitation_token", None)
        request.session.pop("onboarding_invitation_kind", None)

    if scope == "agency":
        invitation = result.invitation
        membership = result.membership
        _cache_group_membership_for_current_session(
            user=request.user,
            group_path=result.assigned_group_path,
        )
        return render(
            request,
            "exchange_agreement/onboarding_result.html",
            {
                "success": True,
                "title": "Onboarding completato",
                "message": (
                    "Accesso attivato con successo. Il tuo account e' stato associato "
                    "all'agenzia invitata."
                ),
                "entity_label": "Agenzia",
                "entity_code": invitation.agency.agency_key,
                "role": membership.get_role_display(),
                "group_path": result.assigned_group_path,
                "home_url": user_area_url,
                "invite_url": "",
                "show_sidebar": False,
            },
        )

    invitation = result[0]
    membership = result[1]
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
            "entity_label": "Contratto",
            "entity_code": invitation.contract.contract_code,
            "role": membership.get_role_display(),
            "home_url": user_area_url,
            "invite_url": "",
            "show_sidebar": False,
        },
    )


def _accept_onboarding_token(*, token: str, user, invitation_kind: str | None):
    if invitation_kind == "agency":
        result = accept_agency_invitation_for_user(token=token, user=user)
        return "agency", result

    if invitation_kind == "contract":
        result = accept_invitation_for_user(token=token, user=user)
        return "contract", result

    try:
        result = accept_invitation_for_user(token=token, user=user)
        return "contract", result
    except ContractInvitation.DoesNotExist:
        result = accept_agency_invitation_for_user(token=token, user=user)
        return "agency", result


def _reject_onboarding_token(*, token: str, user, invitation_kind: str | None):
    if invitation_kind == "agency":
        result = reject_agency_invitation_for_user(token=token, user=user)
        return "agency", result

    if invitation_kind == "contract":
        result = reject_contract_invitation_for_user(token=token, user=user)
        return "contract", result

    try:
        result = reject_contract_invitation_for_user(token=token, user=user)
        return "contract", result
    except ContractInvitation.DoesNotExist:
        result = reject_agency_invitation_for_user(token=token, user=user)
        return "agency", result


def _decode_jwt_payload_without_verification(token: str) -> dict:
    """Decode JWT payload for UI display only (no signature verification)."""
    if not token or "." not in token:
        return {}
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
        claims = json.loads(decoded)
    except (ValueError, UnicodeDecodeError):
        return {}
    return claims if isinstance(claims, dict) else {}


def _build_identity_privileges(user) -> dict:
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )

    claims: dict = {}
    groups: list[str] = []
    realm_roles: list[str] = []

    if social:
        extra_data = social.extra_data or {}
        if isinstance(extra_data.get("groups"), list):
            groups = extra_data.get("groups", [])
        realm_access = extra_data.get("realm_access")
        if isinstance(realm_access, dict) and isinstance(
            realm_access.get("roles"), list
        ):
            realm_roles = realm_access["roles"]

        # Fallback: claims may be nested in id_token either as a decoded dict
        # (provider-specific storage) or as a raw JWT string.
        if not groups or not realm_roles:
            id_token = extra_data.get("id_token")
            if isinstance(id_token, dict):
                claims = id_token
            elif isinstance(id_token, str):
                claims = _decode_jwt_payload_without_verification(id_token)
            else:
                claims = {}

            if not groups and isinstance(claims.get("groups"), list):
                groups = claims.get("groups", [])
            if not realm_roles:
                realm_access = claims.get("realm_access")
                if isinstance(realm_access, dict) and isinstance(
                    realm_access.get("roles"), list
                ):
                    realm_roles = realm_access["roles"]

    # Derive app-level role labels from group path convention, e.g. "/rpsd/admin".
    derived_roles = sorted(
        {
            g.rsplit("/", 1)[-1]
            for g in groups
            if isinstance(g, str) and g.startswith("/rpsd/") and "/" in g
        }
    )

    return {
        "auth_source": "OIDC" if social else "LOCAL_DJANGO",
        "provider": social.provider if social else "",
        "provider_uid": social.uid if social else "",
        "groups": [g for g in groups if isinstance(g, str)],
        "realm_roles": [r for r in realm_roles if isinstance(r, str)],
        "derived_roles": derived_roles,
        "is_staff": bool(user.is_staff),
        "is_superuser": bool(user.is_superuser),
    }


@login_required
def user_area(request: HttpRequest) -> HttpResponse:
    contract_memberships = (
        ContractMembership.objects.select_related("contract")
        .filter(user=request.user)
        .order_by("contract__contract_code")
    )
    agency_memberships = (
        AgencyMembership.objects.select_related("agency")
        .filter(user=request.user)
        .order_by("agency__name")
    )
    agency_scope = resolve_user_agency_scope(request.user)
    identity_privileges = _build_identity_privileges(request.user)
    user_email = (request.user.email or "").strip().lower()
    invitation_filter = Q(accepted_by=request.user)
    if user_email:
        invitation_filter = invitation_filter | Q(email__iexact=user_email)

    pending_invitations = ContractInvitation.objects.filter(
        invitation_filter,
        status=ContractInvitation.Status.PENDING,
    ).count() + AgencyInvitation.objects.filter(
        invitation_filter,
        status=AgencyInvitation.Status.PENDING,
    ).count()
    accepted_invitations = ContractInvitation.objects.filter(
        invitation_filter,
        status=ContractInvitation.Status.ACCEPTED,
    ).count() + AgencyInvitation.objects.filter(
        invitation_filter,
        status=AgencyInvitation.Status.ACCEPTED,
    ).count()
    rejected_invitations = ContractInvitation.objects.filter(
        invitation_filter,
        status=ContractInvitation.Status.REJECTED,
    ).count() + AgencyInvitation.objects.filter(
        invitation_filter,
        status=AgencyInvitation.Status.REJECTED,
    ).count()
    revoked_invitations = ContractInvitation.objects.filter(
        invitation_filter,
        status=ContractInvitation.Status.REVOKED,
    ).count() + AgencyInvitation.objects.filter(
        invitation_filter,
        status=AgencyInvitation.Status.REVOKED,
    ).count()

    return render(
        request,
        "exchange_agreement/user_area.html",
        {
            "contract_memberships": contract_memberships,
            "agency_memberships": agency_memberships,
            "can_create_agency_invites": agency_scope.is_platform_admin
            or bool(agency_scope.admin_agency_keys),
            "can_create_contract_invites": request.user.is_superuser
            or agency_scope.is_platform_admin
            or bool(agency_scope.admin_agency_keys)
            or bool(agency_scope.editor_agency_keys),
            "identity_privileges": identity_privileges,
            "invitation_summary": {
                "pending": pending_invitations,
                "accepted": accepted_invitations,
                "rejected": rejected_invitations,
                "revoked": revoked_invitations,
            },
        },
    )


@login_required
def received_invitations(request: HttpRequest) -> HttpResponse:
    user_email = (request.user.email or "").strip().lower()
    base_query = Q(accepted_by=request.user)
    if user_email:
        base_query = base_query | Q(email__iexact=user_email)

    contract_invitations = (
        ContractInvitation.objects.select_related(
            "contract", "invited_by", "accepted_by"
        )
        .filter(base_query)
        .order_by("-created_at")
    )
    agency_invitations = (
        AgencyInvitation.objects.select_related("agency", "invited_by", "accepted_by")
        .filter(base_query)
        .order_by("-created_at")
    )
    return render(
        request,
        "exchange_agreement/received_invitations.html",
        {
            "contract_invitations": contract_invitations,
            "agency_invitations": agency_invitations,
        },
    )


@login_required
def agencies_page(request: HttpRequest) -> HttpResponse:
    agency_scope = resolve_user_agency_scope(request.user)
    membership_by_agency_id = {
        membership.agency_id: membership
        for membership in AgencyMembership.objects.select_related("agency")
        .filter(user=request.user)
        .order_by("agency__name")
    }

    if agency_scope.is_platform_admin:
        agencies = list(Agency.objects.all().order_by("name"))
    else:
        scope_keys = (
            set(agency_scope.admin_agency_keys)
            | set(agency_scope.editor_agency_keys)
            | set(agency_scope.reader_agency_keys)
        )
        membership_keys = {
            membership.agency.agency_key for membership in membership_by_agency_id.values()
        }
        visible_keys = scope_keys | membership_keys
        agencies = list(Agency.objects.filter(agency_key__in=visible_keys).order_by("name"))

    agency_rows = []
    for agency in agencies:
        membership = membership_by_agency_id.get(agency.id)
        if agency_scope.is_platform_admin:
            role_label = "Platform admin"
        elif agency.agency_key in agency_scope.admin_agency_keys:
            role_label = AgencyMembership.Role.AGENCY_ADMIN.label
        elif agency.agency_key in agency_scope.editor_agency_keys:
            role_label = AgencyMembership.Role.AGENCY_EDITOR.label
        elif agency.agency_key in agency_scope.reader_agency_keys:
            role_label = AgencyMembership.Role.AGENCY_READER.label
        elif membership is not None:
            role_label = membership.get_role_display()
        else:
            role_label = "Membro"

        agency_rows.append(
            {
                "agency": agency,
                "membership": membership,
                "role_label": role_label,
            }
        )

    return render(
        request,
        "exchange_agreement/agencies.html",
        {
            "agency_rows": agency_rows,
            "is_platform_admin": agency_scope.is_platform_admin,
            "can_bootstrap_agency": request.user.is_superuser
            or agency_scope.is_platform_admin,
        },
    )


def _can_view_agency(*, user, agency: Agency, agency_scope) -> bool:
    if user.is_superuser or agency_scope.is_platform_admin:
        return True

    if agency.agency_key in (
        set(agency_scope.admin_agency_keys)
        | set(agency_scope.editor_agency_keys)
        | set(agency_scope.reader_agency_keys)
    ):
        return True

    return AgencyMembership.objects.filter(user=user, agency=agency).exists()


def _can_create_contract_for_agency(*, user, agency: Agency, agency_scope) -> bool:
    if user.is_superuser or agency_scope.is_platform_admin:
        return True
    return agency.agency_key in agency_scope.admin_agency_keys


def _can_create_contract_invitation_for_agency(*, user, agency: Agency, agency_scope) -> bool:
    if user.is_superuser or agency_scope.is_platform_admin:
        return True
    return agency.agency_key in (
        set(agency_scope.admin_agency_keys) | set(agency_scope.editor_agency_keys)
    )


def _agency_invitation_summary(agency: Agency) -> dict[str, int]:
    return {
        "pending": AgencyInvitation.objects.filter(
            agency=agency, status=AgencyInvitation.Status.PENDING
        ).count(),
        "accepted": AgencyInvitation.objects.filter(
            agency=agency, status=AgencyInvitation.Status.ACCEPTED
        ).count(),
        "rejected": AgencyInvitation.objects.filter(
            agency=agency, status=AgencyInvitation.Status.REJECTED
        ).count(),
        "revoked": AgencyInvitation.objects.filter(
            agency=agency, status=AgencyInvitation.Status.REVOKED
        ).count(),
        "expired": AgencyInvitation.objects.filter(
            agency=agency, status=AgencyInvitation.Status.EXPIRED
        ).count(),
    }


def _agency_contracts_qs(agency: Agency):
    return Contract.objects.select_related("lot", "contractor_company", "flow_profile").filter(
        client_agency=agency
    ).order_by("-start_date", "contract_code")


@login_required
def agency_detail_page(request: HttpRequest, agency_key: str) -> HttpResponse:
    agency = get_object_or_404(Agency, agency_key=agency_key)
    agency_scope = resolve_user_agency_scope(request.user)
    if not _can_view_agency(user=request.user, agency=agency, agency_scope=agency_scope):
        raise PermissionDenied("Non hai accesso a questa agenzia.")

    membership = AgencyMembership.objects.filter(user=request.user, agency=agency).first()
    invitation_summary = _agency_invitation_summary(agency)
    latest_invitations = list(
        AgencyInvitation.objects.select_related("invited_by", "accepted_by", "rejected_by")
        .filter(agency=agency)
        .order_by("-created_at")[:10]
    )
    contracts = list(_agency_contracts_qs(agency))

    return render(
        request,
        "exchange_agreement/agency_detail.html",
        {
            "agency": agency,
            "membership": membership,
            "is_platform_admin": agency_scope.is_platform_admin,
            "invitation_summary": invitation_summary,
            "latest_invitations": latest_invitations,
            "contracts": contracts,
            "can_create_agency_invites": request.user.is_superuser
            or agency_scope.is_platform_admin
            or agency.agency_key in agency_scope.admin_agency_keys,
            "can_create_contract": _can_create_contract_for_agency(
                user=request.user,
                agency=agency,
                agency_scope=agency_scope,
            ),
        },
    )


@login_required
def agency_contracts_page(request: HttpRequest, agency_key: str) -> HttpResponse:
    agency = get_object_or_404(Agency, agency_key=agency_key)
    agency_scope = resolve_user_agency_scope(request.user)
    if not _can_view_agency(user=request.user, agency=agency, agency_scope=agency_scope):
        raise PermissionDenied("Non hai accesso a questa agenzia.")

    contracts = list(_agency_contracts_qs(agency))
    return render(
        request,
        "exchange_agreement/agency_contracts.html",
        {
            "agency": agency,
            "contracts": contracts,
            "can_create_contract": _can_create_contract_for_agency(
                user=request.user,
                agency=agency,
                agency_scope=agency_scope,
            ),
        },
    )


@login_required
def agency_contract_detail_page(
    request: HttpRequest,
    agency_key: str,
    contract_code: str,
) -> HttpResponse:
    agency = get_object_or_404(Agency, agency_key=agency_key)
    agency_scope = resolve_user_agency_scope(request.user)
    if not _can_view_agency(user=request.user, agency=agency, agency_scope=agency_scope):
        raise PermissionDenied("Non hai accesso a questa agenzia.")

    contract = get_object_or_404(
        Contract.objects.select_related(
            "lot",
            "client_agency",
            "contractor_company",
            "flow_profile",
            "replaced_by",
        ),
        contract_code=contract_code,
        client_agency=agency,
    )

    return render(
        request,
        "exchange_agreement/agency_contract_detail.html",
        {
            "agency": agency,
            "contract": contract,
            "can_create_contract_invites": _can_create_contract_invitation_for_agency(
                user=request.user,
                agency=agency,
                agency_scope=agency_scope,
            ),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def create_agency_contract_page(request: HttpRequest, agency_key: str) -> HttpResponse:
    agency = get_object_or_404(Agency, agency_key=agency_key)
    agency_scope = resolve_user_agency_scope(request.user)
    if not _can_create_contract_for_agency(
        user=request.user,
        agency=agency,
        agency_scope=agency_scope,
    ):
        raise PermissionDenied("Solo platform admin o agency admin possono creare contratti.")

    companies = list(Company.objects.all().order_by("name"))
    lots = list(Lot.objects.all().order_by("id"))
    status_choices = [
        (status_value, status_label)
        for status_value, status_label in Contract.ContractStatus.choices
        if status_value != Contract.ContractStatus.CLOSED
    ]
    result_context = {
        "error_message": "",
        "success_message": "",
        "created_contract": None,
        "form_values": {
            "contract_code": "",
            "contractor_company_id": "",
            "lot_id": "",
            "start_date": "",
            "end_date": "",
            "tender_id": "",
            "status": Contract.ContractStatus.DRAFT,
        },
    }

    if request.method == "POST":
        form_values = {
            "contract_code": request.POST.get("contract_code", "").strip(),
            "contractor_company_id": request.POST.get("contractor_company_id", "").strip(),
            "lot_id": request.POST.get("lot_id", "").strip(),
            "start_date": request.POST.get("start_date", "").strip(),
            "end_date": request.POST.get("end_date", "").strip(),
            "tender_id": request.POST.get("tender_id", "").strip(),
            "status": request.POST.get("status", "").strip() or Contract.ContractStatus.DRAFT,
        }
        result_context["form_values"] = form_values

        if not form_values["contract_code"]:
            result_context["error_message"] = "Il codice contratto e' obbligatorio."
        else:
            company = Company.objects.filter(id=form_values["contractor_company_id"]).first()
            lot = Lot.objects.filter(id=form_values["lot_id"]).first()

            if company is None:
                result_context["error_message"] = "Seleziona una azienda valida."
            elif lot is None:
                result_context["error_message"] = "Seleziona un lotto valido."
            elif form_values["status"] not in {choice[0] for choice in status_choices}:
                result_context["error_message"] = "Stato contratto non supportato."
            else:
                try:
                    start_date_value = date.fromisoformat(form_values["start_date"])
                except ValueError:
                    result_context["error_message"] = "La data inizio non e' valida."
                else:
                    end_date_value = None
                    if form_values["end_date"]:
                        try:
                            end_date_value = date.fromisoformat(form_values["end_date"])
                        except ValueError:
                            result_context["error_message"] = "La data fine non e' valida."

                    if not result_context["error_message"]:
                        try:
                            contract = Contract.objects.create(
                                contract_code=form_values["contract_code"],
                                client_agency=agency,
                                contractor_company=company,
                                lot=lot,
                                start_date=start_date_value,
                                end_date=end_date_value,
                                tender_id=form_values["tender_id"],
                                status=form_values["status"],
                            )
                            result_context["success_message"] = (
                                "Contratto creato correttamente."
                            )
                            result_context["created_contract"] = contract
                        except ValidationError as exc:
                            result_context["error_message"] = (
                                f"Validazione contratto fallita: {exc}"
                            )
                        except IntegrityError:
                            result_context["error_message"] = (
                                "Impossibile creare contratto: vincolo dati non rispettato."
                            )

    return render(
        request,
        "exchange_agreement/agency_contract_create.html",
        {
            "agency": agency,
            "companies": companies,
            "lots": lots,
            "status_choices": status_choices,
            **result_context,
        },
    )


@login_required
def platform_configuration_page(request: HttpRequest) -> HttpResponse:
    agency_scope = resolve_user_agency_scope(request.user)
    if not agency_scope.is_platform_admin:
        raise PermissionDenied("Solo gli utenti del gruppo /rpsd/admin possono accedere.")

    return render(
        request,
        "exchange_agreement/platform_configuration.html",
        {
            "global_sections": [
                "Parametri IAM/OIDC globali",
                "Politiche inviti e scadenze",
                "Parametri piattaforma trasversali ai componenti",
            ]
        },
    )


def _contracts_available_for_contract_invites(user):
    contracts = Contract.objects.select_related("client_agency").order_by(
        "contract_code"
    )
    if user.is_superuser:
        return contracts

    agency_scope = resolve_user_agency_scope(user)
    if agency_scope.is_platform_admin:
        return contracts

    allowed_agency_keys = set(agency_scope.admin_agency_keys) | set(
        agency_scope.editor_agency_keys
    )
    if not allowed_agency_keys:
        return Contract.objects.none()
    return contracts.filter(client_agency__agency_key__in=allowed_agency_keys)


@login_required
@require_http_methods(["GET", "POST"])
def create_contract_invitation_page(request: HttpRequest) -> HttpResponse:
    contracts_qs = _contracts_available_for_contract_invites(request.user)
    contracts = list(contracts_qs)
    selected_contract_code = (
        request.POST.get("contract_code", "").strip()
        or request.GET.get("contract_code", "").strip()
    )
    selected_contract = (
        contracts_qs.filter(contract_code=selected_contract_code).first()
        if selected_contract_code
        else None
    )
    role_choices = [
        (ContractMembership.Role.CONTRACT_EDITOR, "Contract editor"),
        (ContractMembership.Role.CONTRACT_READER, "Contract reader"),
    ]
    result_context = {
        "error_message": "",
        "success_message": "",
        "created_invitation": None,
    }

    if request.method == "POST":
        contract_code = (
            selected_contract.contract_code
            if selected_contract is not None
            else request.POST.get("contract_code", "").strip()
        )
        role_to_assign = request.POST.get("role_to_assign", "").strip()
        email = request.POST.get("email", "").strip().lower() or None
        contract = (
            selected_contract
            if selected_contract is not None
            else contracts_qs.filter(contract_code=contract_code).first()
        )
        if contract is None:
            result_context["error_message"] = (
                "Contratto non disponibile nel tuo perimetro autorizzativo."
            )
        elif role_to_assign not in {
            ContractMembership.Role.CONTRACT_EDITOR,
            ContractMembership.Role.CONTRACT_READER,
        }:
            result_context["error_message"] = (
                "I ruoli consentiti sono solo contract_editor e contract_reader."
            )
        else:
            try:
                invitation = ContractInvitation.objects.create(
                    contract=contract,
                    email=email,
                    role_to_assign=role_to_assign,
                    invited_by=request.user,
                    status=ContractInvitation.Status.PENDING,
                )
                invite_url = request.build_absolute_uri(
                    reverse(
                        "invitation-landing-root",
                        kwargs={"token": invitation.token},
                    )
                )
                result_context["success_message"] = (
                    "Invito contratto creato correttamente."
                )
                result_context["created_invitation"] = {
                    "token": invitation.token,
                    "invite_url": invite_url,
                    "contract_code": invitation.contract.contract_code,
                    "role": invitation.get_role_to_assign_display(),
                    "email": invitation.email,
                    "expires_at": invitation.expires_at,
                }
            except (ValidationError, IntegrityError) as exc:
                result_context["error_message"] = (
                    f"Impossibile creare invito contratto: {exc}"
                )

    return render(
        request,
        "exchange_agreement/contract_invitation_create.html",
        {
            "contracts": contracts,
            "selected_contract": selected_contract,
            "role_choices": role_choices,
            **result_context,
        },
    )


def _agencies_available_for_agency_invites(user):
    agency_scope = resolve_user_agency_scope(user)
    if user.is_superuser or agency_scope.is_platform_admin:
        return Agency.objects.all().order_by("name")
    return Agency.objects.filter(agency_key__in=agency_scope.admin_agency_keys).order_by(
        "name"
    )


@login_required
@require_http_methods(["GET", "POST"])
def create_agency_invitation_page(request: HttpRequest) -> HttpResponse:
    agencies_qs = _agencies_available_for_agency_invites(request.user)
    agencies = list(agencies_qs)
    selected_agency_key = (
        request.POST.get("selected_agency_key", "").strip()
        or request.GET.get("agency_key", "").strip()
    )
    selected_agency = (
        agencies_qs.filter(agency_key=selected_agency_key).first()
        if selected_agency_key
        else None
    )

    role_choices = list(AgencyMembership.Role.choices)
    result_context = {
        "error_message": "",
        "success_message": "",
        "created_invitation": None,
    }
    if selected_agency_key and selected_agency is None:
        result_context["error_message"] = (
            "Agenzia richiesta non disponibile nel tuo perimetro autorizzativo."
        )

    if request.method == "POST":
        agency_id = request.POST.get("agency_id", "").strip()
        role_to_assign = request.POST.get("role_to_assign", "").strip()
        email = request.POST.get("email", "").strip()
        agency = None
        if selected_agency is not None:
            agency = selected_agency
            if agency_id and str(agency.id) != agency_id:
                result_context["error_message"] = (
                    "Agenzia selezionata non coerente con la richiesta."
                )
        elif agency_id:
            agency = agencies_qs.filter(pk=agency_id).first()
            if agency is None:
                result_context["error_message"] = (
                    "Agenzia non disponibile nel tuo perimetro autorizzativo."
                )
        else:
            result_context["error_message"] = "Seleziona una agenzia valida."

        if agency is None and not result_context["error_message"]:
            result_context["error_message"] = "Agenzia non disponibile."

        if result_context["error_message"]:
            return render(
                request,
                "exchange_agreement/agency_invitation_create.html",
                {
                    "agencies": agencies,
                    "selected_agency": selected_agency,
                    "selected_agency_key": selected_agency_key,
                    "role_choices": role_choices,
                    **result_context,
                },
            )
        try:
            created = create_agency_invitation(
                actor=request.user,
                agency=agency,
                role_to_assign=role_to_assign,
                email=email,
                provision_user_if_missing=True,
            )
            invite_url = request.build_absolute_uri(
                reverse(
                    "invitation-landing-root",
                    kwargs={"token": created.invitation.token},
                )
            )
            result_context["success_message"] = (
                "Invito agenzia creato correttamente e provisioning IAM completato."
            )
            result_context["created_invitation"] = {
                "token": created.invitation.token,
                "invite_url": invite_url,
                "agency_name": created.invitation.agency.name,
                "agency_key": created.invitation.agency.agency_key,
                "role": created.invitation.get_role_to_assign_display(),
                "email": created.invitation.email,
                "group_path": created.assigned_group_path,
                "expires_at": created.invitation.expires_at,
                "provisioned_user_id": created.provisioned_user_id,
            }
        except AgencyInvitationPermissionError as exc:
            result_context["error_message"] = str(exc)
        except (
            AgencyInvitationValidationError,
            AgencyInvitationProvisioningError,
        ) as exc:
            result_context["error_message"] = str(exc)

    return render(
        request,
        "exchange_agreement/agency_invitation_create.html",
        {
            "agencies": agencies,
            "selected_agency": selected_agency,
            "selected_agency_key": selected_agency_key,
            "role_choices": role_choices,
            **result_context,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def bootstrap_agency_page(request: HttpRequest) -> HttpResponse:
    agency_scope = resolve_user_agency_scope(request.user)
    if not (request.user.is_superuser or agency_scope.is_platform_admin):
        raise PermissionDenied("Platform admin scope required.")

    result_context = {
        "error_message": "",
        "success_message": "",
        "created_bootstrap": None,
    }

    if request.method == "POST":
        agency_name = request.POST.get("agency_name", "").strip()
        agency_key = request.POST.get("agency_key", "").strip() or None
        initial_admin_email = request.POST.get("initial_admin_email", "").strip()

        try:
            created = bootstrap_agency_with_admin_invitation(
                actor=request.user,
                agency_name=agency_name,
                agency_key=agency_key,
                initial_admin_email=initial_admin_email,
                provision_user_if_missing=True,
            )
            invite_url = request.build_absolute_uri(
                reverse(
                    "invitation-landing-root",
                    kwargs={"token": created.invitation.token},
                )
            )
            result_context["success_message"] = (
                "Bootstrap agenzia completato con successo."
            )
            result_context["created_bootstrap"] = {
                "agency_id": created.agency.id,
                "agency_name": created.agency.name,
                "agency_key": created.agency.agency_key,
                "invitation_token": created.invitation.token,
                "invitation_url": invite_url,
                "invitation_email": created.invitation.email,
                "invitation_expires_at": created.invitation.expires_at,
                "assigned_group_path": created.assigned_group_path,
                "provisioned_user_id": created.provisioned_user_id,
            }
        except AgencyBootstrapPermissionError as exc:
            result_context["error_message"] = str(exc)
        except (
            AgencyBootstrapValidationError,
            AgencyBootstrapProvisioningError,
        ) as exc:
            result_context["error_message"] = str(exc)

    return render(
        request,
        "exchange_agreement/agency_bootstrap.html",
        result_context,
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
        "can_reject": False,
        "invitation_type": "",
        "submission_error": "",
        "success_message": "",
        "prepared_username": "",
        "credential_setup_required": False,
        "show_sidebar": False,
    }

    contract_invitation = (
        ContractInvitation.objects.select_related("contract")
        .filter(token=token)
        .first()
    )
    agency_invitation = (
        AgencyInvitation.objects.select_related("agency")
        .filter(token=token)
        .first()
    )

    invitation = contract_invitation or agency_invitation
    if invitation is None:
        return render(request, "exchange_agreement/invitation_landing.html", context)

    invitation_type = "contract" if contract_invitation else "agency"

    if (
        invitation.status == invitation.Status.PENDING
        and invitation.expires_at > now
    ):
        state = "valid"
        can_continue = True
    elif invitation.status == invitation.Status.ACCEPTED:
        state = "accepted"
        can_continue = False
    elif invitation.status == invitation.Status.REJECTED:
        state = "rejected"
        can_continue = False
    elif invitation.status == invitation.Status.REVOKED:
        state = "revoked"
        can_continue = False
    else:
        state = "expired"
        can_continue = False

    context.update(
        {
            "invitation": invitation,
            "invitation_type": invitation_type,
            "state": state,
            "can_continue": can_continue,
            "can_reject": bool(
                can_continue
                and invitation.email
                and request.user.is_authenticated
                and (request.user.email or "").strip().lower()
                == invitation.email.lower()
            ),
            "continue_button_label": (
                "Accetta invito"
                if request.user.is_authenticated
                else "Accedi e accetta invito"
            ),
            "credential_setup_required": bool(
                can_continue
                and invitation.email
                and not request.user.is_authenticated
            ),
        }
    )

    if request.method == "POST":
        action = (request.POST.get("action") or "continue-login").strip()
        if not can_continue:
            context["submission_error"] = "Questo invito non e' piu' utilizzabile."
            return render(
                request, "exchange_agreement/invitation_landing.html", context
            )

        if action == "prepare-credentials":
            email = request.POST.get("email", "")
            password_1 = request.POST.get("password1", "")
            password_2 = request.POST.get("password2", "")
            if password_1 != password_2:
                context["submission_error"] = "Le password inserite non coincidono."
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )
            try:
                username = _prepare_invitation_credentials(
                    invitation=invitation,
                    email=email,
                    password=password_1,
                )
            except (ValueError, KeycloakAdminConfigError) as exc:
                context["submission_error"] = str(exc)
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )
            except KeycloakAdminAPIError as exc:
                context["submission_error"] = (
                    "Errore durante la preparazione credenziali IAM: "
                    f"{exc.detail or exc}"
                )
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )

            context["success_message"] = (
                "Credenziali iniziali impostate correttamente. "
                "Procedi con la login."
            )
            context["prepared_username"] = username
            return render(request, "exchange_agreement/invitation_landing.html", context)

        if action == "reject-invitation":
            if not request.user.is_authenticated:
                context["submission_error"] = (
                    "Per rifiutare l'invito devi prima effettuare il login."
                )
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )
            try:
                _reject_onboarding_token(
                    token=token,
                    user=request.user,
                    invitation_kind=invitation_type,
                )
            except (
                ContractInvitation.DoesNotExist,
                AgencyInvitation.DoesNotExist,
            ):
                context["submission_error"] = "Invito non trovato."
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )
            except InvitationRejectValidationError as exc:
                context["submission_error"] = str(exc)
                return render(
                    request, "exchange_agreement/invitation_landing.html", context
                )

            context["state"] = "rejected"
            context["can_continue"] = False
            context["can_reject"] = False
            context["success_message"] = (
                "Invito rifiutato correttamente. Puoi chiudere questa pagina."
            )
            return render(
                request, "exchange_agreement/invitation_landing.html", context
            )

        request.session["onboarding_invitation_token"] = str(invitation.token)
        request.session["onboarding_invitation_kind"] = invitation_type
        callback_url = reverse("exchange_agreement:onboarding-callback")
        if request.user.is_authenticated:
            return redirect(callback_url)
        return redirect(_build_oidc_login_url(callback_url))

    return render(request, "exchange_agreement/invitation_landing.html", context)
