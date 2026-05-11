# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from rpsd_config.server.socialaccount_adapter import _extract_groups_from_extra_data

from ...services.agency_memberships import sync_agency_memberships_from_groups


class Command(BaseCommand):
    help = "Synchronize Django agency memberships from stored OIDC group claims."

    def add_arguments(self, parser):
        parser.add_argument("--user-id", type=int, help="Limit sync to one user id.")
        parser.add_argument(
            "--username",
            help="Limit sync to one username.",
        )
        parser.add_argument(
            "--authoritative",
            action="store_true",
            help=(
                "Treat stored claims as authoritative and revoke active local "
                "memberships missing from them."
            ),
        )

    def handle(self, *args, **options):
        user_model = get_user_model()
        users = user_model.objects.all().order_by("id")
        if options.get("user_id"):
            users = users.filter(id=options["user_id"])
        if options.get("username"):
            users = users.filter(username=options["username"])
        if not users.exists():
            raise CommandError("No users matched the provided filters.")

        total_touched = 0
        total_revoked = 0
        for user in users:
            social = (
                SocialAccount.objects.filter(user=user)
                .order_by("-last_login", "-date_joined")
                .first()
            )
            if social is None or not isinstance(social.extra_data, dict):
                continue
            groups = _extract_groups_from_extra_data(social.extra_data)
            result = sync_agency_memberships_from_groups(
                user=user,
                groups=groups,
                authoritative=bool(options["authoritative"]),
            )
            total_touched += result.touched
            total_revoked += result.revoked

        self.stdout.write(
            self.style.SUCCESS(
                "Agency membership sync completed: "
                f"touched={total_touched} revoked={total_revoked}"
            )
        )
