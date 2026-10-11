# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exchange_agreement", "0042_validation_catalog_proxies")]
    operations = [
        migrations.RenameField(
            model_name="indicatorversion",
            old_name="input_contract",
            new_name="input_schema",
        ),
        migrations.RenameField(
            model_name="indicatorversion",
            old_name="output_contract",
            new_name="output_schema",
        ),
        migrations.AddField(
            model_name="indicatorversion",
            name="parameter_schema",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
