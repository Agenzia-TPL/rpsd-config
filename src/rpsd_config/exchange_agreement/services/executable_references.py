# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared validators for immutable executable artifact references."""

import re

from django.core.exceptions import ValidationError

ARTIFACT_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9+.-]*:\S+$")


def validate_artifact_identifier(value: str) -> str:
    normalized = (value or "").strip()
    if len(normalized) > 512 or not ARTIFACT_IDENTIFIER_RE.fullmatch(normalized):
        raise ValidationError(
            "artifact_identifier must use <scheme>:<opaque-value>, without spaces."
        )
    return normalized
