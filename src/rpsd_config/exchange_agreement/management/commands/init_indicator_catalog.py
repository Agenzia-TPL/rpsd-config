# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.indicator_catalog_bootstrap import (
    ensure_commercial_speed_example,
)


class Command(BaseCommand):
    help = "Create the idempotent multi-format indicator catalog example."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("The actor does not exist.") from exc
        version = ensure_commercial_speed_example(actor=actor)
        self.stdout.write(self.style.SUCCESS(f"Indicator version ready: {version}"))
