# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from allauth.socialaccount.models import SocialAccount
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings

from rpsd_config.admin_dataset_exchange.forms import (
    FragmentValidationRuleAdminForm,
    RequirementFragmentAdminForm,
)
from rpsd_config.admin_dataset_exchange.proxies import RequirementFragmentAdminProxy
from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    FragmentValidationRule,
    RequirementFragment,
    RequirementFragmentStatusEvent,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.requirement_fragments import (
    RequirementFragmentTransitionError,
    canonical_requirement_fragment_catalog_json,
    deprecate_requirement_fragment,
    publish_requirement_fragment,
    serialize_requirement_fragment_catalog,
    withdraw_requirement_fragment,
)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class RequirementFragmentCatalogTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="fragment-admin",
            password="test-password",
        )
        self.dataset = Dataset.objects.create(code="netex", name="NeTEx")
        self.specification = DatasetSpecification.objects.create(
            dataset=self.dataset,
            code="netex-ita_v001",
            version="001",
            description="NeTEx Italia v1",
        )
        self.specification = publish_dataset_specification(
            self.specification,
            actor=self.user,
        )

    def _xpath_fragment(
        self,
        *,
        code="service-journey",
        result_kind=RequirementFragment.ResultKind.PRESENCE,
        path="//netex:ServiceJourney",
    ):
        return RequirementFragment.objects.create(
            dataset_specification=self.specification,
            code=code,
            name="Service Journey",
            description="NeTEx service journey requirement.",
            locator_type=RequirementFragment.LocatorType.XPATH,
            result_kind=result_kind,
            locator_definition={
                "path": path,
                "namespaces": {"netex": "http://www.netex.org.uk/netex"},
            },
        )

    def _rule(self, fragment, rule_type, parameters=None, **kwargs):
        return FragmentValidationRule.objects.create(
            requirement_fragment=fragment,
            rule_type=rule_type,
            parameters=parameters or {},
            **kwargs,
        )

    def test_xpath_locator_is_version_specific_and_rejects_open_json(self):
        fragment = self._xpath_fragment()
        self.assertEqual(fragment.dataset_specification, self.specification)

        with self.assertRaises(ValidationError):
            RequirementFragment.objects.create(
                dataset_specification=self.specification,
                code="missing-namespaces",
                name="Missing namespaces",
                description="Invalid XPath locator.",
                locator_type=RequirementFragment.LocatorType.XPATH,
                result_kind=RequirementFragment.ResultKind.PRESENCE,
                locator_definition={"path": "//ServiceJourney", "namespaces": {}},
            )

        with self.assertRaises(ValidationError):
            RequirementFragment.objects.create(
                dataset_specification=self.specification,
                code="unknown-key",
                name="Unknown key",
                description="Invalid closed schema.",
                locator_type=RequirementFragment.LocatorType.XPATH,
                result_kind=RequirementFragment.ResultKind.PRESENCE,
                locator_definition={
                    "path": "//netex:ServiceJourney",
                    "namespaces": {"netex": "urn:netex"},
                    "python": "run()",
                },
            )

        with self.assertRaises(ValidationError):
            self._xpath_fragment()

    def test_table_locators_distinguish_presence_from_scalar_values(self):
        presence = RequirementFragment.objects.create(
            dataset_specification=self.specification,
            code="gtfs-stop-times",
            name="GTFS stop times",
            description="Presence of the GTFS stop-times resource.",
            locator_type=RequirementFragment.LocatorType.TABLE,
            result_kind=RequirementFragment.ResultKind.PRESENCE,
            locator_definition={
                "resource": "stop_times.txt",
                "columns": ["trip_id", "arrival_time"],
            },
        )
        scalar = RequirementFragment.objects.create(
            dataset_specification=self.specification,
            code="gtfs-arrival-time",
            name="GTFS arrival time",
            description="Arrival-time values.",
            locator_type=RequirementFragment.LocatorType.TABLE,
            result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
            locator_definition={
                "resource": "stop_times.txt",
                "column": "arrival_time",
            },
        )
        self.assertEqual(presence.locator_definition["columns"][1], "arrival_time")
        self.assertEqual(scalar.locator_definition["column"], "arrival_time")

        with self.assertRaises(ValidationError):
            RequirementFragment.objects.create(
                dataset_specification=self.specification,
                code="gtfs-invalid-scalar",
                name="Invalid scalar",
                description="A scalar locator cannot declare columns.",
                locator_type=RequirementFragment.LocatorType.TABLE,
                result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
                locator_definition={
                    "resource": "stop_times.txt",
                    "columns": ["arrival_time"],
                },
            )

    def test_rule_registry_normalizes_defaults_and_rejects_invalid_combinations(self):
        scalar = self._xpath_fragment(
            code="operating-day-type",
            result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
            path="//netex:DayType/netex:Name/text()",
        )
        self._rule(scalar, FragmentValidationRule.RuleType.EXISTS)
        non_empty = self._rule(
            scalar,
            FragmentValidationRule.RuleType.NON_EMPTY,
        )
        allowed = self._rule(
            scalar,
            FragmentValidationRule.RuleType.ALL_VALUES_IN_SET,
            {
                "allowed_values": ["lun", "sab", "dom"],
                "case_sensitive": False,
            },
            severity=FragmentValidationRule.Severity.WARNING,
        )
        self._rule(
            scalar,
            FragmentValidationRule.RuleType.CONTAINS_ALL_VALUES,
            {"required_values": ["lun", "sab", "dom"]},
        )
        self._rule(
            scalar,
            FragmentValidationRule.RuleType.SET_EQUALS,
            {"expected_values": ["lun", "sab", "dom"]},
        )

        self.assertEqual(non_empty.parameters, {"trim": True})
        self.assertFalse(allowed.parameters["case_sensitive"])
        self.assertTrue(allowed.parameters["trim"])
        self.assertEqual(allowed.severity, FragmentValidationRule.Severity.WARNING)

        with self.assertRaises(ValidationError):
            self._rule(
                self._xpath_fragment(code="presence-only"),
                FragmentValidationRule.RuleType.NON_EMPTY,
            )
        with self.assertRaises(ValidationError):
            self._rule(
                self._xpath_fragment(
                    code="unknown-version",
                    result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
                ),
                FragmentValidationRule.RuleType.NON_EMPTY,
                rule_version=2,
            )
        with self.assertRaises(ValidationError):
            self._rule(
                self._xpath_fragment(
                    code="normalized-duplicates",
                    result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
                ),
                FragmentValidationRule.RuleType.ALL_VALUES_IN_SET,
                {
                    "allowed_values": ["LUN", " lun "],
                    "case_sensitive": False,
                    "trim": True,
                },
            )

    def test_lifecycle_audits_and_freezes_fragment_and_rules(self):
        fragment = self._xpath_fragment()
        rule = self._rule(fragment, FragmentValidationRule.RuleType.EXISTS)

        fragment = publish_requirement_fragment(fragment, actor=self.user)
        event = RequirementFragmentStatusEvent.objects.get(
            requirement_fragment=fragment
        )
        self.assertEqual(event.from_status, RequirementFragment.Status.DRAFT)
        self.assertEqual(event.to_status, RequirementFragment.Status.PUBLISHED)
        self.assertEqual(event.changed_by, self.user)

        fragment.description = "Changed in place"
        with self.assertRaises(ValidationError):
            fragment.save()
        rule.severity = FragmentValidationRule.Severity.WARNING
        with self.assertRaises(ValidationError):
            rule.save()
        with self.assertRaises(ValidationError):
            rule.delete()
        with self.assertRaises(ValidationError):
            fragment.delete()

        fragment = deprecate_requirement_fragment(fragment, actor=self.user)
        fragment = withdraw_requirement_fragment(fragment, actor=self.user)
        self.assertEqual(fragment.status, RequirementFragment.Status.WITHDRAWN)
        self.assertEqual(fragment.status_events.count(), 3)
        with self.assertRaises(RequirementFragmentTransitionError):
            publish_requirement_fragment(fragment, actor=self.user)

    def test_fragment_requires_published_dataset_specification_to_publish(self):
        draft_specification = DatasetSpecification.objects.create(
            dataset=self.dataset,
            code="netex-ita_v002",
            version="002",
            description="Draft NeTEx specification",
        )
        fragment = RequirementFragment.objects.create(
            dataset_specification=draft_specification,
            code="service-journey",
            name="Service Journey",
            description="Draft fragment.",
            locator_type=RequirementFragment.LocatorType.XPATH,
            result_kind=RequirementFragment.ResultKind.PRESENCE,
            locator_definition={
                "path": "//netex:ServiceJourney",
                "namespaces": {"netex": "urn:netex"},
            },
        )
        with self.assertRaises(RequirementFragmentTransitionError):
            publish_requirement_fragment(fragment, actor=self.user)

    def test_serializer_and_read_api_are_deterministic_and_published_only(self):
        second = self._xpath_fragment(
            code="z-values",
            result_kind=RequirementFragment.ResultKind.SCALAR_VALUES,
        )
        self._rule(second, FragmentValidationRule.RuleType.NON_EMPTY)
        self._rule(second, FragmentValidationRule.RuleType.EXISTS)
        publish_requirement_fragment(second, actor=self.user)

        first = self._xpath_fragment(code="a-presence")
        self._rule(first, FragmentValidationRule.RuleType.EXISTS)
        publish_requirement_fragment(first, actor=self.user)
        self._xpath_fragment(code="draft-not-exposed")

        first_payload = serialize_requirement_fragment_catalog(self.specification)
        second_payload = serialize_requirement_fragment_catalog(self.specification)
        self.assertEqual(first_payload, second_payload)
        self.assertEqual(
            [item["code"] for item in first_payload], ["a-presence", "z-values"]
        )
        self.assertEqual(
            [rule["rule_type"] for rule in first_payload[1]["rules"]],
            ["exists", "non_empty"],
        )
        self.assertEqual(
            canonical_requirement_fragment_catalog_json(self.specification),
            canonical_requirement_fragment_catalog_json(self.specification),
        )

        self.client.force_login(self.user)
        response = self.client.get("/exchange_agreement/api/v1/datasets/netex")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [
                item["code"]
                for item in response.json()["specifications"][0]["fragments"]
            ],
            ["a-presence", "z-values"],
        )

    def test_guided_admin_forms_build_closed_json(self):
        fragment_form = RequirementFragmentAdminForm(
            data={
                "dataset_specification": self.specification.pk,
                "code": "guided-xpath",
                "name": "Guided XPath",
                "description": "Created through typed form fields.",
                "locator_type": RequirementFragment.LocatorType.XPATH,
                "result_kind": RequirementFragment.ResultKind.SCALAR_VALUES,
                "xpath_path": "//netex:DayType/netex:Name/text()",
                "xpath_namespaces": "netex=http://www.netex.org.uk/netex",
            }
        )
        self.assertTrue(fragment_form.is_valid(), fragment_form.errors)
        fragment = fragment_form.save()
        self.assertNotIn("locator_definition", fragment_form.fields)
        self.assertEqual(
            fragment.locator_definition["path"], "//netex:DayType/netex:Name/text()"
        )

        rule_form = FragmentValidationRuleAdminForm(
            data={
                "rule_type": FragmentValidationRule.RuleType.ALL_VALUES_IN_SET,
                "rule_version": 1,
                "severity": FragmentValidationRule.Severity.ERROR,
                "trim": "on",
                "values": "lun\nsab\ndom",
            },
            instance=FragmentValidationRule(requirement_fragment=fragment),
        )
        self.assertTrue(rule_form.is_valid(), rule_form.errors)
        rule = rule_form.save()
        self.assertNotIn("parameters", rule_form.fields)
        self.assertEqual(rule.parameters["allowed_values"], ["lun", "sab", "dom"])

    def test_admin_permissions_are_limited_to_platform_roles(self):
        regular = get_user_model().objects.create_user(username="regular")
        platform = get_user_model().objects.create_user(username="platform")
        SocialAccount.objects.create(
            user=platform,
            provider="openid_connect",
            uid="fragment-platform-admin",
            extra_data={"id_token": {"groups": ["/rpsd/admin"]}},
        )
        model_admin = admin.site._registry[RequirementFragmentAdminProxy]
        factory = RequestFactory()

        request = factory.get("/")
        request.user = regular
        self.assertFalse(model_admin.has_add_permission(request))
        request.user = platform
        self.assertTrue(model_admin.has_add_permission(request))
