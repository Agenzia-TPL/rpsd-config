# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0034_relational_processing_profiles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthorityMembership",
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
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "authority",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="exchange_agreement.authority",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="authority_memberships_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="authority_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Authority membership",
                "verbose_name_plural": "Authority memberships",
                "ordering": ["authority__name", "user__username"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("authority", "user"),
                        name="unique_authority_membership_user",
                    )
                ],
            },
        ),
        migrations.AddField(
            model_name="contract",
            name="governing_authority",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Governing authority with read-only visibility of the contract."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contracts",
                to="exchange_agreement.authority",
            ),
        ),
        migrations.AddField(
            model_name="contractindicator",
            name="logical_indicator",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Stable target-model indicator. The legacy indicator definition "
                    "is retained temporarily for API v1 compatibility."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="contract_links",
                to="exchange_agreement.indicator",
            ),
        ),
        migrations.AddConstraint(
            model_name="contractindicator",
            constraint=models.UniqueConstraint(
                condition=models.Q(logical_indicator__isnull=False),
                fields=("contract", "logical_indicator"),
                name="unique_contract_logical_indicator",
            ),
        ),
        migrations.CreateModel(
            name="ContractConfigurationRevision",
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
                ("revision_number", models.PositiveIntegerField()),
                ("code", models.CharField(max_length=128, unique=True)),
                ("valid_from", models.DateField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("approved", "Approved"),
                            ("withdrawn", "Withdrawn"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("change_reason", models.TextField()),
                (
                    "snapshot_schema_version",
                    models.CharField(default="canonical-json-v1", max_length=32),
                ),
                ("configuration_snapshot", models.JSONField(blank=True, default=dict)),
                ("snapshot_checksum", models.CharField(blank=True, max_length=71)),
                ("approved_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("withdrawn_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contract_configuration_revisions_approved",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "contract",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="configuration_revisions",
                        to="exchange_agreement.contract",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contract_configuration_revisions_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "processing_profile_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contract_revisions",
                        to="exchange_agreement.processingprofileversion",
                    ),
                ),
                (
                    "replaces_revision",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="replacement_revisions",
                        to="exchange_agreement.contractconfigurationrevision",
                    ),
                ),
                (
                    "withdrawn_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contract_configuration_revisions_withdrawn",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Contract configuration revision",
                "verbose_name_plural": "Contract configuration revisions",
                "ordering": ["contract__contract_code", "valid_from", "revision_number"],
                "indexes": [
                    models.Index(
                        fields=["contract", "status", "valid_from"],
                        name="ix_contract_rev_resolution",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("contract", "revision_number"),
                        name="unique_contract_revision_number",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(status="approved"),
                        fields=("contract", "valid_from"),
                        name="unique_approved_contract_revision_date",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ContractIndicatorConfiguration",
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
                ("thresholds", models.JSONField(blank=True, default=dict)),
                ("aggregation", models.JSONField(blank=True, default=dict)),
                ("penalties", models.JSONField(blank=True, default=dict)),
                ("parameters", models.JSONField(blank=True, default=dict)),
                (
                    "contract_indicator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revision_configurations",
                        to="exchange_agreement.contractindicator",
                    ),
                ),
                (
                    "processing_profile_indicator_version",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contract_indicator_configurations",
                        to="exchange_agreement.processingprofileindicatorversion",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="indicator_configurations",
                        to="exchange_agreement.contractconfigurationrevision",
                    ),
                ),
            ],
            options={
                "verbose_name": "Contract indicator configuration",
                "verbose_name_plural": "Contract indicator configurations",
                "ordering": ["contract_indicator__logical_indicator__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("revision", "contract_indicator"),
                        name="unique_revision_contract_indicator",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ContractInputSelection",
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
                    "processing_profile_input_flow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contract_input_selections",
                        to="exchange_agreement.processingprofileinputflow",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="input_selections",
                        to="exchange_agreement.contractconfigurationrevision",
                    ),
                ),
            ],
            options={
                "verbose_name": "Contract input selection",
                "verbose_name_plural": "Contract input selections",
                "ordering": ["processing_profile_input_flow__dataset__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("revision", "processing_profile_input_flow"),
                        name="unique_contract_revision_input",
                    )
                ],
            },
        ),
    ]
