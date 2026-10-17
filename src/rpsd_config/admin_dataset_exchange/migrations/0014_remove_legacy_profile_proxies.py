# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("admin_dataset_exchange", "0013_validationtypeversionadminproxy")]
    operations = [
        migrations.DeleteModel(name="NetexValidationProfileAdminProxy"),
        migrations.DeleteModel(name="SiriValidationProfileAdminProxy"),
    ]
