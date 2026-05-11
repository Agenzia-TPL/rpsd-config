# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0029_configuration_assets"),
        ("admin_dataset_exchange", "0002_platform_initialization_profile_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="ConfigurationAssetAdminProxy",
            fields=[],
            options={
                "verbose_name": "Configuration asset",
                "verbose_name_plural": "Configuration assets",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.configurationasset",),
        ),
        migrations.CreateModel(
            name="ConfigurationAssetEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Configuration asset event",
                "verbose_name_plural": "Configuration asset events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.configurationassetevent",),
        ),
    ]
