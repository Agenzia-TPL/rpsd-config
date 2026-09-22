# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def common_version_fields():
    return [
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
            "engine",
            models.CharField(
                choices=[("prefect", "Prefect")],
                default="prefect",
                max_length=16,
            ),
        ),
        ("deployment_name", models.CharField(blank=True, max_length=255)),
        ("artifact_identifier", models.CharField(blank=True, max_length=512)),
        ("invocation_contract", models.JSONField(blank=True, default=dict)),
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
    ]


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0032_indicator_version_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="InputFlowVersion",
            fields=common_version_fields()
            + [
                ("compatibility", models.JSONField(blank=True, default=dict)),
                (
                    "dataset_specification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="input_flow_versions",
                        to="exchange_agreement.datasetspecification",
                    ),
                ),
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_versions_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Input flow version",
                "verbose_name_plural": "Input flow versions",
                "ordering": ["dataset_specification__code", "version", "code"],
                "indexes": [
                    models.Index(
                        fields=["dataset_specification", "status"],
                        name="ix_input_flow_spec_status",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset_specification", "version"),
                        name="uniq_input_flow_specification_version",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="OrchestrationFlowVersion",
            fields=common_version_fields()
            + [
                (
                    "published_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(class)s_versions_published",
                        to=settings.AUTH_USER_MODEL,
                    ),
                )
            ],
            options={
                "verbose_name": "Orchestration flow version",
                "verbose_name_plural": "Orchestration flow versions",
                "ordering": ["version", "code"],
            },
        ),
        migrations.CreateModel(
            name="InputFlowVersionStatusEvent",
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
                        related_name="input_flow_version_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "input_flow_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.inputflowversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Input flow version status event",
                "verbose_name_plural": "Input flow version status events",
                "ordering": ["changed_at", "id"],
            },
        ),
        migrations.CreateModel(
            name="OrchestrationFlowVersionStatusEvent",
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
                        related_name="orchestration_flow_version_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "orchestration_flow_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.orchestrationflowversion",
                    ),
                ),
            ],
            options={
                "verbose_name": "Orchestration flow version status event",
                "verbose_name_plural": "Orchestration flow version status events",
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
