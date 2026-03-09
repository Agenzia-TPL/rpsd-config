from datetime import date

from django.db import migrations


def add_years_safe(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def backfill_contract_end_dates(apps, schema_editor):
    Contract = apps.get_model("exchange_agreement", "Contract")
    for contract in Contract.objects.filter(end_date__isnull=True).iterator():
        contract.end_date = add_years_safe(contract.start_date, 6)
        contract.save(update_fields=["end_date"])


def noop_reverse(apps, schema_editor):
    # Data migration intentionally not reversed.
    return


class Migration(migrations.Migration):
    dependencies = [
        (
            "exchange_agreement",
            "0007_remove_contract_unique_contract_version_per_pair_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(backfill_contract_end_dates, noop_reverse),
    ]
