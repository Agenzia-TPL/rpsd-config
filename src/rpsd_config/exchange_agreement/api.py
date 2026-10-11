# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import hashlib
import re
import uuid
from datetime import date
from urllib.parse import urlencode

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import AuthenticationError, HttpError
from ninja.security import HttpBearer, SessionAuth

from rpsd_config.server.bearer_auth import BearerTokenAuth
from rpsd_config.server.m2m_auth import (
    M2MClientTokenAuth,
    M2MTokenValidationError,
    extract_m2m_client_id,
    validate_m2m_token,
)

from .models import (
    Agency,
    AgencyInvitation,
    Company,
    ConfigurationAsset,
    Contract,
    ContractInvitation,
    ContractMembership,
    ContractPublication,
    Dataset,
    DatasetSpecification,
    Indicator,
    IndicatorVersion,
    InputFlowVersion,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
    OrchestrationFlowVersion,
    ProcessingProfileVersion,
    RequirementFragment,
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
from .services.api_usage import record_api_usage
from .services.configuration_assets import load_configuration_asset_content
from .services.flow_catalog import (
    input_flow_runtime_projection,
    orchestration_flow_runtime_projection,
)
from .services.indicator_catalog import serialize_indicator_catalog_entry
from .services.ingest_resolution import (
    IngestResolutionError,
    resolve_current_contract_configuration,
    resolve_current_ingest_configuration,
)
from .services.m2m_audit import audit_m2m_event, resolve_request_id
from .services.m2m_grants import (
    accessible_contracts_for_principal,
    ensure_default_contract_ingest_grant,
    require_m2m_contract_access,
    require_m2m_principal,
)
from .services.processing_profiles import (
    legacy_flow_profile_options,
    serialize_processing_profile,
)
from .services.publication import PublishContractError, publish_contract
from .services.requirement_fragments import serialize_requirement_fragment_catalog


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


class DatasetSpecificationAssetSchema(Schema):
    role: str
    required: bool
    asset_type: str
    what: str
    version: int
    checksum_sha256: str


class FragmentValidationRuleSchema(Schema):
    rule_type: str
    rule_version: int
    severity: str
    parameters: dict


class RequirementFragmentSchema(Schema):
    code: str
    name: str
    description: str
    locator_type: str
    result_kind: str
    locator_definition: dict
    status: str
    rules: list[FragmentValidationRuleSchema]


class DatasetSpecificationSchema(Schema):
    code: str
    version: str
    description: str
    status: str
    metadata: dict
    published_at: str | None
    assets: list[DatasetSpecificationAssetSchema]
    fragments: list[RequirementFragmentSchema]


class DatasetCatalogSchema(Schema):
    code: str
    name: str
    description: str
    status: str
    specifications: list[DatasetSpecificationSchema]


class IndicatorVersionCatalogSchema(Schema):
    code: str
    version: str
    description: str
    formula_description: str
    input_schema: dict
    output_schema: dict
    input_contract: dict
    output_contract: dict
    parameter_schema: dict
    execution_engine: str
    execution_reference: str
    artifact_identifier: str
    status: str
    published_at: str | None
    required_fragments: list[RequirementFragmentSchema]


class IndicatorCatalogSchema(Schema):
    code: str
    name: str
    description: str
    status: str
    versions: list[IndicatorVersionCatalogSchema]


class InputFlowCatalogSchema(Schema):
    code: str
    version: str
    name: str
    description: str
    dataset_specification_code: str
    what: str
    engine: str
    deployment_name: str
    artifact_identifier: str
    invocation_contract: dict
    compatibility: dict
    status: str
    published_at: str | None


class OrchestrationFlowCatalogSchema(Schema):
    code: str
    version: str
    name: str
    description: str
    engine: str
    deployment_name: str
    artifact_identifier: str
    invocation_contract: dict
    status: str
    published_at: str | None


class ProcessingProfileInputSchema(Schema):
    dataset_code: str
    dataset_name: str
    dataset_specification_code: str
    dataset_specification_version: str


class ProcessingProfileIndicatorSchema(Schema):
    indicator_code: str
    indicator_name: str
    indicator_version_code: str
    indicator_version: str
    proposed_by_default: bool


class ProcessingProfileCatalogSchema(Schema):
    code: str
    version: str
    name: str
    description: str
    status: str
    published_at: str | None
    inputs: list[ProcessingProfileInputSchema]
    indicators: list[ProcessingProfileIndicatorSchema]


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
    flow_profile_code: str | None = None


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
    configuration_revision_code: str
    configuration_revision_number: int
    configuration_valid_from: str
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


class M2MIngestAuthorizationResponse(Schema):
    allowed: bool
    contract_code: str
    data_category: str
    flow_profile_code: str
    flow: str
    grant_id: int | None


class DatasetSpecificationResolutionSchema(Schema):
    code: str
    version: str


class FlowVersionResolutionSchema(Schema):
    code: str
    version: str
    engine: str
    deployment_name: str
    artifact_identifier: str


class IngestResolutionV2(Schema):
    schema_version: str
    contract_code: str
    configuration_revision_code: str
    data_category: str
    dataset_specification: DatasetSpecificationResolutionSchema
    input_flow_version: FlowVersionResolutionSchema
    orchestration_flow_version: FlowVersionResolutionSchema
    snapshot_schema_version: str
    snapshot_checksum: str


class M2MErrorDetailSchema(Schema):
    code: str
    message: str
    correlation_id: str


class M2MErrorEnvelopeSchema(Schema):
    error: M2MErrorDetailSchema


class M2MUserSchema(Schema):
    username: str
    email: str
    display_name: str
    contract_codes: list[str]
    roles: list[str]


class ConfigurationAssetSchema(Schema):
    id: int
    asset_type: str
    what: str
    label: str
    version: int
    status: str
    is_active: bool
    storage_url: str
    checksum_sha256: str
    content_type: str
    size_bytes: int
    original_filename: str
    uploaded_at: str
    activated_at: str | None
    download_url: str


class ConfigAssetM2MTokenAuth(HttpBearer):
    allowed_client_setting = "CONFIG_ASSETS_M2M_ALLOWED_CLIENT_IDS"

    def authenticate(self, request, token):
        try:
            claims = validate_m2m_token(token)
            client_id = extract_m2m_client_id(claims)
        except M2MTokenValidationError as exc:
            setattr(request, "m2m_auth_reason", exc.reason)
            return None

        allowed = {
            item.strip()
            for item in getattr(
                settings,
                self.allowed_client_setting,
                "",
            ).split(",")
            if item.strip()
        }
        if client_id not in allowed:
            setattr(request, "m2m_auth_reason", "config-asset-client-not-allowed")
            return None
        request.integration_client_id = client_id
        request.integration_claims = claims
        return client_id


class ValidationServiceTokenAuth(ConfigAssetM2MTokenAuth):
    """Explicit platform service allowlist; independent from company grants."""

    allowed_client_setting = "VALIDATION_M2M_ALLOWED_CLIENT_IDS"

    def authenticate(self, request, token):
        result = super().authenticate(request, token)
        if result is not None:
            request.validation_service_client_id = result
        return result


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

config_asset_m2m_auth = ConfigAssetM2MTokenAuth()
DATA_CATEGORY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _m2m_correlation_id(request) -> str:
    existing = getattr(request, "m2m_correlation_id", "") or resolve_request_id(request)
    correlation_id = existing.strip() if isinstance(existing, str) else ""
    if not correlation_id:
        correlation_id = str(uuid.uuid4())
    request.m2m_correlation_id = correlation_id
    return correlation_id


def _m2m_v2_error(request, *, status: int, code: str, message: str):
    correlation_id = _m2m_correlation_id(request)
    record_api_usage(
        version="v3" if "/v3/" in request.path else "v2",
        endpoint="validation-plan" if "/v3/" in request.path else "ingest-resolution",
        outcome=code,
        correlation_id=correlation_id,
    )
    return status, M2MErrorEnvelopeSchema(
        error=M2MErrorDetailSchema(
            code=code,
            message=message,
            correlation_id=correlation_id,
        )
    )


@m2m_api.exception_handler(AuthenticationError)
def m2m_authentication_error(request, exc):
    if "/v2/" not in request.path and "/v3/" not in request.path:
        return m2m_api.create_response(
            request,
            {"detail": str(exc)},
            status=exc.status_code,
        )

    reason = getattr(request, "m2m_auth_reason", "")
    inactive_reasons = {
        "principal-suspended",
        "principal-revoked",
        "principal-not-active",
    }
    status = 403 if reason in inactive_reasons else 401
    code = "ingest_not_authorized" if status == 403 else "authentication_failed"
    message = (
        "M2M principal is not authorized"
        if status == 403
        else "M2M authentication failed"
    )
    _status, envelope = _m2m_v2_error(
        request,
        status=status,
        code=code,
        message=message,
    )
    return m2m_api.create_response(request, envelope.dict(), status=status)


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
        "lot",
        "client_agency",
        "contractor_company",
        "governing_authority",
        "replaced_by",
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
    contract_filter |= Q(
        governing_authority__memberships__user=user,
        governing_authority__memberships__is_active=True,
    )
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
        slug=dataset.code,
        name=dataset.name,
        description=dataset.description,
    )


def _dataset_specification_schema(
    specification: DatasetSpecification,
) -> DatasetSpecificationSchema:
    links = specification.asset_links.select_related("configuration_asset").all()
    assets = [
        DatasetSpecificationAssetSchema(
            role=link.role,
            required=link.required,
            asset_type=link.configuration_asset.asset_type,
            what=link.configuration_asset.what,
            version=link.configuration_asset.version,
            checksum_sha256=link.configuration_asset.checksum_sha256,
        )
        for link in links
    ]
    return DatasetSpecificationSchema(
        code=specification.code,
        version=specification.version,
        description=specification.description,
        status=specification.status,
        metadata=specification.metadata,
        published_at=(
            specification.published_at.isoformat()
            if specification.published_at
            else None
        ),
        assets=assets,
        fragments=serialize_requirement_fragment_catalog(specification),
    )


def _dataset_catalog_schema(dataset: Dataset) -> DatasetCatalogSchema:
    specifications = [
        _dataset_specification_schema(specification)
        for specification in dataset.specifications.all()
        if specification.status == DatasetSpecification.Status.PUBLISHED
    ]
    return DatasetCatalogSchema(
        code=dataset.code,
        name=dataset.name,
        description=dataset.description,
        status=dataset.status,
        specifications=specifications,
    )


def _input_flow_catalog_schema(flow: InputFlowVersion) -> InputFlowCatalogSchema:
    payload = input_flow_runtime_projection(flow)
    return InputFlowCatalogSchema(
        **payload,
        name=flow.name,
        description=flow.description,
        status=flow.status,
        published_at=flow.published_at.isoformat() if flow.published_at else None,
    )


def _orchestration_flow_catalog_schema(
    flow: OrchestrationFlowVersion,
) -> OrchestrationFlowCatalogSchema:
    payload = orchestration_flow_runtime_projection(flow)
    return OrchestrationFlowCatalogSchema(
        **payload,
        name=flow.name,
        description=flow.description,
        status=flow.status,
        published_at=flow.published_at.isoformat() if flow.published_at else None,
    )


def _processing_profile_ref_schema(
    profile: ProcessingProfileVersion,
) -> FlowProfileRefSchema:
    return FlowProfileRefSchema(
        code=profile.code,
        name=profile.name,
        schema_version=profile.version,
        # In this projection "active" means selected by today's approved
        # contract revision, not mutable catalog lifecycle state.
        is_active=True,
    )


def _processing_profile_legacy_schema(
    profile: ProcessingProfileVersion,
) -> FlowProfileSchema:
    return FlowProfileSchema(
        code=profile.code,
        name=profile.name,
        schema_version=profile.version,
        is_active=profile.status == ProcessingProfileVersion.Status.PUBLISHED,
        description=profile.description,
        options=legacy_flow_profile_options(profile),
    )


def _fragment_structure_schema(fragment: RequirementFragment) -> StructureSchema:
    locator = (
        fragment.locator_definition
        if isinstance(fragment.locator_definition, dict)
        else {}
    )
    definition = dict(locator)
    xpath = locator.get("path", "") if fragment.locator_type == "xpath" else ""
    if xpath:
        definition["xpath"] = xpath
    definition.setdefault("fields", [])
    return StructureSchema(
        id=fragment.id,
        name=fragment.name,
        description=fragment.description,
        dataset=_dataset_ref(fragment.dataset_specification.dataset),
        definition=definition,
        xpath=xpath,
        fields=[],
    )


def _indicator_version_legacy_schema(version: IndicatorVersion) -> IndicatorSchema:
    fragments = list(version.required_fragments.all())
    fragments.sort(
        key=lambda item: (item.dataset_specification.dataset.code, item.code)
    )
    return IndicatorSchema(
        code=version.indicator.code,
        type="OTHER",
        name=version.indicator.name,
        description=version.indicator.description,
        formula=version.formula_description,
        notes=version.description,
        sql_procedure_name=version.execution_reference,
        sql_snippet="",
        structures=[_fragment_structure_schema(item) for item in fragments],
    )


def _current_processing_profile(contract: Contract) -> ProcessingProfileVersion | None:
    try:
        return resolve_current_contract_configuration(
            contract
        ).revision.processing_profile_version
    except IngestResolutionError:
        return None


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
        flow_profile=(
            _processing_profile_ref_schema(profile)
            if (profile := _current_processing_profile(contract))
            else None
        ),
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
        flow_profile=(
            _processing_profile_ref_schema(profile)
            if (profile := _current_processing_profile(contract))
            else None
        ),
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
        configuration_revision_code=publication.configuration_revision.code,
        configuration_revision_number=(
            publication.configuration_revision.revision_number
        ),
        configuration_valid_from=(
            publication.configuration_revision.valid_from.isoformat()
        ),
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
        configuration_revision_code=summary.configuration_revision_code,
        configuration_revision_number=summary.configuration_revision_number,
        configuration_valid_from=summary.configuration_valid_from,
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


def _legacy_revision_flow_profile_schema(contract: Contract) -> FlowProfileSchema:
    current = resolve_current_contract_configuration(contract)
    snapshot = current.snapshot
    profile = current.revision.processing_profile_version
    selected_inputs = {
        item["dataset_code"]: item
        for item in snapshot.get("inputs", [])
        if isinstance(item, dict) and isinstance(item.get("dataset_code"), str)
    }

    data_ingestion = {}
    for link in profile.input_flow_links.select_related(
        "dataset", "input_flow_version"
    ).order_by("dataset__code"):
        selected = selected_inputs.get(link.dataset.code)
        flow_snapshot = selected.get("input_flow", {}) if selected else {}
        deployment_name = (
            flow_snapshot.get("deployment_name")
            if selected
            else link.input_flow_version.deployment_name
        )
        data_ingestion[link.dataset.code] = {
            "flow": deployment_name,
            "active": selected is not None,
            "description": link.input_flow_version.description,
        }

    profile_snapshot = snapshot.get("processing_profile", {})
    return FlowProfileSchema(
        code=profile_snapshot.get("code", profile.code),
        name=profile_snapshot.get("name", profile.name),
        schema_version=profile_snapshot.get("version", profile.version),
        is_active=True,
        description=profile_snapshot.get("description", profile.description),
        options={
            "general_profile": profile_snapshot.get("code", profile.code),
            "planned_master": {},
            "data_ingestion": data_ingestion,
            "data_retention": {},
        },
    )


def _legacy_revision_required_inputs_schema(
    contract: Contract,
) -> RequiredInputsResponse:
    current = resolve_current_contract_configuration(contract)
    snapshot = current.snapshot
    inputs_by_specification = {
        item.get("dataset_specification", {}).get("code"): item
        for item in snapshot.get("inputs", [])
        if isinstance(item, dict)
        and isinstance(item.get("dataset_specification"), dict)
    }
    groups: dict[str, dict] = {}
    structure_id = 0
    for indicator in snapshot.get("indicators", []):
        if not isinstance(indicator, dict):
            continue
        indicator_code = indicator.get("indicator_code", "")
        for fragment in indicator.get("fragments", []):
            if not isinstance(fragment, dict):
                continue
            specification_code = fragment.get("dataset_specification_code")
            selected_input = inputs_by_specification.get(specification_code)
            if not isinstance(selected_input, dict):
                raise IngestResolutionError(
                    "configuration_invariant_violation",
                    "A required fragment has no selected input",
                )
            dataset_code = selected_input.get("dataset_code", "")
            dataset = DatasetRefSchema(
                slug=dataset_code,
                name=selected_input.get("dataset_name", dataset_code),
                description=selected_input.get("dataset_description", ""),
            )
            group = groups.setdefault(
                dataset_code,
                {
                    "dataset": dataset,
                    "structures": [],
                    "used_by_indicators": set(),
                },
            )
            locator = fragment.get("locator_definition", {})
            if not isinstance(locator, dict):
                locator = {}
            xpath = (
                locator.get("path", "")
                if fragment.get("locator_type") == "xpath"
                else ""
            )
            definition = dict(locator)
            if xpath:
                definition["xpath"] = xpath
            definition.setdefault("fields", [])
            structure_id += 1
            group["structures"].append(
                StructureSchema(
                    id=structure_id,
                    name=fragment.get("name") or fragment.get("code", ""),
                    description=fragment.get("description", ""),
                    dataset=dataset,
                    definition=definition,
                    xpath=xpath,
                    fields=[],
                )
            )
            group["used_by_indicators"].add(indicator_code)

    return RequiredInputsResponse(
        contract_code=contract.contract_code,
        required_inputs=[
            RequiredInputGroupSchema(
                dataset=group["dataset"],
                structures=group["structures"],
                used_by_indicators=sorted(group["used_by_indicators"]),
            )
            for _, group in sorted(groups.items())
        ],
    )


def _legacy_revision_error(exc: IngestResolutionError) -> HttpError:
    messages = {
        "contract_not_effective": "Contract is not effective today.",
        "configuration_not_ready": "No current flow profile assigned to contract.",
        "data_category_not_configured": (
            "Data category is not supported by flow profile."
        ),
        "configuration_invariant_violation": (
            "Current contract configuration is invalid."
        ),
    }
    return HttpError(400, messages.get(exc.code, "Contract configuration unavailable."))


def _reject_legacy_temporal_parameters(request) -> None:
    temporal_parameters = {"reference_date", "service_day", "valid_from"}
    if temporal_parameters.intersection(request.GET):
        raise HttpError(400, "Client-supplied resolution dates are not supported.")


def _mark_legacy_m2m_response(
    request,
    response: HttpResponse,
    *,
    endpoint: str,
    contract_code: str,
    data_category: str | None = None,
) -> None:
    correlation_id = _m2m_correlation_id(request)
    response["Deprecation"] = "true"
    response["Link"] = (
        f"</exchange_agreement/api/m2m/v2/contracts/{contract_code}/"
        'ingest-resolution{?data_category}>; rel="successor-version"'
    )
    response["X-Correlation-ID"] = correlation_id
    record_api_usage(
        version="v1",
        endpoint=endpoint,
        outcome="success",
        correlation_id=correlation_id,
        contract_code=contract_code,
        data_category=data_category,
    )


def _contract_indicators_schema(contract: Contract) -> list[ContractIndicatorSchema]:
    current = resolve_current_contract_configuration(contract)
    snapshots = [
        item
        for item in current.snapshot.get("indicators", [])
        if isinstance(item, dict)
    ]
    version_codes = {
        item.get("indicator_version", {}).get("code")
        for item in snapshots
        if isinstance(item.get("indicator_version"), dict)
    }
    versions = {
        version.code: version
        for version in IndicatorVersion.objects.select_related("indicator")
        .prefetch_related("required_fragments__dataset_specification__dataset")
        .filter(code__in=version_codes)
    }

    result = []
    for item in sorted(snapshots, key=lambda value: value.get("indicator_code", "")):
        version_data = item.get("indicator_version", {})
        version = versions.get(version_data.get("code"))
        if version is None:
            raise IngestResolutionError(
                "configuration_invariant_violation",
                "A configured indicator version is not available",
            )
        params = {
            name: item[name]
            for name in ("thresholds", "aggregation", "penalties", "parameters")
            if item.get(name) not in (None, {}, [])
        }
        result.append(
            ContractIndicatorSchema(
                indicator=_indicator_version_legacy_schema(version),
                contract_params=params or None,
            )
        )
    return result


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


def _configuration_asset_schema(request, asset: ConfigurationAsset):
    return ConfigurationAssetSchema(
        id=asset.pk,
        asset_type=asset.asset_type,
        what=asset.what,
        label=asset.label,
        version=asset.version,
        status=asset.status,
        is_active=asset.is_active,
        storage_url=asset.storage_url,
        checksum_sha256=asset.checksum_sha256,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        original_filename=asset.original_filename,
        uploaded_at=asset.uploaded_at.isoformat(),
        activated_at=asset.activated_at.isoformat() if asset.activated_at else None,
        download_url=request.build_absolute_uri(
            f"/exchange_agreement/api/m2m/v1/config-assets/{asset.pk}/download"
        ),
    )


def _configuration_assets_qs():
    return ConfigurationAsset.objects.all().order_by(
        "asset_type",
        "what",
        "-version",
    )


@m2m_api.get(
    "/v2/contracts/{contract_code}/ingest-resolution",
    response={
        200: IngestResolutionV2,
        401: M2MErrorEnvelopeSchema,
        403: M2MErrorEnvelopeSchema,
        404: M2MErrorEnvelopeSchema,
        409: M2MErrorEnvelopeSchema,
        422: M2MErrorEnvelopeSchema,
        503: M2MErrorEnvelopeSchema,
    },
)
def m2m_contract_ingest_resolution_v2(
    request,
    contract_code: str,
    data_category: str | None = None,
):
    unexpected = set(request.GET) - {"data_category"}
    category_values = request.GET.getlist("data_category")
    category = (data_category or "").strip().lower()
    if (
        unexpected
        or len(category_values) != 1
        or not DATA_CATEGORY_PATTERN.fullmatch(category)
    ):
        return _m2m_v2_error(
            request,
            status=422,
            code="invalid_request",
            message="The request must contain only one valid data_category",
        )

    try:
        principal = require_m2m_principal(request)
        contract = (
            Contract.objects.select_related("contractor_company")
            .filter(
                contract_code=contract_code,
                contractor_company=principal.company,
            )
            .first()
        )
        if contract is None:
            return _m2m_v2_error(
                request,
                status=404,
                code="contract_not_found",
                message="Contract not found",
            )

        today = timezone.localdate()
        if (
            contract.status != Contract.ContractStatus.ACTIVE
            or contract.start_date > today
            or (contract.end_date is not None and contract.end_date < today)
        ):
            return _m2m_v2_error(
                request,
                status=409,
                code="contract_not_effective",
                message="Contract is not effective today",
            )

        checked_at = timezone.now()
        grant = (
            IntegrationGrant.objects.filter(
                principal=principal,
                contract=contract,
                action=IntegrationGrant.Action.INGEST_WRITE,
                status=IntegrationGrant.Status.ACTIVE,
            )
            .filter(Q(data_category__isnull=True) | Q(data_category=category))
            .filter(
                Q(valid_from__isnull=True) | Q(valid_from__lte=checked_at),
                Q(valid_to__isnull=True) | Q(valid_to__gte=checked_at),
            )
            .order_by("-data_category", "id")
            .first()
        )
        if grant is None:
            return _m2m_v2_error(
                request,
                status=403,
                code="ingest_not_authorized",
                message="Ingest is not authorized for this contract and category",
            )

        resolution = resolve_current_ingest_configuration(contract, category)
    except IngestResolutionError as exc:
        return _m2m_v2_error(
            request,
            status=409,
            code=exc.code,
            message=exc.public_message,
        )
    except DatabaseError:
        return _m2m_v2_error(
            request,
            status=503,
            code="configuration_service_unavailable",
            message="Configuration service is temporarily unavailable",
        )

    correlation_id = _m2m_correlation_id(request)
    audit_m2m_event(
        "api.ingest_resolution",
        endpoint_version="v2",
        outcome="allowed",
        correlation_id=correlation_id,
        principal_id=principal.pk,
        company_id=principal.company_id,
        contract_code=contract.contract_code,
        data_category=category,
        revision_code=resolution.revision.code,
    )
    record_api_usage(
        version="v2",
        endpoint="ingest-resolution",
        outcome="success",
        correlation_id=correlation_id,
        contract_code=contract.contract_code,
        data_category=category,
        revision_code=resolution.revision.code,
    )
    return IngestResolutionV2(
        schema_version="ingest-resolution/v2",
        contract_code=contract.contract_code,
        configuration_revision_code=resolution.revision.code,
        data_category=category,
        dataset_specification=DatasetSpecificationResolutionSchema(
            **resolution.dataset_specification
        ),
        input_flow_version=FlowVersionResolutionSchema(**resolution.input_flow_version),
        orchestration_flow_version=FlowVersionResolutionSchema(
            **resolution.orchestration_flow_version
        ),
        snapshot_schema_version=resolution.snapshot_schema_version,
        snapshot_checksum=resolution.snapshot_checksum,
    )


@m2m_api.get(
    "/v3/contracts/{contract_code}/validation-plan",
    auth=[M2MClientTokenAuth(), ValidationServiceTokenAuth()],
    response={
        200: dict,
        401: M2MErrorEnvelopeSchema,
        403: M2MErrorEnvelopeSchema,
        404: M2MErrorEnvelopeSchema,
        409: M2MErrorEnvelopeSchema,
        422: M2MErrorEnvelopeSchema,
        503: M2MErrorEnvelopeSchema,
    },
)
def m2m_contract_validation_plan_v3(
    request,
    contract_code: str,
    data_category: str | None = None,
):
    unexpected = set(request.GET) - {"data_category"}
    category_values = request.GET.getlist("data_category")
    category = (data_category or "").strip().lower()
    if (
        unexpected
        or len(category_values) != 1
        or not DATA_CATEGORY_PATTERN.fullmatch(category)
    ):
        return _m2m_v2_error(
            request,
            status=422,
            code="invalid_request",
            message="The request must contain only one valid data_category",
        )

    try:
        service_client = getattr(request, "validation_service_client_id", None)
        principal = None if service_client else require_m2m_principal(request)
        contracts = Contract.objects.select_related("contractor_company").filter(
            contract_code=contract_code
        )
        if principal is not None:
            contracts = contracts.filter(contractor_company=principal.company)
        contract = contracts.first()
        if contract is None:
            return _m2m_v2_error(
                request,
                status=404,
                code="contract_not_found",
                message="Contract not found",
            )

        today = timezone.localdate()
        if (
            contract.status != Contract.ContractStatus.ACTIVE
            or contract.start_date > today
            or (contract.end_date is not None and contract.end_date < today)
        ):
            return _m2m_v2_error(
                request,
                status=409,
                code="contract_not_effective",
                message="Contract is not effective today",
            )

        if principal is not None:
            checked_at = timezone.now()
            grant = (
                IntegrationGrant.objects.filter(
                    principal=principal,
                    contract=contract,
                    action=IntegrationGrant.Action.INGEST_WRITE,
                    status=IntegrationGrant.Status.ACTIVE,
                )
                .filter(Q(data_category__isnull=True) | Q(data_category=category))
                .filter(
                    Q(valid_from__isnull=True) | Q(valid_from__lte=checked_at),
                    Q(valid_to__isnull=True) | Q(valid_to__gte=checked_at),
                )
                .order_by("-data_category", "id")
                .first()
            )
            if grant is None:
                return _m2m_v2_error(
                    request,
                    status=403,
                    code="ingest_not_authorized",
                    message="Ingest is not authorized for this contract and category",
                )

        resolution = resolve_current_ingest_configuration(contract, category)
        from rpsd_config.exchange_agreement.services.validation_plans import (
            validation_plan_from_resolution,
        )

        plan = validation_plan_from_resolution(resolution)
    except IngestResolutionError as exc:
        return _m2m_v2_error(
            request,
            status=409,
            code=exc.code,
            message=exc.public_message,
        )
    except DatabaseError:
        return _m2m_v2_error(
            request,
            status=503,
            code="configuration_service_unavailable",
            message="Configuration service is temporarily unavailable",
        )

    correlation_id = _m2m_correlation_id(request)
    audit_m2m_event(
        "api.validation_plan",
        endpoint_version="v3",
        outcome="allowed",
        correlation_id=correlation_id,
        principal_id=principal.pk if principal else None,
        company_id=principal.company_id if principal else None,
        contract_code=contract.contract_code,
        data_category=category,
        revision_code=resolution.revision.code,
        snapshot_schema_version=resolution.snapshot_schema_version,
        snapshot_checksum=resolution.snapshot_checksum,
    )
    record_api_usage(
        version="v3",
        endpoint="validation-plan",
        outcome="success",
        correlation_id=correlation_id,
        contract_code=contract.contract_code,
        data_category=category,
        revision_code=resolution.revision.code,

    )
    return plan


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
def m2m_contract_flow_profile(
    request,
    contract_code: str,
    response: HttpResponse,
):
    _reject_legacy_temporal_parameters(request)
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    try:
        flow_profile = _legacy_revision_flow_profile_schema(contract)
    except IngestResolutionError as exc:
        raise _legacy_revision_error(exc) from exc
    _mark_legacy_m2m_response(
        request,
        response,
        endpoint="flow-profile",
        contract_code=contract.contract_code,
    )
    return ContractFlowProfileResponse(
        contract_code=contract.contract_code,
        flow_profile=flow_profile,
    )


@m2m_api.get(
    "/v1/contracts/{contract_code}/ingest-authorization",
    response=M2MIngestAuthorizationResponse,
)
def m2m_contract_ingest_authorization(
    request,
    contract_code: str,
    data_category: str,
    response: HttpResponse,
):
    _reject_legacy_temporal_parameters(request)
    data_category = data_category.strip().lower()
    if not data_category:
        raise HttpError(400, "data_category is required.")

    _principal, contract, grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
        data_category=data_category,
    )

    try:
        resolution = resolve_current_ingest_configuration(contract, data_category)
    except IngestResolutionError as exc:
        if exc.code == "data_category_not_configured":
            current = resolve_current_contract_configuration(contract)
            if current.revision.processing_profile_version.input_flow_links.filter(
                dataset__code=data_category
            ).exists():
                raise HttpError(
                    400,
                    "Data category is inactive for this contract.",
                ) from exc
        raise _legacy_revision_error(exc) from exc

    profile_snapshot = resolution.snapshot.get("processing_profile", {})
    flow_profile_code = profile_snapshot.get("code", "")
    if not flow_profile_code:
        raise HttpError(400, "Current contract configuration is invalid.")
    _mark_legacy_m2m_response(
        request,
        response,
        endpoint="ingest-authorization",
        contract_code=contract.contract_code,
        data_category=data_category,
    )

    return M2MIngestAuthorizationResponse(
        allowed=True,
        contract_code=contract.contract_code,
        data_category=data_category,
        flow_profile_code=flow_profile_code,
        flow=resolution.input_flow_version["deployment_name"],
        grant_id=grant.pk if grant else None,
    )


@m2m_api.get(
    "/v1/contracts/{contract_code}/required-inputs",
    response=RequiredInputsResponse,
)
def m2m_contract_required_inputs(
    request,
    contract_code: str,
    response: HttpResponse,
):
    _reject_legacy_temporal_parameters(request)
    _principal, contract, _grant = require_m2m_contract_access(
        request,
        contract_code=contract_code,
    )
    try:
        payload = _legacy_revision_required_inputs_schema(contract)
    except IngestResolutionError as exc:
        raise _legacy_revision_error(exc) from exc
    _mark_legacy_m2m_response(
        request,
        response,
        endpoint="required-inputs",
        contract_code=contract.contract_code,
    )
    return payload


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
        ContractPublication.objects.select_related(
            "contract", "configuration_revision", "published_by"
        )
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


@m2m_api.get(
    "/v1/config-assets",
    response=list[ConfigurationAssetSchema],
    auth=config_asset_m2m_auth,
)
def m2m_config_assets(
    request,
    asset_type: str | None = None,
    status: str | None = None,
    what: str | None = None,
):
    qs = _configuration_assets_qs()
    if asset_type:
        qs = qs.filter(asset_type=asset_type.strip())
    if status:
        qs = qs.filter(status=status.strip())
    if what:
        qs = qs.filter(what=what.strip().lower())
    return [_configuration_asset_schema(request, asset) for asset in qs]


@m2m_api.get(
    "/v1/config-assets/active",
    response=ConfigurationAssetSchema,
    auth=config_asset_m2m_auth,
)
def m2m_active_config_asset(request, asset_type: str, what: str | None = None):
    qs = _configuration_assets_qs().filter(
        asset_type=asset_type.strip(),
        is_active=True,
    )
    if what:
        qs = qs.filter(what=what.strip().lower())
    asset = qs.first()
    if asset is None:
        raise HttpError(404, "Active configuration asset not found.")
    return _configuration_asset_schema(request, asset)


@m2m_api.get(
    "/v1/config-assets/{asset_id}",
    response=ConfigurationAssetSchema,
    auth=config_asset_m2m_auth,
)
def m2m_config_asset_detail(request, asset_id: int):
    asset = ConfigurationAsset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise HttpError(404, "Configuration asset not found.")
    return _configuration_asset_schema(request, asset)


@m2m_api.get("/v1/config-assets/{asset_id}/download", auth=config_asset_m2m_auth)
def m2m_config_asset_download(request, asset_id: int):
    asset = ConfigurationAsset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise HttpError(404, "Configuration asset not found.")
    try:
        content = load_configuration_asset_content(asset)
    except ValidationError as exc:
        raise HttpError(500, f"Configuration asset integrity error: {exc}") from exc
    response = HttpResponse(
        content,
        content_type=asset.content_type or "application/octet-stream",
    )
    response["Content-Disposition"] = (
        f'attachment; filename="{asset.original_filename}"'
    )
    response["X-RPSD-Checksum-SHA256"] = asset.checksum_sha256
    return response


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
        with transaction.atomic():
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
            ensure_default_contract_ingest_grant(
                contract=contract,
                actor=request.user,
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
    try:
        flow_profile = _legacy_revision_flow_profile_schema(contract)
    except IngestResolutionError:
        flow_profile = None
    return ContractFlowProfileResponse(
        contract_code=contract.contract_code,
        flow_profile=flow_profile,
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

    if not ProcessingProfileVersion.objects.filter(
        code=payload.flow_profile_code,
        status=ProcessingProfileVersion.Status.PUBLISHED,
    ).exists():
        raise HttpError(404, "Published processing profile not found.")
    raise HttpError(
        409,
        "Direct flow profile assignment is no longer supported; create a contract "
        "configuration revision.",
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
        "contract", "configuration_revision", "published_by"
    ).get(pk=publication.pk)
    return _contract_publication_detail_schema(publication)


@api.get(
    "/v1/contracts/{contract_code}/publications",
    response=list[ContractPublicationSummarySchema],
)
def list_contract_publications(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    publications = (
        ContractPublication.objects.select_related(
            "contract", "configuration_revision", "published_by"
        )
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
        ContractPublication.objects.select_related(
            "contract", "configuration_revision", "published_by"
        )
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
    try:
        return _contract_indicators_schema(contract)
    except IngestResolutionError as exc:
        raise _legacy_revision_error(exc) from exc


@api.get(
    "/v1/contracts/{contract_code}/indicators/{indicator_code}",
    response=ContractIndicatorSchema,
)
def get_contract_indicator(request, contract_code: str, indicator_code: str):
    contract = _get_authorized_contract(request, contract_code)
    try:
        indicators = _contract_indicators_schema(contract)
    except IngestResolutionError as exc:
        raise _legacy_revision_error(exc) from exc
    for item in indicators:
        if item.indicator.code == indicator_code:
            return item
    raise HttpError(404, "Indicator not found for the selected contract.")


@api.get(
    "/v1/contracts/{contract_code}/required-inputs", response=RequiredInputsResponse
)
def get_contract_required_inputs(request, contract_code: str):
    contract = _get_authorized_contract(request, contract_code)
    try:
        return _legacy_revision_required_inputs_schema(contract)
    except IngestResolutionError as exc:
        raise _legacy_revision_error(exc) from exc


@api.get("/v1/flow-catalog/input", response=list[InputFlowCatalogSchema])
def list_published_input_flows(request):
    _require_auth(request)
    flows = (
        InputFlowVersion.objects.filter(status=InputFlowVersion.Status.PUBLISHED)
        .select_related("dataset_specification__dataset")
        .order_by("dataset_specification__code", "version", "code")
    )
    return [_input_flow_catalog_schema(flow) for flow in flows]


@api.get("/v1/flow-catalog/input/{flow_code}", response=InputFlowCatalogSchema)
def get_published_input_flow(request, flow_code: str):
    _require_auth(request)
    flow = (
        InputFlowVersion.objects.filter(
            code=flow_code,
            status=InputFlowVersion.Status.PUBLISHED,
        )
        .select_related("dataset_specification__dataset")
        .first()
    )
    if flow is None:
        raise HttpError(404, "Published input flow not found.")
    return _input_flow_catalog_schema(flow)


@api.get(
    "/v1/flow-catalog/orchestration",
    response=list[OrchestrationFlowCatalogSchema],
)
def list_published_orchestration_flows(request):
    _require_auth(request)
    flows = OrchestrationFlowVersion.objects.filter(
        status=OrchestrationFlowVersion.Status.PUBLISHED
    ).order_by("version", "code")
    return [_orchestration_flow_catalog_schema(flow) for flow in flows]


@api.get(
    "/v1/flow-catalog/orchestration/{flow_code}",
    response=OrchestrationFlowCatalogSchema,
)
def get_published_orchestration_flow(request, flow_code: str):
    _require_auth(request)
    flow = OrchestrationFlowVersion.objects.filter(
        code=flow_code,
        status=OrchestrationFlowVersion.Status.PUBLISHED,
    ).first()
    if flow is None:
        raise HttpError(404, "Published orchestration flow not found.")
    return _orchestration_flow_catalog_schema(flow)


@api.get(
    "/v1/processing-profiles",
    response=list[ProcessingProfileCatalogSchema],
)
def list_published_processing_profiles(request):
    _require_auth(request)
    profiles = (
        ProcessingProfileVersion.objects.filter(
            status=ProcessingProfileVersion.Status.PUBLISHED
        )
        .prefetch_related(
            "input_flow_links__dataset",
            "input_flow_links__input_flow_version__dataset_specification",
            "indicator_version_links__indicator_version__indicator",
        )
        .order_by("name", "version", "code")
    )
    return [serialize_processing_profile(profile) for profile in profiles]


@api.get(
    "/v1/processing-profiles/{profile_code}",
    response=ProcessingProfileCatalogSchema,
)
def get_published_processing_profile(request, profile_code: str):
    _require_auth(request)
    profile = ProcessingProfileVersion.objects.filter(
        code=profile_code,
        status=ProcessingProfileVersion.Status.PUBLISHED,
    ).first()
    if profile is None:
        raise HttpError(404, "Published processing profile not found.")
    return serialize_processing_profile(profile)


@api.get("/v1/indicator-catalog", response=list[IndicatorCatalogSchema])
def list_published_indicator_catalog(request):
    _require_auth(request)
    indicators = (
        Indicator.objects.filter(
            status=Indicator.Status.ACTIVE,
            versions__status=IndicatorVersion.Status.PUBLISHED,
        )
        .prefetch_related(
            "versions__required_fragments__dataset_specification",
            "versions__required_fragments__validation_rules",
        )
        .order_by("code")
        .distinct()
    )
    return [serialize_indicator_catalog_entry(indicator) for indicator in indicators]


@api.get(
    "/v1/indicator-catalog/{indicator_code}",
    response=IndicatorCatalogSchema,
)
def get_published_indicator_catalog_entry(request, indicator_code: str):
    _require_auth(request)
    indicator = (
        Indicator.objects.filter(
            code=indicator_code,
            status=Indicator.Status.ACTIVE,
            versions__status=IndicatorVersion.Status.PUBLISHED,
        )
        .prefetch_related(
            "versions__required_fragments__dataset_specification",
            "versions__required_fragments__validation_rules",
        )
        .distinct()
        .first()
    )
    if indicator is None:
        raise HttpError(404, "Published indicator not found.")
    return serialize_indicator_catalog_entry(indicator)


@api.get("/v1/indicators", response=list[IndicatorSchema])
def list_indicators(request):
    _require_auth(request)
    versions = (
        IndicatorVersion.objects.filter(
            status=IndicatorVersion.Status.PUBLISHED,
            indicator__status=Indicator.Status.ACTIVE,
        )
        .select_related("indicator")
        .prefetch_related("required_fragments__dataset_specification__dataset")
        .order_by("indicator__code", "-version", "-id")
    )
    latest_by_indicator = {}
    for version in versions:
        latest_by_indicator.setdefault(version.indicator.code, version)
    return [
        _indicator_version_legacy_schema(version)
        for version in latest_by_indicator.values()
    ]


@api.get("/v1/indicators/{indicator_code}", response=IndicatorSchema)
def get_indicator(request, indicator_code: str):
    _require_auth(request)
    version = (
        IndicatorVersion.objects.filter(
            indicator__code=indicator_code,
            indicator__status=Indicator.Status.ACTIVE,
            status=IndicatorVersion.Status.PUBLISHED,
        )
        .select_related("indicator")
        .prefetch_related("required_fragments__dataset_specification__dataset")
        .order_by("-version", "-id")
        .first()
    )
    if version is None:
        raise HttpError(404, "Indicator not found.")
    return _indicator_version_legacy_schema(version)


@api.get("/v1/indicators/{indicator_code}/structures", response=list[StructureSchema])
def get_indicator_structures(request, indicator_code: str):
    _require_auth(request)
    version = (
        IndicatorVersion.objects.filter(
            indicator__code=indicator_code,
            indicator__status=Indicator.Status.ACTIVE,
            status=IndicatorVersion.Status.PUBLISHED,
        )
        .select_related("indicator")
        .prefetch_related("required_fragments__dataset_specification__dataset")
        .order_by("-version", "-id")
        .first()
    )
    if version is None:
        raise HttpError(404, "Indicator not found.")
    return _indicator_version_legacy_schema(version).structures


@api.get("/v1/structures", response=list[StructureSchema])
def list_structures(request, dataset_slug: str | None = None):
    _require_auth(request)
    qs = RequirementFragment.objects.filter(
        status=RequirementFragment.Status.PUBLISHED,
        dataset_specification__status=DatasetSpecification.Status.PUBLISHED,
    ).select_related("dataset_specification__dataset")
    if dataset_slug:
        qs = qs.filter(dataset_specification__dataset__code=dataset_slug)
    return [
        _fragment_structure_schema(fragment)
        for fragment in qs.order_by("dataset_specification__dataset__code", "name")
    ]


@api.get("/v1/datasets", response=list[DatasetCatalogSchema])
def list_published_datasets(request):
    _require_auth(request)
    datasets = (
        Dataset.objects.filter(
            status=Dataset.Status.ACTIVE,
            specifications__status=DatasetSpecification.Status.PUBLISHED,
        )
        .prefetch_related(
            "specifications__asset_links__configuration_asset",
            "specifications__requirement_fragments__validation_rules",
        )
        .order_by("code")
        .distinct()
    )
    return [_dataset_catalog_schema(dataset) for dataset in datasets]


@api.get("/v1/datasets/{dataset_code}", response=DatasetCatalogSchema)
def get_published_dataset(request, dataset_code: str):
    _require_auth(request)
    dataset = (
        Dataset.objects.filter(
            code=dataset_code,
            status=Dataset.Status.ACTIVE,
            specifications__status=DatasetSpecification.Status.PUBLISHED,
        )
        .prefetch_related(
            "specifications__asset_links__configuration_asset",
            "specifications__requirement_fragments__validation_rules",
        )
        .distinct()
        .first()
    )
    if dataset is None:
        raise HttpError(404, "Published dataset not found.")
    return _dataset_catalog_schema(dataset)


@api.get("/v1/structures/{structure_id}", response=StructureSchema)
def get_structure(request, structure_id: int):
    _require_auth(request)
    fragment = (
        RequirementFragment.objects.filter(
            id=structure_id,
            status=RequirementFragment.Status.PUBLISHED,
            dataset_specification__status=DatasetSpecification.Status.PUBLISHED,
        )
        .select_related("dataset_specification__dataset")
        .first()
    )
    if fragment is None:
        raise HttpError(404, "Structure not found.")
    return _fragment_structure_schema(fragment)


@api.get("/v1/flow-profiles", response=list[FlowProfileSchema])
def list_flow_profiles(request, is_active: bool | None = None):
    _require_auth(request)
    processing_profiles = ProcessingProfileVersion.objects.filter(
        status=ProcessingProfileVersion.Status.PUBLISHED
    )
    if is_active is False:
        processing_profiles = processing_profiles.none()
    return [
        _processing_profile_legacy_schema(profile)
        for profile in processing_profiles.order_by("code")
    ]


@api.get("/v1/flow-profiles/{flow_code}", response=FlowProfileSchema)
def get_flow_profile(request, flow_code: str):
    _require_auth(request)
    processing_profile = ProcessingProfileVersion.objects.filter(
        code=flow_code,
        status=ProcessingProfileVersion.Status.PUBLISHED,
    ).first()
    if processing_profile is not None:
        return _processing_profile_legacy_schema(processing_profile)
    raise HttpError(404, "Flow profile not found.")


@api.get("/v1/publications/{publication_id}", response=ContractPublicationDetailSchema)
def get_publication(request, publication_id: int):
    publication = (
        ContractPublication.objects.select_related(
            "contract", "configuration_revision", "published_by"
        )
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


@m2m_api.get(
    "/v3/validation-assets/{asset_type}/{dataset_code}/{version}/download",
    auth=[config_asset_m2m_auth, ValidationServiceTokenAuth()],
)
def m2m_validation_asset_download(
    request, asset_type: str, dataset_code: str, version: int
):
    """Resolve a frozen, stable asset identity for the external validator."""
    asset = ConfigurationAsset.objects.filter(
        asset_type=asset_type, what=dataset_code, version=version
    ).first()
    if asset is None:
        return m2m_api.create_response(
            request, {"detail": "Asset not found"}, status=404
        )
    try:
        content = load_configuration_asset_content(asset)
    except ValidationError as exc:
        return m2m_api.create_response(
            request,
            {
                "code": getattr(exc, "code", "invalid_schema_bundle"),
                "detail": "Validation asset integrity check failed",
            },
            status=409,
        )
    except Http404:
        return m2m_api.create_response(
            request,
            {"code": "missing_asset", "detail": "Asset content not found"},
            status=404,
        )
    if hashlib.sha256(content).hexdigest() != asset.checksum_sha256:
        return m2m_api.create_response(
            request, {"detail": "Asset checksum mismatch"}, status=409
        )
    response = HttpResponse(
        content, content_type=asset.content_type or "application/octet-stream"
    )
    response["X-RPSD-Checksum-SHA256"] = asset.checksum_sha256
    return response
