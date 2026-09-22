# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Guided admin forms for declarative requirement fragments."""

from django import forms
from django.core.exceptions import ValidationError

from rpsd_config.exchange_agreement.models import (
    FragmentValidationRule,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.fragment_registry import (
    RULE_ALL_VALUES_IN_SET,
    RULE_CONTAINS_ALL_VALUES,
    RULE_SET_EQUALS,
    validate_locator_definition,
    validate_rule_parameters,
)


def _lines(value: str) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


class RequirementFragmentAdminForm(forms.ModelForm):
    xpath_path = forms.CharField(required=False, label="XPath")
    xpath_namespaces = forms.CharField(
        required=False,
        label="XPath namespaces",
        help_text="One prefix=URI entry per line.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    table_resource = forms.CharField(required=False, label="Table resource")
    table_column = forms.CharField(required=False, label="Scalar column")
    table_columns = forms.CharField(
        required=False,
        label="Presence columns",
        help_text="One column per line.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = RequirementFragment
        fields = (
            "dataset_specification",
            "code",
            "name",
            "description",
            "locator_type",
            "result_kind",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        definition = self.instance.locator_definition or {}
        if self.instance.locator_type == RequirementFragment.LocatorType.XPATH:
            self.fields["xpath_path"].initial = definition.get("path", "")
            self.fields["xpath_namespaces"].initial = "\n".join(
                f"{prefix}={uri}"
                for prefix, uri in definition.get("namespaces", {}).items()
            )
        elif self.instance.locator_type == RequirementFragment.LocatorType.TABLE:
            self.fields["table_resource"].initial = definition.get("resource", "")
            self.fields["table_column"].initial = definition.get("column", "")
            self.fields["table_columns"].initial = "\n".join(
                definition.get("columns", [])
            )
        if (
            self.instance.pk
            and self.instance.status != RequirementFragment.Status.DRAFT
        ):
            for field in self.fields.values():
                field.disabled = True

    def clean(self):
        cleaned = super().clean()
        locator_type = cleaned.get("locator_type")
        result_kind = cleaned.get("result_kind")
        if locator_type == RequirementFragment.LocatorType.XPATH:
            namespaces = {}
            for line in _lines(cleaned.get("xpath_namespaces", "")):
                if "=" not in line:
                    self.add_error(
                        "xpath_namespaces",
                        "Each namespace must use the prefix=URI form.",
                    )
                    continue
                prefix, uri = line.split("=", 1)
                namespaces[prefix.strip()] = uri.strip()
            definition = {
                "path": cleaned.get("xpath_path", ""),
                "namespaces": namespaces,
            }
        else:
            definition = {"resource": cleaned.get("table_resource", "")}
            if result_kind == RequirementFragment.ResultKind.SCALAR_VALUES:
                definition["column"] = cleaned.get("table_column", "")
            else:
                columns = _lines(cleaned.get("table_columns", ""))
                if columns:
                    definition["columns"] = columns
        try:
            self.instance.locator_definition = validate_locator_definition(
                locator_type,
                result_kind,
                definition,
            )
        except ValidationError as exc:
            self.add_error(None, exc)
        return cleaned


class FragmentValidationRuleAdminForm(forms.ModelForm):
    trim = forms.BooleanField(required=False, initial=True)
    case_sensitive = forms.BooleanField(required=False, initial=True)
    values = forms.CharField(
        required=False,
        help_text=(
            "One allowed, required or expected value per line, according to rule type."
        ),
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    class Meta:
        model = FragmentValidationRule
        fields = (
            "rule_type",
            "rule_version",
            "severity",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parameters = self.instance.parameters or {}
        self.fields["trim"].initial = parameters.get("trim", True)
        self.fields["case_sensitive"].initial = parameters.get("case_sensitive", True)
        for key in ("allowed_values", "required_values", "expected_values"):
            if key in parameters:
                self.fields["values"].initial = "\n".join(parameters[key])
                break

    def clean(self):
        cleaned = super().clean()
        rule_type = cleaned.get("rule_type")
        parameters = {}
        if rule_type == FragmentValidationRule.RuleType.NON_EMPTY:
            parameters["trim"] = cleaned.get("trim", False)
        elif rule_type in {
            RULE_ALL_VALUES_IN_SET,
            RULE_CONTAINS_ALL_VALUES,
            RULE_SET_EQUALS,
        }:
            values_key = {
                RULE_ALL_VALUES_IN_SET: "allowed_values",
                RULE_CONTAINS_ALL_VALUES: "required_values",
                RULE_SET_EQUALS: "expected_values",
            }[rule_type]
            parameters = {
                values_key: _lines(cleaned.get("values", "")),
                "case_sensitive": cleaned.get("case_sensitive", False),
                "trim": cleaned.get("trim", False),
            }
        fragment = self.instance.requirement_fragment
        if fragment is not None:
            try:
                self.instance.parameters = validate_rule_parameters(
                    rule_type,
                    cleaned.get("rule_version"),
                    fragment.result_kind,
                    parameters,
                )
            except ValidationError as exc:
                self.add_error(None, exc)
        return cleaned
