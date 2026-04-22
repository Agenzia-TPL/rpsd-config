# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0022_integration_grant_constraints_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="integrationprincipal",
            name="client_secret_ciphertext",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="integrationprincipal",
            name="client_secret_key_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="integrationprincipal",
            name="client_secret_updated_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
