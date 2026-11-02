# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Apply or preview the packaged, reviewed-source indicator catalog."""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Preview the packaged Tools 0.2.0 catalog; --apply creates drafts only."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "seed_data/tools_v020/catalog.json"
        call_command(
            "import_tools_catalog",
            package=path,
            actor=options["actor"],
            apply=options["apply"],
            report=options["report"],
            stdout=self.stdout,
            stderr=self.stderr,
        )
