# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0033_versioned_flow_catalog"),
        ("admin_dataset_exchange", "0006_indicator_catalog_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="InputFlowVersionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Input flow version",
                "verbose_name_plural": "Input flow versions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.inputflowversion",),
        ),
        migrations.CreateModel(
            name="InputFlowVersionStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Input flow version status event",
                "verbose_name_plural": "Input flow version status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.inputflowversionstatusevent",),
        ),
        migrations.CreateModel(
            name="OrchestrationFlowVersionAdminProxy",
            fields=[],
            options={
                "verbose_name": "Orchestration flow version",
                "verbose_name_plural": "Orchestration flow versions",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.orchestrationflowversion",),
        ),
        migrations.CreateModel(
            name="OrchestrationFlowVersionStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Orchestration flow version status event",
                "verbose_name_plural": "Orchestration flow version status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.orchestrationflowversionstatusevent",),
        ),
    ]
