# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Load a pinned shared SIRI XSD bundle without changing dataset specifications."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.siri_profile_seed import (
    SCHEMA_RESOURCES,
    ensure_siri_schema_asset,
)


class Command(BaseCommand):
    help = "Seed only a shared SIRI XSD asset; dataset and profile links are unchanged."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument(
            "--standard-version",
            choices=tuple(SCHEMA_RESOURCES),
            default="2.2.1",
            help="Pinned SIRI release to load (default: 2.2.1).",
        )

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            asset = ensure_siri_schema_asset(
                actor=actor, standard_version=options["standard_version"]
            )
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            OSError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"SIRI {options['standard_version']} schema ready: "
            f"{asset.what}, asset version {asset.version}, id {asset.pk}, "
            f"SHA-256 {asset.checksum_sha256}. "
            "Dataset specifications, profiles and contracts are unchanged."
        )
