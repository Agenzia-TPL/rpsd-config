# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0032_indicator_version_catalog"),
        ("admin_dataset_exchange", "0005_requirement_fragment_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="IndicatorAdminProxy",
            fields=[],
            options={
                "verbose_name": "Indicator",
                "verbose_name_plural": "Indicators",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.indicator",),
        ),
        migrations.CreateModel(
            name="IndicatorVersionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Indicator version",
                "verbose_name_plural": "Indicator versions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.indicatorversion",),
        ),
        migrations.CreateModel(
            name="IndicatorVersionStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Indicator version status event",
                "verbose_name_plural": "Indicator version status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.indicatorversionstatusevent",),
        ),
    ]
