# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Closed registry rejects incomplete or mismatched rule definitions."""

import json

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.validation_registry import (
    capability_manifest,
    validate_prefect_reference,
    validate_rule_definition,
)


class ValidationRegistryTests(SimpleTestCase):
    def values(self, **overrides):
        return (
            dict(
                validation_type="xpath",
                definition="//n:DayTypeRef[not(@ref = //n:DayType/@id)]",
                language_version="3.1",
                options={"namespaces": {"n": "http://www.netex.org.uk/netex"}},
                result_contract="violating_entities",
            )
            | overrides
        )

    def test_full_xpath_with_literal_uri_and_axes(self):
        validate_rule_definition(
            **self.values(definition="//n:Line[@id='urn:test:value']/ancestor::n:Frame")
        )
        self.assertIn("xpath", [c["validation_type"] for c in capability_manifest()])

    def test_missing_namespace_and_unknown_options(self):
        for options in ({}, {"arbitrary": "python"}, {"namespaces": {"n": ""}}):
            with self.subTest(options=options), self.assertRaises(ValidationError):
                validate_rule_definition(**self.values(options=options))

    def test_unknown_type_version_and_result_contract(self):
        for value in (
            {"validation_type": "python"},
            {"language_version": "9"},
            {"result_contract": "boolean_assertion"},
            {"definition": ""},
        ):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                validate_rule_definition(**self.values(**value))

    def test_bundle_descriptor_is_data(self):
        value = dict(
            asset_code="netex",
            asset_version="1",
            entrypoint="schema.xsd",
            bundle_sha256="a" * 64,
        )
        validate_rule_definition(
            **self.values(
                validation_type="xsd_bundle",
                definition=json.dumps(value),
                language_version="1.0",
                options={},
                result_contract="structured_report",
            )
        )
        value["bundle_sha256"] = "bad"
        with self.assertRaises(ValidationError):
            validate_rule_definition(
                **self.values(
                    validation_type="xsd_bundle",
                    definition=json.dumps(value),
                    language_version="1.0",
                    options={},
                    result_contract="structured_report",
                )
            )

    def test_prefect_reference_requires_flow_and_deployment(self):
        validate_prefect_reference("validators/default")
        for reference in ("", "task", "flow/deployment/extra", "flow/ deploy"):
            with self.subTest(reference=reference), self.assertRaises(ValidationError):
                validate_prefect_reference(reference)

    def test_malformed_json_options_raise_validation_errors(self):
        for policy in ([], {}, 12, None):
            with (
                self.subTest(policy=policy),
                self.assertRaises(ValidationError) as error,
            ):
                validate_rule_definition(
                    **self.values(
                        options={
                            "namespaces": {"n": "urn:netex"},
                            "empty_context": policy,
                        }
                    )
                )
            self.assertEqual(error.exception.code, "invalid_definition_options")
        with self.assertRaises(ValidationError) as error:
            validate_rule_definition(**self.values(validation_type=[]))
        self.assertEqual(error.exception.code, "unsupported_validation_type")

    def test_legacy_exists_is_not_a_target_interpreter(self):
        with self.assertRaises(ValidationError) as error:
            validate_rule_definition(**self.values(validation_type="exists"))
        self.assertEqual(error.exception.code, "unsupported_validation_type")

    def test_stable_error_codes(self):
        for values, code in (
            ({"validation_type": "shell"}, "unsupported_validation_type"),
            ({"options": {"unexpected": True}}, "invalid_definition_options"),
        ):
            with (
                self.subTest(values=values),
                self.assertRaises(ValidationError) as error,
            ):
                validate_rule_definition(**self.values(**values))
            self.assertEqual(error.exception.code, code)

    def test_non_xml_definition_contracts_and_explicit_options(self):
        for kind, definition, options in (
            (
                "csv_expression",
                {"predicate": "required_columns", "columns": ["id", "line"]},
                {"delimiter": ";", "encoding": "utf-8", "header": True},
            ),
            (
                "spreadsheet_expression",
                {"predicate": "required_columns", "columns": ["id"]},
                {"sheet": "Journeys", "header_row": 1},
            ),
            (
                "text_expression",
                {"predicate": "matches", "pattern": "^[0-9]+$", "scope": "line"},
                {"encoding": "utf-8"},
            ),
        ):
            values = self.values(
                validation_type=kind,
                definition=json.dumps(definition),
                language_version="1",
                options=options,
            )
            validate_rule_definition(**values)
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                validate_rule_definition(**(values | {"options": {}}))
        for capability in capability_manifest():
            self.assertEqual(capability["runtime_status"], "external_not_verified")

    def test_nx005_is_kept_as_a_relational_expression(self):
        expression = (
            "//n:DayTypeAssignment/n:OperatingPeriodRef"
            "[not(@ref = //n:operatingPeriods/*/@id)]"
        )
        validate_rule_definition(**self.values(definition=expression))
        # Config stores the exact supplied expression, without narrowing targets
        # or adding a version join not present in the source requirement.
        self.assertIn("operatingPeriods/*/@id", expression)
