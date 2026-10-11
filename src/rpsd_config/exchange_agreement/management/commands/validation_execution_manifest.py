# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Export requirements for deployment readiness checks without contacting Prefect."""

import json

from django.core.management.base import BaseCommand

from rpsd_config.exchange_agreement.services.validation_catalog import (
    validation_execution_manifest,
)


class Command(BaseCommand):
    help = "Export published validation rules and interpreter capabilities as JSON."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(validation_execution_manifest(), sort_keys=True))
