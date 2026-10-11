# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Bundle inspection freezes files and rejects unresolved schema imports."""

import io
import json
import stat
import zipfile
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)
from rpsd_config.exchange_agreement.services.schema_bundles import (
    inspect_schema_bundle,
    verify_schema_bundle,
)


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

    def test_explicit_entrypoint_from_archive_and_digest_verification(self):
        files = {
            "manifest.json": json.dumps({"entrypoint": "schemas/root.xsd"}),
            "schemas/root.xsd": '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>',
        }
        content = self.bundle(files)
        manifest = inspect_schema_bundle(content)
        verify_schema_bundle(content, manifest)
        manifest["files"][0]["sha256"] = "a" * 64
        with self.assertRaises(ValidationError) as error:
            verify_schema_bundle(content, manifest)
        self.assertEqual(error.exception.code, "invalid_schema_bundle")

    def test_nested_relative_import_is_local(self):
        files = {
            "schemas/root.xsd": '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:import namespace="urn:types" schemaLocation="../types.xsd"/>'
            "</xs:schema>",
            "types.xsd": '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            ' targetNamespace="urn:types"/>',
        }
        inspect_schema_bundle(self.bundle(files), entrypoint="schemas/root.xsd")

    def test_doctype_encoding_and_locationless_import_are_rejected(self):
        for text in (
            '<!DOCTYPE schema [<!ENTITY x "expanded">]><xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">&x;</xs:schema>',
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:import namespace="urn:remote"/></xs:schema>',
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>'.encode("utf-16"),
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:include schemaLocation="file:///tmp/types.xsd"/></xs:schema>',
        ):
            with self.subTest(text=text), self.assertRaises(ValidationError) as error:
                inspect_schema_bundle(self.bundle({"root.xsd": text}))
            self.assertEqual(error.exception.code, "invalid_schema_bundle")

    def test_duplicate_and_special_paths_are_rejected(self):
        for path, mode in (
            ("root.xsd", stat.S_IFLNK),
            ("root.xsd", stat.S_IFIFO),
            ("C:root.xsd", stat.S_IFREG),
            ("./root.xsd", stat.S_IFREG),
        ):
            data = io.BytesIO()
            with zipfile.ZipFile(data, "w") as archive:
                info = zipfile.ZipInfo(path)
                info.external_attr = mode << 16
                archive.writestr(info, "schema")
            with self.subTest(path=path, mode=mode), self.assertRaises(ValidationError):
                inspect_schema_bundle(data.getvalue())
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr("root.xsd", "first")
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr("root.xsd", "second")
        with self.assertRaises(ValidationError):
            inspect_schema_bundle(data.getvalue())

    def test_limits_and_malformed_manifest(self):
        content = self.bundle({"root.xsd": "schema"})
        with patch(
            "rpsd_config.exchange_agreement.services.schema_bundles.MAX_FILE_BYTES", 1
        ):
            with self.assertRaises(ValidationError):
                inspect_schema_bundle(content)
        for manifest in ("not json", "[]", '{"entrypoint":"../root.xsd"}'):
            with self.subTest(manifest=manifest), self.assertRaises(ValidationError):
                inspect_schema_bundle(
                    self.bundle({"manifest.json": manifest, "root.xsd": "schema"})
                )
