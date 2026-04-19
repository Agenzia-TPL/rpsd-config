# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import uuid

import django.db.models.deletion
from django.conf import settings
from django.core.validators import RegexValidator
from django.db import migrations, models
from django.db.models.functions.datetime import Now
from django.utils.text import slugify

import rpsd_config.exchange_agreement.models


def _normalize_agency_key(raw_value: str) -> str:
    normalized = slugify((raw_value or "").strip(), allow_unicode=False)
    normalized = normalized.strip("-")
    if not normalized:
        normalized = "agency"
    if len(normalized) < 3:
        normalized = f"{normalized}-agency"
    if len(normalized) > 40:
        normalized = normalized[:40].rstrip("-")
    if len(normalized) < 3:
        normalized = (normalized + "000")[:3]
    return normalized


def backfill_agency_key(apps, schema_editor):
    Agency = apps.get_model("exchange_agreement", "Agency")
    used = set(
        Agency.objects.exclude(agency_key__isnull=True).values_list("agency_key", flat=True)
    )
    for agency in Agency.objects.all().order_by("id"):
        if agency.agency_key:
            continue
        base = _normalize_agency_key(getattr(agency, "name", ""))
        candidate = base
        suffix = 2
        while candidate in used:
            suffix_part = f"-{suffix}"
            trimmed = base[: 40 - len(suffix_part)].rstrip("-")
            if not trimmed:
                trimmed = "agency"
            candidate = f"{trimmed}{suffix_part}"
            suffix += 1
        agency.agency_key = candidate
        agency.save(update_fields=["agency_key"])
        used.add(candidate)


def forward_convert_contract_admin_invites(apps, schema_editor):
    ContractInvitation = apps.get_model("exchange_agreement", "ContractInvitation")
    ContractInvitation.objects.filter(role_to_assign="contract_admin").update(
        role_to_assign="contract_editor"
    )


def noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0016_contractpublication"),
    ]

    operations = [
        migrations.AddField(
            model_name="agency",
            name="agency_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Stable immutable key used for IAM group paths (example: atpl-milano).",
                max_length=40,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(backfill_agency_key, noop_reverse),
        migrations.AlterField(
            model_name="agency",
            name="agency_key",
            field=models.CharField(
                db_index=True,
                help_text="Stable immutable key used for IAM group paths (example: atpl-milano).",
                max_length=40,
                unique=True,
                validators=[
                    RegexValidator(
                        message="Agency key must match ^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$ (lowercase letters, digits, hyphen).",
                        regex="^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$",
                    )
                ],
            ),
        ),
        migrations.CreateModel(
            name="AgencyMembership",
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
                    "role",
                    models.CharField(
                        choices=[
                            ("agency_admin", "Agency admin"),
                            ("agency_editor", "Agency editor"),
                            ("agency_reader", "Agency reader"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="memberships",
                        to="exchange_agreement.agency",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agency_memberships_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agency_memberships",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Agency membership",
                "verbose_name_plural": "Agency memberships",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("agency", "user"), name="unique_agency_membership_user"
                    )
                ],
                "indexes": [
                    models.Index(
                        fields=["agency", "role"],
                        name="exchange_ag_agency__7c6292_idx",
                    ),
                    models.Index(fields=["user"], name="exchange_ag_user_id_0f6f1c_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="AgencyInvitation",
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
                    "token",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "email",
                    models.EmailField(
                        blank=True,
                        help_text="Optional target email. If empty, the invitation is open and can be used by the first user who accepts the token.",
                        max_length=254,
                        null=True,
                    ),
                ),
                (
                    "role_to_assign",
                    models.CharField(
                        choices=[
                            ("agency_admin", "Agency admin"),
                            ("agency_editor", "Agency editor"),
                            ("agency_reader", "Agency reader"),
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        default=rpsd_config.exchange_agreement.models._default_invitation_expiration
                    ),
                ),
                ("accepted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("accepted", "Accepted"),
                            ("expired", "Expired"),
                            ("revoked", "Revoked"),
                        ],
                        default="pending",
                        max_length=16,
                    ),
                ),
                (
                    "accepted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agency_invitations_accepted",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "agency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invitations",
                        to="exchange_agreement.agency",
                    ),
                ),
                (
                    "invited_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agency_invitations_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Agency invitation",
                "verbose_name_plural": "Agency invitations",
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("email__isnull", False), ("status", "pending")),
                        fields=("agency", "email", "role_to_assign"),
                        name="unique_pending_agency_invitation_per_email_role",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("email__isnull", True), ("status", "pending")),
                        fields=("agency", "role_to_assign"),
                        name="unique_pending_open_agency_invitation_per_role",
                    ),
                ],
                "indexes": [
                    models.Index(
                        fields=["agency", "status"],
                        name="exchange_ag_agency__d98d05_idx",
                    ),
                    models.Index(
                        fields=["email"], name="exchange_ag_email_1a96fc_idx"
                    ),
                    models.Index(
                        fields=["token"], name="exchange_ag_token_2b4a38_idx"
                    ),
                ],
            },
        ),
        migrations.AlterField(
            model_name="contractmembership",
            name="role",
            field=models.CharField(
                choices=[
                    ("contract_admin", "Contract admin"),
                    ("contract_editor", "Contract editor"),
                    ("contract_reader", "Contract reader"),
                ],
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="contractinvitation",
            name="role_to_assign",
            field=models.CharField(
                choices=[
                    ("contract_admin", "Contract admin"),
                    ("contract_editor", "Contract editor"),
                    ("contract_reader", "Contract reader"),
                ],
                max_length=32,
            ),
        ),
        migrations.RunPython(forward_convert_contract_admin_invites, noop_reverse),
        migrations.AddConstraint(
            model_name="contractinvitation",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("role_to_assign__in", ["contract_editor", "contract_reader"])
                ),
                name="contract_invitation_role_editor_or_reader_only",
            ),
        ),
    ]
