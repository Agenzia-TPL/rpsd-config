# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0021_integration_grant"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="integrationgrant",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("valid_from__isnull", True))
                    | models.Q(("valid_to__isnull", True))
                    | models.Q(("valid_to__gte", models.F("valid_from")))
                ),
                name="integration_grant_valid_window",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("status", "active"),
                    ("data_category__isnull", False),
                ),
                fields=("principal", "contract", "action", "data_category"),
                name="uniq_active_integration_grant_with_category",
            ),
        ),
        migrations.AddConstraint(
            model_name="integrationgrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("status", "active"),
                    ("data_category__isnull", True),
                ),
                fields=("principal", "contract", "action"),
                name="uniq_active_integration_grant_no_category",
            ),
        ),
        migrations.AddIndex(
            model_name="integrationgrant",
            index=models.Index(
                fields=["principal", "status", "action"],
                name="ix_igr_pri_stat_act",
            ),
        ),
        migrations.AddIndex(
            model_name="integrationgrant",
            index=models.Index(
                fields=["contract", "status", "action"],
                name="ix_igr_ctr_stat_act",
            ),
        ),
        migrations.AddIndex(
            model_name="integrationgrant",
            index=models.Index(
                fields=["principal", "contract", "status"],
                name="ix_igr_pri_ctr_stat",
            ),
        ),
    ]
