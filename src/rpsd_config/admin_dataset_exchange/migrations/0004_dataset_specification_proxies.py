# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0030_versioned_dataset_catalog"),
        ("admin_dataset_exchange", "0003_configuration_asset_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="DatasetSpecificationAdminProxy",
            fields=[],
            options={
                "verbose_name": "Dataset specification",
                "verbose_name_plural": "Dataset specifications",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.datasetspecification",),
        ),
        migrations.CreateModel(
            name="DatasetSpecificationStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Dataset specification status event",
                "verbose_name_plural": "Dataset specification status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.datasetspecificationstatusevent",),
        ),
    ]
