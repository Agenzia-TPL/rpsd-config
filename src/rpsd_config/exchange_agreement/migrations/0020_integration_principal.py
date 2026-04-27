# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models.functions.datetime import Now


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0019_platform_initialization_profiles"),
    ]

    operations = [
        migrations.CreateModel(
            name="IntegrationPrincipal",
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
                ("name", models.CharField(max_length=128)),
                ("environment", models.CharField(db_index=True, default="prod", max_length=8)),
                ("keycloak_client_id", models.CharField(max_length=255, unique=True)),
                (
                    "keycloak_client_uuid",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("suspended", "Suspended"),
                            ("revoked", "Revoked"),
                        ],
                        db_index=True,
                        default="active",
                        max_length=16,
                    ),
                ),
                (
                    "last_secret_rotation_at",
                    models.DateTimeField(blank=True, db_index=True, null=True),
                ),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="integration_principals",
                        to="exchange_agreement.company",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="integration_principals_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Integration principal",
                "verbose_name_plural": "Integration principals",
                "indexes": [
                    models.Index(fields=["company", "environment"], name="exchange_ag_company_09bbf6_idx"),
                    models.Index(fields=["company", "status"], name="exchange_ag_company_ec5e2b_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("company", "name", "environment"),
                        name="unique_integration_principal_per_company_name_env",
                    )
                ],
            },
        ),
    ]
