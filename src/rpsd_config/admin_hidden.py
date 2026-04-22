# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib import admin

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    Authority,
    Company,
    Contract,
    ContractDocument,
    ContractIndicator,
    ContractInvitation,
    ContractMembership,
    ContractPublication,
    Dataset,
    FlowProfile,
    IntegrationGrant,
    IntegrationPrincipal,
    IndicatorProfile,
    IndicatorDef,
    Lot,
    NetexValidationProfile,
    SiriValidationProfile,
    Structure,
)


class _HiddenAdmin(admin.ModelAdmin):
    """Registered only to enable autocomplete; hidden from index."""

    search_fields = ("id",)

    def get_model_perms(self, request):
        return {}


class _VisibleReadOnlyAdmin(_HiddenAdmin):
    """Visible in admin index, but not editable from Django admin."""

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = [field.name for field in self.model._meta.fields]
        for field_name in self.readonly_fields:
            if field_name not in fields:
                fields.append(field_name)
        return tuple(fields)


@admin.register(Agency)
class AgencyHidden(_HiddenAdmin):
    search_fields = ("name", "agency_key")


@admin.register(Company)
class CompanyHidden(_HiddenAdmin):
    search_fields = ("name",)


@admin.register(IntegrationPrincipal)
class IntegrationPrincipalHidden(_VisibleReadOnlyAdmin):
    list_display = (
        "company",
        "name",
        "environment",
        "keycloak_client_id",
        "keycloak_client_uuid",
        "status",
        "client_secret_key_id",
        "client_secret_updated_at",
        "last_secret_rotation_at",
        "created_by",
        "updated_at",
    )
    list_filter = ("status", "environment", "company")
    search_fields = ("company__name", "name", "keycloak_client_id")
    exclude = ("client_secret_ciphertext",)
    readonly_fields = ("created_at", "updated_at", "last_secret_rotation_at")


@admin.register(IntegrationGrant)
class IntegrationGrantHidden(_VisibleReadOnlyAdmin):
    list_display = (
        "principal",
        "contract",
        "action",
        "data_category",
        "status",
        "valid_from",
        "valid_to",
        "created_by",
        "updated_at",
    )
    list_filter = ("status", "action", "data_category")
    search_fields = (
        "principal__keycloak_client_id",
        "principal__company__name",
        "contract__contract_code",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Authority)
class AuthorityHidden(_HiddenAdmin):
    search_fields = ("name",)


@admin.register(Lot)
class LotHidden(_HiddenAdmin):
    search_fields = ("description",)


@admin.register(Dataset)
class DatasetHidden(_HiddenAdmin):
    search_fields = ("slug", "name")


@admin.register(FlowProfile)
class FlowProfileHidden(_HiddenAdmin):
    search_fields = ("code", "name")


@admin.register(NetexValidationProfile)
class NetexValidationProfileHidden(_HiddenAdmin):
    search_fields = ("label", "file")


@admin.register(SiriValidationProfile)
class SiriValidationProfileHidden(_HiddenAdmin):
    search_fields = ("profile_type", "label", "file")


@admin.register(IndicatorProfile)
class IndicatorProfileHidden(_HiddenAdmin):
    search_fields = ("label", "file")


@admin.register(Structure)
class StructureHidden(_HiddenAdmin):
    search_fields = ("name", "dataset__slug")


@admin.register(IndicatorDef)
class IndicatorDefHidden(_HiddenAdmin):
    search_fields = ("code", "name")


@admin.register(Contract)
class ContractHidden(_HiddenAdmin):
    search_fields = ("contract_code",)


@admin.register(ContractDocument)
class ContractDocumentHidden(_HiddenAdmin):
    search_fields = ("name", "file")


@admin.register(ContractIndicator)
class ContractIndicatorHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "indicator__code", "indicator__name")


@admin.register(ContractMembership)
class ContractMembershipHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "user__username", "user__email")


@admin.register(ContractInvitation)
class ContractInvitationHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "email", "token")


@admin.register(AgencyMembership)
class AgencyMembershipHidden(_HiddenAdmin):
    search_fields = ("agency__name", "agency__agency_key", "user__username", "user__email")


@admin.register(AgencyInvitation)
class AgencyInvitationHidden(_HiddenAdmin):
    list_display = (
        "agency",
        "email",
        "role_to_assign",
        "status",
        "expires_at",
        "invited_by",
        "accepted_by",
        "rejected_by",
    )
    list_filter = ("status", "role_to_assign", "agency")
    readonly_fields = (
        "token",
        "created_at",
        "updated_at",
        "accepted_at",
        "rejected_at",
    )
    search_fields = ("agency__name", "agency__agency_key", "email", "token")

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)


@admin.register(ContractPublication)
class ContractPublicationHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "snapshot_checksum")
