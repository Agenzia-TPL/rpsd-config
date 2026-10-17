# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit additive seed of contractual evaluation examples."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.exchange_agreement.services.evaluation_seed import (
    ensure_evaluation_demo,
)


class Command(BaseCommand):
    help = (
        "Create typed evaluation catalog and two "
        "deterministic draft contracts; no approval/runtime."
    )

    def add_arguments(self, parser):
        parser.add_argument("--actor", required=True)

    def handle(self, *args, **options):
        try:
            actor = get_user_model().objects.get(username=options["actor"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("The actor does not exist.") from exc
        profile, revisions = ensure_evaluation_demo(actor=actor)
        self.stdout.write(
            f"Profile {profile.code}; draft examples: "
            f"{', '.join(r.code for r in revisions)}. "
            "Approval remains required; penalties are cumulative; "
            "runtime not provisioned."
        )
