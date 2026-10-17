# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared guided forms for admin and contractual evaluation pages."""

from django import forms
from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.models import (
    IndicatorDimension,
    IndicatorEvaluationThreshold,
    IndicatorPenalty,
)
from rpsd_config.exchange_agreement.services.evaluation_schema import metric_catalog
from rpsd_config.exchange_agreement.services.indicator_evaluations import (
    indicator_version,
    period_context,
    validate_dimensions,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
)


class EvaluationFormMixin:
    "Filter every relational choice to the owner; model validation is authoritative."

    def __init__(self, *args, owner=None, **kwargs):
        if owner is not None and kwargs.get("instance") is None:
            kwargs["instance"] = self._meta.model(contract_revision_indicator=owner)
        super().__init__(*args, **kwargs)
        from rpsd_config.exchange_agreement.field_guidance import field_guide

        for name, field in self.fields.items():
            info = field_guide(self._meta.model, name)
            if info:
                field.label, field.help_text = info.label, info.help
        owner = owner or getattr(self.instance, "contract_revision_indicator", None)
        self.owner = owner
        if owner is None:
            return
        self.instance.contract_revision_indicator = owner
        _, version = indicator_version(self.instance)
        metrics = metric_catalog(version)
        codes = set().union(*(set(m["dimensions"]) for m in metrics.values()))
        if "group_by_dimensions" in self.fields:
            self.fields[
                "group_by_dimensions"
            ].queryset = IndicatorDimension.objects.filter(code__in=codes)
        metric_field = (
            "quantity_metric_code"
            if issubclass(self._meta.model, IndicatorPenalty)
            else "metric_code"
        )
        if metric_field not in self.fields:
            return
        self.fields[metric_field] = forms.ChoiceField(
            choices=[
                ("", "---------"),
                *(
                    (code, f"{code} · {m['unit']} · {m['grain']}")
                    for code, m in metrics.items()
                ),
            ],
            required=False,
            label=self.fields[metric_field].label,
            help_text=(
                "Output dell'esatta versione indicatore; unità e "
                "grana non sono modificabili qui."
            ),
        )
        if "activation_threshold" in self.fields:
            self.fields[
                "activation_threshold"
            ].queryset = owner.evaluation_thresholds.all()
        for name in ("period_start_date", "period_end_date"):
            self.fields[name].widget = forms.DateInput(
                attrs={"type": "date"}, format="%Y-%m-%d"
            )
        if (
            self.instance.pk
            and self.instance.contract_revision_indicator.revision.status != "draft"
        ):
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        values = super().clean()
        for name in ("external_parameter_schema", "external_parameters"):
            if name in self.fields and name in values and values[name] is None:
                values[name] = {}
        if self.owner is None:
            raise ValidationError("Choose a revision indicator first.")
        if "group_by_dimensions" in values:
            # Use bound field values, not stale instance attributes, for M:N validation.
            for name, value in values.items():
                if name != "group_by_dimensions":
                    setattr(self.instance, name, value)
            self.instance._pending_dimensions = [
                d.code for d in values["group_by_dimensions"]
            ]
            validate_dimensions(self.instance, self.instance._pending_dimensions)
        return values

    def context_preview(self):
        try:
            return period_context(self.instance, complete=False)
        except ValidationError as exc:
            return {"error": " ".join(exc.messages)}


class EvaluationThresholdForm(EvaluationFormMixin, forms.ModelForm):
    class Meta:
        model = IndicatorEvaluationThreshold
        exclude = ("contract_revision_indicator", "created_at", "updated_at")


class IndicatorPenaltyForm(EvaluationFormMixin, forms.ModelForm):
    class Meta:
        model = IndicatorPenalty
        exclude = ("contract_revision_indicator", "created_at", "updated_at")


class IndicatorParametersForm(forms.Form):
    """One guided input per declared parameter, including typed JSON lists."""

    def __init__(self, *args, owner, **kwargs):
        super().__init__(*args, **kwargs)
        self.owner = owner
        self.schema = owner.processing_profile_indicator_version.indicator_version.parameter_schema
        if not self.schema:
            self.fields["values"] = forms.JSONField(
                required=False,
                initial=owner.parameters,
                label="Parametri JSON",
                help_text=(
                    "Versione senza schema tipizzato: conserva i valori "
                    "precedenti; nessuna interpretazione automatica."
                ),
            )
        for name, spec in self.schema.get("properties", {}).items():
            required = name in self.schema.get("required", [])
            common = {
                "required": required,
                "label": name,
                "initial": owner.parameters.get(name),
                "help_text": spec.get("description", ""),
            }
            if spec["type"] == "array":
                common["help_text"] += (
                    ' Lista JSON, ad esempio ["2", "3"]. '
                    + spec.get("reference_namespace", "")
                )
                field = forms.JSONField(**common)
            elif "enum" in spec:
                field = forms.TypedChoiceField(
                    choices=[(v, str(v)) for v in spec["enum"]],
                    coerce=type(spec["enum"][0]),
                    **common,
                )
            elif spec["type"] == "boolean":
                field = forms.TypedChoiceField(
                    choices=[("true", "Sì"), ("false", "No")],
                    coerce=lambda v: v == "true",
                    **common,
                )
            elif spec["type"] == "integer":
                field = forms.IntegerField(
                    min_value=spec.get("minimum"),
                    max_value=spec.get("maximum"),
                    **common,
                )
            elif spec["type"] == "number":
                # Business JSON uses deterministic integers or decimal strings.
                field = forms.DecimalField(
                    min_value=spec.get("minimum"),
                    max_value=spec.get("maximum"),
                    **common,
                )
            else:
                field = forms.CharField(**common)
            self.fields[name] = field

    def clean(self):
        values = super().clean()
        if not self.schema:
            values = values.get("values") or {}
            if not isinstance(values, dict):
                raise ValidationError("I parametri devono essere un oggetto JSON.")
        values = {k: v for k, v in values.items() if v is not None and v != ""}
        if self.schema.get("allow_extra"):
            values = {
                **{
                    k: v
                    for k, v in self.owner.parameters.items()
                    if k not in self.schema.get("properties", {})
                },
                **values,
            }
        from decimal import Decimal

        values = {
            k: (
                str(v)
                if self.schema.get("schema_version") == 2
                else int(v)
                if v == int(v)
                else v
            )
            if isinstance(v, Decimal)
            else v
            for k, v in values.items()
        }
        validate_indicator_parameters(self.schema, values)
        return values
