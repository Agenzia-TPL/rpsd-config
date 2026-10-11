# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Golden bytes keep legacy and target JSON checksum conventions identical."""

from decimal import Decimal

from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.contract_revisions import (
    canonical_json_bytes,
    canonical_snapshot_checksum,
)


class SnapshotCanonicalContractTests(SimpleTestCase):
    def test_golden_unicode_null_empty_and_numeric_values(self):
        payload = {
            "z": [],
            "a": {
                "unicode": "Linea città",
                "null": None,
                "integer": 12,
                "decimal": Decimal("1.20"),
                "bool": True,
            },
        }
        golden = (
            '{"a":{"bool":true,"decimal":"1.20","integer":12,"null":null,'
            '"unicode":"Linea città"},"z":[]}'
        ).encode()
        self.assertEqual(canonical_json_bytes(payload), golden)
        self.assertEqual(canonical_json_bytes({"a": payload["a"], "z": []}), golden)
        self.assertEqual(
            canonical_snapshot_checksum(payload),
            "sha256:66ef4449014eaef95fd57c41cdcae88b306ff010183521991533079fe8af3618",
        )
