from rpsd_config.exchange_agreement.models import Agency, Authority, Company


class AgencyAdminProxy(Agency):
    class Meta:
        proxy = True
        app_label = "admin_stakeholders"
        verbose_name = "Agency"
        verbose_name_plural = "Agencies"


class CompanyAdminProxy(Company):
    class Meta:
        proxy = True
        app_label = "admin_stakeholders"
        verbose_name = "Company"
        verbose_name_plural = "Companies"


class AuthorityAdminProxy(Authority):
    class Meta:
        proxy = True
        app_label = "admin_stakeholders"
        verbose_name = "Authority"
        verbose_name_plural = "Authorities"
