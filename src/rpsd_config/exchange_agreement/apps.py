from django.apps import AppConfig


class ExchangeAgreementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rpsd_config.exchange_agreement"

    def ready(self):
        import rpsd_config.exchange_agreement.signals
