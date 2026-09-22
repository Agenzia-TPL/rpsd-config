# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "exchange_agreement",
            "0036_contractconfigurationrevision_withdrawal_reason_and_more",
        ),
    ]

    operations = [
        # The temporary nullable state lets the FK be added without inventing a
        # revision for legacy publications. Development environments must use
        # the documented config-only reset before applying the final constraint.
        migrations.AddField(
            model_name="contractpublication",
            name="configuration_revision",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="publications",
                to="exchange_agreement.contractconfigurationrevision",
            ),
        ),
        migrations.AlterField(
            model_name="contractpublication",
            name="snapshot_checksum",
            field=models.CharField(max_length=71),
        ),
        migrations.AlterField(
            model_name="contractpublication",
            name="snapshot_schema_version",
            field=models.CharField(default="canonical-json-v1", max_length=32),
        ),
        migrations.AlterField(
            model_name="contractpublication",
            name="configuration_revision",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="publications",
                to="exchange_agreement.contractconfigurationrevision",
            ),
        ),
    ]
