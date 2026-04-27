# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def resolve_request_id(request=None) -> str:
    if request is None:
        return ""
    return (
        request.headers.get("X-Request-ID")
        or request.headers.get("X-Correlation-ID")
        or ""
    )


def audit_m2m_event(event: str, **metadata: Any) -> None:
    safe_metadata = {
        key: value
        for key, value in metadata.items()
        if "secret" not in key.lower() and value is not None
    }
    LOGGER.info("m2m.%s %s", event, safe_metadata)
