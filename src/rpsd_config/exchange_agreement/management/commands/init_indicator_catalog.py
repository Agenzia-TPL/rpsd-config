# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.indicator_catalog_bootstrap import (
    ensure_commercial_speed_example,
)


class Command(BaseCommand):
    help = "Create the idempotent multi-format indicator catalog example."

    def handle(self, *args, **options):
        version = ensure_commercial_speed_example()
        self.stdout.write(self.style.SUCCESS(f"Indicator version ready: {version}"))
