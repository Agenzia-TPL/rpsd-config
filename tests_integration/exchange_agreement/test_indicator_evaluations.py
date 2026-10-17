# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Revision evaluation ownership, calendar, freeze and economic conditions."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase, TransactionTestCase

from rpsd_config.exchange_agreement.models import (
    EvaluationThresholdDimension,
    IndicatorDimension,
    IndicatorEvaluationThreshold,
    IndicatorPenalty,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.indicator_evaluations import (
    period_context,
    save_evaluation,
    serialize_evaluation,
)
from tests_integration.exchange_agreement.test_contract_configuration_revisions import (
    _ContractRevisionFixtureMixin,
)


class _EvaluationFixtureMixin(_ContractRevisionFixtureMixin):
    def setUp(self):
        def publish(version, **kwargs):
            version.output_schema = {
                "schema_version": 2,
                "identifier": "missed-journeys-output-v2",
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
            version.save()
            return publish_indicator_version(version, **kwargs)

        with patch(
            (
                "tests_integration.exchange_agreement.test_contract_c"
                "onfiguration_revisions.publish_indicator_version"
            ),
            side_effect=publish,
        ):
            super().setUp()
        self.revision = self._revision(number=1, valid_from=self.contract.start_date)
        self.owner = self.revision.indicator_configurations.get()
        self.owner.thresholds = {}
        self.owner.penalties = {}
        self.owner.save()
        self.line = IndicatorDimension.objects.create(code="line", name="Line")

    def threshold(self, **kwargs):
        values = dict(
            contract_revision_indicator=self.owner,
            code="daily-missed",
            name="Daily missed",
            metric_code="missed",
            aggregation_method="sum",
            violation_operator="gt",
            limit_value=Decimal("3"),
            period_type="daily",
            evaluation_timezone="Europe/Rome",
            partial_period_policy="complete_only",
            severity="alert",
            missing_data_policy="not_evaluable",
        )
        values.update(kwargs)
        return IndicatorEvaluationThreshold.objects.create(**values)


class EvaluationTests(_EvaluationFixtureMixin, TestCase):
    def test_custom_windows_are_inclusive_and_contract_end_is_frozen(self):
        start = self.contract.start_date + timedelta(days=2)
        for kind, extra, end in (
            (
                "custom_range",
                {"period_start_date": start, "period_end_date": start},
                start,
            ),
            (
                "custom_duration_days",
                {"period_start_date": start, "period_days": 3},
                start + timedelta(days=2),
            ),
            (
                "custom_to_contract_end",
                {"period_start_date": start},
                self.contract.end_date,
            ),
        ):
            with self.subTest(kind=kind):
                target = self.threshold(code=kind, period_type=kind, **extra)
                frozen = serialize_evaluation(target)
                self.assertEqual(frozen["context"]["resolved_end"], end.isoformat())
        self.assertEqual(frozen["context"]["end_source"], "contract")

    def test_calendar_matrix_and_days_fail_on_invalid_input(self):
        for kwargs in (
            {"period_type": "daily", "period_start_date": self.contract.start_date},
            {"period_type": "custom_duration_days", "period_days": 0},
            {"period_type": "custom_duration_days", "period_days": True},
            {"evaluation_timezone": "not/a/timezone"},
            {
                "period_type": "custom_range",
                "period_start_date": self.contract.start_date,
                "period_end_date": self.contract.start_date - timedelta(days=1),
            },
        ):
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaises(ValidationError),
                transaction.atomic(),
            ):
                self.threshold(**kwargs)

    def test_draft_is_incomplete_but_approval_contract_is_strict(self):
        target = self.threshold(
            period_type="custom_to_contract_end", period_start_date=None
        )
        with self.assertRaises(ValidationError):
            period_context(target, complete=True)

    def test_direct_and_native_dimension_writes_share_validation(self):
        target = self.threshold()
        target.group_by_dimensions.add(self.line)
        self.assertEqual(
            list(target.group_by_dimensions.values_list("code", flat=True)), ["line"]
        )
        other = IndicatorDimension.objects.create(code="company", name="Company")
        for operation in (
            lambda: target.group_by_dimensions.add(other),
            lambda: EvaluationThresholdDimension.objects.create(
                threshold=target, dimension=other
            ),
        ):
            with self.assertRaises(ValidationError), transaction.atomic():
                operation()

    def test_foreign_threshold_is_rejected_and_owner_cannot_move(self):
        target = self.threshold()
        second = self._revision(number=2, valid_from=self.contract.start_date)
        other_owner = second.indicator_configurations.get()
        with self.assertRaises(ValidationError):
            IndicatorPenalty.objects.create(
                contract_revision_indicator=other_owner,
                code="wrong",
                name="Wrong",
                activation_threshold=target,
            )
        target.contract_revision_indicator = other_owner
        with self.assertRaises(ValidationError):
            target.save()

    def test_per_unit_configuration_retains_franchise_without_calculating(self):
        target = self.threshold()
        penalty = IndicatorPenalty.objects.create(
            contract_revision_indicator=self.owner,
            code="missed",
            name="Missed penalty",
            activation_threshold=target,
            calculation_method="per_unit",
            quantity_metric_code="missed",
            quantity_aggregation_method="sum",
            allowance_quantity=Decimal("10"),
            unit_amount=Decimal("50"),
            currency="EUR",
            amount_rounding_mode="half_up",
        )
        row = serialize_evaluation(penalty)
        self.assertEqual(row["allowance_quantity"], "10")
        self.assertEqual(row["activation_threshold_code"], target.code)
        self.assertNotIn("calculated_amount", row)
        penalty.period_type = "monthly"
        with self.assertRaises(ValidationError):
            penalty.save()

    def test_frozen_content_blocks_instance_bulk_and_through_mutations(self):
        target = self.threshold()
        save_evaluation(target, dimensions=[self.line], actor=self.user)
        self._approve_first_revision(self.revision)
        for operation in (
            lambda: target.save(),
            lambda: target.delete(),
            lambda: IndicatorEvaluationThreshold.objects.filter(pk=target.pk).delete(),
            lambda: target.group_by_dimensions.clear(),
            lambda: IndicatorEvaluationThreshold.objects.filter(pk=target.pk).update(
                name="changed"
            ),
        ):
            with self.assertRaises(ValidationError), transaction.atomic():
                operation()
        self.assertEqual(
            IndicatorEvaluationThreshold.objects.get(pk=target.pk).name, "Daily missed"
        )

    def test_snapshot_and_new_api_preserve_economics_and_reject_old_consumers(self):
        from rpsd_config.exchange_agreement.models import (
            IntegrationGrant,
            IntegrationPrincipal,
        )
        from rpsd_config.server.m2m_auth import M2MAuthContext

        self.threshold()
        approved = self._approve_first_revision(self.revision)
        self.assertEqual(approved.snapshot_schema_version, "canonical-json-v3")
        self.assertEqual(
            approved.configuration_snapshot["evaluation_configurations"][0][
                "thresholds"
            ][0]["code"],
            "daily-missed",
        )
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="032-client",
            environment="dev",
            keycloak_client_id="032-client",
            keycloak_client_uuid="032-uuid",
        )
        IntegrationGrant.objects.create(
            principal=principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        context = M2MAuthContext(
            principal=principal, client_id="032-client", claims={"azp": "032-client"}
        )
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token", return_value=context
        ):
            for version, status in ((3, 409), (4, 200)):
                response = self.client.get(
                    f"/exchange_agreement/api/m2m/v{version}/contracts/{self.contract.contract_code}/validation-plan?data_category=netex",
                    HTTP_AUTHORIZATION="Bearer test",
                )
                self.assertEqual(response.status_code, status, response.content[:400])
                if version == 4:
                    self.assertEqual(
                        response.json()["schema_version"], "validation-plan-v2"
                    )
                    self.assertIn("evaluation_configurations", response.json())

    def test_web_and_admin_pages_render_with_context_and_enforce_scope(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        self.client.force_login(self.user)
        target = self.threshold()
        path = reverse(
            "exchange_agreement:indicator-evaluations",
            args=[self.contract.contract_code, self.revision.pk, self.owner.pk],
        )
        self.assertContains(self.client.get(path), "Dalla data X alla data Y")
        for name in ("indicatorevaluationthreshold", "indicatorpenalty"):
            add = reverse(f"admin:admin_agreements_{name}adminproxy_add")
            response = self.client.get(add, {"owner_id": self.owner.pk})
            self.assertEqual(response.status_code, 200, response.content[:400])
        change = reverse(
            "admin:admin_agreements_indicatorevaluationthresholdadminproxy_change",
            args=[target.pk],
        )
        self.assertEqual(self.client.get(change).status_code, 200)
        stranger = get_user_model().objects.create_user(username="032-stranger")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(
            self.client.post(
                path,
                {
                    "action": "delete-evaluation",
                    "kind": "threshold",
                    "target_id": target.pk,
                },
            ).status_code,
            403,
        )
        self.assertTrue(
            IndicatorEvaluationThreshold.objects.filter(pk=target.pk).exists()
        )

    def test_clone_remaps_thresholds_and_selection_save_keeps_existing_rows(self):
        from rpsd_config.exchange_agreement.services.contract_revisions import (
            replace_draft_configuration,
        )
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            clone_evaluations,
        )

        target = self.threshold()
        penalty = IndicatorPenalty.objects.create(
            contract_revision_indicator=self.owner,
            code="fixed",
            name="Fixed",
            activation_threshold=target,
            calculation_method="fixed_amount",
            fixed_amount=Decimal("500"),
            currency="EUR",
            amount_rounding_mode="half_up",
        )
        second = self._revision(number=2, valid_from=self.contract.start_date)
        other_owner = second.indicator_configurations.get()
        clone_evaluations(self.owner, other_owner, actor=self.user)
        copied = other_owner.evaluation_penalties.get()
        self.assertNotEqual(
            copied.activation_threshold_id, penalty.activation_threshold_id
        )
        self.assertEqual(
            copied.activation_threshold.contract_revision_indicator_id, other_owner.pk
        )
        replace_draft_configuration(
            self.revision,
            selections=list(
                self.revision.input_selections.values_list(
                    "processing_profile_input_flow_id", flat=True
                )
            ),
            indicator_configs=[
                {
                    "processing_profile_indicator_version": (
                        self.owner.processing_profile_indicator_version
                    ),
                    "parameters": self.owner.parameters,
                    "aggregation": self.owner.aggregation,
                }
            ],
            actor=self.user,
        )
        self.assertTrue(
            IndicatorEvaluationThreshold.objects.filter(pk=target.pk).exists()
        )
        self.assertTrue(IndicatorPenalty.objects.filter(pk=penalty.pk).exists())

    def test_draft_removal_handles_protected_internal_references(self):
        from rpsd_config.exchange_agreement.services.contract_drafts import (
            delete_revision_draft,
        )

        target = self.threshold()
        IndicatorPenalty.objects.create(
            contract_revision_indicator=self.owner,
            code="fixed",
            name="Fixed",
            activation_threshold=target,
            calculation_method="fixed_amount",
            fixed_amount=Decimal("500"),
        )
        delete_revision_draft(self.revision, actor=self.user)
        self.assertFalse(
            IndicatorEvaluationThreshold.objects.filter(pk=target.pk).exists()
        )

    def test_penalty_combination_is_explicit_and_quantity_dimensions_match(self):
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            evaluation_snapshot,
        )

        target = self.threshold()
        penalty = IndicatorPenalty.objects.create(
            contract_revision_indicator=self.owner,
            code="fixed",
            name="Fixed",
            activation_threshold=target,
            calculation_method="fixed_amount",
            fixed_amount=Decimal("500"),
            currency="EUR",
            amount_rounding_mode="half_up",
        )
        self.assertEqual(
            evaluation_snapshot(self.revision)[0]["penalty_combination_policy"],
            "cumulative",
        )
        penalty.fixed_amount = Decimal("-1")
        with self.assertRaises(ValidationError):
            penalty.save()

    def test_closed_end_requirement_and_duration_overflow(self):
        from datetime import date

        target = self.threshold(
            period_type="custom_duration_days",
            period_start_date=self.contract.start_date,
            period_days=2,
        )
        target.period_start_date = date.max
        target.period_days = 2
        with self.assertRaises(ValidationError):
            period_context(target, complete=True)
        from django.db import models

        models.QuerySet(self.contract.__class__).filter(pk=self.contract.pk).update(
            end_date=None
        )
        target = self.threshold(
            code="until-end",
            period_type="custom_to_contract_end",
            period_start_date=self.contract.start_date,
        )
        with self.assertRaises(ValidationError):
            serialize_evaluation(target)


class EvaluationSeedTests(TestCase):
    def test_seed_twice_has_stable_relations_and_distinct_contract_parameters(self):
        from django.contrib.auth import get_user_model

        from rpsd_config.exchange_agreement.services.evaluation_seed import (
            ensure_evaluation_demo,
        )

        actor = get_user_model().objects.create_user(
            username="032-seeder", is_superuser=True, is_staff=True
        )
        profile, revisions = ensure_evaluation_demo(actor=actor)
        owners = [r.indicator_configurations.get() for r in revisions]
        self.assertNotEqual(owners[0].parameters, owners[1].parameters)
        before = list(
            IndicatorEvaluationThreshold.objects.order_by("pk").values_list(
                "pk", flat=True
            )
        )
        again, repeated = ensure_evaluation_demo(actor=actor)
        self.assertEqual(profile.pk, again.pk)
        self.assertEqual([r.pk for r in revisions], [r.pk for r in repeated])
        self.assertEqual(
            before,
            list(
                IndicatorEvaluationThreshold.objects.order_by("pk").values_list(
                    "pk", flat=True
                )
            ),
        )
        self.assertEqual(IndicatorPenalty.objects.count(), 2)
        self.assertTrue(all(r.status == "draft" for r in repeated))

    def test_inventory_reports_legacy_without_modifying_it(self):
        from io import StringIO

        from django.core.management import call_command

        output = StringIO()
        call_command("inventory_indicator_evaluations", stdout=output)
        self.assertIn('"count": 0', output.getvalue())

    def test_new_economic_json_writes_are_rejected(self):
        from django.contrib.auth import get_user_model

        from rpsd_config.exchange_agreement.services.evaluation_seed import (
            ensure_evaluation_demo,
        )
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        actor = get_user_model().objects.create_user(
            username="032-cutover", is_superuser=True
        )
        _, revisions = ensure_evaluation_demo(actor=actor)
        owner = revisions[0].indicator_configurations.get()
        with self.assertRaisesMessage(ValidationError, "read-only"):
            save_revision_indicator_values(
                revisions[0],
                version_code=owner.processing_profile_indicator_version.indicator_version.code,
                values={
                    "parameters": owner.parameters,
                    "aggregation": {},
                    "thresholds": {"minimum": "10"},
                    "penalties": {},
                },
                actor=actor,
            )
        owner.refresh_from_db()
        self.assertEqual(owner.thresholds, {})


class EvaluationConcurrencyTests(_EvaluationFixtureMixin, TransactionTestCase):
    def test_approval_serializes_with_threshold_edit(self):
        from threading import Barrier, Thread

        from django.db import close_old_connections

        from rpsd_config.exchange_agreement.models import ContractConfigurationRevision

        barrier = Barrier(2)
        target = self.threshold()
        failures = []

        def edit():
            close_old_connections()
            try:
                with transaction.atomic():
                    ContractConfigurationRevision.objects.select_for_update().get(
                        pk=self.revision.pk
                    )
                    barrier.wait(timeout=20)
                    current = IndicatorEvaluationThreshold.objects.get(pk=target.pk)
                    current.limit_value = Decimal("8")
                    current.save()
            except Exception as exc:
                failures.append(exc)
            finally:
                close_old_connections()

        def approve():
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                self._approve_first_revision(self.revision)
            except Exception as exc:
                failures.append(exc)
            finally:
                close_old_connections()

        threads = [Thread(target=edit), Thread(target=approve)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=40)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.revision.refresh_from_db()
        threshold = self.revision.configuration_snapshot["evaluation_configurations"][
            0
        ]["thresholds"][0]
        self.assertEqual(Decimal(threshold["limit_value"]), Decimal("8"))

    def test_approval_winner_blocks_later_edit(self):
        from threading import Barrier, Thread

        from django.db import close_old_connections

        from rpsd_config.exchange_agreement.models import ContractConfigurationRevision

        barrier = Barrier(2)
        target = self.threshold()
        outcomes = []

        def approve():
            close_old_connections()
            try:
                with transaction.atomic():
                    self.contract.__class__.objects.select_for_update().get(
                        pk=self.contract.pk
                    )
                    ContractConfigurationRevision.objects.select_for_update().get(
                        pk=self.revision.pk
                    )
                    barrier.wait(timeout=20)
                    self._approve_first_revision(self.revision)
                outcomes.append("approved")
            finally:
                close_old_connections()

        def edit():
            close_old_connections()
            try:
                barrier.wait(timeout=20)
                current = IndicatorEvaluationThreshold.objects.get(pk=target.pk)
                current.limit_value = Decimal("8")
                current.save()
                outcomes.append("edited")
            except ValidationError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [Thread(target=approve), Thread(target=edit)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=40)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(set(outcomes), {"approved", "rejected"})
        self.assertEqual(
            IndicatorEvaluationThreshold.objects.get(pk=target.pk).limit_value,
            Decimal("3"),
        )
