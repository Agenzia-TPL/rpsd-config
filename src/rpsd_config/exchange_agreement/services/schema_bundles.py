# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Inspect immutable XSD archives as configuration data, without validating datasets."""

import hashlib
import io
import json
import posixpath
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from django.core.exceptions import ValidationError

MAX_FILES = 4096
MAX_TOTAL_BYTES = 128 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
XSD_NAMESPACE = "{http://www.w3.org/2001/XMLSchema}"


def inspect_schema_bundle(content: bytes, *, entrypoint: str = "") -> dict:
    """Resolve includes/imports within a checksummed archive manifest."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if (
                not entries
                or len(entries) > MAX_FILES
                or sum(e.file_size for e in entries) > MAX_TOTAL_BYTES
            ):
                raise ValidationError("Schema archive exceeds the configured limits.")
            files = {}
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or str(path) != entry.filename
                    or entry.filename in files
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or entry.file_size > MAX_FILE_BYTES
                ):
                    raise ValidationError("Unsafe or duplicate schema archive path.")
                files[entry.filename] = archive.read(entry)
            if not entrypoint and "manifest.json" in files:
                descriptor = json.loads(files["manifest.json"])
                if not isinstance(descriptor, dict) or not isinstance(
                    descriptor.get("entrypoint"), str
                ):
                    raise ValidationError("Invalid schema entrypoint manifest.")
                entrypoint = descriptor["entrypoint"]
            schemas = sorted(name for name in files if name.endswith(".xsd"))
            if not entrypoint and len(schemas) == 1:
                entrypoint = schemas[0]
            if entrypoint not in schemas:
                raise ValidationError("Declare an XSD entrypoint in manifest.json.")
            for name in schemas:
                if b"<!DOCTYPE" in files[name] or b"<!ENTITY" in files[name]:
                    raise ValidationError(
                        "DTD/entity declarations are not supported in schema bundles."
                    )
                tree = ElementTree.fromstring(files[name])
                if tree.tag != XSD_NAMESPACE + "schema":
                    raise ValidationError("Archive XSD entry is not a schema.")
                for tag in ("include", "import", "redefine"):
                    for node in tree.findall(XSD_NAMESPACE + tag):
                        location = node.get("schemaLocation")
                        if not location:
                            if tag == "import":
                                continue
                            raise ValidationError("Schema dependency has no location.")
                        resolved = posixpath.normpath(
                            posixpath.join(posixpath.dirname(name), location)
                        )
                        if (
                            ":" in location
                            or location.startswith("/")
                            or resolved not in schemas
                        ):
                            raise ValidationError(
                                "Schema dependencies must resolve inside the bundle."
                            )
            return {
                "schema_version": 1,
                "entrypoint": entrypoint,
                "bundle_sha256": hashlib.sha256(content).hexdigest(),
                "files": [
                    {
                        "path": name,
                        "sha256": hashlib.sha256(files[name]).hexdigest(),
                        "size_bytes": len(files[name]),
                    }
                    for name in sorted(files)
                ],
            }
    except (
        zipfile.BadZipFile,
        ValueError,
        KeyError,
        RuntimeError,
        ElementTree.ParseError,
    ) as exc:
        raise ValidationError("Invalid schema bundle.") from exc
