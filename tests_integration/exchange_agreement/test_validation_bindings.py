# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Dataset policy, indicator impact and dependency closure remain independent."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from rpsd_config.exchange_agreement.models import (
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
    IndicatorVersionInput,
    ValidationRule,
    ValidationRuleVersion,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    DatasetSpecificationTransitionError,
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.indicator_dependencies import (
    add_indicator_dependency,
    resolve_indicator_closure,
)
from rpsd_config.exchange_agreement.services.validation_bindings import (
    bind_dataset_rule,
    bind_indicator_rule,
    required_dataset_specifications,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    transition_validation_rule,
)


class ValidationBindingsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(
            username="binding-admin", is_superuser=True
        )
        self.dataset = Dataset.objects.create(code="netex", name="NeTEx")
        self.spec = publish_dataset_specification(
            DatasetSpecification.objects.create(
                dataset=self.dataset,
                code="netex-ita_v002",
                version="002",
                metadata={"format": "xml"},
            )
        )
        rule = ValidationRule.objects.create(
            code="calendar-ref", name="Calendar reference"
        )
        version = ValidationRuleVersion.objects.create(
            rule=rule,
            version="1",
            name="Calendar reference",
            validation_type="xpath",
            definition="//n:DayTypeRef[not(@ref=//n:DayType/@id)]",
            language_version="1.0",
            options={"namespaces": {"n": "http://www.netex.org.uk/netex"}},
            execution_reference="validators/default",
        )
        self.rule = transition_validation_rule(
            version, target_status="published", actor=self.admin
        )
        self.binding = bind_dataset_rule(
            specification=self.spec,
            rule_version=self.rule,
            import_policy="indicator_only",
            actor=self.admin,
        )
        self.dimension = IndicatorDimension.objects.create(code="line", name="Line")

    def indicator(self, code):
        logical = Indicator.objects.create(code=code, name=code, description=code)
        return IndicatorVersion.objects.create(
            indicator=logical,
            code=code + "_001",
            version="001",
            description=code,
            formula_description="Count",
            execution_engine="prefect",
            execution_reference="indicators/" + code,
            artifact_identifier="git:rpsd-flows@fixture",
        )

    def test_base_policy_cannot_be_added_to_published_specification(self):
        self.binding.import_policy = "reject_import"
        with self.assertRaises(ValidationError):
            self.binding.save()
        self.assertEqual(self.binding.indicator_bindings.count(), 0)

    def test_dimension_binding_is_atomic_and_does_not_change_import_policy(self):
        version = self.indicator("journeys")
        with self.assertRaises(ValidationError):
            bind_indicator_rule(
                indicator_version=version,
                dataset_rule=self.binding,
                impact="dimension",
                dimensions=[],
                actor=self.admin,
            )
        self.assertFalse(version.rule_bindings.exists())
        result = bind_indicator_rule(
            indicator_version=version,
            dataset_rule=self.binding,
            impact="dimension",
            dimensions=[self.dimension],
            actor=self.admin,
        )
        result.validate_complete()
        self.assertEqual(self.binding.import_policy, "indicator_only")
        publish_indicator_version(version, actor=self.admin)
        with self.assertRaises(ValidationError):
            result.dimension_links.all().delete()
        with self.assertRaises(ValidationError):
            version.rule_bindings.all().delete()

    def test_rule_free_input_is_preserved_and_inherited(self):
        prerequisite = self.indicator("base-count")
        IndicatorVersionInput.objects.create(
            indicator_version=prerequisite, dataset_specification=self.spec
        )
        prerequisite = publish_indicator_version(prerequisite, actor=self.admin)
        parent = self.indicator("composite-count")
        add_indicator_dependency(
            dependent=parent, prerequisite=prerequisite, actor=self.admin
        )
        closure = resolve_indicator_closure([parent])
        self.assertEqual([s.code for s in closure["specifications"]], [self.spec.code])
        self.assertEqual(
            closure["paths"][prerequisite.pk], [[parent.code, prerequisite.code]]
        )
        self.assertEqual(required_dataset_specifications(prerequisite), [self.spec])

    def test_shared_prerequisite_keeps_both_paths(self):
        base = publish_indicator_version(self.indicator("shared"), actor=self.admin)
        left = self.indicator("left")
        right = self.indicator("right")
        add_indicator_dependency(dependent=left, prerequisite=base, actor=self.admin)
        add_indicator_dependency(dependent=right, prerequisite=base, actor=self.admin)
        left = publish_indicator_version(left, actor=self.admin)
        right = publish_indicator_version(right, actor=self.admin)
        root = self.indicator("root")
        add_indicator_dependency(dependent=root, prerequisite=left, actor=self.admin)
        add_indicator_dependency(dependent=root, prerequisite=right, actor=self.admin)
        closure = resolve_indicator_closure([root])
        self.assertEqual(len(closure["versions"]), 4)
        self.assertEqual(len(closure["paths"][base.pk]), 2)

    def test_self_reference_and_unpublished_prerequisite_are_rejected(self):
        version = self.indicator("draft")
        with self.assertRaises(ValidationError):
            add_indicator_dependency(
                dependent=version, prerequisite=version, actor=self.admin
            )
        other = self.indicator("other")
        with self.assertRaises(ValidationError):
            add_indicator_dependency(
                dependent=version, prerequisite=other, actor=self.admin
            )
        self.assertFalse(IndicatorVersionDependency.objects.exists())

    def draft_spec(self, version="003", dataset=None, file_format="xml"):
        return DatasetSpecification.objects.create(
            dataset=dataset or self.dataset,
            code=f"{(dataset or self.dataset).code}_{version}",
            version=version,
            metadata={"format": file_format},
        )

    def published_rule(self, code):
        version = ValidationRuleVersion.objects.create(
            rule=ValidationRule.objects.create(code=code, name=code),
            version="001",
            name=code,
            validation_type="xpath",
            definition="//n:Line[not(@id)]",
            language_version="1.0",
            options={"namespaces": {"n": "urn:netex"}},
            execution_reference="validators/default",
        )
        return transition_validation_rule(
            version, target_status="published", actor=self.admin
        )

    def test_same_rule_can_be_reused_but_duplicate_pair_is_rejected(self):
        other = self.draft_spec()
        link = bind_dataset_rule(
            specification=other,
            rule_version=self.rule,
            import_policy="warn",
            actor=self.admin,
        )
        self.assertEqual(link.created_by, self.admin)
        with self.assertRaises(ValidationError):
            bind_dataset_rule(
                specification=other,
                rule_version=self.rule,
                import_policy="reject_import",
                actor=self.admin,
            )
        self.assertEqual(other.rule_bindings.count(), 1)

    def test_base_and_indicator_policies_preserve_distinct_consumers(self):
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            resolve_dataset_rules,
        )

        spec = self.draft_spec()
        base = bind_dataset_rule(
            specification=spec,
            rule_version=self.rule,
            import_policy="reject_import",
            actor=self.admin,
        )
        warning = bind_dataset_rule(
            specification=spec,
            rule_version=self.published_rule("base-warning"),
            import_policy="warn",
            actor=self.admin,
        )
        publish_dataset_specification(spec, actor=self.admin)
        extra = bind_dataset_rule(
            specification=spec,
            rule_version=self.published_rule("optional-check"),
            import_policy="indicator_only",
            actor=self.admin,
        )
        left, right = self.indicator("consumer-left"), self.indicator("consumer-right")
        bind_indicator_rule(
            indicator_version=left,
            dataset_rule=base,
            impact="calculation",
            dimensions=[],
            actor=self.admin,
        )
        bind_indicator_rule(
            indicator_version=right,
            dataset_rule=base,
            impact="dimension",
            dimensions=[self.dimension],
            actor=self.admin,
        )
        bind_indicator_rule(
            indicator_version=left,
            dataset_rule=extra,
            impact="calculation",
            dimensions=[],
            actor=self.admin,
        )
        old_plan = resolve_dataset_rules(spec, [])
        self.assertEqual(
            {item["import_policy"] for item in old_plan}, {"reject_import", "warn"}
        )
        plan = resolve_dataset_rules(spec, [right, left, left])
        self.assertEqual(len(plan), 3)
        shared = next(
            item for item in plan if item["rule"]["rule_code"] == self.rule.rule.code
        )
        self.assertEqual(shared["import_policy"], "reject_import")
        self.assertEqual(
            [item["impact"] for item in shared["consumers"]],
            ["calculation", "dimension"],
        )
        self.assertEqual(shared["consumers"][1]["affected_dimensions"], ["line"])
        self.assertEqual(warning.import_policy, "warn")
        self.assertEqual(len(resolve_dataset_rules(spec, [right])), 2)
        bind_dataset_rule(
            specification=spec,
            rule_version=self.published_rule("new-use"),
            import_policy="indicator_only",
            actor=self.admin,
        )
        self.assertEqual(old_plan, resolve_dataset_rules(spec, []))

    def test_calculation_dimensions_and_duplicate_dimensions_roll_back(self):
        version = self.indicator("invalid-dimensions")
        for impact, dimensions in [
            ("calculation", [self.dimension]),
            ("dimension", [self.dimension, self.dimension]),
        ]:
            with self.subTest(impact=impact), self.assertRaises(ValidationError):
                bind_indicator_rule(
                    indicator_version=version,
                    dataset_rule=self.binding,
                    impact=impact,
                    dimensions=dimensions,
                    actor=self.admin,
                )
        self.assertFalse(version.rule_bindings.exists())

    def test_update_binding_is_atomic_and_freezes_after_publication(self):
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            update_indicator_rule,
        )

        version = self.indicator("editable-binding")
        binding = bind_indicator_rule(
            indicator_version=version,
            dataset_rule=self.binding,
            impact="dimension",
            dimensions=[self.dimension],
            actor=self.admin,
        )
        with self.assertRaises(ValidationError):
            update_indicator_rule(
                binding, impact="dimension", dimensions=[], actor=self.admin
            )
        binding.refresh_from_db()
        self.assertEqual(binding.affected_dimensions.count(), 1)
        binding = update_indicator_rule(
            binding, impact="calculation", dimensions=[], actor=self.admin
        )
        self.assertEqual(binding.affected_dimensions.count(), 0)
        publish_indicator_version(version, actor=self.admin)
        with self.assertRaises(ValidationError):
            update_indicator_rule(
                binding,
                impact="dimension",
                dimensions=[self.dimension],
                actor=self.admin,
            )

    def test_stale_published_rule_is_not_accepted_after_deprecation(self):
        spec = self.draft_spec()
        transition_validation_rule(
            self.rule, target_status="deprecated", actor=self.admin, reason="Retired"
        )
        with self.assertRaises(ValidationError):
            bind_dataset_rule(
                specification=spec,
                rule_version=self.rule,
                import_policy="warn",
                actor=self.admin,
            )
        with self.assertRaises(ValidationError):
            bind_indicator_rule(
                indicator_version=self.indicator("stale-rule"),
                dataset_rule=self.binding,
                impact="calculation",
                dimensions=[],
                actor=self.admin,
            )
        self.assertFalse(spec.rule_bindings.exists())

    def test_dataset_publication_revalidates_base_rules(self):
        spec = self.draft_spec()
        bind_dataset_rule(
            specification=spec,
            rule_version=self.rule,
            import_policy="reject_import",
            actor=self.admin,
        )
        transition_validation_rule(
            self.rule, target_status="deprecated", actor=self.admin, reason="Retired"
        )
        with self.assertRaises(DatasetSpecificationTransitionError) as error:
            publish_dataset_specification(spec, actor=self.admin)
        self.assertEqual(error.exception.code, "unpublished_rule")
        spec.refresh_from_db()
        self.assertEqual(spec.status, "draft")
        self.assertFalse(spec.status_events.exists())

    def test_format_errors_and_frozen_dataset_bindings(self):
        from django.db.models.deletion import Collector, ProtectedError

        from rpsd_config.exchange_agreement.models import DatasetVersionRule

        csv = Dataset.objects.create(code="csv-input", name="CSV")
        with self.assertRaises(ValidationError) as error:
            bind_dataset_rule(
                specification=self.draft_spec(dataset=csv, file_format="csv"),
                rule_version=self.rule,
                import_policy="warn",
                actor=self.admin,
            )
        self.assertEqual(
            error.exception.error_dict["__all__"][0].code, "unsupported_rule_format"
        )
        with self.assertRaises(ValidationError):
            self.binding.delete()
        with self.assertRaises(ValidationError):
            DatasetVersionRule.objects.filter(pk=self.binding.pk).update(
                import_policy="warn"
            )
        with self.assertRaises(ProtectedError):
            Collector(using="default").collect([self.rule])

    def test_permissions_and_rule_free_conflicting_inputs(self):
        from django.core.exceptions import PermissionDenied

        from rpsd_config.exchange_agreement.services.validation_bindings import (
            declare_indicator_input,
        )

        editor = get_user_model().objects.create_user(username="binding-editor")
        version = self.indicator("required-inputs")
        for operation in [
            lambda: bind_dataset_rule(
                specification=self.spec,
                rule_version=self.rule,
                import_policy="warn",
                actor=editor,
            ),
            lambda: bind_indicator_rule(
                indicator_version=version,
                dataset_rule=self.binding,
                impact="calculation",
                dimensions=[],
                actor=editor,
            ),
            lambda: declare_indicator_input(
                indicator_version=version, specification=self.spec, actor=editor
            ),
        ]:
            with self.assertRaises(PermissionDenied):
                operation()
        declare_indicator_input(
            indicator_version=version, specification=self.spec, actor=self.admin
        )
        other = publish_dataset_specification(self.draft_spec(), actor=self.admin)
        declare_indicator_input(
            indicator_version=version, specification=other, actor=self.admin
        )
        with self.assertRaises(ValidationError) as error:
            required_dataset_specifications(version)
        self.assertEqual(error.exception.code, "conflicting_dataset_versions")

    def test_profile_requires_rule_free_input_and_exact_dataset_version(self):
        from rpsd_config.exchange_agreement.models import (
            InputFlowVersion,
            OrchestrationFlowVersion,
            ProcessingProfileInputFlow,
            ProcessingProfileVersion,
        )
        from rpsd_config.exchange_agreement.services.validation_bindings import (
            declare_indicator_input,
            validate_profile_input_coverage,
        )

        version = self.indicator("coverage-inputs")
        declare_indicator_input(
            indicator_version=version, specification=self.spec, actor=self.admin
        )
        orchestration = OrchestrationFlowVersion.objects.create(
            code="test-orchestration",
            version="001",
            name="Orchestration",
            description="Orchestration fixture",
            engine="prefect",
            deployment_name="contracts/default",
            artifact_identifier="git:rpsd-flows@test",
        )
        profile = ProcessingProfileVersion.objects.create(
            code="coverage-profile",
            version="001",
            name="Coverage profile",
            description="Input coverage fixture",
            orchestration_flow_version=orchestration,
        )
        with self.assertRaises(ValidationError) as error:
            validate_profile_input_coverage(profile, [version])
        self.assertEqual(error.exception.code, "missing_profile_input")
        other = publish_dataset_specification(self.draft_spec(), actor=self.admin)
        flow = InputFlowVersion.objects.create(
            dataset_specification=other,
            code="test-input-flow",
            version="001",
            name="Input",
            description="Input fixture",
            engine="prefect",
            deployment_name="imports/default",
            artifact_identifier="git:rpsd-flows@test",
        )
        link = ProcessingProfileInputFlow.objects.create(
            processing_profile_version=profile,
            dataset=self.dataset,
            input_flow_version=flow,
        )
        with self.assertRaises(ValidationError) as error:
            validate_profile_input_coverage(profile, [version])
        self.assertEqual(error.exception.code, "missing_profile_input")
        matching_flow = InputFlowVersion.objects.create(
            dataset_specification=self.spec,
            code="matching-input-flow",
            version="001",
            name="Input",
            description="Input fixture",
            engine="prefect",
            deployment_name="imports/default",
            artifact_identifier="git:rpsd-flows@test",
        )
        link.input_flow_version = matching_flow
        link.save()
        validate_profile_input_coverage(profile, [version])

    def test_dimension_identity_and_provenance_cannot_change(self):
        self.dimension.code = "different"
        with self.assertRaises(ValidationError):
            self.dimension.save()
        with self.assertRaises(ValidationError):
            IndicatorDimension.objects.filter(pk=self.dimension.pk).update(
                code="different"
            )
        spec = self.draft_spec()
        binding = bind_dataset_rule(
            specification=spec,
            rule_version=self.rule,
            import_policy="warn",
            actor=self.admin,
        )
        binding.created_by = None
        with self.assertRaises(ValidationError):
            binding.save()
        binding.refresh_from_db()
        self.assertEqual(binding.created_by, self.admin)

    def test_incomplete_binding_blocks_indicator_publication(self):
        from rpsd_config.exchange_agreement.models import IndicatorVersionRule

        version = self.indicator("incomplete-binding")
        IndicatorVersionRule.objects.create(
            indicator_version=version,
            dataset_version_rule=self.binding,
            impact="dimension",
        )
        with self.assertRaises(ValidationError):
            publish_indicator_version(version, actor=self.admin)
        version.refresh_from_db()
        self.assertEqual(version.status, "draft")
        self.assertFalse(version.status_events.exists())

    def test_admin_rejects_forged_changes_to_published_applicability(self):
        from django.contrib import admin
        from django.test import RequestFactory
        from django.urls import reverse

        from rpsd_config.admin_dataset_exchange.proxies import (
            DatasetVersionRuleAdminProxy,
        )

        self.admin.is_staff = True
        self.admin.save()
        request = RequestFactory().get("/admin/")
        request.user = self.admin
        model_admin = admin.site._registry[DatasetVersionRuleAdminProxy]
        self.assertFalse(model_admin.has_change_permission(request, self.binding))
        self.assertFalse(model_admin.has_delete_permission(request, self.binding))
        self.assertNotIn("delete_selected", model_admin.get_actions(request))
        self.client.force_login(self.admin)
        url = reverse(
            "admin:admin_dataset_exchange_datasetversionruleadminproxy_change",
            args=[self.binding.pk],
        )
        self.assertEqual(
            self.client.post(url, {"import_policy": "reject_import"}).status_code, 403
        )
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.import_policy, "indicator_only")

    def test_admin_creation_records_authenticated_actor(self):
        from django.urls import reverse

        from rpsd_config.exchange_agreement.models import DatasetVersionRule

        self.admin.is_staff = True
        self.admin.save()
        self.client.force_login(self.admin)
        spec = self.draft_spec()
        url = reverse("admin:admin_dataset_exchange_datasetversionruleadminproxy_add")
        response = self.client.post(
            url,
            {
                "dataset_specification": spec.pk,
                "rule_version": self.rule.pk,
                "import_policy": "warn",
                "_save": "Save",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            DatasetVersionRule.objects.get(dataset_specification=spec).created_by,
            self.admin,
        )
