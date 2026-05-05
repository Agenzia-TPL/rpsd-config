# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


def scope_existing_lots_by_contract_agency(apps, schema_editor):
    Lot = apps.get_model("exchange_agreement", "Lot")
    Contract = apps.get_model("exchange_agreement", "Contract")

    for lot in Lot.objects.order_by("id"):
        agency_ids = list(
            Contract.objects.filter(lot_id=lot.id)
            .order_by("client_agency_id")
            .values_list("client_agency_id", flat=True)
            .distinct()
        )
        if not agency_ids:
            continue

        lot.agency_id = agency_ids[0]
        lot.save(update_fields=["agency"])

        for agency_id in agency_ids[1:]:
            agency_lot = Lot.objects.create(
                agency_id=agency_id,
                short_description=lot.short_description,
                description=lot.description,
            )
            Contract.objects.filter(
                lot_id=lot.id,
                client_agency_id=agency_id,
            ).update(lot_id=agency_lot.id)


class Migration(migrations.Migration):

    dependencies = [
        ("exchange_agreement", "0025_lot_short_description_required_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="lot",
            name="agency",
            field=models.ForeignKey(
                blank=True,
                help_text="Agency that owns this service lot.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="lots",
                to="exchange_agreement.agency",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="lot",
            name="unique_lot_short_description_ci",
        ),
        migrations.RunPython(
            scope_existing_lots_by_contract_agency,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="lot",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("short_description"),
                "agency",
                name="unique_lot_short_description_per_agency_ci",
            ),
        ),
    ]
