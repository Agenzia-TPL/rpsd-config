# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent development seed for the target configuration model."""

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyMembership,
    Authority,
    Company,
    Contract,
    ContractConfigurationRevision,
    ContractMembership,
    ContractPublication,
    Lot,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
)
from rpsd_config.exchange_agreement.services.contract_revisions import (
    approve_contract_revision,
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.flow_catalog_bootstrap import (
    ensure_standard_flow_catalog,
)
from rpsd_config.exchange_agreement.services.indicator_catalog_bootstrap import (
    ensure_commercial_speed_example,
)
from rpsd_config.exchange_agreement.services.processing_profiles import (
    publish_processing_profile,
)
from rpsd_config.exchange_agreement.services.publication import publish_contract


@dataclass(frozen=True)
class DevelopmentSeedResult:
    contract_code: str
    revision_code: str
    profile_code: str
    publication_version: int


def _ensure_platform_user():
    user_model = get_user_model()
    user, _created = user_model.objects.get_or_create(
        username="dummy_admin",
        defaults={"email": "dummy_admin@example.com"},
    )
    changed_fields = []
    for field_name in ("is_active", "is_staff", "is_superuser"):
        if not getattr(user, field_name):
            setattr(user, field_name, True)
            changed_fields.append(field_name)
    user.set_password("dummy_admin")
    changed_fields.append("password")
    user.save(update_fields=changed_fields)
    return user


def _ensure_processing_profile(*, actor) -> ProcessingProfileVersion:
    input_flows, orchestration = ensure_standard_flow_catalog()
    indicator_version = ensure_commercial_speed_example(actor=actor)
    profile, _created = ProcessingProfileVersion.objects.get_or_create(
        code="netex-siri-commercial-speed_001",
        defaults={
            "version": "001",
            "name": "NeTEx and SIRI commercial speed",
            "description": (
                "Development profile covering the inputs required by commercial speed "
                "and an optional SIRI PT input."
            ),
            "orchestration_flow_version": orchestration,
        },
    )
    if profile.status == ProcessingProfileVersion.Status.DRAFT:
        selected_flows = {
            flow.dataset_specification.dataset.code: flow
            for flow in input_flows
            if flow.dataset_specification.dataset.code
            in {"netex", "siri-vm", "siri-pt"}
        }
        for dataset_code in ("netex", "siri-vm", "siri-pt"):
            flow = selected_flows[dataset_code]
            ProcessingProfileInputFlow.objects.get_or_create(
                processing_profile_version=profile,
                dataset=flow.dataset_specification.dataset,
                defaults={"input_flow_version": flow},
            )
        ProcessingProfileIndicatorVersion.objects.get_or_create(
            processing_profile_version=profile,
            indicator_version=indicator_version,
            defaults={"proposed_by_default": True},
        )
        profile = publish_processing_profile(profile)
    return profile


@transaction.atomic
def ensure_target_development_seed() -> DevelopmentSeedResult:
    """Create one complete target-model scenario without duplicating records."""

    if not settings.DEBUG:
        raise ValidationError("The demo seed is allowed only with DEBUG=True.")
    actor = _ensure_platform_user()
    profile = _ensure_processing_profile(actor=actor)
    from rpsd_config.exchange_agreement.services.validation_seed import (
        ensure_validation_demo,
    )

    profile = ensure_validation_demo(actor=actor)
    from rpsd_config.exchange_agreement.services.csv_validation_seed import (
        ensure_csv_validation_demo,
    )

    ensure_csv_validation_demo(actor=actor)
    agency, _created = Agency.objects.get_or_create(
        agency_key="demo-agency",
        defaults={
            "name": "Demo Agency",
            "description": "Development agency for the target configuration model.",
        },
    )
    company, _created = Company.objects.get_or_create(
        name="Demo TPL Company",
        defaults={"description": "Development public transport operator."},
    )
    authority, _created = Authority.objects.get_or_create(
        name="Demo Governing Authority",
        authority_type=Authority.AuthorityType.REGION,
        defaults={"description": "Read-only governing authority for the demo."},
    )
    lot, _created = Lot.objects.get_or_create(
        agency=agency,
        short_description="DEMO-LOT-1",
        defaults={"description": "Demo service lot"},
    )
    today = timezone.localdate()
    contract, _created = Contract.objects.get_or_create(
        contract_code="DEMO-CONTRACT-001",
        defaults={
            "client_agency": agency,
            "contractor_company": company,
            "governing_authority": authority,
            "lot": lot,
            "start_date": today,
            "status": Contract.ContractStatus.ACTIVE,
        },
    )
    AgencyMembership.objects.get_or_create(
        agency=agency,
        user=actor,
        defaults={
            "role": AgencyMembership.Role.AGENCY_ADMIN,
            "status": AgencyMembership.Status.ACTIVE,
            "created_by": actor,
        },
    )
    ContractMembership.objects.get_or_create(
        contract=contract,
        user=actor,
        defaults={
            "role": ContractMembership.Role.CONTRACT_ADMIN,
            "created_by": actor,
        },
    )

    revision = ContractConfigurationRevision.objects.filter(contract=contract).first()
    if revision is None:
        revision = create_revision_draft(
            contract,
            profile,
            today,
            actor,
            change_reason="Initial target-model development configuration.",
        )
        from rpsd_config.exchange_agreement.services.revision_indicator_values import (
            save_revision_indicator_values,
        )

        for code, parameters in (
            ("demo-composed-performance_001", {"sample_window_minutes": 15}),
            ("demo-journey-count_001", {"minimum_journeys": 1}),
        ):
            save_revision_indicator_values(
                revision,
                version_code=code,
                actor=actor,
                values={
                    "parameters": parameters,
                    "thresholds": {},
                    "aggregation": {},
                    "penalties": {},
                },
            )
        revision = approve_contract_revision(revision, actor=actor)

    if (
        revision.processing_profile_version_id != profile.pk
        or revision.snapshot_schema_version != "canonical-json-v2"
    ):
        raise ValidationError(
            "Existing development contract uses an obsolete seed; "
            "reset the explicit development target first."
        )

    publication = ContractPublication.objects.filter(contract=contract).first()
    if publication is None:
        publication = publish_contract(contract=contract, user=actor)

    return DevelopmentSeedResult(
        contract_code=contract.contract_code,
        revision_code=revision.code,
        profile_code=profile.code,
        publication_version=publication.publication_version,
    )
