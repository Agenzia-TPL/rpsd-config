# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.core.validators
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0029_configuration_assets"),
    ]

    operations = [
        migrations.RenameField(
            model_name="dataset",
            old_name="slug",
            new_name="code",
        ),
        migrations.AlterField(
            model_name="dataset",
            name="code",
            field=models.SlugField(
                help_text=(
                    "Canonical TransportMessage.what value, e.g. netex or siri-vm."
                ),
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Dataset code must contain lowercase letters, digits "
                            "and hyphens (examples: netex, siri-vm)."
                        ),
                        regex="^[a-z0-9]+(?:-[a-z0-9]+)*$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="dataset",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("deprecated", "Deprecated")],
                db_index=True,
                default="active",
                max_length=16,
            ),
        ),
        migrations.AlterModelOptions(
            name="dataset",
            options={
                "ordering": ["code"],
                "verbose_name": "Dataset",
                "verbose_name_plural": "Datasets",
            },
        ),
        migrations.AlterModelOptions(
            name="structure",
            options={
                "ordering": ["dataset__code", "name"],
                "verbose_name": "Structure",
                "verbose_name_plural": "Structures",
            },
        ),
        migrations.CreateModel(
            name="DatasetSpecification",
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
                        auto_now_add=True,
                        db_default=django.db.models.functions.datetime.Now(),
                        db_index=True,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                ("code", models.CharField(max_length=96, unique=True)),
                ("version", models.CharField(max_length=32)),
                ("description", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("deprecated", "Deprecated"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "published_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="specifications",
                        to="exchange_agreement.dataset",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="dataset_specifications_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Dataset specification",
                "verbose_name_plural": "Dataset specifications",
                "ordering": ["dataset__code", "version", "code"],
                "indexes": [
                    models.Index(
                        fields=["dataset", "status"],
                        name="ix_dataset_spec_dataset_status",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset", "version"),
                        name="uniq_dataset_specification_version",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="DatasetSpecificationAsset",
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
                    "role",
                    models.CharField(
                        choices=[
                            ("validation_schema", "Validation schema"),
                            ("constraint", "Constraint"),
                            ("documentation", "Documentation"),
                            ("example", "Example"),
                            ("other", "Other"),
                        ],
                        max_length=32,
                    ),
                ),
                ("required", models.BooleanField(default=True)),
                (
                    "configuration_asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="dataset_specification_links",
                        to="exchange_agreement.configurationasset",
                    ),
                ),
                (
                    "dataset_specification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="asset_links",
                        to="exchange_agreement.datasetspecification",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dataset specification asset",
                "verbose_name_plural": "Dataset specification assets",
                "ordering": ["role", "configuration_asset_id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "dataset_specification",
                            "configuration_asset",
                            "role",
                        ),
                        name="uniq_dataset_spec_asset_role",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="datasetspecification",
            name="assets",
            field=models.ManyToManyField(
                blank=True,
                related_name="dataset_specifications",
                through=("exchange_agreement.DatasetSpecificationAsset"),
                to="exchange_agreement.configurationasset",
            ),
        ),
        migrations.CreateModel(
            name="DatasetSpecificationStatusEvent",
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
                ("from_status", models.CharField(blank=True, max_length=16)),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("published", "Published"),
                            ("deprecated", "Deprecated"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "changed_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="dataset_specification_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "dataset_specification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.datasetspecification",
                    ),
                ),
            ],
            options={
                "verbose_name": "Dataset specification status event",
                "verbose_name_plural": "Dataset specification status events",
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
