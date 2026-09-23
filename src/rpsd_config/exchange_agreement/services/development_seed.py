# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Idempotent development seed for the target configuration model."""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyMembership,
    Authority,
    Company,
    Contract,
    ContractConfigurationRevision,
    ContractIndicator,
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


def _ensure_processing_profile() -> ProcessingProfileVersion:
    input_flows, orchestration = ensure_standard_flow_catalog()
    indicator_version = ensure_commercial_speed_example()
    profile, _created = ProcessingProfileVersion.objects.get_or_create(
        code="netex-siri-commercial-speed_001",
        defaults={
            "version": "001",
            "name": "NeTEx and SIRI commercial speed",
            "description": (
                "Development profile covering the inputs required by commercial speed."
            ),
            "orchestration_flow_version": orchestration,
        },
    )
    if profile.status == ProcessingProfileVersion.Status.DRAFT:
        selected_flows = {
            flow.dataset_specification.dataset.code: flow
            for flow in input_flows
            if flow.dataset_specification.dataset.code in {"netex", "siri-vm"}
        }
        for dataset_code in ("netex", "siri-vm"):
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

    actor = _ensure_platform_user()
    profile = _ensure_processing_profile()
    logical_indicator = (
        profile.indicator_version_links.select_related("indicator_version__indicator")
        .get(proposed_by_default=True)
        .indicator_version.indicator
    )

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

    ContractIndicator.objects.get_or_create(
        contract=contract,
        logical_indicator=logical_indicator,
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
        revision = approve_contract_revision(revision, actor=actor)

    publication = ContractPublication.objects.filter(contract=contract).first()
    if publication is None:
        publication = publish_contract(contract=contract, user=actor)

    return DevelopmentSeedResult(
        contract_code=contract.contract_code,
        revision_code=revision.code,
        profile_code=profile.code,
        publication_version=publication.publication_version,
    )
