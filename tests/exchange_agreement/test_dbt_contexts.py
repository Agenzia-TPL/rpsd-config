# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Document checks do not interpret test instructions or depend on datasets."""

import json

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from rpsd_config.exchange_agreement.services.dbt_contexts import load_dbt_context
from rpsd_config.exchange_agreement.services.validation_registry import (
    capability_manifest,
    validate_rule_definition,
)


def context_document():
    return {
        "schema_version": "dbt-context-v1",
        "requirement": {
            "code": "COVERS",
            "description": "Ogni corsa prevista è rappresentata.",
        },
        "rule": {
            "code": "COVERS",
            "description": "Considerare anche le soppressioni.",
            "engine": "dbt",
        },
        "relations": [],
        "notes": [],
        "provenance": {},
    }


class DbtContextTests(SimpleTestCase):
    def test_documentary_rule_has_no_operational_capability(self):
        text = json.dumps(context_document())
        validate_rule_definition(
            validation_type="dbt",
            language_version="1",
            definition=text,
            options={},
            result_contract="structured_report",
        )
        self.assertNotIn("dbt", [c["validation_type"] for c in capability_manifest()])
        self.assertEqual(load_dbt_context(text).rule["code"], "COVERS")

    def test_editorial_conditions_remain_uninterpreted(self):
        data = context_document()
        data["rule"]["when"] = (
            "Condizione in prosa: AND oppure OR secondo il contratto."
        )
        self.assertEqual(
            load_dbt_context(json.dumps(data)).rule["when"], data["rule"]["when"]
        )

    def test_malformed_duplicate_or_inconsistent_documents_are_rejected(self):
        examples = [
            "{}",
            '{"schema_version":"one","schema_version":"two"}',
            '{"x":NaN}',
        ]
        for value in examples:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                load_dbt_context(value)
        for field, value in (
            ("schema_version", "v9"),
            ("relations", [{"code": "X"}, {"code": "X"}]),
        ):
            data = context_document()
            data[field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                load_dbt_context(json.dumps(data))
        data = context_document()
        data["requirement"]["relations"] = ["MISSING"]
        with self.assertRaises(ValidationError):
            load_dbt_context(json.dumps(data))
