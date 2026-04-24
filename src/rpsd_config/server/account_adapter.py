# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from uuid import UUID

from allauth.account.adapter import DefaultAccountAdapter
from django.utils import timezone


class RpsdAccountAdapter(DefaultAccountAdapter):
    """Allow signup only when onboarding invitation session token is valid."""

    def is_open_for_signup(self, request):
        session = getattr(request, "session", None)
        if session is None:
            return False

        invitation_token = session.get("onboarding_invitation_token")
        if not invitation_token:
            return False
        try:
            normalized_token = str(UUID(str(invitation_token)))
        except (TypeError, ValueError):
            return False

        invitation_kind = session.get("onboarding_invitation_kind")
        from rpsd_config.exchange_agreement.models import (
            AgencyInvitation,
            ContractInvitation,
        )

        if invitation_kind == "agency":
            return AgencyInvitation.objects.filter(
                token=normalized_token,
                status=AgencyInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).exists()

        if invitation_kind == "contract":
            return ContractInvitation.objects.filter(
                token=normalized_token,
                status=ContractInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).exists()

        return (
            ContractInvitation.objects.filter(
                token=normalized_token,
                status=ContractInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).exists()
            or AgencyInvitation.objects.filter(
                token=normalized_token,
                status=AgencyInvitation.Status.PENDING,
                expires_at__gt=timezone.now(),
            ).exists()
        )
