# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0034_relational_processing_profiles"),
        ("admin_dataset_exchange", "0007_flow_catalog_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProcessingProfileVersionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Processing profile version",
                "verbose_name_plural": "Processing profile versions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.processingprofileversion",),
        ),
        migrations.CreateModel(
            name="ProcessingProfileVersionStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Processing profile version status event",
                "verbose_name_plural": "Processing profile version status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.processingprofileversionstatusevent",),
        ),
    ]
