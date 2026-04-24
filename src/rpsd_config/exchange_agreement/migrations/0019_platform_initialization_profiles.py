# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.core.validators
from django.db import migrations, models
from django.db.models.functions.datetime import Now

import rpsd_config.exchange_agreement.models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0018_invitation_rejected_state"),
    ]

    operations = [
        migrations.CreateModel(
            name="IndicatorProfile",
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
                ("label", models.CharField(blank=True, default="", max_length=128)),
                (
                    "file",
                    models.FileField(
                        help_text="Indicator definition file (.yml/.yaml).",
                        max_length=512,
                        upload_to=rpsd_config.exchange_agreement.models.indicator_profile_upload_path,
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                allowed_extensions=["yml", "yaml"]
                            )
                        ],
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=False)),
            ],
            options={
                "verbose_name": "Indicator profile",
                "verbose_name_plural": "Indicator profiles",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="NetexValidationProfile",
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
                ("label", models.CharField(blank=True, default="", max_length=128)),
                (
                    "file",
                    models.FileField(
                        help_text="Validation profile file (.xsd).",
                        max_length=512,
                        upload_to=rpsd_config.exchange_agreement.models.netex_profile_upload_path,
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                allowed_extensions=["xsd"]
                            )
                        ],
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=False)),
            ],
            options={
                "verbose_name": "Netex validation profile",
                "verbose_name_plural": "Netex validation profiles",
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(is_active=True),
                        fields=("is_active",),
                        name="uniq_active_netex_validation_profile",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SiriValidationProfile",
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
                    "profile_type",
                    models.CharField(
                        choices=[
                            ("siri-pt", "SIRI PT"),
                            ("siri-sx", "SIRI SX"),
                            ("siri-vm", "SIRI VM"),
                            ("siri-sm", "SIRI SM"),
                        ],
                        default="siri-pt",
                        max_length=32,
                    ),
                ),
                ("label", models.CharField(blank=True, default="", max_length=128)),
                (
                    "file",
                    models.FileField(
                        help_text="SIRI validation profile file (.xsd/.xml).",
                        max_length=512,
                        upload_to=rpsd_config.exchange_agreement.models.siri_profile_upload_path,
                        validators=[
                            django.core.validators.FileExtensionValidator(
                                allowed_extensions=["xsd", "xml"]
                            )
                        ],
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=False)),
            ],
            options={
                "verbose_name": "SIRI validation profile",
                "verbose_name_plural": "SIRI validation profiles",
                "ordering": ["profile_type", "-created_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(is_active=True),
                        fields=("profile_type",),
                        name="uniq_active_siri_profile_by_type",
                    )
                ],
            },
        ),
    ]
