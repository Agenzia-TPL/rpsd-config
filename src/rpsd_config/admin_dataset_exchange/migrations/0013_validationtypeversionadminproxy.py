# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_dataset_exchange", "0012_delete_indicatorprofileadminproxy"),
        ("exchange_agreement", "0051_validation_type_catalog"),
    ]
    operations = [
        migrations.CreateModel(
            name="ValidationTypeVersionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Tipo e versione del linguaggio",
                "verbose_name_plural": "Tipi e versioni dei linguaggi",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.validationtypeversion",),
        )
    ]
