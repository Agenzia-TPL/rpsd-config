# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Create an additive validation demo without deploying or creating live contracts."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.csv_validation_seed import (
    ensure_csv_validation_demo,
)
from rpsd_config.exchange_agreement.services.validation_seed import (
    ensure_validation_demo,
)


class Command(BaseCommand):
    help = (
        "Seed a composed indicator and XML/CSV validation "
        "catalog; runtime references are fixtures."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("The actor does not exist.") from exc
        profile = ensure_validation_demo(actor=actor)
        csv_profile = ensure_csv_validation_demo(actor=actor)
        self.stdout.write(
            f"Profiles {profile.code}, {csv_profile.code}; "
            "deployment references require external provisioning."
        )
