# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Inventory or conservatively backfill validation definitions; never purge a DB."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from rpsd_config.exchange_agreement.services.validation_migration import (
    convert_legacy_rules,
    validation_migration_inventory,
)


class Command(BaseCommand):
    help = "Dry-run validation migration; apply only an explicit reviewed inventory."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True, choices=["default"])
        parser.add_argument("--expected-database-name", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--inventory-file")
        parser.add_argument("--actor")

    def handle(self, *args, **options):
        connection = connections[options["database"]]
        if connection.settings_dict["NAME"] != options["expected_database_name"]:
            raise CommandError("The database name does not match the explicit target.")
        if not options["apply"]:
            report = validation_migration_inventory()
        else:
            if not options["inventory_file"] or not options["actor"]:
                raise CommandError(

                        "Apply requires --inventory-file and --actor; verify "
                        "backup/restore first."

                )
            try:
                inventory = json.loads(Path(options["inventory_file"]).read_text())
                actor = get_user_model().objects.get(username=options["actor"])
                report = convert_legacy_rules(actor=actor, expected_inventory=inventory)
            except (ValueError, OSError, get_user_model().DoesNotExist) as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, sort_keys=True, ensure_ascii=False))
