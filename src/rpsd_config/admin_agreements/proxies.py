# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
    ContractDocument,
    ContractInvitation,
    ContractMembership,
    ContractPublication,
)


class ContractAdminProxy(Contract):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract"
        verbose_name_plural = "Contracts"


class ContractConfigurationRevisionAdminProxy(ContractConfigurationRevision):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract configuration revision"
        verbose_name_plural = "Contract configuration revisions"


class ContractDocumentAdminProxy(ContractDocument):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract document"
        verbose_name_plural = "Contract documents"


class ContractMembershipAdminProxy(ContractMembership):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract membership"
        verbose_name_plural = "Contract memberships"


class ContractInvitationAdminProxy(ContractInvitation):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract invitation"
        verbose_name_plural = "Contract invitations"


class ContractPublicationAdminProxy(ContractPublication):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract publication"
        verbose_name_plural = "Contract publications"


from rpsd_config.exchange_agreement.models import (  # noqa: E402
    IndicatorEvaluationThreshold,
    IndicatorPenalty,
)


class IndicatorEvaluationThresholdAdminProxy(IndicatorEvaluationThreshold):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Soglia dell'indicatore contrattuale"
        verbose_name_plural = "Soglie degli indicatori contrattuali"


class IndicatorPenaltyAdminProxy(IndicatorPenalty):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Penale dell'indicatore contrattuale"
        verbose_name_plural = "Penali degli indicatori contrattuali"
