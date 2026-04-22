# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0023_integration_principal_secret_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="integrationgrant",
            name="uniq_active_integration_grant_with_category",
        ),
        migrations.RemoveConstraint(
            model_name="integrationgrant",
            name="uniq_active_integration_grant_no_category",
        ),
        migrations.RenameIndex(
            model_name="integrationprincipal",
            new_name="exchange_ag_company_ec5e2b_idx",
            old_name="exchange_ag_company_4e66f1_idx",
        ),
        migrations.RenameIndex(
            model_name="integrationprincipal",
            new_name="exchange_ag_company_09bbf6_idx",
            old_name="exchange_ag_company_2505ac_idx",
        ),
        migrations.AddConstraint(
            model_name="integrationgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("data_category__isnull", False), ("status", "active")),
                fields=("principal", "contract", "action", "data_category"),
                name="uniq_active_integration_grant_with_category",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("data_category__isnull", True), ("status", "active")),
                fields=("principal", "contract", "action"),
                name="uniq_active_integration_grant_no_category",
            ),
        ),
    ]
