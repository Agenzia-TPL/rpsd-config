from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin_agreements", "0009_indicatorevaluationthresholdadminproxy_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContractRevisionIndicatorAdminProxy",
            fields=[],
            options={
                "verbose_name": "Indicatore della revisione contrattuale",
                "verbose_name_plural": "Indicatori delle revisioni contrattuali",
                "proxy": True,
                "indexes": [],
                "constraints": [],
            },
            bases=("exchange_agreement.contractrevisionindicator",),
        ),
    ]
