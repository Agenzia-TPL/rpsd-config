# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Seed pinned CORSE_PDE file requirements from an explicitly stored bundle."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.models import ConfigurationAsset
from rpsd_config.exchange_agreement.services.corse_pde_seed import ensure_corse_pde_demo


class Command(BaseCommand):
    help = "Seed the CORSE_PDE file-only fixture; EA workflow/runtime are excluded."

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)
        parser.add_argument("--schema-asset-id", type=int, required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            asset = ConfigurationAsset.objects.get(pk=options["schema_asset_id"])
            profile = ensure_corse_pde_demo(actor=actor, schema_asset=asset)
        except (
            get_user_model().DoesNotExist,
            ConfigurationAsset.DoesNotExist,
            PermissionDenied,
            ValidationError,
            ValueError,
        ) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Profile {profile.code}: pinned XSD + 13 XPath rules; "
            "WF-001 excluded, external runtime not provisioned."
        )
