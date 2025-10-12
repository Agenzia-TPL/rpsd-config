from rpsd_config.exchange_agreement.models import Line, Lot, Stop, Trip


class LotAdminProxy(Lot):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Lot"
        verbose_name_plural = "Lots"

class LineAdminProxy(Line):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Line"
        verbose_name_plural = "Lines"

class StopAdminProxy(Stop):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Stop"
        verbose_name_plural = "Stops"

class TripAdminProxy(Trip):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
