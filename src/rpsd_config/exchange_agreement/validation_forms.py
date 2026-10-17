# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared forms for atomic indicator impact and dimension replacement."""

from django import forms
from django.core.exceptions import ValidationError
from django.db import transaction

from rpsd_config.exchange_agreement.field_guidance import (
    DIMENSIONS_HELP,
    IMPACT_HELP,
    IMPORT_POLICY_HELP,
)
from rpsd_config.exchange_agreement.models import (
    DatasetVersionRule,
    IndicatorDimension,
    IndicatorVersionRule,
    IndicatorVersionRuleDimension,
)


class IndicatorRuleForm(forms.ModelForm):
    """Validate the submitted composition, then replace old dimensions atomically."""

    dimensions = forms.ModelMultipleChoiceField(
        queryset=IndicatorDimension.objects.all(),
        required=False,
        label="Dimensioni interessate",
        help_text=DIMENSIONS_HELP,
    )

    class Meta:
        model = IndicatorVersionRule
        fields = (
            "indicator_version",
            "dataset_specification",
            "rule_version",
            "impact",
            "dimensions",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "impact" in self.fields:
            self.fields["impact"].help_text = IMPACT_HELP
        if self.instance.pk and "dimensions" in self.fields:
            self.fields["dimensions"].initial = self.instance.affected_dimensions.all()

    def clean(self):
        values = super().clean()
        if "impact" in values and bool(values.get("dimensions")) != (
            values["impact"] == "dimension"
        ):
            raise ValidationError(
                "dimension richiede dimensioni; calculation non ne ammette."
            )
        return values

    def _update_errors(self, errors):
        # Model.clean checks the persisted dimensions; this form replaces them.
        # Ignore only that stale-composition error when the submitted form has
        # explicitly removed all dimensions. Save still invokes model validation
        # after removing the old links, under the owner's transaction lock.
        if (
            self.instance.pk
            and self.cleaned_data.get("impact") == "calculation"
            and "dimensions" in self.cleaned_data
            and not self.cleaned_data["dimensions"]
            and hasattr(errors, "error_dict")
        ):
            filtered = {
                key: [e for e in values if e.code != "invalid_impact_dimensions"]
                for key, values in errors.error_dict.items()
            }
            filtered = {key: values for key, values in filtered.items() if values}
            if not filtered:
                return
            errors = ValidationError(filtered)
        super()._update_errors(errors)

    def _post_clean(self):
        super()._post_clean()
        if not self.errors:
            try:
                with transaction.atomic():
                    self.instance.check_editable()
            except ValidationError as exc:
                self.add_error(None, exc)

    def save(self, commit=True):
        binding = super().save(commit=False)
        if not commit:
            return binding
        with transaction.atomic():
            binding.check_editable()
            if binding.pk:
                binding.dimension_links.all().delete()
            binding.save()
            self.save_dimensions()
        return binding

    def save_dimensions(self):
        """Complete a binding in the same transaction as its saved parent."""
        binding = self.instance
        binding.dimension_links.all().delete()
        for dimension in self.cleaned_data["dimensions"]:
            IndicatorVersionRuleDimension.objects.create(
                binding=binding, dimension=dimension
            )
        binding.validate_complete()


class DatasetRuleForm(forms.ModelForm):
    """Explain when dataset rules run and how their import policies differ."""

    class Meta:
        model = DatasetVersionRule
        fields = ("dataset_specification", "rule_version", "failure_policy")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Django removes frozen fields before constructing a readonly admin form.
        if "failure_policy" not in self.fields:
            return
        self.fields["failure_policy"].label = "Politica di import"
        self.fields["failure_policy"].choices = [
            ("reject_import", "Blocco dell’import: sempre per questo dataset"),
            ("warn", "Avviso dataset: sempre per questo dataset"),
        ]
        self.fields["failure_policy"].help_text = IMPORT_POLICY_HELP
