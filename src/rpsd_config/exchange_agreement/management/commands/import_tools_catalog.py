# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Validate or atomically import an offline Tools catalog package."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from rpsd_config.exchange_agreement.services.catalog_contract import (
    documentary_package,
    load_package,
)
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
        parser.add_argument("--scenario")
        parser.add_argument("--dbt-contexts-only", action="store_true")

    def handle(self, *args, **options):
        report = None
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            package = load_package(options["package"].read_text())
            if options["dbt_contexts_only"]:
                package = documentary_package(package)
            path = options["report"]
            if path and path.resolve() == options["package"].resolve():
                raise ValueError(
                    "Il report non può sovrascrivere il pacchetto sorgente."
                )
            previous = json.loads(path.read_text()) if path and path.exists() else None
            if previous and not previous.get("applied"):
                previous = None
            if options["apply"]:
                with transaction.atomic():
                    report = apply_catalog(
                        package,
                        actor=actor,
                        previous_manifest=previous,
                        scenario=options["scenario"],
                    )
                    if path:
                        path.write_text(
                            json.dumps(
                                report, ensure_ascii=False, indent=2, sort_keys=True
                            )
                            + "\n"
                        )
            else:
                report = plan_catalog(package, actor=actor).report
                if path and not previous:
                    path.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
                        + "\n"
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
            report = None
            raise CommandError(str(exc)) from exc
        finally:
            if report is not None:
                text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
                self.stdout.write(text)
