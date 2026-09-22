# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_stakeholders", "0001_initial"),
        ("exchange_agreement", "0035_contract_configuration_revisions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuthorityMembershipAdminProxy",
            fields=[],
            options={
                "verbose_name": "Authority membership",
                "verbose_name_plural": "Authority memberships",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.authoritymembership",),
        )
    ]
