# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0019_platform_initialization_profiles"),
        ("admin_dataset_exchange", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="NetexValidationProfileAdminProxy",
            fields=[],
            options={
                "verbose_name": "Netex validation profile",
                "verbose_name_plural": "Netex validation profiles",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.netexvalidationprofile",),
        ),
        migrations.CreateModel(
            name="SiriValidationProfileAdminProxy",
            fields=[],
            options={
                "verbose_name": "SIRI validation profile",
                "verbose_name_plural": "SIRI validation profiles",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.sirivalidationprofile",),
        ),
        migrations.CreateModel(
            name="IndicatorProfileAdminProxy",
            fields=[],
            options={
                "verbose_name": "Indicator profile",
                "verbose_name_plural": "Indicator profiles",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.indicatorprofile",),
        ),
    ]
