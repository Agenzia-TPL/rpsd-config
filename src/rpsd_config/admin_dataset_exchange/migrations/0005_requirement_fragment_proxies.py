# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("exchange_agreement", "0031_requirement_fragment_catalog"),
        ("admin_dataset_exchange", "0004_dataset_specification_proxies"),
    ]

    operations = [
        migrations.CreateModel(
            name="RequirementFragmentAdminProxy",
            fields=[],
            options={
                "verbose_name": "Requirement fragment",
                "verbose_name_plural": "Requirement fragments",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.requirementfragment",),
        ),
        migrations.CreateModel(
            name="RequirementFragmentStatusEventAdminProxy",
            fields=[],
            options={
                "verbose_name": "Requirement fragment status event",
                "verbose_name_plural": "Requirement fragment status events",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.requirementfragmentstatusevent",),
        ),
    ]
