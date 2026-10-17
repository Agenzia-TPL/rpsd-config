# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only inventory of economic JSON requiring explicit interpretation."""

import json

from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.models import (
    ContractDependencyConfiguration,
    ContractRevisionIndicator,
)


class Command(BaseCommand):
    help = "Report legacy economic JSON without clearing, converting or evaluating it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check",
            action="store_true",
            help="Exit nonzero if unresolved JSON remains.",
        )

    def handle(self, *args, **options):
        rows = []
        for model in (ContractRevisionIndicator, ContractDependencyConfiguration):
            for config in (
                model.objects.select_related("revision")
                .only(
                    "id",
                    "revision_id",
                    "thresholds",
                    "penalties",
                    "revision__code",
                    "revision__status",
                )
                .exclude(thresholds={}, penalties={})
            ):
                rows.append(
                    {
                        "model": model.__name__,
                        "id": config.pk,
                        "revision": config.revision.code,
                        "status": config.revision.status,
                        "has_thresholds": bool(config.thresholds),
                        "has_penalties": bool(config.penalties),
                        "resolution": "explicit_mapping_required",
                    }
                )
        self.stdout.write(
            json.dumps({"count": len(rows), "unresolved": rows}, sort_keys=True)
        )
        if rows and options["check"]:
            raise CommandError(
                "Legacy economic JSON requires explicit review; no "
                "records were modified."
            )
