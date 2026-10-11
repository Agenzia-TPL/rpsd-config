# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Malformed schemas and contract-specific scalar values."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.parameter_schema import (
    validate_indicator_parameters,
    validate_parameter_schema,
)


class ParameterSchemaTests(SimpleTestCase):
    def schema(self, prop):
        return {
            "schema_version": 1,
            "properties": {"window": prop},
            "required": ["window"],
        }

    def test_malformed_property_definitions_are_validation_errors(self):
        for prop in (
            {"type": []},
            {"type": "integer", "enum": [True]},
            {"type": "number", "minimum": float("nan")},
            {"type": "string", "description": []},
            {"type": "integer", "minimum": 10, "maximum": 2},
        ):
            with self.subTest(prop=prop), self.assertRaises(ValidationError):
                validate_parameter_schema(self.schema(prop))

    def test_required_type_bounds_and_extra_values(self):
        schema = self.schema({"type": "integer", "minimum": 1, "maximum": 30})
        validate_indicator_parameters(schema, {"window": 10})
        for values in (
            {},
            {"window": True},
            {"window": 31},
            {"window": 10, "other": 1},
            [],
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                validate_indicator_parameters(schema, values)

    def test_non_finite_values_and_boolean_schema_version_are_rejected(self):
        with self.assertRaises(ValidationError):
            validate_indicator_parameters(
                self.schema({"type": "number"}), {"window": float("inf")}
            )
        with self.assertRaises(ValidationError):
            validate_parameter_schema({"schema_version": True})
