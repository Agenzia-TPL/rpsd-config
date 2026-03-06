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
    """Execute Django management commands."""
    # Intercept custom devserver command
    if len(sys.argv) > 1 and sys.argv[1] == "devserver":
        return devserver()
    return _execute(sys.argv)


# Run Django development server with configured host and port
def devserver():
    """Run Django development server with configured host and port."""
    from rpsd_config.server.settings import ProjectSettings

    settings = ProjectSettings()
    bind_address = f"{settings.APP_HOST}:{settings.APP_PORT}"
    return _execute([sys.argv[0], "runserver", bind_address])


if __name__ == "__main__":
    main()
