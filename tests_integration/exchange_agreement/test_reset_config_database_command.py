# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

from io import StringIO
from unittest.mock import call, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from rpsd_config.exchange_agreement.management.commands.reset_config_database import (
    Command as ResetCommand,
)
from rpsd_config.exchange_agreement.management.commands.reset_config_database import (
    DatabaseTarget,
)


class ResetConfigDatabaseCommandTests(SimpleTestCase):
    target = DatabaseTarget(
        alias="default",
        vendor="postgresql",
        name="rpsd_config_dev",
        host="postgis",
        port="5432",
    )

    def test_show_target_is_read_only(self):
        output = StringIO()
        with (
            patch.object(ResetCommand, "_target", return_value=self.target),
            patch.object(ResetCommand, "_reset_public_schema") as reset_schema,
        ):
            call_command("reset_config_database", show_target=True, stdout=output)

        reset_schema.assert_not_called()
        self.assertIn("database=rpsd_config_dev", output.getvalue())
        self.assertIn("schema=public", output.getvalue())

    @override_settings(DEBUG=True)
    def test_exact_database_confirmation_is_required(self):
        with (
            patch.object(ResetCommand, "_target", return_value=self.target),
            patch.object(ResetCommand, "_reset_public_schema") as reset_schema,
            self.assertRaisesMessage(CommandError, "must exactly match"),
        ):
            call_command(
                "reset_config_database",
                confirm_database="another_database",
            )

        reset_schema.assert_not_called()

    @override_settings(DEBUG=True)
    def test_protected_postgres_database_is_rejected(self):
        protected = DatabaseTarget(
            alias="default",
            vendor="postgresql",
            name="postgres",
            host="postgis",
            port="5432",
        )
        with (
            patch.object(ResetCommand, "_target", return_value=protected),
            patch.object(ResetCommand, "_reset_public_schema") as reset_schema,
            self.assertRaisesMessage(CommandError, "empty or protected"),
        ):
            call_command("reset_config_database", confirm_database="postgres")

        reset_schema.assert_not_called()

    @override_settings(DEBUG=True)
    def test_valid_reset_migrates_and_seeds_only_config(self):
        with (
            patch.object(ResetCommand, "_target", return_value=self.target),
            patch.object(ResetCommand, "_reset_public_schema") as reset_schema,
            patch(
                "rpsd_config.exchange_agreement.management.commands."
                "reset_config_database.call_command"
            ) as nested_command,
        ):
            call_command(
                "reset_config_database",
                confirm_database=self.target.name,
                verbosity=0,
            )

        reset_schema.assert_called_once_with()
        self.assertEqual(
            nested_command.call_args_list,
            [
                call("migrate", database="default", interactive=False, verbosity=1),
                call("seed_target_demo", verbosity=1),
            ],
        )
