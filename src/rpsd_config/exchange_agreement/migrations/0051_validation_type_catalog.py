# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Now

PAIRS = [
    ("xpath", "1.0"),
    ("xpath", "2.0"),
    ("xpath", "3.1"),
    ("xsd_bundle", "1.0"),
    ("csv_expression", "1"),
    ("spreadsheet_expression", "1"),
    ("text_expression", "1"),
]


def populate_catalog(apps, schema_editor):
    """Seed known pairs and reject unresolved legacy definitions atomically."""
    alias = schema_editor.connection.alias
    catalog = apps.get_model("exchange_agreement", "ValidationTypeVersion")
    versions = apps.get_model("exchange_agreement", "ValidationRuleVersion")
    rows = {
        pair: catalog.objects.using(alias).get_or_create(
            validation_type=pair[0], language_version=pair[1]
        )[0]
        for pair in PAIRS
    }
    invalid = []
    for version in versions.objects.using(alias).all():
        pair = (version.validation_type, version.language_version)
        if pair not in rows:
            invalid.append(version.pk)
        else:
            version.validation_type_version_id = rows[pair].pk
            version.save(update_fields=["validation_type_version"])
    if invalid:
        raise RuntimeError(
            f"Unregistered type/language pairs on rule version IDs {invalid}"
        )


def restore_pairs(apps, schema_editor):
    versions = apps.get_model("exchange_agreement", "ValidationRuleVersion")
    for version in versions.objects.using(
        schema_editor.connection.alias
    ).select_related("validation_type_version"):
        version.validation_type = version.validation_type_version.validation_type
        version.language_version = version.validation_type_version.language_version
        version.save(update_fields=["validation_type", "language_version"])


class Migration(migrations.Migration):
    dependencies = [("exchange_agreement", "0050_dataset_specification_format")]
    operations = [
        migrations.CreateModel(
            name="ValidationTypeVersion",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True, db_index=True, db_default=Now()
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("validation_type", models.CharField(max_length=32)),
                ("language_version", models.CharField(max_length=16)),
            ],
            options={
                "ordering": ["validation_type", "language_version"],
                "verbose_name": "Tipo e versione del linguaggio",
                "verbose_name_plural": "Tipi e versioni dei linguaggi",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("validation_type", "language_version"),
                        name="uniq_validation_type_language",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="validationruleversion",
            name="validation_type_version",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rule_versions",
                to="exchange_agreement.validationtypeversion",
                verbose_name="Tipo di validazione e versione del linguaggio",
            ),
        ),
        migrations.RunPython(populate_catalog, restore_pairs),
        migrations.RemoveField(
            model_name="validationruleversion", name="validation_type"
        ),
        migrations.RemoveField(
            model_name="validationruleversion", name="language_version"
        ),
        migrations.AlterField(
            model_name="validationruleversion",
            name="validation_type_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="rule_versions",
                to="exchange_agreement.validationtypeversion",
                verbose_name="Tipo di validazione e versione del linguaggio",
            ),
        ),
    ]
