# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Validation primitives for contract revision business configuration."""

import math
from decimal import Decimal

from django.core.exceptions import ValidationError

FORBIDDEN_SCHEDULING_KEYS = {
    "cron",
    "frequency",
    "interval",
    "schedule",
    "scheduled_at",
    "trigger",
    "trigger_mode",
}


def _normalize_json_value(value, *, path: str):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValidationError(f"{path} cannot contain NaN or infinity.")
        raise ValidationError(
            f"{path} cannot contain floats; use a decimal string instead."
        )
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = _normalize_json_value(item, path=f"{path}[{index}]")
        return value
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{path} keys must be strings.")
            if key.strip().lower() in FORBIDDEN_SCHEDULING_KEYS:
                raise ValidationError(
                    f"{path}.{key} is execution scheduling and is not allowed."
                )
            value[key] = _normalize_json_value(item, path=f"{path}.{key}")
        return value
    raise ValidationError(f"{path} contains unsupported value {type(value).__name__}.")


def validate_business_configuration(value, *, field_name: str) -> dict:
    """Accept deterministic business JSON and reject execution scheduling."""

    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a JSON object.")
    return _normalize_json_value(value, path=field_name)
