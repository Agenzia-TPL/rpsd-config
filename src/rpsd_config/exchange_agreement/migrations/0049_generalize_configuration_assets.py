# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.core.validators
from django.conf import settings
from django.db import migrations, models


def audit_asset_codes(apps, schema_editor):
    """Fail explicitly instead of rewriting frozen asset identities."""
    import re

    assets = apps.get_model("exchange_agreement", "ConfigurationAsset")
    invalid = [
        pk
        for pk, code in assets.objects.using(
            schema_editor.connection.alias
        ).values_list("pk", "what")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", code or "")
    ]
    if invalid:
        raise RuntimeError(f"Invalid existing asset codes; review asset IDs {invalid}.")


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0048_contract_revision_indicators"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(audit_asset_codes, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="configurationasset",
            name="config_asset_supported_dataset_type",
        ),
        migrations.AlterField(
            model_name="configurationasset",
            name="asset_type",
            field=models.CharField(
                choices=[
                    ("xsd_schema", "Schema XSD"),
                    ("xsd_bundle", "Bundle XSD"),
                    ("json_schema", "Schema JSON"),
                    ("document", "Documento"),
                    ("archive", "Archivio generico"),
                    ("other", "Altro file tecnico"),
                    ("netex_xsd", "NeTEx XSD (compatibilità)"),
                    ("siri_profile", "SIRI profile"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="configurationasset",
            name="what",
            field=models.CharField(
                db_index=True,
                max_length=64,
                validators=[
                    django.core.validators.RegexValidator("^[a-z0-9][a-z0-9_-]{0,63}$")
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="configurationasset",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "asset_type__in",
                        [
                            "xsd_schema",
                            "xsd_bundle",
                            "json_schema",
                            "document",
                            "archive",
                            "other",
                            "netex_xsd",
                            "siri_profile",
                        ],
                    )
                ),
                name="config_asset_supported_dataset_type",
            ),
        ),
    ]
