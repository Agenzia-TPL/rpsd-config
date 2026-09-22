# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.dataset_catalog_bootstrap import (
    ensure_initial_dataset_catalog,
)


class Command(BaseCommand):
    help = "Ensure the initial versioned dataset catalog exists."

    def handle(self, *args, **options):
        specifications = ensure_initial_dataset_catalog()
        self.stdout.write(
            self.style.SUCCESS(
                f"Dataset catalog initialized: {len(specifications)} specifications."
            )
        )
