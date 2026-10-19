# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Load SIRI 2.1 schemas and Italian examples without resetting data."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.siri_profile_seed import (
    ensure_siri_italian_profile,
)


class Command(BaseCommand):
    help = "Seed one shared SIRI 2.1 XSD bundle and service-specific asset links."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            specifications = ensure_siri_italian_profile(actor=actor)
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            OSError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            "SIRI assets ready: "
            + ", ".join(spec.code for spec in specifications)
            + ". Existing published versions, profiles and contracts are unchanged."
        )
