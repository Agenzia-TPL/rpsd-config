# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("exchange_agreement", "0052_separate_dataset_indicator_rules")]
    operations = [
        migrations.AddField(
            model_name="processingprofileversion",
            name="indicator_versions",
            field=models.ManyToManyField(
                blank=True,
                related_name="allowing_profile_versions",
                through="exchange_agreement.ProcessingProfileIndicatorVersion",
                through_fields=("processing_profile_version", "indicator_version"),
                to="exchange_agreement.indicatorversion",
            ),
        ),
        migrations.AddField(
            model_name="indicatorversion",
            name="input_specifications",
            field=models.ManyToManyField(
                blank=True,
                related_name="requiring_indicator_versions",
                through="exchange_agreement.IndicatorVersionInput",
                through_fields=("indicator_version", "dataset_specification"),
                to="exchange_agreement.datasetspecification",
            ),
        ),
        migrations.AddField(
            model_name="indicatorversion",
            name="prerequisites",
            field=models.ManyToManyField(
                blank=True,
                related_name="dependent_versions",
                symmetrical=False,
                through="exchange_agreement.IndicatorVersionDependency",
                through_fields=("dependent", "prerequisite"),
                to="exchange_agreement.indicatorversion",
            ),
        ),
        migrations.AddField(
            model_name="processingprofileversion",
            name="input_flow_versions",
            field=models.ManyToManyField(
                blank=True,
                related_name="using_profile_versions",
                through="exchange_agreement.ProcessingProfileInputFlow",
                through_fields=("processing_profile_version", "input_flow_version"),
                to="exchange_agreement.inputflowversion",
            ),
        ),
    ]
