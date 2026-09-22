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
        ("exchange_agreement", "0030_versioned_dataset_catalog"),
    ]

    operations = [
        migrations.CreateModel(
            name="RequirementFragment",
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
                ("code", models.SlugField(max_length=96)),
                ("name", models.CharField(max_length=128)),
                ("description", models.TextField()),
                (
                    "locator_type",
                    models.CharField(
                        choices=[("xpath", "XPath"), ("table", "Table")],
                        max_length=16,
                    ),
                ),
                (
                    "result_kind",
                    models.CharField(
                        choices=[
                            ("presence", "Presence"),
                            ("scalar_values", "Scalar values"),
                        ],
                        max_length=24,
                    ),
                ),
                ("locator_definition", models.JSONField(default=dict)),
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
                    "dataset_specification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirement_fragments",
                        to="exchange_agreement.datasetspecification",
                    ),
                ),
            ],
            options={
                "verbose_name": "Requirement fragment",
                "verbose_name_plural": "Requirement fragments",
                "ordering": ["dataset_specification__code", "code"],
                "indexes": [
                    models.Index(
                        fields=["dataset_specification", "status"],
                        name="ix_fragment_spec_status",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("dataset_specification", "code"),
                        name="uniq_requirement_fragment_spec_code",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="FragmentValidationRule",
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
                    "rule_type",
                    models.CharField(
                        choices=[
                            ("exists", "Exists"),
                            ("non_empty", "Non-empty"),
                            ("all_values_in_set", "All values in set"),
                            ("contains_all_values", "Contains all values"),
                            ("set_equals", "Set equals"),
                        ],
                        max_length=32,
                    ),
                ),
                ("rule_version", models.PositiveIntegerField(default=1)),
                ("parameters", models.JSONField(blank=True, default=dict)),
                (
                    "severity",
                    models.CharField(
                        choices=[("error", "Error"), ("warning", "Warning")],
                        default="error",
                        max_length=16,
                    ),
                ),
                (
                    "requirement_fragment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="validation_rules",
                        to="exchange_agreement.requirementfragment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Fragment validation rule",
                "verbose_name_plural": "Fragment validation rules",
                "ordering": ["rule_type", "rule_version", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("requirement_fragment", "rule_type"),
                        name="uniq_fragment_validation_rule_type",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RequirementFragmentStatusEvent",
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
                        related_name="requirement_fragment_status_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requirement_fragment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="status_events",
                        to="exchange_agreement.requirementfragment",
                    ),
                ),
            ],
            options={
                "verbose_name": "Requirement fragment status event",
                "verbose_name_plural": "Requirement fragment status events",
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
