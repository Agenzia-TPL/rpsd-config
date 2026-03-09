from django.apps import AppConfig


class ExchangeAgreementConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rpsd_config.exchange_agreement"

    def ready(self):
        from allauth.socialaccount.providers.openid_connect.provider import (
            OpenIDConnectProvider,
        )

        from rpsd_config.server.oidc_adapter import (
            RpsdOpenIDConnectOAuth2Adapter,
        )

        OpenIDConnectProvider.oauth2_adapter_class = RpsdOpenIDConnectOAuth2Adapter
        import rpsd_config.exchange_agreement.signals  # noqa: F401
