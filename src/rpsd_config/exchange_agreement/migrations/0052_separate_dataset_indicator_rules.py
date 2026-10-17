# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import django.db.models.deletion
from django.db import migrations, models


def separate_bindings(apps, schema_editor):
    """Preserve indicator binding identities/dimensions before removing the bridge."""
    alias = schema_editor.connection.alias
    indicators = apps.get_model("exchange_agreement", "IndicatorVersionRule")
    datasets = apps.get_model("exchange_agreement", "DatasetVersionRule")
    invalid = list(
        datasets.objects.using(alias)
        .exclude(import_policy__in=["reject_import", "warn", "indicator_only"])
        .values_list("pk", flat=True)
    )
    orphans = list(
        datasets.objects.using(alias)
        .filter(import_policy="indicator_only", indicator_bindings__isnull=True)
        .values_list("pk", flat=True)
    )
    if invalid or orphans:
        raise RuntimeError(
            f"Review dataset rule IDs before separation: invalid={invalid}, "
            f"orphan indicator_only={orphans}"
        )
    for binding in indicators.objects.using(alias).select_related(
        "dataset_version_rule"
    ):
        old = binding.dataset_version_rule
        binding.dataset_specification_id = old.dataset_specification_id
        binding.rule_version_id = old.rule_version_id
        binding.save(update_fields=["dataset_specification", "rule_version"])
    # Deletion follows removal of the protected FK in the operation sequence.


def remove_indicator_only(apps, schema_editor):
    datasets = apps.get_model("exchange_agreement", "DatasetVersionRule")
    datasets.objects.using(schema_editor.connection.alias).filter(
        failure_policy="indicator_only"
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("exchange_agreement", "0051_validation_type_catalog")]
    operations = [
        migrations.AddField(
            model_name="indicatorversionrule",
            name="dataset_specification",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="indicator_rule_bindings",
                to="exchange_agreement.datasetspecification",
            ),
        ),
        migrations.AddField(
            model_name="indicatorversionrule",
            name="rule_version",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="indicator_bindings",
                to="exchange_agreement.validationruleversion",
            ),
        ),
        migrations.RunPython(separate_bindings),
        migrations.RemoveConstraint(
            model_name="indicatorversionrule", name="uniq_indicator_version_rule"
        ),
        migrations.RemoveField(
            model_name="indicatorversionrule", name="dataset_version_rule"
        ),
        migrations.RenameField(
            model_name="datasetversionrule",
            old_name="import_policy",
            new_name="failure_policy",
        ),
        migrations.RunPython(remove_indicator_only),
        migrations.AlterField(
            model_name="datasetversionrule",
            name="failure_policy",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("reject_import", "Reject the transfer"),
                    ("warn", "Accept with dataset warning"),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="indicatorversionrule",
            name="dataset_specification",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="indicator_rule_bindings",
                to="exchange_agreement.datasetspecification",
            ),
        ),
        migrations.AlterField(
            model_name="indicatorversionrule",
            name="rule_version",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="indicator_bindings",
                to="exchange_agreement.validationruleversion",
            ),
        ),
        migrations.AddConstraint(
            model_name="indicatorversionrule",
            constraint=models.UniqueConstraint(
                fields=("indicator_version", "dataset_specification", "rule_version"),
                name="uniq_indicator_version_rule",
            ),
        ),
    ]
