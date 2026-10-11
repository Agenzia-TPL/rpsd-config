# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only inventory of calculation provenance and legacy indicator files."""

import json

from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    indicator_artifact_inventory,
)


class Command(BaseCommand):
    help = (
        "Inventory indicator artifact identifiers separately from legacy YAML assets."
    )

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(indicator_artifact_inventory(), sort_keys=True))
