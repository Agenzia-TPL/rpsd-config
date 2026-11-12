# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only inventory for an explicitly selected development seed attempt."""

from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.configuration_handoff import json_text
from rpsd_config.exchange_agreement.services.seed_cleanup import inventory_seed


class Command(BaseCommand):
    help = "Inventario senza scritture DB, per digest esatti dei seed da scartare."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--package-digest", action="append", required=True)
        parser.add_argument("--scenario", required=True)
        parser.add_argument("--output", type=Path, required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(
                **{get_user_model().USERNAME_FIELD: options["actor"]}
            )
            report = inventory_seed(
                options["package_digest"], actor=actor, scenario=options["scenario"]
            )
            options["output"].write_text(json_text(report))
            self.stdout.write(json_text(report))
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            ValueError,
            OSError,
        ) as exc:
            raise CommandError(str(exc)) from exc
