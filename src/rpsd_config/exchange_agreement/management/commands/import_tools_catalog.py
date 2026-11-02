# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Validate or atomically import an offline Tools catalog package."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.catalog_contract import load_package
from rpsd_config.exchange_agreement.services.catalog_import import (
    CatalogImportError,
    apply_catalog,
    plan_catalog,
)


class Command(BaseCommand):
    help = "Import a pinned catalog: default dry-run, explicit --apply, no publication."

    def add_arguments(self, parser):
        parser.add_argument("--package", type=Path, required=True)
        parser.add_argument("--actor", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--report", type=Path)

    def handle(self, *args, **options):
        report = None
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            package = load_package(options["package"].read_text())
            report = (
                apply_catalog(package, actor=actor)
                if options["apply"]
                else plan_catalog(package, actor=actor).report
            )
        except CatalogImportError as exc:
            report = exc.report
            raise CommandError(str(exc)) from exc
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            OSError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        finally:
            if report is not None:
                text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
                self.stdout.write(text)
                if options["report"]:
                    options["report"].write_text(text + "\n")
