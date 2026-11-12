# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Export one authorized saved contract revision, optionally with its assets."""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.http import Http404

from rpsd_config.exchange_agreement.models import ContractConfigurationRevision
from rpsd_config.exchange_agreement.services.configuration_exports import (
    ConfigurationExportError,
    export_contract_configuration,
)
from rpsd_config.exchange_agreement.services.configuration_handoff import (
    json_text,
    write_configuration_handoff,
)


class Command(BaseCommand):
    help = "Esporta una revisione esatta: preview in bozza o snapshot congelato."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--contract-code", required=True)
        parser.add_argument("--revision-code", required=True)
        parser.add_argument(
            "--scope", choices=("revision", "dataset", "indicator"), default="revision"
        )
        parser.add_argument("--dataset-code")
        parser.add_argument("--indicator-version-code")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--handoff-dir", type=Path)
        parser.add_argument("--include-assets", action="store_true")
        parser.add_argument("--seed-manifest", type=Path)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(
                **{get_user_model().USERNAME_FIELD: options["actor"]}
            )
            common = {
                "actor": actor,
                "contract_code": options["contract_code"],
                "revision_code": options["revision_code"],
            }
            if options["handoff_dir"]:
                if (
                    options["output"]
                    or options["scope"] != "revision"
                    or options["dataset_code"]
                    or options["indicator_version_code"]
                ):
                    raise CommandError(
                        "--handoff-dir produce tutti i perimetri; "
                        "non combinare con --output o target."
                    )
                report = write_configuration_handoff(
                    **common,
                    directory=options["handoff_dir"],
                    include_assets=options["include_assets"],
                    seed_manifest=(
                        json.loads(options["seed_manifest"].read_text())
                        if options["seed_manifest"]
                        else None
                    ),
                )
                self.stdout.write(json_text(report))
                if not report["complete"]:
                    raise CommandError(
                        "Consegna incompleta: vedere manifest.json; "
                        "i JSON diagnostici sono conservati."
                    )
            else:
                if options["include_assets"] or options["seed_manifest"]:
                    raise CommandError(
                        "--include-assets/--seed-manifest richiedono --handoff-dir."
                    )
                payload = export_contract_configuration(
                    **common,
                    **{
                        k: options[k]
                        for k in ("scope", "dataset_code", "indicator_version_code")
                    },
                )
                content = json_text(payload)
                if options["output"]:
                    options["output"].write_text(content)
                else:
                    self.stdout.write(content)
        except (
            get_user_model().DoesNotExist,
            ContractConfigurationRevision.DoesNotExist,
            PermissionDenied,
            ValidationError,
            ConfigurationExportError,
            Http404,
            OSError,
            ValueError,
        ) as exc:
            raise CommandError(
                str(exc) or "Attore o revisione non disponibili."
            ) from exc
