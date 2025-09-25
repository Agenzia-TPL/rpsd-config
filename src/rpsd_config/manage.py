#!/usr/bin/env python
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
    return _execute(sys.argv)


# Run Django development server with default arguments (used in pyproject.toml)
def server():
    return _execute([sys.argv[0], "runserver", "0.0.0.0:8000"])


if __name__ == "__main__":
    main()
