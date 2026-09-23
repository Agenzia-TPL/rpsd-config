# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    AgencyMembership,
    ContractConfigurationRevision,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    ContractRevisionPermissionError,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    ContractRevisionValidationError,
    approve_revision,
    available_processing_profiles,
    create_replacement_revision,
    create_revision_draft,
    replace_draft_configuration,
    validate_revision_for_approval,
    withdraw_revision,
)

from .test_contract_configuration_revisions import _ContractRevisionFixtureMixin


class RevisionCompositionApprovalTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.agency_user = get_user_model().objects.create_user(
            username="agency-revision-editor",
            password="test-password",
        )
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.agency_user,
            role=AgencyMembership.Role.AGENCY_EDITOR,
            status=AgencyMembership.Status.ACTIVE,
            created_by=self.user,
        )
        self.agency_admin = get_user_model().objects.create_user(
            username="agency-revision-admin",
            password="test-password",
        )
        AgencyMembership.objects.create(
            agency=self.agency,
            user=self.agency_admin,
            role=AgencyMembership.Role.AGENCY_ADMIN,
            status=AgencyMembership.Status.ACTIVE,
            created_by=self.user,
        )

    def test_agency_creates_complete_guided_draft_from_published_profile(self):
        revision = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_user,
            change_reason="Initial monitoring configuration.",
        )

        self.assertEqual(revision.revision_number, 1)
        self.assertEqual(revision.created_by, self.agency_user)
        self.assertEqual(revision.input_selections.count(), 2)
        configuration = revision.indicator_configurations.get()
        self.assertEqual(configuration.contract_indicator, self.contract_indicator)
        self.assertEqual(validate_revision_for_approval(revision), ())
        self.assertEqual(
            available_processing_profiles(self.contract, self.agency_user),
            (self.profile,),
        )

        draft_profile = ProcessingProfileVersion.objects.create(
            code="unpublished-profile_001",
            version="001",
            name="Unpublished profile",
            description="Profile not yet approved by the platform.",
            orchestration_flow_version=(self.profile.orchestration_flow_version),
        )
        with self.assertRaises(ContractRevisionValidationError) as raised:
            create_revision_draft(
                self.contract,
                draft_profile,
                timezone.localdate(),
                self.agency_user,
            )
        self.assertEqual(raised.exception.code, "profile_not_published")

    def test_replace_derives_mandatory_inputs_and_is_atomic(self):
        revision = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_user,
        )
        configuration = revision.indicator_configurations.get()

        replace_draft_configuration(
            revision,
            selections=[],
            indicator_configs=[
                {
                    "contract_indicator": configuration.contract_indicator,
                    "processing_profile_indicator_version": (
                        configuration.processing_profile_indicator_version
                    ),
                    "thresholds": {"minimum": "15.5"},
                }
            ],
            actor=self.agency_user,
        )

        issues = validate_revision_for_approval(revision)
        self.assertEqual(issues, ())
        self.assertEqual(revision.input_selections.count(), 2)

        with self.assertRaises(ValidationError):
            replace_draft_configuration(
                revision,
                selections=[self.profile_input],
                indicator_configs=[
                    {
                        "contract_indicator": configuration.contract_indicator,
                        "processing_profile_indicator_version": (
                            configuration.processing_profile_indicator_version
                        ),
                        "parameters": {"cron": "0 0 * * *"},
                    }
                ],
                actor=self.agency_user,
            )
        self.assertEqual(revision.input_selections.count(), 2)
        self.assertEqual(revision.indicator_configurations.count(), 1)

    def test_contract_owner_approves_and_approval_is_atomic(self):
        revision = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_user,
            change_reason="Approved configuration reason.",
        )
        with self.assertRaises(ContractRevisionPermissionError):
            approve_revision(revision, self.agency_user)

        with patch(
            "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
            return_value=self.contract.start_date,
        ):
            approved = approve_revision(revision, self.agency_admin)

        event = approved.status_events.get()
        self.assertEqual(event.to_status, ContractConfigurationRevision.Status.APPROVED)
        self.assertEqual(event.changed_by, self.agency_admin)
        self.assertEqual(event.snapshot_checksum, approved.snapshot_checksum)
        self.assertEqual(event.reason, "Approved configuration reason.")

    def test_external_selection_and_snapshot_failure_leave_draft_unchanged(self):
        revision = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_user,
        )
        foreign_profile = ProcessingProfileVersion.objects.create(
            code="foreign-profile_001",
            version="001",
            name="Foreign profile",
            description="Profile used to verify membership validation.",
            orchestration_flow_version=self.profile.orchestration_flow_version,
        )
        foreign_input = ProcessingProfileInputFlow.objects.create(
            processing_profile_version=foreign_profile,
            dataset=self.profile_input.dataset,
            input_flow_version=self.profile_input.input_flow_version,
        )
        revision.input_selections.filter(
            processing_profile_input_flow=self.profile_input
        ).update(processing_profile_input_flow=foreign_input)
        issues = validate_revision_for_approval(revision)
        self.assertIn("input_not_in_profile", {issue.code for issue in issues})

        revision.input_selections.filter(
            processing_profile_input_flow=foreign_input
        ).update(processing_profile_input_flow=self.profile_input)
        with (
            patch(
                "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
                return_value=self.contract.start_date,
            ),
            patch(
                "rpsd_config.exchange_agreement.services.contract_revisions.build_revision_snapshot",
                side_effect=TypeError("snapshot failure"),
            ),
            self.assertRaisesMessage(TypeError, "snapshot failure"),
        ):
            approve_revision(revision, self.agency_admin)

        revision.refresh_from_db()
        self.assertEqual(revision.status, ContractConfigurationRevision.Status.DRAFT)
        self.assertEqual(revision.configuration_snapshot, {})
        self.assertEqual(revision.snapshot_checksum, "")
        self.assertFalse(revision.status_events.exists())

    def test_replacement_and_future_withdrawal_keep_audit_and_snapshot(self):
        first = create_revision_draft(
            self.contract,
            self.profile,
            self.contract.start_date,
            self.agency_user,
        )
        with patch(
            "rpsd_config.exchange_agreement.services.contract_revisions.timezone.localdate",
            return_value=self.contract.start_date,
        ):
            first = approve_revision(first, self.agency_admin)

        replacement = create_replacement_revision(
            first,
            self.profile,
            self.agency_user,
            change_reason="Move to the replacement configuration.",
        )
        replacement.valid_from = timezone.localdate() + timedelta(days=1)
        replacement.save()
        replacement = approve_revision(replacement, self.agency_admin)
        original_snapshot = replacement.configuration_snapshot

        with self.assertRaises(ContractRevisionValidationError) as raised:
            withdraw_revision(replacement, "", self.agency_admin)
        self.assertEqual(raised.exception.code, "withdrawal_reason_required")

        replacement = withdraw_revision(
            replacement,
            "Deployment superseded before its effective date.",
            self.agency_admin,
        )
        self.assertEqual(
            replacement.status,
            ContractConfigurationRevision.Status.WITHDRAWN,
        )
        self.assertEqual(replacement.configuration_snapshot, original_snapshot)
        event = replacement.status_events.order_by("changed_at", "id").last()
        self.assertEqual(
            event.to_status,
            ContractConfigurationRevision.Status.WITHDRAWN,
        )
        self.assertEqual(
            event.reason,
            "Deployment superseded before its effective date.",
        )
