# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
import django.db.models.functions.datetime
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("exchange_agreement", "0028_operationalflow"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigurationAsset",
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
                    "asset_type",
                    models.CharField(
                        choices=[
                            ("netex_xsd", "NeTEx XSD"),
                            ("siri_profile", "SIRI profile"),
                            ("indicator_yaml", "Indicator YAML"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("what", models.CharField(blank=True, db_index=True, default="", max_length=64)),
                ("label", models.CharField(blank=True, default="", max_length=128)),
                ("version", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("stored", "Stored"),
                            ("active", "Active"),
                            ("archived", "Archived"),
                        ],
                        db_index=True,
                        default="stored",
                        max_length=16,
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=False)),
                ("storage_url", models.CharField(max_length=1024)),
                ("storage_provider", models.CharField(max_length=32)),
                ("storage_key", models.CharField(blank=True, default="", max_length=512)),
                ("original_filename", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, default="", max_length=128)),
                ("checksum_sha256", models.CharField(db_index=True, max_length=64)),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                (
                    "uploaded_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                    ),
                ),
                ("activated_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("archived_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("publish_status", models.CharField(blank=True, default="", max_length=16)),
                ("last_publish_error", models.TextField(blank=True, default="")),
                (
                    "activated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="configuration_assets_activated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="configuration_assets_uploaded",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Configuration asset",
                "verbose_name_plural": "Configuration assets",
                "ordering": ["asset_type", "what", "-version", "-created_at"],
                "indexes": [
                    models.Index(
                        fields=["asset_type", "what", "status"],
                        name="exchange_ag_asset__0b9d8a_idx",
                    ),
                    models.Index(
                        fields=["is_active", "asset_type", "what"],
                        name="exchange_ag_is_act_0a33d7_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ConfigurationAssetEvent",
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
                ("event_type", models.CharField(db_index=True, max_length=64)),
                ("routing_key", models.CharField(db_index=True, max_length=128)),
                ("payload", models.JSONField(default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("published", "Published"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.TextField(blank=True, default="")),
                ("published_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "asset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="events",
                        to="exchange_agreement.configurationasset",
                    ),
                ),
            ],
            options={
                "verbose_name": "Configuration asset event",
                "verbose_name_plural": "Configuration asset events",
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["status", "event_type"],
                        name="exchange_ag_status_b0c3a4_idx",
                    ),
                    models.Index(
                        fields=["asset", "status"],
                        name="exchange_ag_asset_i_b487ba_idx",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="indicatorprofile",
            name="configuration_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="indicator_profiles",
                to="exchange_agreement.configurationasset",
            ),
        ),
        migrations.AddField(
            model_name="netexvalidationprofile",
            name="configuration_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="netex_profiles",
                to="exchange_agreement.configurationasset",
            ),
        ),
        migrations.AddField(
            model_name="sirivalidationprofile",
            name="configuration_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="siri_profiles",
                to="exchange_agreement.configurationasset",
            ),
        ),
        migrations.AlterField(
            model_name="sirivalidationprofile",
            name="profile_type",
            field=models.CharField(
                choices=[
                    ("siri-pt", "SIRI PT"),
                    ("siri-et", "SIRI ET"),
                    ("siri-st", "SIRI ST"),
                    ("siri-ct", "SIRI CT"),
                    ("siri-cm", "SIRI CM"),
                    ("siri-gm", "SIRI GM"),
                    ("siri-fm", "SIRI FM"),
                    ("siri-sx", "SIRI SX"),
                    ("siri-vm", "SIRI VM"),
                    ("siri-sm", "SIRI SM"),
                ],
                default="siri-pt",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="configurationasset",
            constraint=models.UniqueConstraint(
                fields=("asset_type", "what", "version"),
                name="uniq_config_asset_type_what_version",
            ),
        ),
        migrations.AddConstraint(
            model_name="configurationasset",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("asset_type", "what"),
                name="uniq_active_config_asset_type_what",
            ),
        ),
    ]
