# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import SessionAuth

from rpsd_config.server.bearer_auth import BearerTokenAuth
from rpsd_config.server.m2m_auth import M2MClientTokenAuth

from .models import (
    Agency,
    AgencyInvitation,
    Company,
    Contract,
    ContractIndicator,
    ContractInvitation,
    ContractMembership,
    ContractPublication,
    FlowProfile,
    IndicatorDef,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
    Structure,
)
from .rbac import resolve_user_agency_scope
from .services.agency_bootstrap import (
    AgencyBootstrapPermissionError,
    AgencyBootstrapProvisioningError,
    AgencyBootstrapValidationError,
    bootstrap_agency_with_admin_invitation,
)
from .services.agency_invitations import (
    AgencyInvitationPermissionError,
    AgencyInvitationProvisioningError,
    AgencyInvitationValidationError,
    create_agency_invitation,
)
from .services.m2m_audit import audit_m2m_event
from .services.m2m_grants import (
    accessible_contracts_for_principal,
    require_m2m_contract_access,
    require_m2m_principal,
)
from .services.publication import PublishContractError, publish_contract


class InvitationCheckResponse(Schema):
    valid: bool
    invitation_type: str
    status: str
    is_open_invitation: bool
    role_to_assign: str
    contract_code: str
    agency_key: str
    expires_at: str
    message: str


class InvitationStartResponse(Schema):
    ok: bool
    redirect_url: str
    provider_id: str
    invitation_type: str
    message: str


class AgencyInvitationCreateRequest(Schema):
    agency_id: int
    role_to_assign: str
    email: str | None = None
    provision_user_if_missing: bool = True


class AgencyInvitationCreateResponse(Schema):
    token: str
    invitation_url: str
    agency_id: int
    agency_key: str
    role_to_assign: str
    status: str
    expires_at: str
    assigned_group_path: str
    provisioned_user_id: str | None


class AgencyBootstrapRequest(Schema):
    agency_name: str
    initial_admin_email: str
    agency_key: str | None = None
    provision_user_if_missing: bool = True


class AgencyBootstrapResponse(Schema):
    agency_id: int
    agency_name: str
    agency_key: str
    invitation_token: str
    invitation_url: str
    invitation_status: str
    invitation_expires_at: str
    assigned_group_path: str
    provisioned_user_id: str | None


class DatasetRefSchema(Schema):
    slug: str
    name: str
    description: str


class StructureSchema(Schema):
    id: int
    name: str
    description: str
    dataset: DatasetRefSchema
    definition: dict
    xpath: str
    fields: list[str]


class IndicatorSchema(Schema):
    code: str
    type: str
    name: str
    description: str
    formula: str
    notes: str
    sql_procedure_name: str
    sql_snippet: str
    structures: list[StructureSchema]


class ContractIndicatorSchema(Schema):
    indicator: IndicatorSchema
    contract_params: dict | None


class FlowProfileRefSchema(Schema):
    code: str
    name: str
    schema_version: str
    is_active: bool


class FlowProfileSchema(FlowProfileRefSchema):
    description: str
    options: dict


class AgencyRefSchema(Schema):
    id: int
    name: str


class CompanyRefSchema(Schema):
    id: int
    name: str


class LotRefSchema(Schema):
    id: int
    short_description: str
    description: str


class ContractSummarySchema(Schema):
    contract_code: str
    status: str
    contract_type: str
    version: int
    start_date: str
    end_date: str | None
    tender_id: str
    is_active_today: bool
    lot: LotRefSchema
    client_agency: AgencyRefSchema
    contractor_company: CompanyRefSchema
    flow_profile: FlowProfileRefSchema | None


class ContractDetailSchema(ContractSummarySchema):
    contract_program_file: str | None
    contract_program_file_url: str | None
    replaced_by_contract_code: str | None
    closed_at: str | None
    closed_reason: str


class RequiredInputGroupSchema(Schema):
    dataset: DatasetRefSchema
    structures: list[StructureSchema]
    used_by_indicators: list[str]


class RequiredInputsResponse(Schema):
    contract_code: str
    required_inputs: list[RequiredInputGroupSchema]


class ContractFlowProfileResponse(Schema):
    contract_code: str
    flow_profile: FlowProfileSchema | None


class ContractFlowProfileUpdateRequest(Schema):
    flow_profile_code: str


class ContractCreateRequest(Schema):
    contract_code: str
    client_agency_id: int
    contractor_company_id: int
    lot_id: int
    start_date: date
    end_date: date | None = None
    tender_id: str = ""
    status: str = Contract.ContractStatus.DRAFT


class ContractInvitationCreateRequest(Schema):
    role_to_assign: str
    email: str | None = None


class ContractInvitationCreateResponse(Schema):
    token: str
    invitation_url: str
    contract_code: str
    role_to_assign: str
    status: str
    expires_at: str
    invitation_type: str = "contract"


class PublicationActorSchema(Schema):
    username: str
    email: str
    display_name: str


class ContractPublicationSummarySchema(Schema):
    id: int
    contract_code: str
    publication_version: int
    published_at: str
    published_by: PublicationActorSchema | None
    snapshot_schema_version: str
    snapshot_checksum: str


class ContractPublicationDetailSchema(ContractPublicationSummarySchema):
    snapshot: dict


class M2MCompanySchema(Schema):
    id: int
    name: str


class M2MMeSchema(Schema):
    keycloak_client_id: str
    environment: str
    status: str
    company: M2MCompanySchema


class M2MGrantSchema(Schema):
    contract_code: str
    action: str
    data_category: str | None
    status: str
    valid_from: str | None
    valid_to: str | None


class M2MUserSchema(Schema):
    username: str
    email: str
    display_name: str
    contract_codes: list[str]
    roles: list[str]


api = NinjaAPI(
    title="RPSD Exchange Agreement API",
    version="1.0",
    auth=[SessionAuth(), BearerTokenAuth()],
)

m2m_api = NinjaAPI(
    title="RPSD Exchange Agreement M2M API",
    version="1.0",
    auth=M2MClientTokenAuth(),
    urls_namespace="exchange-agreement-m2m-api",
)


def _oidc_provider_id() -> str:
    oidc_config = settings.SOCIALACCOUNT_PROVIDERS.get("openid_connect", {})
    apps = oidc_config.get("APPS") or []
    if not apps:
        return "keycloak"
    return apps[0].get("provider_id", "keycloak")


def _build_oidc_login_url(callback_url: str) -> str:
    provider_id = _oidc_provider_id()
    query = urlencode({"process": "login", "next": callback_url})
    return f"/accounts/oidc/{provider_id}/login/?{query}"


def _require_auth(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        raise HttpError(401, "Authentication required.")
    return user


def _authorized_contracts_qs(request):
    user = _require_auth(request)
    qs = Contract.objects.select_related(
        "lot", "client_agency", "contractor_company", "replaced_by", "flow_profile"
    )
    if user.is_superuser:
        return qs
    scope = resolve_user_agency_scope(user)
    if scope.is_platform_admin:
        return qs

    agency_keys = (
        set(scope.admin_agency_keys)
        | set(scope.editor_agency_keys)
        | set(scope.reader_agency_keys)
    )
    contract_filter = Q(memberships__user=user)
    if agency_keys:
        contract_filter |= Q(client_agency__agency_key__in=agency_keys)
    return qs.filter(contract_filter).distinct()


def _get_authorized_contract(request, contract_code: str) -> Contract:
    contract = (
        _authorized_contracts_qs(request).filter(contract_code=contract_code).first()
    )
    if contract is None:
        raise HttpError(404, "Contract not found.")
    return contract


def _can_create_contract_for_agency(*, user, agency_key: str) -> bool:
    if user.is_superuser:
        return True
    scope = resolve_user_agency_scope(user)
    return scope.is_platform_admin or agency_key in scope.admin_agency_keys


def _can_write_contract(*, user, contract: Contract) -> bool:
    if user.is_superuser:
        return True

    scope = resolve_user_agency_scope(user)
    agency_key = contract.client_agency.agency_key
    if scope.is_platform_admin or agency_key in scope.admin_agency_keys:
        return True
    if agency_key in scope.editor_agency_keys:
        return True

    return ContractMembership.objects.filter(
        contract=contract,
        user=user,
        role__in={
            ContractMembership.Role.CONTRACT_ADMIN,
            ContractMembership.Role.CONTRACT_EDITOR,
        },
    ).exists()


def _can_create_contract_invitation(*, user, contract: Contract) -> bool:
    if user.is_superuser:
        return True

    scope = resolve_user_agency_scope(user)
    agency_key = contract.client_agency.agency_key
    if scope.is_platform_admin:
        return True
    return (
        agency_key in scope.admin_agency_keys or agency_key in scope.editor_agency_keys
    )


def _require_contract_write(request, contract: Contract):
    user = _require_auth(request)
    if not _can_write_contract(user=user, contract=contract):
        raise HttpError(403, "Contract write scope required.")
    return user


def _require_contract_create(request, agency: Agency):
    user = _require_auth(request)
    if not _can_create_contract_for_agency(user=user, agency_key=agency.agency_key):
        raise HttpError(403, "Agency admin scope required to create contract.")
    return user


def _require_contract_invitation_creator(request, contract: Contract):
    user = _require_auth(request)
    if not _can_create_contract_invitation(user=user, contract=contract):
        raise HttpError(403, "Contract invitation scope required.")
    return user


def _dataset_ref(dataset) -> DatasetRefSchema:
    return DatasetRefSchema(
        slug=dataset.slug,
        name=dataset.name,
        description=dataset.description,
    )


def _flow_profile_ref_schema(
    flow_profile: FlowProfile | None,
) -> FlowProfileRefSchema | None:
    if flow_profile is None:
        return None
    return FlowProfileRefSchema(
        code=flow_profile.code,
        name=flow_profile.name,
        schema_version=flow_profile.schema_version,
        is_active=flow_profile.is_active,
    )


def _flow_profile_schema(flow_profile: FlowProfile) -> FlowProfileSchema:
    options = flow_profile.options if isinstance(flow_profile.options, dict) else {}
    return FlowProfileSchema(
        code=flow_profile.code,
        name=flow_profile.name,
        schema_version=flow_profile.schema_version,
        is_active=flow_profile.is_active,
        description=flow_profile.description,
        options=options,
    )


def _structure_schema(structure: Structure) -> StructureSchema:
    definition = structure.definition if isinstance(structure.definition, dict) else {}
    return StructureSchema(
        id=structure.id,
        name=structure.name,
        description=structure.description,
        dataset=_dataset_ref(structure.dataset),
        definition=definition,
        xpath=structure.get_xpath_selector(),
        fields=structure.get_mandatory_fields(),
    )


def _indicator_schema(indicator: IndicatorDef) -> IndicatorSchema:
    structures_raw = list(indicator.structures.all())
    structures_raw.sort(key=lambda s: (s.dataset.slug, s.name))
    structures = [_structure_schema(s) for s in structures_raw]
    return IndicatorSchema(
        code=indicator.code,
        type=indicator.type,
        name=indicator.name,
        description=indicator.description,
        formula=indicator.formula,
        notes=indicator.notes,
        sql_procedure_name=indicator.sql_procedure_name,
        sql_snippet=indicator.sql_snippet,
        structures=structures,
    )


def _contract_summary_schema(contract: Contract) -> ContractSummarySchema:
    return ContractSummarySchema(
        contract_code=contract.contract_code,
        status=contract.status,
        contract_type=contract.contract_type,
        version=contract.version,
        start_date=contract.start_date.isoformat(),
        end_date=contract.end_date.isoformat() if contract.end_date else None,
        tender_id=contract.tender_id,
        is_active_today=contract.is_active_today,
        lot=LotRefSchema(
            id=contract.lot_id,
            short_description=contract.lot.short_description,
            description=contract.lot.description,
        ),
        client_agency=AgencyRefSchema(
            id=contract.client_agency_id,
            name=contract.client_agency.name,
        ),
        contractor_company=CompanyRefSchema(
            id=contract.contractor_company_id,
            name=contract.contractor_company.name,
        ),
        flow_profile=_flow_profile_ref_schema(contract.flow_profile),
    )


def _contract_detail_schema(request, contract: Contract) -> ContractDetailSchema:
    file_name = (
        contract.contract_program_file.name if contract.contract_program_file else None
    )
    file_url = (
        request.build_absolute_uri(contract.contract_program_file.url)
        if contract.contract_program_file
        else None
    )
    return ContractDetailSchema(
        contract_code=contract.contract_code,
        status=contract.status,
        contract_type=contract.contract_type,
        version=contract.version,
        start_date=contract.start_date.isoformat(),
        end_date=contract.end_date.isoformat() if contract.end_date else None,
        tender_id=contract.tender_id,
        is_active_today=contract.is_active_today,
        lot=LotRefSchema(
            id=contract.lot_id,
            short_description=contract.lot.short_description,
            description=contract.lot.description,
        ),
        client_agency=AgencyRefSchema(
            id=contract.client_agency_id,
            name=contract.client_agency.name,
        ),
        contractor_company=CompanyRefSchema(
            id=contract.contractor_company_id,
            name=contract.contractor_company.name,
        ),
        flow_profile=_flow_profile_ref_schema(contract.flow_profile),
        contract_program_file=file_name,
        contract_program_file_url=file_url,
        replaced_by_contract_code=contract.replaced_by.contract_code
        if contract.replaced_by
        else None,
        closed_at=contract.closed_at.isoformat() if contract.closed_at else None,
        closed_reason=contract.closed_reason,
    )


def _require_agency_invitation_admin(request, agency: Agency):
    user = _require_auth(request)
    scope = resolve_user_agency_scope(user)
    if not scope.can_manage_agency(agency.agency_key):
        raise HttpError(403, "Agency admin scope required.")
    return user


def _require_platform_admin(request):
    user = _require_auth(request)
    if user.is_superuser:
        return user
    scope = resolve_user_agency_scope(user)
    if not scope.is_platform_admin:
        raise HttpError(403, "Platform admin scope required.")
    return user


def _publication_actor_schema(user) -> PublicationActorSchema | None:
    if not user:
        return None
    display_name = getattr(user, "get_full_name", lambda: "")() or getattr(
        user, "username", ""
    )
    return PublicationActorSchema(
        username=getattr(user, "username", ""),
        email=getattr(user, "email", ""),
        display_name=display_name,
    )


def _contract_publication_summary_schema(
    publication: ContractPublication,
) -> ContractPublicationSummarySchema:
    return ContractPublicationSummarySchema(
        id=publication.id,
        contract_code=publication.contract.contract_code,
        publication_version=publication.publication_version,
        published_at=publication.published_at.isoformat(),
        published_by=_publication_actor_schema(publication.published_by),
        snapshot_schema_version=publication.snapshot_schema_version,
        snapshot_checksum=publication.snapshot_checksum,
    )


def _contract_publication_detail_schema(
    publication: ContractPublication,
) -> ContractPublicationDetailSchema:
    summary = _contract_publication_summary_schema(publication)
    return ContractPublicationDetailSchema(
        id=summary.id,
        contract_code=summary.contract_code,
        publication_version=summary.publication_version,
        published_at=summary.published_at,
        published_by=summary.published_by,
        snapshot_schema_version=summary.snapshot_schema_version,
        snapshot_checksum=summary.snapshot_checksum,
        snapshot=publication.snapshot if isinstance(publication.snapshot, dict) else {},
    )


def _m2m_company_schema(company: Company) -> M2MCompanySchema:
    return M2MCompanySchema(id=company.id, name=company.name)


def _m2m_me_schema(principal: IntegrationPrincipal) -> M2MMeSchema:
    return M2MMeSchema(
        keycloak_client_id=principal.keycloak_client_id,
        environment=principal.environment,
        status=principal.status,
        company=_m2m_company_schema(principal.company),
    )


def _m2m_grant_schema(grant: IntegrationGrant) -> M2MGrantSchema:
    return M2MGrantSchema(
        contract_code=grant.contract.contract_code,
        action=grant.action,
        data_category=grant.data_category,
        status=grant.status,
        valid_from=grant.valid_from.isoformat() if grant.valid_from else None,
        valid_to=grant.valid_to.isoformat() if grant.valid_to else None,
    )


def _contract_required_inputs_schema(contract: Contract) -> RequiredInputsResponse:
    links = (
        ContractIndicator.objects.select_related("indicator")
        .prefetch_related("indicator__structures__dataset")
        .filter(contract=contract)
        .order_by("indicator__code")
    )

    groups: dict[str, dict] = {}
    for link in links:
        indicator_code = link.indicator.code
        for structure in link.indicator.structures.all():
            dataset = structure.dataset
            key = dataset.slug
            group = groups.setdefault(
                key,
                {
                    "dataset": _dataset_ref(dataset),
                    "structures_by_id": {},
                    "used_by_indicators": set(),
                },
            )
            group["structures_by_id"][structure.id] = _structure_schema(structure)
            group["used_by_indicators"].add(indicator_code)

    required_inputs = [
        RequiredInputGroupSchema(
            dataset=group["dataset"],
            structures=list(group["structures_by_id"].values()),
            used_by_indicators=sorted(group["used_by_indicators"]),
        )
        for _, group in sorted(groups.items())
    ]
    return RequiredInputsResponse(
        contract_code=contract.contract_code,
        required_inputs=required_inputs,
    )


def _contract_indicators_schema(contract: Contract) -> list[ContractIndicatorSchema]:
    links = (
        ContractIndicator.objects.select_related("indicator")
        .prefetch_related("indicator__structures__dataset")
        .filter(contract=contract)
        .order_by("indicator__code")
    )
    return [
        ContractIndicatorSchema(
            indicator=_indicator_schema(link.indicator),
            contract_params=link.params,
        )
        for link in links
    ]


def _m2m_user_schema_map(memberships) -> list[M2MUserSchema]:
    by_user: dict[int, dict] = {}
    for membership in memberships:
        user = membership.user
        item = by_user.setdefault(
            user.id,
            {
                "user": user,
                "contract_codes": set(),
                "roles": set(),
            },
        )
        item["contract_codes"].add(membership.contract.contract_code)
        item["roles"].add(membership.role)

    result = []
    for item in by_user.values():
        user = item["user"]
        display_name = getattr(user, "get_full_name", lambda: "")() or user.username
        result.append(
            M2MUserSchema(
                username=user.username,
                email=user.email,
                display_name=display_name,
                contract_codes=sorted(item["contract_codes"]),
                roles=sorted(item["roles"]),
            )
        )
    result.sort(key=lambda user: (user.email, user.username))
    return result


@m2m_api.get("/v1/me", response=M2MMeSchema)
def m2m_me(request):
    principal = require_m2m_principal(request)
    return _m2m_me_schema(principal)


@m2m_api.get("/v1/company", response=M2MCompanySchema)
def m2m_company(request):
    principal = require_m2m_principal(request)
    return _m2m_company_schema(principal.company)


@m2m_api.get("/v1/grants", response=list[M2MGrantSchema])
def m2m_grants(request):
    principal = require_m2m_principal(request)
    grants = (
        IntegrationGrant.objects.select_related("contract")
        .filter(principal=principal)
        .order_by("contract__contract_code", "action", "data_category", "id")
    )
    return [_m2m_grant_schema(grant) for grant in grants]


@m2m_api.get("/v1/contracts", response=list[ContractSummarySchema])
def m2m_contracts(request):
    principal = require_m2m_principal(request)
    contracts = accessible_contracts_for_principal(principal).order_by(
        "-start_date",
        "contract_code",
    )
    audit_m2m_event(
        "api.contracts_listed",
        principal_id=principal.pk,
        company_id=principal.company_id,
        keycloak_client_id=principal.keycloak_client_id,
    )
    return [_contract_summary_schema(contract) for contract in contracts]


@m2m_api.get("/v1/contracts/{contract_code}", response=ContractDetailSchema)
def m2m_contract_detail(request, contract_code: str):
    principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    audit_m2m_event(
        "api.contract_detail",
        principal_id=principal.pk,
        company_id=principal.company_id,
        keycloak_client_id=principal.keycloak_client_id,
        contract_code=contract.contract_code,
    )
    return _contract_detail_schema(request, contract)


@m2m_api.get(
    "/v1/contracts/{contract_code}/flow-profile",
    response=ContractFlowProfileResponse,
)
def m2m_contract_flow_profile(request, contract_code: str):
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    return ContractFlowProfileResponse(
        contract_code=contract.contract_code,
        flow_profile=_flow_profile_schema(contract.flow_profile)
        if contract.flow_profile
        else None,
    )


@m2m_api.get(
    "/v1/contracts/{contract_code}/required-inputs",
    response=RequiredInputsResponse,
)
def m2m_contract_required_inputs(request, contract_code: str):
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    return _contract_required_inputs_schema(contract)


@m2m_api.get(
    "/v1/contracts/{contract_code}/indicators",
    response=list[ContractIndicatorSchema],
)
def m2m_contract_indicators(request, contract_code: str):
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    return _contract_indicators_schema(contract)


@m2m_api.get(
    "/v1/contracts/{contract_code}/publications",
    response=list[ContractPublicationSummarySchema],
)
def m2m_contract_publications(request, contract_code: str):
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    publications = (
        ContractPublication.objects.select_related("contract", "published_by")
        .filter(contract=contract)
        .order_by("-publication_version")
    )
    return [_contract_publication_summary_schema(item) for item in publications]


@m2m_api.get("/v1/company/users", response=list[M2MUserSchema])
def m2m_company_users(request):
    principal = require_m2m_principal(request)
    memberships = (
        ContractMembership.objects.select_related("user", "contract")
        .filter(contract__contractor_company=principal.company)
        .order_by("user__email", "user__username", "contract__contract_code")
    )
    return _m2m_user_schema_map(memberships)


@m2m_api.get("/v1/contracts/{contract_code}/users", response=list[M2MUserSchema])
def m2m_contract_users(request, contract_code: str):
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    memberships = (
        ContractMembership.objects.select_related("user", "contract")
        .filter(contract=contract)
        .order_by("user__email", "user__username")
    )
    return _m2m_user_schema_map(memberships)


@api.get("/v1/contracts", response=list[ContractSummarySchema])
def list_contracts(
    request,
    status: str | None = None,
    lot_id: int | None = None,
    client_agency_id: int | None = None,
    contractor_company_id: int | None = None,
    active_on: date | None = None,
):
    qs = _authorized_contracts_qs(request)
    if status:
        qs = qs.filter(status=status)
    if lot_id:
        qs = qs.filter(lot_id=lot_id)
    if client_agency_id:
        qs = qs.filter(client_agency_id=client_agency_id)
    if contractor_company_id:
        qs = qs.filter(contractor_company_id=contractor_company_id)
    if active_on:
        qs = qs.filter(start_date__lte=active_on).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=active_on)
        )
    return [
        _contract_summary_schema(contract)
        for contract in qs.order_by("-start_date", "contract_code")
    ]


@api.get("/v1/contracts/{contract_code}", response=ContractDetailSchema)
def get_contract(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    return _contract_detail_schema(request, contract)


@api.post("/v1/contracts", response=ContractDetailSchema)
def create_contract(request, payload: ContractCreateRequest):
    agency = Agency.objects.filter(id=payload.client_agency_id).first()
    if agency is None:
        raise HttpError(404, "Client agency not found.")
    _require_contract_create(request, agency)

    lot = Lot.objects.filter(id=payload.lot_id, agency=agency).first()
    if lot is None:
        raise HttpError(404, "Lot not found.")

    company = Company.objects.filter(id=payload.contractor_company_id).first()
    if company is None:
        raise HttpError(404, "Contractor company not found.")

    allowed_status = {choice[0] for choice in Contract.ContractStatus.choices}
    if payload.status not in allowed_status:
        raise HttpError(400, "Unsupported contract status.")
    if payload.status == Contract.ContractStatus.CLOSED:
        raise HttpError(400, "Closed contracts cannot be created directly.")

    try:
        contract = Contract.objects.create(
            contract_code=payload.contract_code,
            client_agency=agency,
            contractor_company=company,
            lot=lot,
            start_date=payload.start_date,
            end_date=payload.end_date,
            tender_id=payload.tender_id,
            status=payload.status,
        )
    except ValidationError as exc:
        raise HttpError(400, f"Contract validation failed: {exc}") from exc
    except IntegrityError as exc:
        raise HttpError(
            400,
            "Unable to create contract due to constraint violation.",
        ) from exc

    return _contract_detail_schema(request, contract)


@api.post(
    "/v1/contracts/{contract_code}/invitations",
    response=ContractInvitationCreateResponse,
)
def create_contract_invitation(
    request, contract_code: str, payload: ContractInvitationCreateRequest
):
    contract = _get_authorized_contract(request, contract_code)
    actor = _require_contract_invitation_creator(request, contract)

    allowed_roles = {
        ContractMembership.Role.CONTRACT_EDITOR,
        ContractMembership.Role.CONTRACT_READER,
    }
    if payload.role_to_assign not in allowed_roles:
        raise HttpError(
            400,
            "Contract invitations can assign only contract_editor or contract_reader.",
        )

    email = (payload.email or "").strip().lower() or None
    try:
        invitation = ContractInvitation.objects.create(
            contract=contract,
            email=email,
            role_to_assign=payload.role_to_assign,
            invited_by=actor,
            status=ContractInvitation.Status.PENDING,
        )
    except ValidationError as exc:
        raise HttpError(400, f"Invitation validation failed: {exc}") from exc
    except IntegrityError as exc:
        raise HttpError(
            400,
            "A pending invitation with the same target already exists "
            "for this contract.",
        ) from exc

    invitation_url = request.build_absolute_uri(
        reverse("invitation-landing-root", kwargs={"token": invitation.token})
    )
    return ContractInvitationCreateResponse(
        token=str(invitation.token),
        invitation_url=invitation_url,
        contract_code=invitation.contract.contract_code,
        role_to_assign=invitation.role_to_assign,
        status=invitation.status,
        expires_at=invitation.expires_at.isoformat(),
    )


@api.get(
    "/v1/contracts/{contract_code}/flow-profile", response=ContractFlowProfileResponse
)
def get_contract_flow_profile(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    return ContractFlowProfileResponse(
        contract_code=contract.contract_code,
        flow_profile=_flow_profile_schema(contract.flow_profile)
        if contract.flow_profile
        else None,
    )


@api.put(
    "/v1/contracts/{contract_code}/flow-profile", response=ContractFlowProfileResponse
)
def set_contract_flow_profile(
    request, contract_code: str, payload: ContractFlowProfileUpdateRequest
):
    contract = _get_authorized_contract(request, contract_code)
    _require_contract_write(request, contract)

    if contract.status == Contract.ContractStatus.CLOSED:
        raise HttpError(400, "Cannot modify flow profile on a closed contract.")

    flow_profile = FlowProfile.objects.filter(
        code=payload.flow_profile_code, is_active=True
    ).first()
    if flow_profile is None:
        raise HttpError(404, "Active flow profile not found.")

    contract.flow_profile = flow_profile
    contract.save(update_fields=["flow_profile", "updated_at"])
    return ContractFlowProfileResponse(
        contract_code=contract.contract_code,
        flow_profile=_flow_profile_schema(flow_profile),
    )


@api.post(
    "/v1/contracts/{contract_code}/publish", response=ContractPublicationDetailSchema
)
def publish_contract_endpoint(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    user = _require_contract_write(request, contract)
    try:
        publication = publish_contract(contract=contract, user=user)
    except PublishContractError as exc:
        raise HttpError(exc.status_code, exc.message) from exc
    publication = ContractPublication.objects.select_related(
        "contract", "published_by"
    ).get(pk=publication.pk)
    return _contract_publication_detail_schema(publication)


@api.get(
    "/v1/contracts/{contract_code}/publications",
    response=list[ContractPublicationSummarySchema],
)
def list_contract_publications(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    publications = (
        ContractPublication.objects.select_related("contract", "published_by")
        .filter(contract=contract)
        .order_by("-publication_version")
    )
    return [_contract_publication_summary_schema(item) for item in publications]


@api.get(
    "/v1/contracts/{contract_code}/publications/{publication_version}",
    response=ContractPublicationDetailSchema,
)
def get_contract_publication_by_version(
    request, contract_code: str, publication_version: int
):
    contract = _get_authorized_contract(request, contract_code)
    publication = (
        ContractPublication.objects.select_related("contract", "published_by")
        .filter(contract=contract, publication_version=publication_version)
        .first()
    )
    if publication is None:
        raise HttpError(404, "Contract publication not found.")
    return _contract_publication_detail_schema(publication)


@api.get(
    "/v1/contracts/{contract_code}/indicators", response=list[ContractIndicatorSchema]
)
def list_contract_indicators(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    return _contract_indicators_schema(contract)


@api.get(
    "/v1/contracts/{contract_code}/indicators/{indicator_code}",
    response=ContractIndicatorSchema,
)
def get_contract_indicator(request, contract_code: str, indicator_code: str):
    contract = _get_authorized_contract(request, contract_code)
    link = (
        ContractIndicator.objects.select_related("indicator")
        .prefetch_related("indicator__structures__dataset")
        .filter(contract=contract, indicator__code=indicator_code)
        .first()
    )
    if link is None:
        raise HttpError(404, "Indicator not found for the selected contract.")
    return ContractIndicatorSchema(
        indicator=_indicator_schema(link.indicator),
        contract_params=link.params,
    )


@api.get(
    "/v1/contracts/{contract_code}/required-inputs", response=RequiredInputsResponse
)
def get_contract_required_inputs(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    return _contract_required_inputs_schema(contract)


@api.get("/v1/indicators", response=list[IndicatorSchema])
def list_indicators(request):
    _require_auth(request)
    indicators = (
        IndicatorDef.objects.prefetch_related("structures__dataset")
        .all()
        .order_by("code")
    )
    return [_indicator_schema(indicator) for indicator in indicators]


@api.get("/v1/indicators/{indicator_code}", response=IndicatorSchema)
def get_indicator(request, indicator_code: str):
    _require_auth(request)
    indicator = (
        IndicatorDef.objects.prefetch_related("structures__dataset")
        .filter(code=indicator_code)
        .first()
    )
    if indicator is None:
        raise HttpError(404, "Indicator not found.")
    return _indicator_schema(indicator)


@api.get("/v1/indicators/{indicator_code}/structures", response=list[StructureSchema])
def get_indicator_structures(request, indicator_code: str):
    _require_auth(request)
    indicator = (
        IndicatorDef.objects.prefetch_related("structures__dataset")
        .filter(code=indicator_code)
        .first()
    )
    if indicator is None:
        raise HttpError(404, "Indicator not found.")
    return [
        _structure_schema(s)
        for s in indicator.structures.select_related("dataset")
        .all()
        .order_by("dataset__slug", "name")
    ]


@api.get("/v1/structures", response=list[StructureSchema])
def list_structures(request, dataset_slug: str | None = None):
    _require_auth(request)
    qs = Structure.objects.select_related("dataset").all()
    if dataset_slug:
        qs = qs.filter(dataset__slug=dataset_slug)
    return [
        _structure_schema(structure)
        for structure in qs.order_by("dataset__slug", "name")
    ]


@api.get("/v1/structures/{structure_id}", response=StructureSchema)
def get_structure(request, structure_id: int):
    _require_auth(request)
    structure = (
        Structure.objects.select_related("dataset").filter(id=structure_id).first()
    )
    if structure is None:
        raise HttpError(404, "Structure not found.")
    return _structure_schema(structure)


@api.get("/v1/flow-profiles", response=list[FlowProfileSchema])
def list_flow_profiles(request, is_active: bool | None = None):
    _require_auth(request)
    qs = FlowProfile.objects.all().order_by("code")
    if is_active is not None:
        qs = qs.filter(is_active=is_active)
    return [_flow_profile_schema(flow_profile) for flow_profile in qs]


@api.get("/v1/flow-profiles/{flow_code}", response=FlowProfileSchema)
def get_flow_profile(request, flow_code: str):
    _require_auth(request)
    flow_profile = FlowProfile.objects.filter(code=flow_code).first()
    if flow_profile is None:
        raise HttpError(404, "Flow profile not found.")
    return _flow_profile_schema(flow_profile)


@api.get("/v1/publications/{publication_id}", response=ContractPublicationDetailSchema)
def get_publication(request, publication_id: int):
    publication = (
        ContractPublication.objects.select_related("contract", "published_by")
        .filter(id=publication_id)
        .first()
    )
    if publication is None:
        raise HttpError(404, "Contract publication not found.")
    _get_authorized_contract(request, publication.contract.contract_code)
    return _contract_publication_detail_schema(publication)


@api.post("/v1/agency-invitations", response=AgencyInvitationCreateResponse)
def create_agency_invitation_endpoint(request, payload: AgencyInvitationCreateRequest):
    agency = Agency.objects.filter(id=payload.agency_id).first()
    if agency is None:
        raise HttpError(404, "Agency not found.")

    actor = _require_agency_invitation_admin(request, agency)
    try:
        created = create_agency_invitation(
            actor=actor,
            agency=agency,
            role_to_assign=payload.role_to_assign,
            email=payload.email,
            provision_user_if_missing=payload.provision_user_if_missing,
        )
    except AgencyInvitationPermissionError as exc:
        raise HttpError(403, str(exc)) from exc
    except AgencyInvitationValidationError as exc:
        raise HttpError(400, str(exc)) from exc
    except AgencyInvitationProvisioningError as exc:
        raise HttpError(502, str(exc)) from exc

    invitation = created.invitation
    invitation_url = request.build_absolute_uri(
        reverse("invitation-landing-root", kwargs={"token": invitation.token})
    )
    return AgencyInvitationCreateResponse(
        token=str(invitation.token),
        invitation_url=invitation_url,
        agency_id=invitation.agency_id,
        agency_key=invitation.agency.agency_key,
        role_to_assign=invitation.role_to_assign,
        status=invitation.status,
        expires_at=invitation.expires_at.isoformat(),
        assigned_group_path=created.assigned_group_path,
        provisioned_user_id=created.provisioned_user_id,
    )


@api.post("/v1/agencies/bootstrap", response=AgencyBootstrapResponse)
def bootstrap_agency_endpoint(request, payload: AgencyBootstrapRequest):
    actor = _require_platform_admin(request)
    try:
        created = bootstrap_agency_with_admin_invitation(
            actor=actor,
            agency_name=payload.agency_name,
            initial_admin_email=payload.initial_admin_email,
            agency_key=payload.agency_key,
            provision_user_if_missing=payload.provision_user_if_missing,
        )
    except AgencyBootstrapPermissionError as exc:
        raise HttpError(403, str(exc)) from exc
    except AgencyBootstrapValidationError as exc:
        raise HttpError(400, str(exc)) from exc
    except AgencyBootstrapProvisioningError as exc:
        raise HttpError(502, str(exc)) from exc

    invitation_url = request.build_absolute_uri(
        reverse("invitation-landing-root", kwargs={"token": created.invitation.token})
    )
    return AgencyBootstrapResponse(
        agency_id=created.agency.id,
        agency_name=created.agency.name,
        agency_key=created.agency.agency_key,
        invitation_token=str(created.invitation.token),
        invitation_url=invitation_url,
        invitation_status=created.invitation.status,
        invitation_expires_at=created.invitation.expires_at.isoformat(),
        assigned_group_path=created.assigned_group_path,
        provisioned_user_id=created.provisioned_user_id,
    )


@api.get("/invitations/{token}/check", response=InvitationCheckResponse, auth=None)
def check_invitation(request, token: str):
    contract_invitation = (
        ContractInvitation.objects.select_related("contract")
        .filter(token=token)
        .first()
    )
    agency_invitation = (
        AgencyInvitation.objects.select_related("agency").filter(token=token).first()
    )
    invitation = contract_invitation or agency_invitation
    if invitation is None:
        return InvitationCheckResponse(
            valid=False,
            invitation_type="missing",
            status="missing",
            is_open_invitation=False,
            role_to_assign="",
            contract_code="",
            agency_key="",
            expires_at="",
            message="Invitation token not found.",
        )

    now = timezone.now()
    valid = (
        invitation.status == invitation.Status.PENDING and invitation.expires_at > now
    )
    invitation_type = "contract" if contract_invitation else "agency"
    return InvitationCheckResponse(
        valid=valid,
        invitation_type=invitation_type,
        status=invitation.status,
        is_open_invitation=not bool(invitation.email),
        role_to_assign=invitation.role_to_assign,
        contract_code=invitation.contract.contract_code
        if invitation_type == "contract"
        else "",
        agency_key=invitation.agency.agency_key if invitation_type == "agency" else "",
        expires_at=invitation.expires_at.isoformat(),
        message="Invitation is valid." if valid else "Invitation is not valid anymore.",
    )


@api.post("/invitations/{token}/start", response=InvitationStartResponse, auth=None)
def start_onboarding(request, token: str):
    contract_invitation = ContractInvitation.objects.filter(token=token).first()
    agency_invitation = AgencyInvitation.objects.filter(token=token).first()
    invitation = contract_invitation or agency_invitation
    if invitation is None:
        return InvitationStartResponse(
            ok=False,
            redirect_url="",
            provider_id="",
            invitation_type="missing",
            message="Invitation token not found.",
        )

    if not invitation.is_valid():
        return InvitationStartResponse(
            ok=False,
            redirect_url="",
            provider_id="",
            invitation_type="contract" if contract_invitation else "agency",
            message="Invitation is not valid anymore.",
        )

    request.session["onboarding_invitation_token"] = token
    request.session["onboarding_invitation_kind"] = (
        "contract" if contract_invitation else "agency"
    )
    callback_url = reverse("exchange_agreement:onboarding-callback")
    redirect_url = _build_oidc_login_url(callback_url)
    return InvitationStartResponse(
        ok=True,
        redirect_url=redirect_url,
        provider_id=_oidc_provider_id(),
        invitation_type="contract" if contract_invitation else "agency",
        message="Invitation accepted for onboarding. Continue with OIDC login.",
    )
