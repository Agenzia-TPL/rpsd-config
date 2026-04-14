#!/usr/bin/env python
# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Django's command-line utility for administrative tasks."""

import os
import sys


def _execute(argv):
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rpsd_config.server.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(argv)


# Run Django management command (used in pyproject.toml)
def main():
    """Execute Django management commands."""
    # Intercept custom devserver command
    if len(sys.argv) > 1 and sys.argv[1] == "devserver":
        return devserver()
    return _execute(sys.argv)


# Run Django development server
def devserver():
    """Run Django development server on 0.0.0.0:8000."""
    return _execute([sys.argv[0], "runserver", "0.0.0.0:8000"])


if __name__ == "__main__":
    main()
