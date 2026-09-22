# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_agreements", "0005_operationalflowadminproxy"),
        ("exchange_agreement", "0035_contract_configuration_revisions"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContractConfigurationRevisionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Contract configuration revision",
                "verbose_name_plural": "Contract configuration revisions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.contractconfigurationrevision",),
        )
    ]
