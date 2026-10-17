# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Inspect immutable XSD archives as configuration data, without validating datasets."""

import hashlib
import io
import json
import posixpath
import re
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from django.conf import settings
from django.core.exceptions import ValidationError

XSD_NAMESPACE = "{http://www.w3.org/2001/XMLSchema}"


def validate_bundle_path(value: str) -> None:
    """Require a canonical portable archive-relative path."""
    if (
        not isinstance(value, str)
        or not value
        or value == "."
        or PurePosixPath(value).is_absolute()
        or ".." in PurePosixPath(value).parts
        or str(PurePosixPath(value)) != value
        or any(c in value for c in ("\\", ":", "\x00"))
    ):
        raise ValidationError(
            "Unsafe schema bundle path.", code="invalid_schema_bundle"
        )


def validate_bundle_manifest(manifest: dict) -> None:
    """Validate immutable metadata without loading the archived files."""
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "entrypoint", "bundle_sha256", "files"}
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != 1
        or not isinstance(manifest["bundle_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", manifest["bundle_sha256"])
        or not isinstance(manifest["files"], list)
        or not 0 < len(manifest["files"]) <= settings.CONFIG_ASSETS_XSD_MAX_FILES
    ):
        raise ValidationError("Invalid bundle manifest.", code="invalid_schema_bundle")
    validate_bundle_path(manifest["entrypoint"])
    paths = []
    total = 0
    for item in manifest["files"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size_bytes"}
            or not isinstance(item["sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", item["sha256"])
            or type(item["size_bytes"]) is not int
            or not 0 <= item["size_bytes"] <= settings.CONFIG_ASSETS_XSD_MAX_FILE_BYTES
        ):
            raise ValidationError(
                "Invalid bundle file metadata.", code="invalid_schema_bundle"
            )
        validate_bundle_path(item["path"])
        paths.append(item["path"])
        total += item["size_bytes"]
    if (
        paths != sorted(set(paths))
        or manifest["entrypoint"] not in paths
        or not manifest["entrypoint"].endswith(".xsd")
        or total > settings.CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES
    ):
        raise ValidationError(
            "Inconsistent bundle manifest.", code="invalid_schema_bundle"
        )


def verify_schema_bundle(content: bytes, manifest: dict) -> None:
    """Verify stored bytes, every file digest and the pinned entrypoint."""
    validate_bundle_manifest(manifest)
    if inspect_schema_bundle(content, entrypoint=manifest["entrypoint"]) != manifest:
        raise ValidationError(
            "Schema bundle checksum/manifest mismatch.", code="invalid_schema_bundle"
        )


def validate_bundle_rule_asset(specification, rule) -> None:
    """Require an exact descriptor matching one schema linked to the dataset."""
    descriptor = json.loads(rule.definition)
    assets = [
        link.configuration_asset
        for link in specification.asset_links.select_related(
            "configuration_asset"
        ).filter(
            role="validation_schema",
            configuration_asset__asset_type__in=[
                "xsd_bundle",
                "netex_xsd",
                "siri_profile",
            ],
            configuration_asset__what=descriptor["asset_code"],
            configuration_asset__version=int(descriptor["asset_version"]),
        )
    ]
    assets = [asset for asset in assets if asset.bundle_manifest]
    if len(assets) > 1:
        raise ValidationError(
            "Ambiguous schema bundle reference.", code="ambiguous_asset"
        )
    if not assets:
        raise ValidationError(
            "The rule requires a linked schema bundle.", code="missing_asset"
        )
    asset = assets[0]
    validate_bundle_manifest(asset.bundle_manifest)
    if (
        descriptor["bundle_sha256"] != asset.checksum_sha256
        or descriptor["bundle_sha256"] != asset.bundle_manifest["bundle_sha256"]
        or descriptor["entrypoint"] != asset.bundle_manifest["entrypoint"]
    ):
        raise ValidationError(
            "Rule descriptor does not match its schema asset.",
            code="invalid_schema_bundle",
        )


def inspect_schema_bundle(content: bytes, *, entrypoint: str = "") -> dict:
    """Resolve includes/imports within a checksummed archive manifest."""
    if (
        not isinstance(content, bytes)
        or len(content) > settings.CONFIG_ASSETS_MAX_UPLOAD_BYTES
    ):
        raise ValidationError(
            f"Schema archive exceeds {settings.CONFIG_ASSETS_MAX_UPLOAD_BYTES} bytes.",
            code="invalid_schema_bundle",
        )
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if (
                not entries
                or len(archive.infolist()) > settings.CONFIG_ASSETS_XSD_MAX_FILES
                or sum(e.file_size for e in entries)
                > settings.CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES
            ):
                raise ValidationError(
                    "Schema archive exceeds configured limits: "
                    f"{settings.CONFIG_ASSETS_XSD_MAX_FILES} entries, "
                    f"{settings.CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES} total bytes."
                )
            files = {}
            for entry in entries:
                validate_bundle_path(entry.filename)
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or str(path) != entry.filename
                    or entry.filename in files
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                    or entry.flag_bits & 1
                ):
                    raise ValidationError("Unsafe or duplicate schema archive path.")
                if entry.file_size > settings.CONFIG_ASSETS_XSD_MAX_FILE_BYTES:
                    raise ValidationError(
                        "Schema entry exceeds "
                        f"{settings.CONFIG_ASSETS_XSD_MAX_FILE_BYTES} bytes."
                    )
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
                text = files[name].decode("utf-8-sig")
                if "<!DOCTYPE" in text or "<!ENTITY" in text:
                    raise ValidationError(
                        "DTD/entity declarations are not supported in schema bundles."
                    )
                tree = ElementTree.fromstring(text)
                if tree.tag != XSD_NAMESPACE + "schema":
                    raise ValidationError("Archive XSD entry is not a schema.")
                for tag in ("include", "import", "redefine"):
                    for node in tree.findall(XSD_NAMESPACE + tag):
                        location = node.get("schemaLocation")
                        if not location:
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
    except ValidationError as exc:
        if getattr(exc, "code", None):
            raise
        raise ValidationError(
            " ".join(exc.messages), code="invalid_schema_bundle"
        ) from exc
    except (
        zipfile.BadZipFile,
        OSError,
        NotImplementedError,
        ValueError,
        KeyError,
        RuntimeError,
        ElementTree.ParseError,
    ) as exc:
        raise ValidationError(
            "Invalid schema bundle.", code="invalid_schema_bundle"
        ) from exc
