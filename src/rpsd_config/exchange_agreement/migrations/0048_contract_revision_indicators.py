# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Replace contract-level indicator identities with revision-owned selections."""

from django.db import migrations, models
from django.db.models import Count, F


def audit_selections(apps, schema_editor):
    """Refuse inconsistent compositions before dropping their redundant link."""
    selections = apps.get_model(
        "exchange_agreement", "ContractIndicatorConfiguration"
    ).objects.using(schema_editor.connection.alias)
    invalid = selections.exclude(
        contract_indicator__contract_id=F("revision__contract_id"),
        contract_indicator__logical_indicator_id=F(
            "processing_profile_indicator_version__indicator_version__indicator_id"
        ),
        processing_profile_indicator_version__processing_profile_version_id=F(
            "revision__processing_profile_version_id"
        ),
    )
    duplicate = (
        selections.values(
            "revision_id",
            "processing_profile_indicator_version__indicator_version__indicator_id",
        )
        .annotate(count=Count("pk"))
        .filter(count__gt=1)
    )
    if invalid.exists() or duplicate.exists():
        raise RuntimeError(
            "Contract revision indicator audit failed: inconsistent or duplicate "
            "selections. Repair the composition before migration 0048."
        )


def rename_indicator_permissions(apps, schema_editor):
    """Preserve existing Django permission grants across the model rename."""
    permissions = apps.get_model("auth", "Permission").objects.using(
        schema_editor.connection.alias
    )
    for action in ("add", "change", "delete", "view"):
        permissions.filter(
            content_type__app_label="exchange_agreement",
            content_type__model__in=(
                "contractindicatorconfiguration",
                "contractrevisionindicator",
            ),
            codename=f"{action}_contractindicatorconfiguration",
        ).update(
            codename=f"{action}_contractrevisionindicator",
            name=f"Can {action} indicatore della revisione",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        (
            "exchange_agreement",
            "0047_remove_indicatorprofile_configuration_asset_and_more",
        ),
        ("admin_agreements", "0008_delete_contractindicatoradminproxy"),
    ]

    operations = [
        migrations.RunPython(audit_selections, migrations.RunPython.noop),
        migrations.RenameModel(
            old_name="ContractIndicatorConfiguration",
            new_name="ContractRevisionIndicator",
        ),
        migrations.RunPython(rename_indicator_permissions, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="contractrevisionindicator",
            name="unique_revision_contract_indicator",
        ),
        migrations.AlterModelOptions(
            name="contractrevisionindicator",
            options={
                "ordering": [
                    "processing_profile_indicator_version__indicator_version__indicator__code"
                ],
                "verbose_name": "Indicatore della revisione",
                "verbose_name_plural": "Indicatori della revisione",
            },
        ),
        migrations.RemoveField(
            model_name="contractrevisionindicator", name="contract_indicator"
        ),
        migrations.AddConstraint(
            model_name="contractrevisionindicator",
            constraint=models.UniqueConstraint(
                fields=("revision", "processing_profile_indicator_version"),
                name="unique_revision_profile_indicator",
            ),
        ),
        migrations.DeleteModel(name="ContractIndicator"),
    ]
