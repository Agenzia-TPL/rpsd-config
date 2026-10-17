# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Seed reusable XSD and non-XML dataset asset examples explicitly."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.dataset_asset_seed import (
    ensure_dataset_asset_examples,
)


class Command(BaseCommand):
    help = "Seed reusable dataset asset examples without resetting application data."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            assets = ensure_dataset_asset_examples(actor=actor)
        except (
            get_user_model().DoesNotExist,
            PermissionDenied,
            ValidationError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Dataset asset examples ready: {len(assets)} exact assets.")
