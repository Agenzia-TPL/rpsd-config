# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Build the Config-owned interchange adapter from a pinned Tools checkout."""

import json
import subprocess
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.tools_catalog_export import (
    ToolsMapping,
    export_tools_catalog,
)


class Command(BaseCommand):
    help = (
        "Export reviewed Tools data and explicit mappings to "
        "deterministic catalog JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--mapping", type=Path, required=True)
        parser.add_argument("--out", type=Path, required=True)
        parser.add_argument("--dbt-contexts-only", action="store_true")

    def handle(self, *args, **options):
        try:
            mapping = ToolsMapping.model_validate_json(options["mapping"].read_text())
            package = export_tools_catalog(
                options["source"].resolve(),
                mapping,
                contexts_only=options["dbt_contexts_only"],
            )
            options["out"].write_text(
                json.dumps(
                    package.model_dump(), sort_keys=True, ensure_ascii=False, indent=2
                )
                + "\n"
            )
        except (
            OSError,
            ValueError,
            ValidationError,
            subprocess.CalledProcessError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Catalog {package.package_digest}: "
            f"{len(package.indicator_versions)} indicator versions, "
            f"{len(package.rule_versions)} rule/context versions, "
            f"{len(package.selection.exclusions)} explicit exclusions."
        )
