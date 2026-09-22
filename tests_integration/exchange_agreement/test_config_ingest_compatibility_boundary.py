# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from pathlib import Path

from django.test import SimpleTestCase


class ConfigIngestCompatibilityBoundaryTests(SimpleTestCase):
    def test_runtime_resolution_introduces_no_external_runtime_clients(self):
        repository_root = Path(__file__).resolve().parents[2]
        runtime_sources = (
            repository_root
            / "src/rpsd_config/exchange_agreement/services/ingest_resolution.py",
            repository_root
            / "src/rpsd_config/exchange_agreement/services/api_usage.py",
            repository_root / "src/rpsd_config/exchange_agreement/api.py",
        )
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in runtime_sources
        ).lower()
        dependency_manifest = (
            (repository_root / "pyproject.toml").read_text(encoding="utf-8").lower()
        )

        for forbidden_runtime_dependency in (
            "prefect.client",
            "prefect_api_url",
            "prefect_api_key",
            "executioncontext",
            "transportmessage",
            "rpsd_transport",
        ):
            self.assertNotIn(forbidden_runtime_dependency, source)
        self.assertNotIn('"prefect', dependency_manifest)
