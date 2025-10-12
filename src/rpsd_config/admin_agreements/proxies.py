from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractDocument,
    ContractIndicator,
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
