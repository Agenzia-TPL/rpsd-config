# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared contextual form for a version-owned analytical dimension."""

from copy import deepcopy

from django import forms

from rpsd_config.exchange_agreement.models import IndicatorVersionDimension


class IndicatorDimensionForm(forms.ModelForm):
    copy_catalog_values = forms.BooleanField(
        required=False,
        initial=True,
        label="Copia ora i valori predefiniti",
        help_text=(
            "Copia una volta dal catalogo; modifiche successive al default "
            "non si propagano alla versione."
        ),
    )

    class Meta:
        model = IndicatorVersionDimension
        fields = (
            "dimension",
            "is_carried",
            "is_monitoring",
            "is_contractual",
            "allowed_values",
        )

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        if owner is not None:
            self.instance.indicator_version = owner
        if self.instance.pk:
            self.fields["copy_catalog_values"].initial = False

    def clean(self):
        values = super().clean()
        if values.get("copy_catalog_values") and values.get("dimension"):
            values["allowed_values"] = deepcopy(values["dimension"].allowed_values)
        return values
