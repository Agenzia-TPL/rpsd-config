# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import hashlib

from django.db import migrations


def verify_recovered_files(apps, schema_editor):
    """Refuse to drop a legacy file reference unless verified asset bytes exist."""
    from rpsd_config.exchange_agreement.models import ConfigurationAsset
    from rpsd_config.exchange_agreement.services.configuration_assets import (
        load_configuration_asset_content,
    )

    for name in ("NetexValidationProfile", "SiriValidationProfile"):
        model = apps.get_model("exchange_agreement", name)
        for profile in model.objects.using(schema_editor.connection.alias).all():
            if not profile.file:
                continue
            try:
                with profile.file.open("rb") as stream:
                    digest = hashlib.sha256(stream.read()).hexdigest()
                asset = ConfigurationAsset.objects.get(
                    pk=profile.configuration_asset_id
                )
                if (
                    hashlib.sha256(load_configuration_asset_content(asset)).hexdigest()
                    != digest
                ):
                    raise ValueError("Linked asset differs from the legacy file.")
            except Exception as exc:
                raise RuntimeError(
                    f"Recover {name} ID={profile.pk} before drop: run "
                    "recover_legacy_validation_profiles --apply and retry migration."
                ) from exc


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0053_explicit_orm_relations"),
        ("admin_dataset_exchange", "0014_remove_legacy_profile_proxies"),
    ]
    operations = [
        migrations.RunPython(verify_recovered_files),
        migrations.DeleteModel(name="NetexValidationProfile"),
        migrations.DeleteModel(name="SiriValidationProfile"),
    ]
