# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.flow_catalog_bootstrap import (
    ensure_standard_flow_catalog,
)


class Command(BaseCommand):
    help = "Register the standard input and orchestration flow catalog."

    def handle(self, *args, **options):
        input_flows, orchestration = ensure_standard_flow_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                f"Flow catalog ready: {len(input_flows)} input flows, "
                f"orchestration {orchestration.code}."
            )
        )
