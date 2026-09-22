# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0033_versioned_flow_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProcessingProfileVersion",
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
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField()),
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
                    "orchestration_flow_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="processing_profile_versions",
                        to="exchange_agreement.orchestrationflowversion",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="processing_profile_versions_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Processing profile version",
                "verbose_name_plural": "Processing profile versions",
                "ordering": ["name", "version", "code"],
                "indexes": [
                    models.Index(
                        fields=["status", "code"],
                        name="ix_process_profile_status",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProcessingProfileInputFlow",
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
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="processing_profile_input_links",
                        to="exchange_agreement.dataset",
                    ),
                ),
                (
                    "input_flow_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="processing_profile_input_links",
                        to="exchange_agreement.inputflowversion",
                    ),
                ),
                (
                    "processing_profile_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="input_flow_links",
                        to="exchange_agreement.processingprofileversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Processing profile input flow",
                "verbose_name_plural": "Processing profile input flows",
                "ordering": ["dataset__code", "input_flow_version__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("processing_profile_version", "dataset"),
                        name="uniq_process_profile_dataset",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProcessingProfileIndicatorVersion",
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
                ("proposed_by_default", models.BooleanField(default=False)),
                (
                    "indicator_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="processing_profile_links",
                        to="exchange_agreement.indicatorversion",
                    ),
                ),
                (
                    "processing_profile_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indicator_version_links",
                        to="exchange_agreement.processingprofileversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Processing profile indicator version",
                "verbose_name_plural": "Processing profile indicator versions",
                "ordering": [
                    "indicator_version__indicator__code",
                    "indicator_version__version",
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("processing_profile_version", "indicator_version"),
                        name="uniq_process_profile_indicator",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ProcessingProfileVersionStatusEvent",
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
                        db_index=True, default=django.utils.timezone.now
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="processing_profile_version_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "processing_profile_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.processingprofileversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Processing profile version status event",
                "verbose_name_plural": "Processing profile version status events",
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
