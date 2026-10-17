# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Verify revision-owned indicator choices and concurrent writers (029)."""

from threading import Barrier, Thread

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import close_old_connections, models, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase

from rpsd_config.admin_agreements.admin import ContractRevisionIndicatorInline
from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    ContractRevisionIndicator,
    IndicatorVersion,
    ProcessingProfileIndicatorVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionError,
    replace_draft_configuration,
)
from tests_integration.exchange_agreement.test_contract_configuration_revisions import (
    _ContractRevisionFixtureMixin,
)


class RevisionIndicatorTests(_ContractRevisionFixtureMixin, TestCase):
    def test_selections_are_revision_owned_and_bulk_bypasses_are_rejected(self):
        first = self._revision(number=1, valid_from=self.contract.start_date)
        second = self._revision(number=2, valid_from=self.contract.start_date)
        first.indicator_configurations.all().delete()
        self.assertEqual(second.indicator_configurations.count(), 1)
        selection = second.indicator_configurations.get()
        for operation in (
            lambda: ContractRevisionIndicator.objects.update(parameters={}),
            lambda: ContractRevisionIndicator.objects.bulk_create([]),
            lambda: ContractRevisionIndicator.objects.bulk_update(
                [selection], ["parameters"]
            ),
        ):
            with self.assertRaises(ValidationError):
                operation()

    def test_selection_ownership_cannot_move_between_drafts(self):
        first = self._revision(number=1, valid_from=self.contract.start_date)
        second = self._revision(number=2, valid_from=self.contract.start_date)
        selection = first.indicator_configurations.get()
        selection.revision = second
        with self.assertRaisesMessage(ValidationError, "cannot move"):
            selection.save()
        selection.refresh_from_db()
        self.assertEqual(selection.revision_id, first.pk)

    def test_permission_rename_keeps_existing_group_grants(self):
        from importlib import import_module

        from django.apps import apps
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType
        from django.db import connection

        content_type = ContentType.objects.get_for_model(ContractRevisionIndicator)
        Permission.objects.filter(
            content_type=content_type, codename="add_contractrevisionindicator"
        ).delete()
        permission = Permission.objects.create(
            content_type=content_type,
            codename="add_contractindicatorconfiguration",
            name="Can add old configuration",
        )
        group = Group.objects.create(name="revision-indicator-editor")
        group.permissions.add(permission)
        migration = import_module(
            "rpsd_config.exchange_agreement.migrations.0048_contract_revision_indicators"
        )
        migration.rename_indicator_permissions(apps, connection.schema_editor())
        permission.refresh_from_db()
        self.assertEqual(permission.codename, "add_contractrevisionindicator")
        self.assertEqual(
            list(group.permissions.values_list("pk", flat=True)), [permission.pk]
        )

    def test_two_versions_of_one_logical_indicator_cannot_be_selected(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        version = IndicatorVersion.objects.create(
            indicator=self.logical_indicator,
            code="alternative_002",
            version="002",
            description="Alternative version",
            formula_description="Count journeys",
        )
        # Simulate a legacy invalid published profile independently of its guards.
        alternate = ProcessingProfileIndicatorVersion(
            processing_profile_version=self.profile, indicator_version=version
        )
        models.QuerySet.bulk_create(
            ProcessingProfileIndicatorVersion.objects.all(), [alternate]
        )
        with self.assertRaisesMessage(ValidationError, "Only one version"):
            ContractRevisionIndicator.objects.create(
                revision=revision, processing_profile_indicator_version=alternate
            )
        self.assertEqual(revision.indicator_configurations.count(), 1)

    def test_frozen_selection_cannot_move_or_be_deleted_by_queryset(self):
        frozen = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        draft = self._revision(number=2, valid_from=self.contract.start_date)
        selection = frozen.indicator_configurations.get()
        selection.revision = draft
        with self.assertRaises(ValidationError):
            selection.save()
        with self.assertRaises(ValidationError), transaction.atomic():
            frozen.indicator_configurations.all().delete()
        self.assertEqual(frozen.indicator_configurations.count(), 1)

    def test_legacy_service_argument_is_rejected_atomically(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        before = list(revision.indicator_configurations.values())
        with self.assertRaisesMessage(ContractRevisionError, "no longer supported"):
            replace_draft_configuration(
                revision,
                [],
                [
                    {
                        "processing_profile_indicator_version": self.profile_indicator,
                        "contract_indicator": 123,
                    }
                ],
                self.user,
            )
        self.assertEqual(list(revision.indicator_configurations.values()), before)

    def test_web_rejects_unknown_profile_choices_without_silent_filtering(self):
        from rpsd_config.exchange_agreement.views import (
            _revision_indicator_configs_from_post,
        )

        revision = self._revision(number=1, valid_from=self.contract.start_date)
        request = RequestFactory().post("/", {"indicator_link_ids": ["999999"]})
        with self.assertRaisesMessage(ContractRevisionError, "revision profile"):
            _revision_indicator_configs_from_post(request, revision)
        self.assertEqual(revision.indicator_configurations.count(), 1)

    def test_admin_choices_are_limited_to_revision_profile(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        request = RequestFactory().get("/admin/")
        request.user = self.user
        inline = ContractRevisionIndicatorInline(
            ContractConfigurationRevision, admin.site
        )
        formset = inline.get_formset(request, revision)
        choices = formset.form.base_fields[
            "processing_profile_indicator_version"
        ].queryset
        self.assertEqual(
            set(choices.values_list("processing_profile_version_id", flat=True)),
            {revision.processing_profile_version_id},
        )


class RevisionIndicatorConcurrencyTests(
    _ContractRevisionFixtureMixin, TransactionTestCase
):
    def test_concurrent_selections_serialize_on_revision(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        revision.indicator_configurations.all().delete()
        barrier = Barrier(2)
        outcomes = []

        def select():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                ContractRevisionIndicator.objects.create(
                    revision_id=revision.pk,
                    processing_profile_indicator_version_id=self.profile_indicator.pk,
                )
                outcomes.append("saved")
            except ValidationError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [Thread(target=select) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertEqual(sorted(outcomes), ["rejected", "saved"])
        self.assertEqual(revision.indicator_configurations.count(), 1)

    def test_approval_and_value_write_use_the_same_revision_lock(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        barrier = Barrier(2)
        outcomes = []

        def write_values():
            close_old_connections()
            try:
                selection = ContractRevisionIndicator.objects.get(revision=revision)
                selection.parameters = {"minimum_samples": 20}
                barrier.wait(timeout=10)
                selection.save()
                outcomes.append("saved")
            except ValidationError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        def approve():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                self._approve_first_revision(revision)
                outcomes.append("approved")
            finally:
                close_old_connections()

        threads = [Thread(target=write_values), Thread(target=approve)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
            self.assertFalse(thread.is_alive())
        self.assertIn("approved", outcomes)
        self.assertEqual(len(outcomes), 2)
        revision.refresh_from_db()
        self.assertEqual(
            revision.configuration_snapshot["indicators"][0]["parameters"],
            revision.indicator_configurations.get().parameters,
        )
