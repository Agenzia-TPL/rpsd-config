# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Interchange tampering and duplicate-key failures need no database."""

import json

from django.test import SimpleTestCase
from pydantic import ValidationError

from rpsd_config.exchange_agreement.services.catalog_contract import (
    load_package,
    seal_package,
)


class CatalogContractTests(SimpleTestCase):
    def test_normalization_integrity_unknown_fields_and_duplicate_keys(self):
        payload = {
            "sources": [],
            "selection": {"roots": []},
            "dimensions": [],
            "indicator_versions": [],
            "dependencies": [],
            "analysis": {},
        }
        first = seal_package(payload)
        encoded = json.dumps(first.model_dump())
        self.assertEqual(load_package(encoded), first)
        self.assertEqual(seal_package(payload).package_digest, first.package_digest)
        with self.assertRaises(ValueError):
            load_package(encoded.replace('"roots": []', '"roots": ["CHANGED"]'))
        with self.assertRaises(ValueError):
            load_package('{"schema_version":"one","schema_version":"two"}')
        with self.assertRaises(ValidationError):
            seal_package({**payload, "contracts": []})
        with self.assertRaises(ValueError):
            load_package('{"number":NaN}')
