# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Parameter list compatibility and output metric contracts (032)."""

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.indicator_registry import (
    validate_technical_contract,
)
from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
    validate_parameter_schema,
)


class EvaluationSchemaTests(SimpleTestCase):
    def setUp(self):
        self.schema = {
            "schema_version": 2,
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {"type": "string"},
                    "min_items": 1,
                    "max_items": 3,
                    "unique_items": True,
                    "reference_namespace": "netex:Line/@id",
                }
            },
            "required": ["lines"],
        }

    def test_lists_preserve_scalar_contracts_and_validate_values(self):
        validate_indicator_parameters(self.schema, {"lines": ["2", "3", "4"]})
        for value in ([], ["2", "2"], [2], "2,3", ["1", "2", "3", "4"]):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_indicator_parameters(self.schema, {"lines": value})
        validate_indicator_parameters(
            {"schema_version": 1, "properties": {"x": {"type": "integer"}}}, {"x": 2}
        )
        bad = deepcopy(self.schema)
        bad["schema_version"] = 1
        with self.assertRaises(ValidationError):
            validate_parameter_schema(bad)

    def test_nested_and_boolean_list_bounds_are_rejected(self):
        for change in (
            {"min_items": True},
            {"items": {"type": "object"}},
            {"items": {"type": "array"}},
        ):
            bad = deepcopy(self.schema)
            bad["properties"]["lines"].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_parameter_schema(bad)

    def test_output_metrics_are_closed_and_distinct_counts_need_a_key(self):
        contract = {
            "schema_version": 2,
            "identifier": "journeys-output",
            "metrics": [
                {
                    "code": "missed",
                    "type": "integer",
                    "unit": "journeys",
                    "grain": "line-day",
                    "dimensions": ["line"],
                    "aggregations": ["sum"],
                }
            ],
        }
        self.assertEqual(
            validate_technical_contract(contract, field_name="output_schema")[
                "metrics"
            ],
            contract["metrics"],
        )
        bad = deepcopy(contract)
        bad["metrics"][0]["aggregations"] = ["count_distinct"]
        with self.assertRaises(ValidationError):
            validate_technical_contract(bad, field_name="output_schema")
        with self.assertRaises(ValidationError):
            validate_technical_contract(contract, field_name="input_schema")

    def test_v2_numbers_can_use_finite_decimal_strings_without_float_serialization(
        self,
    ):
        schema = {
            "schema_version": 2,
            "properties": {
                "weight": {"type": "number", "minimum": "0.1", "maximum": "2.0"}
            },
        }
        validate_indicator_parameters(schema, {"weight": "1.234567"})
        for value in ("NaN", "Infinity", "-1", True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_indicator_parameters(schema, {"weight": value})
