# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations, models


def separate_format(apps, schema_editor):
    """Transfer only known formats, failing atomically on ambiguous records."""
    specs = apps.get_model("exchange_agreement", "DatasetSpecification")
    updates, unresolved = [], []
    for spec in specs.objects.using(schema_editor.connection.alias).select_related(
        "dataset"
    ):
        metadata = spec.metadata
        if not isinstance(metadata, dict):
            unresolved.append((spec.pk, spec.code))
            continue
        fmt = metadata.get("format")
        if "format" not in metadata and (
            spec.dataset.code == "netex" or spec.dataset.code.startswith("siri-")
        ):
            fmt = "xml"
        if fmt not in {"xml", "csv", "xlsx", "txt"}:
            unresolved.append((spec.pk, spec.code))
            continue
        spec.format = fmt
        spec.metadata = {k: v for k, v in metadata.items() if k != "format"}
        updates.append(spec)
    if unresolved:
        raise RuntimeError(
            f"Dataset format requires explicit classification (ID, code): {unresolved}"
        )
    specs.objects.using(schema_editor.connection.alias).bulk_update(
        updates, ["format", "metadata"]
    )


def restore_metadata_format(apps, schema_editor):
    """Restore the previous storage layout without touching frozen snapshots."""
    specs = apps.get_model("exchange_agreement", "DatasetSpecification")
    for spec in specs.objects.using(schema_editor.connection.alias).all():
        spec.metadata = {**spec.metadata, "format": spec.format}
        spec.save(update_fields=["metadata"])


class Migration(migrations.Migration):
    dependencies = [("exchange_agreement", "0049_generalize_configuration_assets")]
    operations = [
        migrations.AddField(
            model_name="datasetspecification",
            name="format",
            field=models.CharField(max_length=8, null=True),
        ),
        migrations.RunPython(separate_format, restore_metadata_format),
        migrations.AlterField(
            model_name="datasetspecification",
            name="format",
            field=models.CharField(
                max_length=8,
                choices=[
                    ("xml", "XML"),
                    ("csv", "CSV"),
                    ("xlsx", "Excel (XLSX)"),
                    ("txt", "Text (TXT)"),
                ],
                verbose_name="Formato del dataset",
            ),
        ),
    ]
