# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    Authority,
    AuthorityMembership,
    Company,
    Contract,
    ContractConfigurationRevision,
    ContractIndicator,
    ContractIndicatorConfiguration,
    ContractInputSelection,
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    InputFlowVersion,
    Lot,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    RequirementFragment,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionError,
    approve_contract_revision,
    canonical_json_bytes,
    canonical_snapshot_checksum,
    resolve_current_contract_revision,
    revision_effective_period,
    revision_temporal_state,
    withdraw_contract_revision,
)
from rpsd_config.exchange_agreement.services.dataset_catalog import (
    publish_dataset_specification,
)
from rpsd_config.exchange_agreement.services.flow_catalog import (
    publish_input_flow_version,
    publish_orchestration_flow_version,
)
from rpsd_config.exchange_agreement.services.flow_catalog_registry import (
    transport_message_invocation_contract,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.exchange_agreement.services.requirement_fragments import (
    publish_requirement_fragment,
)


class _ContractRevisionFixtureMixin:
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="revision-admin",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )
        self.agency = Agency.objects.create(
            name="Agency Milano",
            agency_key="agency-milano",
        )
        self.company = Company.objects.create(name="TPL Company")
        self.lot = Lot.objects.create(
            agency=self.agency,
            short_description="LOT-A",
            description="Lot A",
        )
        today = timezone.localdate()
        self.contract = Contract.objects.create(
            contract_code="CTR-REV-001",
            client_agency=self.agency,
            contractor_company=self.company,
            lot=self.lot,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=365),
            status=Contract.ContractStatus.ACTIVE,
        )
        self.profile = self._published_processing_profile()
        self.contract_indicator = ContractIndicator.objects.create(
            contract=self.contract,
            logical_indicator=self.logical_indicator,
        )

    def _published_processing_profile(self):
        dataset = Dataset.objects.create(code="netex", name="NeTEx")
        specification = publish_dataset_specification(
            DatasetSpecification.objects.create(
                dataset=dataset,
                code="netex-ita_v001",
                version="001",
                description="NeTEx Italia v1",
            ),
            actor=self.user,
        )
        fragment = publish_requirement_fragment(
            RequirementFragment.objects.create(
                dataset_specification=specification,
                code="scheduled-journey-movement",
                name="Scheduled journey movement",
                description="Required scheduled journey movement.",
                locator_type=RequirementFragment.LocatorType.XPATH,
                result_kind=RequirementFragment.ResultKind.PRESENCE,
                locator_definition={
                    "path": "//netex:ServiceJourney",
                    "namespaces": {"netex": "urn:netex"},
                },
            ),
            actor=self.user,
        )
        siri_dataset = Dataset.objects.create(code="siri-vm", name="SIRI VM")
        siri_specification = publish_dataset_specification(
            DatasetSpecification.objects.create(
                dataset=siri_dataset,
                code="siri-vm_v003",
                version="003",
                description="SIRI VM v3",
            ),
            actor=self.user,
        )
        siri_fragment = publish_requirement_fragment(
            RequirementFragment.objects.create(
                dataset_specification=siri_specification,
                code="observed-journey-movement",
                name="Observed journey movement",
                description="Required observed journey movement.",
                locator_type=RequirementFragment.LocatorType.XPATH,
                result_kind=RequirementFragment.ResultKind.PRESENCE,
                locator_definition={
                    "path": "//siri:VehicleActivity",
                    "namespaces": {"siri": "urn:siri"},
                },
            ),
            actor=self.user,
        )
        self.logical_indicator = Indicator.objects.create(
            code="commercial-speed-target",
            name="Commercial speed",
            description="Average commercial speed.",
        )
        indicator_version = IndicatorVersion.objects.create(
            indicator=self.logical_indicator,
            code="commercial-speed-target_001",
            version="001",
            description="Commercial speed definition.",
            formula_description="Distance divided by elapsed time.",
        )
        indicator_version.required_fragments.add(fragment, siri_fragment)
        indicator_version = publish_indicator_version(
            indicator_version, actor=self.user
        )
        input_flow = publish_input_flow_version(
            InputFlowVersion.objects.create(
                dataset_specification=specification,
                code="netex-import_002",
                version="002",
                name="NeTEx import",
                description="Validate and import NeTEx.",
                deployment_name="validators/netex-default",
                artifact_identifier="git:rpsd-flows@netex-import-002",
                invocation_contract=transport_message_invocation_contract(),
                compatibility={"schema_version": 1, "what": "netex"},
            ),
            actor=self.user,
        )
        siri_input_flow = publish_input_flow_version(
            InputFlowVersion.objects.create(
                dataset_specification=siri_specification,
                code="siri-vm-import_003",
                version="003",
                name="SIRI VM import",
                description="Validate and import SIRI VM.",
                deployment_name="validators/siri-vm-default",
                artifact_identifier="git:rpsd-flows@siri-vm-import-003",
                invocation_contract=transport_message_invocation_contract(),
                compatibility={"schema_version": 1, "what": "siri-vm"},
            ),
            actor=self.user,
        )
        orchestration = publish_orchestration_flow_version(
            OrchestrationFlowVersion.objects.create(
                code="contract-processing_001",
                version="001",
                name="Contract processing",
                description="Coordinate contract processing.",
                deployment_name="contract-processing/default",
                artifact_identifier="git:rpsd-flows@contract-processing-001",
                invocation_contract=transport_message_invocation_contract(),
            ),
            actor=self.user,
        )
        profile = ProcessingProfileVersion.objects.create(
            code="tpl-netex_001",
            version="001",
            name="TPL NeTEx",
            description="NeTEx contract monitoring.",
            orchestration_flow_version=orchestration,
        )
        self.profile_input = ProcessingProfileInputFlow.objects.create(
            processing_profile_version=profile,
            dataset=dataset,
            input_flow_version=input_flow,
        )
        self.siri_profile_input = ProcessingProfileInputFlow.objects.create(
            processing_profile_version=profile,
            dataset=siri_dataset,
            input_flow_version=siri_input_flow,
        )
        self.profile_indicator = ProcessingProfileIndicatorVersion.objects.create(
            processing_profile_version=profile,
            indicator_version=indicator_version,
            proposed_by_default=True,
        )
        return publish_processing_profile(profile, actor=self.user)

    def _revision(self, *, number, valid_from, code=None, replaces=None):
        revision = ContractConfigurationRevision.objects.create(
            contract=self.contract,
            revision_number=number,
            code=code or f"ctr-rev-001-r{number:03d}",
            processing_profile_version=self.profile,
            valid_from=valid_from,
            change_reason=f"Revision {number}",
            replaces_revision=replaces,
            created_by=self.user,
        )
        ContractInputSelection.objects.create(
            revision=revision,
            processing_profile_input_flow=self.profile_input,
        )
        ContractInputSelection.objects.create(
            revision=revision,
            processing_profile_input_flow=self.siri_profile_input,
        )
        ContractIndicatorConfiguration.objects.create(
            revision=revision,
            contract_indicator=self.contract_indicator,
            processing_profile_indicator_version=self.profile_indicator,
            thresholds={"minimum": "15.5", "unit": "km/h"},
            aggregation={
                "method": "average",
                "period": "P1M",
                "dimensions": ["line", "journey"],
            },
            penalties={"enabled": True, "currency": "EUR"},
            parameters={"minimum_samples": 10},
        )
        return revision

    def _approve_first_revision(self, revision):
        with patch(
            "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
            return_value=self.contract.start_date,
        ):
            return approve_contract_revision(revision, actor=self.user)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class ContractConfigurationRevisionTests(_ContractRevisionFixtureMixin, TestCase):
    def test_lot_ownership_and_inclusive_contract_overlap(self):
        other_agency = Agency.objects.create(
            name="Other Agency", agency_key="other-agency"
        )
        foreign_lot = Lot.objects.create(
            agency=other_agency,
            short_description="LOT-X",
            description="Foreign lot",
        )
        with self.assertRaises(ValidationError):
            Contract.objects.create(
                contract_code="CTR-WRONG-LOT",
                client_agency=self.agency,
                contractor_company=self.company,
                lot=foreign_lot,
                start_date=timezone.localdate(),
                end_date=timezone.localdate() + timedelta(days=1),
            )
        with self.assertRaises(ValidationError):
            Contract.objects.create(
                contract_code="CTR-OVERLAP",
                client_agency=self.agency,
                contractor_company=self.company,
                lot=self.lot,
                start_date=self.contract.end_date,
                end_date=self.contract.end_date + timedelta(days=10),
            )

    def test_approval_builds_snapshot_and_derived_timeline(self):
        first = self._approve_first_revision(
            self._revision(
                number=1,
                valid_from=self.contract.start_date,
            )
        )
        second = approve_contract_revision(
            self._revision(
                number=2,
                valid_from=timezone.localdate(),
                replaces=first,
            ),
            actor=self.user,
        )

        self.assertEqual(
            revision_effective_period(first),
            (self.contract.start_date, timezone.localdate() - timedelta(days=1)),
        )
        self.assertEqual(
            revision_effective_period(second),
            (timezone.localdate(), self.contract.end_date),
        )
        self.assertEqual(resolve_current_contract_revision(self.contract), second)
        self.assertEqual(revision_temporal_state(first), "expired")
        self.assertEqual(revision_temporal_state(second), "active")
        self.assertNotIn("valid_to", second.configuration_snapshot["revision"])
        self.assertRegex(second.snapshot_checksum, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(
            second.configuration_snapshot["orchestration_flow"]["artifact_identifier"],
            "git:rpsd-flows@contract-processing-001",
        )

    def test_snapshot_is_canonical_and_approved_content_is_immutable(self):
        left = {"b": [Decimal("1.20"), {"z": 1, "a": 2}], "a": "value"}
        right = {"a": "value", "b": [Decimal("1.20"), {"a": 2, "z": 1}]}
        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(
            canonical_snapshot_checksum(left), canonical_snapshot_checksum(right)
        )

        revision = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        original_checksum = revision.snapshot_checksum
        revision.change_reason = "Mutated"
        with self.assertRaises(ValidationError):
            revision.save()
        configuration = revision.indicator_configurations.get()
        configuration.thresholds = {"minimum": "99"}
        with self.assertRaises(ValidationError):
            configuration.save()
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                ContractConfigurationRevision.objects.filter(pk=revision.pk).delete()
        revision.refresh_from_db()
        self.assertEqual(revision.snapshot_checksum, original_checksum)

    def test_sequence_rejects_gaps_in_start_and_retroactive_changes(self):
        with self.assertRaisesMessage(
            ContractRevisionError,
            "first revision must start",
        ):
            approve_contract_revision(
                self._revision(number=1, valid_from=timezone.localdate()),
                actor=self.user,
            )

        first = self._approve_first_revision(
            self._revision(
                number=2,
                code="ctr-rev-001-r002",
                valid_from=self.contract.start_date,
            )
        )
        with self.assertRaisesMessage(ContractRevisionError, "retroactively"):
            approve_contract_revision(
                self._revision(
                    number=3,
                    valid_from=timezone.localdate() - timedelta(days=1),
                    replaces=first,
                ),
                actor=self.user,
            )
        with self.assertRaises(TypeError):
            resolve_current_contract_revision(
                self.contract,
                reference_date=timezone.localdate(),
            )

    def test_only_future_approved_revision_can_be_withdrawn(self):
        first = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        with self.assertRaisesMessage(ContractRevisionError, "cannot be withdrawn"):
            withdraw_contract_revision(
                first,
                reason="Attempt to withdraw current configuration.",
                actor=self.user,
            )

        future = approve_contract_revision(
            self._revision(
                number=2,
                valid_from=timezone.localdate() + timedelta(days=10),
                replaces=first,
            ),
            actor=self.user,
        )
        future = withdraw_contract_revision(
            future,
            reason="The planned configuration is no longer needed.",
            actor=self.user,
        )
        self.assertEqual(future.status, ContractConfigurationRevision.Status.WITHDRAWN)
        self.assertEqual(revision_effective_period(first)[1], self.contract.end_date)

    def test_business_period_is_allowed_but_flow_scheduling_is_not(self):
        revision = self._revision(number=1, valid_from=self.contract.start_date)
        configuration = revision.indicator_configurations.get()
        configuration.aggregation = {"period": "P1M", "window": "calendar-month"}
        configuration.save()
        configuration.parameters = {"cron": "0 0 * * *"}
        with self.assertRaises(ValidationError):
            configuration.save()

        forbidden = {"cron", "frequency", "trigger", "interval", "schedule"}
        fields = {
            field.name for field in ContractIndicatorConfiguration._meta.get_fields()
        }
        self.assertFalse(fields & forbidden)

    def test_authority_membership_is_read_only_contract_visibility(self):
        authority = Authority.objects.create(
            name="Regione Lombardia",
            authority_type=Authority.AuthorityType.REGION,
        )
        authority_user = get_user_model().objects.create_user(
            username="authority-reader",
            password="test-password",
        )
        AuthorityMembership.objects.create(
            authority=authority,
            user=authority_user,
            created_by=self.user,
        )
        self.contract.governing_authority = authority
        self.contract.save()
        self.client.force_login(authority_user)

        response = self.client.get(
            f"/exchange_agreement/api/v1/contracts/{self.contract.contract_code}"
        )
        self.assertEqual(response.status_code, 200)
        write_response = self.client.put(
            f"/exchange_agreement/api/v1/contracts/{self.contract.contract_code}/flow-profile",
            data={"flow_profile_code": "irrelevant"},
            content_type="application/json",
        )
        self.assertEqual(write_response.status_code, 403)


@override_settings(ROOT_URLCONF="rpsd_config.server.urls")
class ContractRevisionConcurrencyTests(
    _ContractRevisionFixtureMixin,
    TransactionTestCase,
):
    reset_sequences = True

    def test_concurrent_approvals_keep_one_revision_per_effective_date(self):
        first = self._approve_first_revision(
            self._revision(number=1, valid_from=self.contract.start_date)
        )
        effective_date = timezone.localdate() + timedelta(days=5)
        candidates = [
            self._revision(
                number=number,
                code=f"ctr-rev-001-concurrent-{number}",
                valid_from=effective_date,
                replaces=first,
            )
            for number in (2, 3)
        ]
        barrier = Barrier(2)
        outcomes = []

        def approve(revision_id):
            close_old_connections()
            revision = ContractConfigurationRevision.objects.get(pk=revision_id)
            actor = get_user_model().objects.get(pk=self.user.pk)
            barrier.wait()
            try:
                approve_contract_revision(revision, actor=actor)
                outcomes.append("approved")
            except ContractRevisionError:
                outcomes.append("rejected")
            finally:
                close_old_connections()

        threads = [
            Thread(target=approve, args=(revision.pk,)) for revision in candidates
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(sorted(outcomes), ["approved", "rejected"])
        self.assertEqual(
            ContractConfigurationRevision.objects.filter(
                contract=self.contract,
                status=ContractConfigurationRevision.Status.APPROVED,
                valid_from=effective_date,
            ).count(),
            1,
        )
