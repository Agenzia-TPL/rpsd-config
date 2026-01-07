from rpsd_config.exchange_agreement.models import Lot, Route, Stop, Trip


class LotAdminProxy(Lot):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Lot"
        verbose_name_plural = "Lots"

class RouteAdminProxy(Route):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Route"
        verbose_name_plural = "Routes"

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
