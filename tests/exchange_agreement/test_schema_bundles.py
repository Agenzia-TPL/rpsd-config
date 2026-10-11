# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Bundle inspection freezes files and rejects unresolved schema imports."""

import io
import zipfile

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)
from rpsd_config.exchange_agreement.services.schema_bundles import inspect_schema_bundle


class SchemaBundleTests(SimpleTestCase):
    def bundle(self, files):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            for path, content in files.items():
                archive.writestr(path, content)
        return data.getvalue()

    def test_include_and_checksums(self):
        content = self.bundle(
            {
                "root.xsd": (
                    "<xs:schema "
                    'xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include '
                    'schemaLocation="types.xsd"/></xs:schema>'
                ),
                "types.xsd": '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>',
            }
        )
        manifest = inspect_schema_bundle(content, entrypoint="root.xsd")
        self.assertEqual(len(manifest["files"]), 2)
        self.assertEqual(len(manifest["bundle_sha256"]), 64)
        self.assertEqual(
            manifest, inspect_schema_bundle(content, entrypoint="root.xsd")
        )

    def test_traversal_and_remote_or_missing_dependency(self):
        for files in (
            {"../root.xsd": "x"},
            {
                "root.xsd": (
                    "<xs:schema "
                    'xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include '
                    'schemaLocation="https://example.org/schema.xsd"/></xs:schema>'
                )
            },
            {
                "root.xsd": (
                    "<xs:schema "
                    'xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include '
                    'schemaLocation="missing.xsd"/></xs:schema>'
                )
            },
        ):
            with self.subTest(files=files), self.assertRaises(ValidationError):
                inspect_schema_bundle(self.bundle(files), entrypoint="root.xsd")

    def test_required_parameters_and_numeric_bounds(self):
        schema = {
            "schema_version": 1,
            "properties": {"window_minutes": {"type": "integer", "minimum": 1}},
            "required": ["window_minutes"],
        }
        validate_indicator_parameters(schema, {"window_minutes": 30})
        for values in (
            {},
            {"window_minutes": True},
            {"window_minutes": 0},
            {"window_minutes": 30, "unknown": 1},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                validate_indicator_parameters(schema, values)
