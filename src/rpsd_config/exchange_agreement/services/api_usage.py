# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Small process-local counters backed by structured audit logging.

The counters provide an instrumentation hook without adding an infrastructure
dependency. Production log collection remains the durable source of usage data.
"""

from collections import Counter
from threading import Lock

from rpsd_config.exchange_agreement.services.m2m_audit import audit_m2m_event

_USAGE = Counter()
_LOCK = Lock()


def record_api_usage(
    *,
    version: str,
    endpoint: str,
    outcome: str,
    **metadata,
) -> None:
    key = (version, endpoint, outcome)
    with _LOCK:
        _USAGE[key] += 1
    audit_m2m_event(
        "api.usage",
        endpoint_version=version,
        endpoint=endpoint,
        outcome=outcome,
        **metadata,
    )


def api_usage_count(*, version: str, endpoint: str, outcome: str) -> int:
    with _LOCK:
        return _USAGE[(version, endpoint, outcome)]


def reset_api_usage_counts() -> None:
    with _LOCK:
        _USAGE.clear()
