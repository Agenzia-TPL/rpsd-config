# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Reproducible draft FID demo, with an external ownership manifest."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rpsd_config.exchange_agreement.services.configuration_handoff import json_text
from rpsd_config.exchange_agreement.services.contract_demo import seed_contract_demo


class Command(BaseCommand):
    help = "Piano demo FID in bozza; --apply esplicito, nessuna pubblicazione."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--namespace", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(
                **{get_user_model().USERNAME_FIELD: options["actor"]}
            )
            path = options["report"]
            previous = json.loads(path.read_text()) if path and path.exists() else None
            if previous is not None and not isinstance(previous, dict):
                raise CommandError("Il report deve contenere un oggetto JSON.")
            if previous and not previous.get("applied"):
                previous = None
            if options["apply"] and path is None:
                raise CommandError(
                    "--apply richiede --report per conservare "
                    "il manifest della pulizia."
                )
            if options["apply"]:
                # A failed report write rolls back the DB scenario as well.
                with transaction.atomic():
                    report = seed_contract_demo(
                        actor=actor,
                        namespace=options["namespace"],
                        apply=True,
                        previous_manifest=previous,
                    )
                    path.write_text(json_text(report))
            else:
                report = seed_contract_demo(actor=actor, namespace=options["namespace"])
                if path and not previous:
                    path.write_text(json_text(report))
            self.stdout.write(json_text(report))
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            PermissionError,
            ValidationError,
            ValueError,
            OSError,
        ) as exc:
            raise CommandError(str(exc)) from exc
