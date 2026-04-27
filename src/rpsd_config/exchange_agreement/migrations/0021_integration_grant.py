# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions.datetime import Now


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0020_integration_principal"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegrationGrant",
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
                        db_default=Now(),
                        db_index=True,
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, db_index=True)),
                (
                    "action",
                    models.CharField(
                        choices=[("ingest:write", "Ingest write")],
                        db_index=True,
                        default="ingest:write",
                        max_length=64,
                    ),
                ),
                ("data_category", models.CharField(blank=True, max_length=64, null=True)),
                ("valid_from", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("valid_to", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("disabled", "Disabled")],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                ("notes", models.TextField(blank=True, default="")),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integration_grants",
                        to="exchange_agreement.contract",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="integration_grants_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "principal",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="grants",
                        to="exchange_agreement.integrationprincipal",
                    ),
                ),
            ],
            options={
                "verbose_name": "Integration grant",
                "verbose_name_plural": "Integration grants",
            },
        ),
    ]
