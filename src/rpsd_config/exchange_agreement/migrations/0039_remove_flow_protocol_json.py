# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0038_remove_contract_flow_profile_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="inputflowversion",
            name="compatibility",
        ),
        migrations.RemoveField(
            model_name="inputflowversion",
            name="invocation_contract",
        ),
        migrations.RemoveField(
            model_name="orchestrationflowversion",
            name="invocation_contract",
        ),
    ]
