# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from ..models import AgencyInvitation, ContractInvitation


class InvitationRejectValidationError(ValueError):
    """Raised when invitation reject flow is not valid for current actor/state."""


@dataclass(frozen=True)
class InvitationRejectResult:
    invitation_type: str
    invitation_id: int
    token: str
    status: str


def _validate_reject_actor_email(*, invitation_email: str | None, actor_email: str) -> None:
    if not invitation_email:
        raise InvitationRejectValidationError(
            "Il rifiuto non e' disponibile per inviti aperti."
        )

    normalized_actor_email = (actor_email or "").strip().lower()
    if not normalized_actor_email:
        raise InvitationRejectValidationError(
            "Utente autenticato senza email: impossibile rifiutare l'invito."
        )

    if normalized_actor_email != invitation_email.lower():
        raise InvitationRejectValidationError(
            "L'utente autenticato non corrisponde all'email target dell'invito."
        )


def _ensure_pending_or_expire(*, invitation) -> str | None:
    if invitation.status != invitation.Status.PENDING:
        raise InvitationRejectValidationError(
            "L'invito non e' in stato pending e non puo' essere rifiutato."
        )

    if invitation.expires_at <= timezone.now():
        invitation.status = invitation.Status.EXPIRED
        invitation.save(update_fields=["status", "updated_at"])
        return "L'invito e' scaduto."
    return None


def reject_contract_invitation_for_user(*, token: str, user) -> InvitationRejectResult:
    expiration_error: str | None = None
    with transaction.atomic():
        invitation = (
            ContractInvitation.objects.select_for_update()
            .select_related("contract")
            .get(token=token)
        )

        expiration_error = _ensure_pending_or_expire(invitation=invitation)
        if not expiration_error:
            _validate_reject_actor_email(
                invitation_email=invitation.email,
                actor_email=getattr(user, "email", ""),
            )

            invitation.status = ContractInvitation.Status.REJECTED
            invitation.rejected_by = user
            invitation.rejected_at = timezone.now()
            invitation.save(
                update_fields=["status", "rejected_by", "rejected_at", "updated_at"]
            )

    if expiration_error:
        raise InvitationRejectValidationError(expiration_error)

    return InvitationRejectResult(
        invitation_type="contract",
        invitation_id=invitation.id,
        token=str(invitation.token),
        status=invitation.status,
    )


def reject_agency_invitation_for_user(*, token: str, user) -> InvitationRejectResult:
    expiration_error: str | None = None
    with transaction.atomic():
        invitation = (
            AgencyInvitation.objects.select_for_update()
            .select_related("agency")
            .get(token=token)
        )

        expiration_error = _ensure_pending_or_expire(invitation=invitation)
        if not expiration_error:
            _validate_reject_actor_email(
                invitation_email=invitation.email,
                actor_email=getattr(user, "email", ""),
            )

            invitation.status = AgencyInvitation.Status.REJECTED
            invitation.rejected_by = user
            invitation.rejected_at = timezone.now()
            invitation.save(
                update_fields=["status", "rejected_by", "rejected_at", "updated_at"]
            )

    if expiration_error:
        raise InvitationRejectValidationError(expiration_error)

    return InvitationRejectResult(
        invitation_type="agency",
        invitation_id=invitation.id,
        token=str(invitation.token),
        status=invitation.status,
    )
