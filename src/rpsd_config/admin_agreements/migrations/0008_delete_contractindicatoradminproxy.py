# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Remove the obsolete contract-level indicator admin identity."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_agreements", "0007_delete_flowprofileadminproxy_and_more"),
        (
            "exchange_agreement",
            "0047_remove_indicatorprofile_configuration_asset_and_more",
        ),
    ]

    # Depend on the revision baseline, not 0047: forcing the core cutover
    # first would leave historical admin proxies without their bases on a
    # clean database. The final core migration depends on this proxy removal.
    operations = [migrations.DeleteModel(name="ContractIndicatorAdminProxy")]
