# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.flow_profiles import (
    ensure_standard_flow_profiles,
    ensure_standard_operational_flows,
)


class Command(BaseCommand):
    help = "Ensure standard platform FlowProfile records exist."

    def handle(self, *args, **options):
        flows = ensure_standard_operational_flows()
        profiles = ensure_standard_flow_profiles()
        self.stdout.write(
            self.style.SUCCESS(
                "FlowProfile standard inizializzati: "
                f"{len(profiles)} profili, {len(flows)} flow operativi."
            )
        )
