from django.apps import AppConfig


class AdminDatasetExchangeConfig(AppConfig):
    name = "rpsd_config.admin_dataset_exchange"
    label = "admin_dataset_exchange"         # app_label usato dall'admin
    verbose_name = "DatasetExchange"        # intestazione nel menu admin
