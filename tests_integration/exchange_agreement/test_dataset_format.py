# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Explicit dataset formats, migration safety and legacy API compatibility."""

import importlib
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.db import connection, models
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase

from rpsd_config.exchange_agreement.api import _dataset_specification_schema
from rpsd_config.exchange_agreement.models import Dataset, DatasetSpecification
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.technical_catalog_views import (
    DatasetSpecificationForm,
)


class DatasetFormatTests(TestCase):
    def setUp(self):
        self.dataset = Dataset.objects.create(code="arbitrary", name="Arbitrary")

    def spec(self, **kwargs):
        return DatasetSpecification.objects.create(
            dataset=self.dataset, code="arbitrary-1", version="1", **kwargs
        )

    def test_explicit_choice_required_even_for_netex(self):
        self.dataset.code = "netex"
        self.dataset.save()
        for fields in ({}, {"format": "json"}):
            with self.assertRaises(ValidationError):
                self.spec(**fields)

    def test_reserved_metadata_key_rejected(self):
        with self.assertRaisesMessage(ValidationError, "dedicated dataset format"):
            self.spec(format="xml", metadata={"format": "csv"})

    def test_published_format_frozen(self):
        spec = publish_dataset_specification(self.spec(format="csv"))
        spec.format = "xml"
        with self.assertRaisesMessage(ValidationError, "immutable"):
            spec.save()

    def test_api_synthesizes_legacy_metadata_without_persisting_it(self):
        spec = self.spec(format="csv", metadata={"source": "test"})
        result = _dataset_specification_schema(spec)
        self.assertEqual(result.format, "csv")
        self.assertEqual(result.metadata, {"format": "csv", "source": "test"})
        spec.refresh_from_db()
        self.assertEqual(spec.metadata, {"source": "test"})

    def test_web_form_choices_and_optional_metadata(self):
        form = DatasetSpecificationForm(
            data={
                "dataset": self.dataset.pk,
                "code": "arbitrary-1",
                "version": "1",
                "format": "xlsx",
                "metadata": "{}",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().format, "xlsx")

    def test_backfill_preserves_other_metadata_and_refuses_ambiguity(self):
        migration = importlib.import_module(
            "rpsd_config.exchange_agreement.migrations.0050_dataset_specification_format"
        )
        spec = self.spec(format="xml")
        # Historical app state bypasses current model guards during backfill.
        models.QuerySet.update(
            DatasetSpecification.objects.filter(pk=spec.pk),
            metadata={"format": "csv", "source": "retained"},
        )
        historical = (
            MigrationExecutor(connection)
            .loader.project_state(
                [("exchange_agreement", "0050_dataset_specification_format")]
            )
            .apps
        )
        migration.separate_format(historical, Mock(connection=connection))
        spec.refresh_from_db()
        self.assertEqual(spec.format, "csv")
        self.assertEqual(spec.metadata, {"source": "retained"})
        with self.assertRaisesMessage(RuntimeError, "explicit classification"):
            migration.separate_format(historical, Mock(connection=connection))
