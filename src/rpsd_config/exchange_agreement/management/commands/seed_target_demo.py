# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.development_seed import (
    ensure_target_development_seed,
)


class Command(BaseCommand):
    help = "Create an idempotent development scenario using the target data model."

    def handle(self, *args, **options):
        try:
            result = ensure_target_development_seed()
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "Target demo ready: "
                f"contract={result.contract_code}, revision={result.revision_code}, "
                f"profile={result.profile_code}, "
                f"publication={result.publication_version}."
            )
        )
