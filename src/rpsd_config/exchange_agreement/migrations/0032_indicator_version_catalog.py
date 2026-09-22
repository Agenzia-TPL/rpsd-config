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
        ("exchange_agreement", "0031_requirement_fragment_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="Indicator",
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
                (
                    "code",
                    models.SlugField(
                        max_length=96,
                        unique=True,
                        validators=[
                            django.core.validators.RegexValidator(
                                message=(
                                    "Indicator code must contain lowercase letters, "
                                    "digits and hyphens."
                                ),
                                regex="^[a-z0-9]+(?:-[a-z0-9]+)*$",
                            )
                        ],
                    ),
                ),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("deprecated", "Deprecated")],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
            ],
            options={
                "verbose_name": "Indicator",
                "verbose_name_plural": "Indicators",
                "ordering": ["code"],
            },
        ),
        migrations.CreateModel(
            name="IndicatorVersion",
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
                ("description", models.TextField()),
                ("formula_description", models.TextField()),
                ("input_contract", models.JSONField(blank=True, default=dict)),
                ("output_contract", models.JSONField(blank=True, default=dict)),
                (
                    "execution_engine",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("", "No execution reference"),
                            ("prefect", "Prefect"),
                            ("dbt", "dbt"),
                            ("external", "External"),
                        ],
                        default="",
                        max_length=16,
                    ),
                ),
                ("execution_reference", models.CharField(blank=True, max_length=255)),
                ("artifact_identifier", models.CharField(blank=True, max_length=512)),
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
                (
                    "published_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "indicator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="versions",
                        to="exchange_agreement.indicator",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="indicator_versions_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "required_fragments",
                    models.ManyToManyField(
                        blank=True,
                        related_name="indicator_versions",
                        to="exchange_agreement.requirementfragment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Indicator version",
                "verbose_name_plural": "Indicator versions",
                "ordering": ["indicator__code", "version", "code"],
                "indexes": [
                    models.Index(
                        fields=["indicator", "status"],
                        name="ix_indicator_version_status",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("indicator", "version"),
                        name="uniq_indicator_version",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="IndicatorVersionStatusEvent",
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
                        related_name="indicator_version_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "indicator_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.indicatorversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Indicator version status event",
                "verbose_name_plural": "Indicator version status events",
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
