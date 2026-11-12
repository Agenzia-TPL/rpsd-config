# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit cleanup for one manifest, with a separate development retirement mode."""

import json
from contextlib import nullcontext
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rpsd_config.exchange_agreement.services.configuration_handoff import json_text
from rpsd_config.exchange_agreement.services.seed_cleanup import cleanup_seed


class Command(BaseCommand):
    help = "Piano pulizia scenario; ritiro pubblicati solo sviluppo, apply esplicito."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--manifest", type=Path, required=True)
        parser.add_argument("--report", type=Path)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--retire-published-development", action="store_true")
        parser.add_argument("--confirm-database")

    def handle(self, *args, **options):
        try:
            path = options["report"]
            if path and path.resolve() == options["manifest"].resolve():
                raise ValueError("Il report non può sovrascrivere il manifest.")
            actor = get_user_model().objects.get(
                **{get_user_model().USERNAME_FIELD: options["actor"]}
            )
            manifest = json.loads(options["manifest"].read_text())
            with transaction.atomic() if options["apply"] else nullcontext():
                report = cleanup_seed(
                    manifest,
                    actor=actor,
                    apply=options["apply"],
                    retire_published=options["retire_published_development"],
                    confirm_database=options["confirm_database"],
                )
                if path:
                    path.write_text(json_text(report))
            self.stdout.write(json_text(report))
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            ValueError,
            OSError,
        ) as exc:
            raise CommandError(str(exc)) from exc
