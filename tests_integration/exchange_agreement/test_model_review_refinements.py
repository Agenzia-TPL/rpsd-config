# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Native ORM relations, contextual admin values and notification protections."""

from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from rpsd_config.admin_agreements.admin import ContractDependencyValuesInline
from rpsd_config.admin_agreements.proxies import ContractConfigurationRevisionAdminProxy
from rpsd_config.admin_audit.proxies import ConfigurationAssetEventAdminProxy
from rpsd_config.exchange_agreement.models import (
    ConfigurationAsset,
    ConfigurationAssetEvent,
    ContractDependencyConfiguration,
    IndicatorDimension,
    IndicatorVersion,
    ProcessingProfileVersion,
    ValidationTypeVersion,
)
from rpsd_config.exchange_agreement.services.configuration_assets import (
    create_asset_event,
    retry_asset_event,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    ContractRevisionPermissionError,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)

from . import test_validation_plan as plan_fixtures
from .test_indicator_dependencies import version


class ModelReviewTests(TestCase):
    def setUp(self):
        plan_fixtures.ValidationPlanTests.setUp(self)
        self.request = RequestFactory().get("/admin/")
        self.request.user = self.admin

    def test_native_relations_preserve_direction_and_freeze(self):
        flow = self.profile.input_flow_links.first().input_flow_version
        spec = flow.dataset_specification
        base = publish_indicator_version(version("orm-base"), actor=self.admin)
        root = version("orm-root")
        root.input_specifications.add(spec)
        root.prerequisites.add(base)
        self.assertEqual(list(root.input_specifications.all()), [spec])
        self.assertEqual(list(root.prerequisites.all()), [base])
        self.assertFalse(base.prerequisites.exists())
        self.assertEqual(list(base.dependent_versions.all()), [root])
        dimension = IndicatorDimension.objects.create(code="orm-line", name="Line")
        edge = root.dependency_links.get()
        edge.required_dimensions.add(dimension)
        self.assertEqual(list(edge.required_dimensions.all()), [dimension])
        root = publish_indicator_version(root, actor=self.admin)
        for operation in (
            root.input_specifications.clear,
            root.prerequisites.clear,
            edge.required_dimensions.clear,
        ):
            with self.assertRaises(ValidationError), transaction.atomic():
                operation()
        with self.assertRaises(ValidationError), transaction.atomic():
            base.prerequisites.add(root)

    def test_native_profile_flows_validate_dataset_and_freeze(self):
        flow = self.profile.input_flow_links.first().input_flow_version
        profile = ProcessingProfileVersion.objects.create(
            code="orm-profile",
            version="1",
            name="ORM",
            description="ORM fixture",
            orchestration_flow_version=self.profile.orchestration_flow_version,
        )
        profile.input_flow_versions.add(
            flow, through_defaults={"dataset": flow.dataset_specification.dataset}
        )
        self.assertEqual(list(profile.input_flow_versions.all()), [flow])
        self.assertIn(profile, flow.using_profile_versions.all())
        # Simulate a pre-existing frozen catalog without changing its composition.
        models.QuerySet.update(
            ProcessingProfileVersion.objects.filter(pk=profile.pk), status="published"
        )
        with self.assertRaises(ValidationError), transaction.atomic():
            profile.input_flow_versions.clear()
        with self.assertRaises(ValidationError):
            profile.input_flow_links.update(dataset_id=999)

    def test_dependency_inline_uses_scoped_domain_service(self):
        inline = ContractDependencyValuesInline(
            ContractConfigurationRevisionAdminProxy, admin.site
        )
        formset_class = inline.get_formset(self.request, self.revision)
        prefix = formset_class.get_default_prefix()
        dependency = IndicatorVersion.objects.get(code="demo-journey-count_001")
        values = {
            f"{prefix}-TOTAL_FORMS": "1",
            f"{prefix}-INITIAL_FORMS": "0",
            f"{prefix}-0-indicator_version": dependency.pk,
        }
        for key in ("parameters", "thresholds", "aggregation", "penalties"):
            values[f"{prefix}-0-{key}"] = "{}"
        formset = formset_class(values, instance=self.revision)
        self.assertTrue(formset.is_valid(), (formset.errors, formset.non_form_errors()))
        result = formset.save()
        self.assertEqual(len(result), 1)
        self.assertEqual(
            ContractDependencyConfiguration.objects.get().indicator_version, dependency
        )
        outsider = get_user_model().objects.create_user(
            username="outsider", is_staff=True
        )
        self.request.user = outsider
        self.assertFalse(inline.has_change_permission(self.request, self.revision))
        forbidden_formset = inline.get_formset(self.request, self.revision)
        forbidden = forbidden_formset(values, instance=self.revision)
        # A direct formset save still invokes domain authorization.
        with self.assertRaises(ContractRevisionPermissionError):
            forbidden.save()

    def test_catalog_pairs_are_protected_and_seeded(self):
        self.assertEqual(ValidationTypeVersion.objects.count(), 7)
        with self.assertRaises(ValidationError):
            ValidationTypeVersion.objects.create(
                validation_type="arbitrary", language_version="99"
            )
        pair = ValidationTypeVersion.objects.first()
        with self.assertRaises(ValidationError):
            ValidationTypeVersion.objects.filter(pk=pair.pk).update(
                language_version="99"
            )

    def asset_event(self):
        asset = ConfigurationAsset.objects.create(
            asset_type="other",
            what="notification-test",
            version=1,
            storage_provider="fs",
            original_filename="test.txt",
            storage_url="fs://not-accessed/test.txt",
            checksum_sha256="a" * 64,
            size_bytes=1,
        )
        return create_asset_event(asset=asset, event_type="config_asset.created")

    @override_settings(CONFIG_ASSETS_RABBITMQ_ENABLED=True)
    def test_retry_is_selective_and_updates_diagnostics(self):
        event, other = self.asset_event(), self.asset_event_with_other_code()

        def publish(current):
            current.status = "published"
            current.attempts += 1
            current.save()
            return current

        with patch(
            "rpsd_config.exchange_agreement.services.configuration_assets.publish_asset_event",
            side_effect=publish,
        ) as sender:
            self.assertEqual(retry_asset_event(event.pk).status, "published")
            self.assertIsNone(retry_asset_event(event.pk))
            sender.assert_called_once()
        other.refresh_from_db()
        self.assertEqual(other.attempts, 0)
        event.asset.refresh_from_db()
        self.assertEqual(event.asset.publish_status, "published")

    def asset_event_with_other_code(self):
        asset = ConfigurationAsset.objects.create(
            asset_type="other",
            what="notification-other",
            version=1,
            storage_provider="fs",
            original_filename="test.txt",
            storage_url="fs://not-accessed/other.txt",
            checksum_sha256="b" * 64,
            size_bytes=1,
        )
        return create_asset_event(asset=asset, event_type="config_asset.created")

    @override_settings(CONFIG_ASSETS_RABBITMQ_ENABLED=False)
    def test_event_admin_readonly_and_disabled_retry(self):
        event = self.asset_event()
        self.client.force_login(self.admin)
        path = reverse(
            "admin:admin_audit_configurationasseteventadminproxy_change",
            args=[event.pk],
        )
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(
            self.client.post(path, {"status": "published"}).status_code, 403
        )
        editor = admin.site._registry[ConfigurationAssetEventAdminProxy]
        self.assertFalse(editor.has_add_permission(self.request))
        self.assertFalse(editor.has_delete_permission(self.request, event))
        self.assertIsNone(retry_asset_event(event.pk))
        event.refresh_from_db()
        self.assertEqual(event.attempts, 0)


@override_settings(CONFIG_ASSETS_RABBITMQ_ENABLED=True)
class NotificationRetryConcurrencyTests(TransactionTestCase):
    def test_two_retries_do_not_send_the_same_event_simultaneously(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        from django.db import close_old_connections

        entered, release = Event(), Event()
        asset = ConfigurationAsset.objects.create(
            asset_type="other",
            what="retry-concurrent",
            version=1,
            original_filename="test.txt",
            storage_provider="fs",
            storage_url="fs://not-accessed/concurrent.txt",
            checksum_sha256="a" * 64,
            size_bytes=1,
        )
        event = create_asset_event(asset=asset, event_type="config_asset.created")

        def send(current):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Concurrent retry test timed out.")
            current.status = "published"
            current.attempts += 1
            current.save()
            return current

        def retry():
            close_old_connections()
            try:
                return retry_asset_event(event.pk)
            finally:
                close_old_connections()

        with patch(
            "rpsd_config.exchange_agreement.services.configuration_assets.publish_asset_event",
            side_effect=send,
        ) as sender:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(retry)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertIsNone(pool.submit(retry).result(timeout=10))
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10).status, "published")
            sender.assert_called_once()
        event.refresh_from_db()
        self.assertEqual(event.attempts, 1)

    def test_retry_does_not_overlap_the_initial_publisher(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from django.db import close_old_connections

        from rpsd_config.exchange_agreement.services.configuration_assets import (
            publish_asset_event,
        )

        entered, release = Event(), Event()
        asset = ConfigurationAsset.objects.create(
            asset_type="other",
            what="initial-publish",
            version=1,
            original_filename="test.txt",
            storage_provider="fs",
            storage_url="fs://not-accessed/initial.txt",
            checksum_sha256="a" * 64,
            size_bytes=1,
        )
        event = create_asset_event(asset=asset, event_type="config_asset.created")

        async def send(**kwargs):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Initial publisher test timed out.")

        carrier = SimpleNamespace(
            start=AsyncMock(),
            stop=AsyncMock(),
            send_slimfast_async=AsyncMock(side_effect=send),
        )

        def publish():
            close_old_connections()
            try:
                return publish_asset_event(
                    ConfigurationAssetEvent.objects.get(pk=event.pk)
                )
            finally:
                close_old_connections()

        with patch("rpsd_transport.get_carrier", return_value=carrier):
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(publish)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertIsNone(retry_asset_event(event.pk))
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10).status, "published")
            carrier.send_slimfast_async.assert_awaited_once()
        event.refresh_from_db()
        self.assertEqual(event.attempts, 1)


class ReviewAdminProtectionTests(TestCase):
    """Additional checks of readonly recovery routes and inline persistence."""

    setUp = ModelReviewTests.setUp
    asset_event = ModelReviewTests.asset_event

    def test_readonly_permission_does_not_authorize_retry(self):
        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType

        reader = get_user_model().objects.create_user(
            username="notification-reader", is_staff=True
        )
        content_type = ContentType.objects.get_for_model(
            ConfigurationAssetEventAdminProxy, for_concrete_model=False
        )
        reader.user_permissions.add(
            Permission.objects.get(
                content_type=content_type,
                codename="view_configurationasseteventadminproxy",
            )
        )
        self.request.user = reader
        editor = admin.site._registry[ConfigurationAssetEventAdminProxy]
        self.assertTrue(editor.has_view_permission(self.request))
        self.assertFalse(editor.has_retry_permission(self.request))
        self.assertNotIn("retry_selected", editor.get_actions(self.request))
        event = self.asset_event()
        hidden = admin.site._registry[ConfigurationAssetEvent]
        self.assertFalse(hidden.has_add_permission(self.request))
        self.assertFalse(hidden.has_change_permission(self.request, event))
        self.assertFalse(hidden.has_delete_permission(self.request, event))

    def test_dependency_dimension_inline_saves_through_relation(self):
        from rpsd_config.admin_dataset_exchange.validation_admin import (
            IndicatorDependencyInline,
        )

        prerequisite = publish_indicator_version(
            version("inline-base"), actor=self.admin
        )
        root = version("inline-root")
        dimension = IndicatorDimension.objects.create(code="inline-line", name="Line")
        inline = IndicatorDependencyInline(IndicatorVersion, admin.site)
        formset_class = inline.get_formset(self.request, root)
        prefix = formset_class.get_default_prefix()
        formset = formset_class(
            {
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "0",
                f"{prefix}-0-prerequisite": prerequisite.pk,
                f"{prefix}-0-dimensions": [dimension.pk],
            },
            instance=root,
        )
        self.assertTrue(formset.is_valid(), (formset.errors, formset.non_form_errors()))
        formset.save()
        self.assertEqual(
            list(root.dependency_links.get().required_dimensions.all()), [dimension]
        )
