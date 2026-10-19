# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Load the pinned Italian NeTEx Lev5 configuration resources."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.netex_profile_seed import (
    ensure_netex_italian_profile,
)


class Command(BaseCommand):
    help = "Seed Italian NeTEx Lev5 XSD bundle, example XML and guidelines PDF."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            specification = ensure_netex_italian_profile(actor=actor)
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
            OSError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"{specification.code}: 3 active assets ready; specification and XSD rule "
            "are not automatically published. Configure the real validator reference "
            "before publishing/binding the rule with reject_import."
        )
