from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractDocument,
    ContractInvitation,
    ContractIndicator,
    ContractMembership,
    ContractPublication,
    FlowProfile,
)


class ContractAdminProxy(Contract):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract"
        verbose_name_plural = "Contracts"

class ContractDocumentAdminProxy(ContractDocument):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract document"
        verbose_name_plural = "Contract documents"

class ContractIndicatorAdminProxy(ContractIndicator):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract indicator"
        verbose_name_plural = "Contract indicators"


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


class FlowProfileAdminProxy(FlowProfile):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Flow profile"
        verbose_name_plural = "Flow profiles"


class ContractPublicationAdminProxy(ContractPublication):
    class Meta:
        proxy = True
        app_label = "admin_agreements"
        verbose_name = "Contract publication"
        verbose_name_plural = "Contract publications"
