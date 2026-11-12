# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Plan/apply deletion of manifest-owned drafts, preserving shared objects."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.configuration_handoff import json_text
from rpsd_config.exchange_agreement.services.draft_cleanup import cleanup_demo


class Command(BaseCommand):
    help = "Piano di pulizia delle sole bozze create dal seed; --apply esplicito."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        try:
            if (
                options["report"]
                and options["report"].resolve() == options["manifest"].resolve()
            ):
                raise CommandError(
                    "Conservare il manifest: --report deve indicare un altro file."
                )
            actor = get_user_model().objects.get(
                **{get_user_model().USERNAME_FIELD: options["actor"]}
            )
            manifest = json.loads(options["manifest"].read_text())
            report = cleanup_demo(manifest, actor=actor, apply=options["apply"])
            if options["report"]:
                options["report"].write_text(json_text(report))
            self.stdout.write(json_text(report))
        except (
            ObjectDoesNotExist,
            PermissionDenied,
            PermissionError,
            ValidationError,
            ValueError,
            OSError,
        ) as exc:
            raise CommandError(str(exc)) from exc
