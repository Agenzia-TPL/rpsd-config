# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.core.validators
import django.db.models.functions.text
from django.db import migrations, models
from django.utils.text import slugify


def _normalize_lot_code(value, fallback):
    code = slugify((value or "").strip(), allow_unicode=False).upper().strip("-")
    if not code:
        code = fallback
    return code[:64].strip("-") or fallback


def backfill_lot_short_descriptions(apps, schema_editor):
    Lot = apps.get_model("exchange_agreement", "Lot")
    used_codes = set()

    for lot in Lot.objects.order_by("id"):
        base_code = _normalize_lot_code(
            lot.short_description,
            fallback=f"LOT-{lot.id}",
        )
        candidate = base_code
        if candidate.lower() in used_codes:
            suffix = f"-{lot.id}"
            candidate = f"{base_code[:64 - len(suffix)]}{suffix}".strip("-")
        while candidate.lower() in used_codes:
            suffix = f"-{lot.id}"
            candidate = f"{candidate[:64 - len(suffix)]}{suffix}".strip("-")

        lot.short_description = candidate
        lot.save(update_fields=["short_description"])
        used_codes.add(candidate.lower())


class Migration(migrations.Migration):

    dependencies = [
        (
            "exchange_agreement",
            "0024_remove_integrationgrant_uniq_active_integration_grant_with_category_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_lot_short_descriptions,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="lot",
            name="short_description",
            field=models.CharField(
                db_index=True,
                help_text="Stable lot code used in business identifiers.",
                max_length=64,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Lot code must contain only uppercase letters, digits "
                            "and hyphens, and cannot start or end with a hyphen."
                        ),
                        regex="^[A-Z0-9](?:[A-Z0-9-]{0,62}[A-Z0-9])?$",
                    )
                ],
            ),
        ),
        migrations.AddConstraint(
            model_name="lot",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("short_description"),
                name="unique_lot_short_description_ci",
            ),
        ),
    ]
