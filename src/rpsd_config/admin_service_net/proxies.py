from rpsd_config.exchange_agreement.models import Lot


class LotAdminProxy(Lot):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
