# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit development-only reset of the rpsd-config PostgreSQL schema."""

from dataclasses import dataclass

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


@dataclass(frozen=True)
class DatabaseTarget:
    alias: str
    vendor: str
    name: str
    host: str
    port: str


class Command(BaseCommand):
    help = (
        "Recreate only the configured rpsd-config public schema, then migrate "
        "and install the target development seed."
    )

    protected_database_names = {"postgres", "template0", "template1"}

    def add_arguments(self, parser):
        parser.add_argument(
            "--show-target",
            action="store_true",
            help="Print the configured database target without changing it.",
        )
        parser.add_argument(
            "--confirm-database",
            help="Exact database name required to authorize the destructive reset.",
        )
        parser.add_argument(
            "--skip-seed",
            action="store_true",
            help="Apply migrations without installing the target demo scenario.",
        )

    @staticmethod
    def _target() -> DatabaseTarget:
        config = connection.settings_dict
        return DatabaseTarget(
            alias=connection.alias,
            vendor=connection.vendor,
            name=str(config.get("NAME") or ""),
            host=str(config.get("HOST") or ""),
            port=str(config.get("PORT") or ""),
        )

    @staticmethod
    def _target_description(target: DatabaseTarget) -> str:
        return (
            f"alias={target.alias} vendor={target.vendor} "
            f"database={target.name} host={target.host or 'local'} "
            f"port={target.port or 'default'} schema=public"
        )

    def _validate_reset(self, target: DatabaseTarget, confirmation: str | None):
        if not settings.DEBUG:
            raise CommandError("Database reset is allowed only with DEBUG=True.")
        if target.alias != "default":
            raise CommandError("Only the default rpsd-config database can be reset.")
        if target.vendor != "postgresql":
            raise CommandError("Database reset supports PostgreSQL only.")
        if not target.name or target.name.lower() in self.protected_database_names:
            raise CommandError("The configured database name is empty or protected.")
        if confirmation != target.name:
            raise CommandError(
                "Refusing reset: --confirm-database must exactly match "
                f"{target.name!r}."
            )

    @staticmethod
    def _reset_public_schema():
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE")
            cursor.execute("CREATE SCHEMA public")
        connection.close()

    def handle(self, *args, **options):
        target = self._target()
        description = self._target_description(target)
        if options["show_target"]:
            self.stdout.write(description)
            return

        self._validate_reset(target, options.get("confirm_database"))
        self.stdout.write(self.style.WARNING(f"Resetting {description}"))
        self._reset_public_schema()
        call_command("migrate", database="default", interactive=False, verbosity=1)
        if not options["skip_seed"]:
            call_command("seed_target_demo", verbosity=1)
        self.stdout.write(
            self.style.SUCCESS("rpsd-config database reset completed successfully.")
        )
