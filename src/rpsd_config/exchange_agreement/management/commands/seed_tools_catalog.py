# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Apply or preview the packaged, reviewed-source indicator catalog."""

from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Preview the packaged indicator catalog or --dbt-contexts-only; "
        "--apply creates drafts only, without publication."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", type=Path)
        parser.add_argument("--dbt-contexts-only", action="store_true")
        parser.add_argument("--scenario")

    def handle(self, *args, **options):
        seed = "tools/catalog.json"
        path = Path(__file__).resolve().parents[2] / "seed_data" / seed
        call_command(
            "import_tools_catalog",
            package=path,
            actor=options["actor"],
            apply=options["apply"],
            report=options["report"],
            dbt_contexts_only=options["dbt_contexts_only"],
            scenario=options["scenario"],
            stdout=self.stdout,
            stderr=self.stderr,
        )
