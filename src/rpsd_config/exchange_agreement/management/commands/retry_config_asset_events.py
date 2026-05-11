# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.configuration_assets import (
    retry_pending_asset_events,
)


class Command(BaseCommand):
    help = "Retry pending or failed configuration asset RabbitMQ events."

    def handle(self, *args, **options):
        count = retry_pending_asset_events()
        self.stdout.write(
            self.style.SUCCESS(f"Eventi asset configurazione processati: {count}.")
        )
