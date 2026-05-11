# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def backfill_agency_membership_sync_fields(apps, schema_editor):
    AgencyMembership = apps.get_model("exchange_agreement", "AgencyMembership")

    role_suffix_by_role = {
        "agency_admin": "admin",
        "agency_editor": "editor",
        "agency_reader": "reader",
    }

    for membership in AgencyMembership.objects.select_related("agency").iterator():
        suffix = role_suffix_by_role.get(membership.role, "")
        if suffix and getattr(membership, "agency_id", None):
            group_path = f"/rpsd/{membership.agency.agency_key}/{suffix}"
        else:
            group_path = ""
        membership.status = "active"
        membership.source = "manual_migration"
        membership.keycloak_group_path = group_path
        membership.save(
            update_fields=["status", "source", "keycloak_group_path", "updated_at"]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0026_lot_agency_scope"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="agencymembership",
            name="keycloak_group_path",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="keycloak_user_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="last_sync_error",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="last_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="source",
            field=models.CharField(
                choices=[
                    ("invitation", "Invitation"),
                    ("bootstrap", "Bootstrap"),
                    ("keycloak_sync", "Keycloak sync"),
                    ("admin_action", "Admin action"),
                    ("manual_migration", "Manual migration"),
                ],
                default="manual_migration",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="status",
            field=models.CharField(
                choices=[
                    ("active", "Active"),
                    ("revoked", "Revoked"),
                    ("sync_error", "Sync error"),
                ],
                default="active",
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="revoked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="agency_memberships_revoked",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="agencymembership",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="agency_memberships_updated",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            backfill_agency_membership_sync_fields,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddIndex(
            model_name="agencymembership",
            index=models.Index(
                fields=["agency", "status"],
                name="exchange_ag_agency__53b6e5_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="agencymembership",
            index=models.Index(
                fields=["user", "status"],
                name="exchange_ag_user_id_4df5d1_idx",
            ),
        ),
    ]
