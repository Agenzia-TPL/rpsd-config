# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import BinaryIO

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ConfigurationAssetEvent,
)


@dataclass(frozen=True)
class StoredConfigurationAsset:
    asset: ConfigurationAsset
    event: ConfigurationAssetEvent


def _storage_provider():
    from rpsd_storage import get_storage_provider
    from rpsd_storage.settings import StorageSettings

    s3_settings = {
        "bucket_name": getattr(settings, "CONFIG_ASSETS_STORAGE_S3_BUCKET_NAME", ""),
        "aws_access_key_id": getattr(
            settings,
            "CONFIG_ASSETS_STORAGE_S3_AWS_ACCESS_KEY_ID",
            "",
        )
        or None,
        "aws_secret_access_key": getattr(
            settings,
            "CONFIG_ASSETS_STORAGE_S3_AWS_SECRET_ACCESS_KEY",
            "",
        )
        or None,
        "aws_session_token": getattr(
            settings,
            "CONFIG_ASSETS_STORAGE_S3_AWS_SESSION_TOKEN",
            "",
        )
        or None,
        "region_name": getattr(settings, "CONFIG_ASSETS_STORAGE_S3_REGION_NAME", "")
        or None,
        "endpoint_url": getattr(settings, "CONFIG_ASSETS_STORAGE_S3_ENDPOINT_URL", "")
        or None,
    }
    storage_settings = StorageSettings(
        provider=getattr(settings, "CONFIG_ASSETS_STORAGE_PROVIDER", "fs"),
        fs={
            "base_path": getattr(
                settings,
                "CONFIG_ASSETS_STORAGE_FS_BASE_PATH",
                "/tmp/rpsd-config-assets",
            )
        },
        s3=s3_settings,
    )
    return get_storage_provider(storage_settings)


def _asset_event_payload(asset: ConfigurationAsset, event_type: str) -> dict:
    return {
        "event_type": event_type,
        "asset_id": asset.pk,
        "asset_type": asset.asset_type,
        "what": asset.what,
        "label": asset.label,
        "version": asset.version,
        "status": asset.status,
        "is_active": asset.is_active,
        "checksum_sha256": asset.checksum_sha256,
        "storage_url": asset.storage_url,
        "content_type": asset.content_type,
        "size_bytes": asset.size_bytes,
        "occurred_at": timezone.now().isoformat(),
    }


def create_asset_event(
    *,
    asset: ConfigurationAsset,
    event_type: str,
) -> ConfigurationAssetEvent:
    routing_key = event_type
    return ConfigurationAssetEvent.objects.create(
        asset=asset,
        event_type=event_type,
        routing_key=routing_key,
        payload=_asset_event_payload(asset, event_type),
        status=ConfigurationAssetEvent.Status.PENDING,
    )


@transaction.atomic
def publish_asset_event(event: ConfigurationAssetEvent) -> ConfigurationAssetEvent:
    if not getattr(settings, "CONFIG_ASSETS_RABBITMQ_ENABLED", True):
        return event

    event = ConfigurationAssetEvent.objects.select_for_update().get(pk=event.pk)
    if event.status == ConfigurationAssetEvent.Status.PUBLISHED:
        return event
    event.attempts += 1
    try:
        from rpsd_transport import get_carrier
        from rpsd_transport.carriers.pubsub.rabbitmq import RabbitMQCarrierOptions
        from rpsd_transport.settings import TransportSettings

        transport_settings = TransportSettings(
            carrier="rabbitmq",
            rabbitmq={
                "url": getattr(
                    settings,
                    "CONFIG_ASSETS_RABBITMQ_URL",
                    "amqp://guest:guest@rabbitmq/",
                ),
                "exchange": getattr(
                    settings,
                    "CONFIG_ASSETS_RABBITMQ_EXCHANGE",
                    "rpsd.config.assets",
                ),
                "exchange_type": getattr(
                    settings,
                    "CONFIG_ASSETS_RABBITMQ_EXCHANGE_TYPE",
                    "topic",
                ),
            },
        )

        async def _publish() -> None:
            carrier = get_carrier(transport_settings)
            await carrier.start()
            try:
                await carrier.send_slimfast_async(
                    recipient=event.routing_key,
                    who="rpsd-config",
                    what="configuration-asset-event",
                    content=json.dumps(event.payload).encode("utf-8"),
                    content_type="application/json",
                    filename=f"{event.event_type}.json",
                    custom_metadata={
                        "asset_id": event.asset_id,
                        "event_type": event.event_type,
                    },
                    options=RabbitMQCarrierOptions(routing_key=event.routing_key),
                )
            finally:
                await carrier.stop()

        asyncio.run(_publish())
    except Exception as exc:  # noqa: BLE001 - event failure must be persisted
        event.status = ConfigurationAssetEvent.Status.FAILED
        event.last_error = str(exc)
        event.save(update_fields=["attempts", "status", "last_error", "updated_at"])
        return event

    event.status = ConfigurationAssetEvent.Status.PUBLISHED
    event.last_error = ""
    event.published_at = timezone.now()
    event.save(
        update_fields=[
            "attempts",
            "status",
            "last_error",
            "published_at",
            "updated_at",
        ]
    )
    return event


@transaction.atomic
def _record_asset_event_result(
    asset: ConfigurationAsset, event: ConfigurationAssetEvent
) -> None:
    """Update delivery diagnostics without replaying stale activation state."""
    ConfigurationAsset.objects.select_for_update().get(pk=asset.pk)
    latest = (
        asset.events.order_by("-created_at", "-pk").values_list("pk", flat=True).first()
    )
    if latest != event.pk:
        asset.refresh_from_db()
        return
    ConfigurationAsset.objects.filter(pk=asset.pk).update(
        publish_status=event.status,
        last_publish_error=event.last_error,
        updated_at=timezone.now(),
    )
    asset.refresh_from_db()


def _lock_asset_family(asset_type: str, what: str) -> None:
    """Serialize version allocation and activation, including the first upload."""
    digest = hashlib.sha256(f"{asset_type}:{what}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _next_asset_version(*, asset_type: str, what: str) -> int:
    latest = (
        ConfigurationAsset.objects.filter(asset_type=asset_type, what=what)
        .order_by("-version")
        .values_list("version", flat=True)
        .first()
    )
    return int(latest or 0) + 1


def _read_uploaded_content(uploaded_file: BinaryIO) -> bytes:
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    limit = settings.CONFIG_ASSETS_MAX_UPLOAD_BYTES
    content = uploaded_file.read(limit + 1)
    if len(content) > limit:
        raise ValidationError(f"Asset exceeds the upload limit of {limit} bytes.")
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    if isinstance(content, str):
        content = content.encode("utf-8")
    return content


def inspect_configuration_asset_upload(
    uploaded_file: BinaryIO, *, asset_type: str, what: str
) -> tuple[str, bytes, dict]:
    """Validate uploaded bytes without persisting or executing their content."""
    filename = getattr(uploaded_file, "name", "")
    ConfigurationAsset.validate_filename_for_type(asset_type, filename)
    ConfigurationAsset.validate_asset_code(what)
    content = _read_uploaded_content(uploaded_file)
    if not content:
        raise ValidationError("Il file asset e' vuoto.")

    from rpsd_config.exchange_agreement.services.schema_bundles import (
        inspect_schema_bundle,
    )

    is_bundle = asset_type == ConfigurationAsset.AssetType.XSD_BUNDLE or (
        asset_type in {"netex_xsd", "siri_profile"}
        and filename.lower().endswith(".zip")
    )
    bundle_manifest = inspect_schema_bundle(content) if is_bundle else {}
    if asset_type == ConfigurationAsset.AssetType.JSON_SCHEMA:
        try:
            json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise ValidationError("Invalid JSON schema file.") from exc
    return filename, content, bundle_manifest


def store_configuration_asset(
    *,
    uploaded_file: BinaryIO,
    asset_type: str,
    what: str,
    label: str = "",
    activate: bool = False,
    uploaded_by=None,
) -> StoredConfigurationAsset:
    filename, content, bundle_manifest = inspect_configuration_asset_upload(
        uploaded_file, asset_type=asset_type, what=what
    )
    content_type = (
        getattr(uploaded_file, "content_type", "") or "application/octet-stream"
    )
    checksum = hashlib.sha256(content).hexdigest()
    try:
        provider = _storage_provider()
    except Exception as exc:
        raise ValidationError(
            "Asset storage is unavailable.", code="asset_storage_error"
        ) from exc

    storage_url = None
    try:
        with transaction.atomic():
            _lock_asset_family(asset_type, what)
            version = _next_asset_version(asset_type=asset_type, what=what)
            storage_what = (
                f"config-assets/{asset_type}/{what}/v{version}/{uuid.uuid4().hex}"
            )
            storage_url, metadata = provider.save(
                content,
                filename=filename,
                who="rpsd-config",
                what=storage_what,
                content_type=content_type,
                custom_metadata={
                    "asset_type": asset_type,
                    "what": what,
                    "version": version,
                },
            )
            asset = ConfigurationAsset(
                asset_type=asset_type,
                what=what,
                label=label,
                version=version,
                status=ConfigurationAsset.Status.ACTIVE
                if activate
                else ConfigurationAsset.Status.STORED,
                is_active=activate,
                storage_url=storage_url,
                storage_provider=getattr(metadata, "provider", ""),
                storage_key=getattr(metadata, "object_id", ""),
                original_filename=filename,
                content_type=content_type,
                checksum_sha256=checksum,
                size_bytes=len(content),
                bundle_manifest=bundle_manifest,
                uploaded_by=uploaded_by
                if getattr(uploaded_by, "is_authenticated", False)
                else None,
                uploaded_at=timezone.now(),
                activated_by=uploaded_by
                if activate and getattr(uploaded_by, "is_authenticated", False)
                else None,
                activated_at=timezone.now() if activate else None,
            )
            if activate:
                ConfigurationAsset.objects.filter(
                    asset_type=asset_type,
                    what=what,
                    is_active=True,
                ).update(
                    is_active=False,
                    status=ConfigurationAsset.Status.ARCHIVED,
                    archived_at=timezone.now(),
                )
            asset.full_clean()
            asset.save()
            event = create_asset_event(
                asset=asset,
                event_type="config_asset.activated"
                if activate
                else "config_asset.created",
            )
    except Exception as exc:
        if storage_url:
            try:
                provider.delete(storage_url)
            except Exception:
                logging.getLogger(__name__).exception(
                    "Failed to remove rolled-back asset"
                )
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError(
            "Asset upload could not be stored.", code="asset_storage_error"
        ) from exc

    event = publish_asset_event(event)
    _record_asset_event_result(asset, event)
    return StoredConfigurationAsset(asset=asset, event=event)


def activate_configuration_asset(
    *,
    asset: ConfigurationAsset,
    actor=None,
) -> ConfigurationAsset:
    with transaction.atomic():
        _lock_asset_family(asset.asset_type, asset.what)
        asset.refresh_from_db()
        ConfigurationAsset.objects.filter(
            asset_type=asset.asset_type,
            what=asset.what,
            is_active=True,
        ).exclude(pk=asset.pk).update(
            is_active=False,
            status=ConfigurationAsset.Status.ARCHIVED,
            archived_at=timezone.now(),
        )
        asset.is_active = True
        asset.status = ConfigurationAsset.Status.ACTIVE
        asset.activated_by = (
            actor if getattr(actor, "is_authenticated", False) else None
        )
        asset.activated_at = timezone.now()
        asset.save()
        event = create_asset_event(asset=asset, event_type="config_asset.activated")

    event = publish_asset_event(event)
    _record_asset_event_result(asset, event)
    return asset


def archive_configuration_asset(
    *,
    asset: ConfigurationAsset,
) -> ConfigurationAsset:
    with transaction.atomic():
        _lock_asset_family(asset.asset_type, asset.what)
        asset.refresh_from_db()
        asset.is_active = False
        asset.status = ConfigurationAsset.Status.ARCHIVED
        asset.archived_at = timezone.now()
        asset.save()
        event = create_asset_event(asset=asset, event_type="config_asset.archived")

    event = publish_asset_event(event)
    _record_asset_event_result(asset, event)
    return asset


def load_configuration_asset_content(asset: ConfigurationAsset) -> bytes:
    try:
        content, _metadata = _storage_provider().load(asset.storage_url)
    except Exception as exc:  # noqa: BLE001 - converted to application-level 404
        raise Http404("Configuration asset content not found.") from exc
    checksum = hashlib.sha256(content).hexdigest()
    if checksum != asset.checksum_sha256:
        raise ValidationError("Configuration asset checksum mismatch.")
    if asset.bundle_manifest:
        from rpsd_config.exchange_agreement.services.schema_bundles import (
            verify_schema_bundle,
        )

        verify_schema_bundle(content, asset.bundle_manifest)
    return content


def retry_pending_asset_events() -> int:
    count = 0
    events = ConfigurationAssetEvent.objects.filter(
        status__in=[
            ConfigurationAssetEvent.Status.PENDING,
            ConfigurationAssetEvent.Status.FAILED,
        ]
    ).order_by("created_at", "id")
    for event in events:
        if retry_asset_event(event.pk) is not None:
            count += 1
    return count


@transaction.atomic
def retry_asset_event(event_id: int) -> ConfigurationAssetEvent | None:
    """Serialize explicit retries and never replay an already published event."""
    event = (
        ConfigurationAssetEvent.objects.select_for_update(skip_locked=True)
        .filter(pk=event_id, status__in=["pending", "failed"])
        .first()
    )
    if event is None or not settings.CONFIG_ASSETS_RABBITMQ_ENABLED:
        return None
    event = publish_asset_event(event)
    _record_asset_event_result(event.asset, event)
    return event
