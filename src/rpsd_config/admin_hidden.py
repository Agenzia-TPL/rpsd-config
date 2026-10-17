# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from django.contrib import admin

from rpsd_config.exchange_agreement.models import (
    Agency,
    AgencyInvitation,
    AgencyMembership,
    Authority,
    Company,
    ConfigurationAsset,
    ConfigurationAssetEvent,
    Contract,
    ContractDocument,
    ContractInvitation,
    ContractMembership,
    ContractPublication,
    Dataset,
    Indicator,
    IntegrationGrant,
    IntegrationPrincipal,
    Lot,
)


class _HiddenAdmin(admin.ModelAdmin):
    """Registered only to enable autocomplete; hidden from index."""

    search_fields = ("id",)

    def get_model_perms(self, request):
        return {}


@admin.register(Agency)
class AgencyHidden(_HiddenAdmin):
    search_fields = ("name", "agency_key")


@admin.register(Company)
class CompanyHidden(_HiddenAdmin):
    search_fields = ("name",)


@admin.register(Authority)
class AuthorityHidden(_HiddenAdmin):
    search_fields = ("name",)


@admin.register(Lot)
class LotHidden(_HiddenAdmin):
    list_display = ("id", "short_description", "description")
    readonly_fields = ("id", "created_at", "updated_at")
    search_fields = ("short_description", "description")

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)


@admin.register(Dataset)
class DatasetHidden(_HiddenAdmin):
    search_fields = ("code", "name")


@admin.register(Indicator)
class IndicatorHidden(_HiddenAdmin):
    search_fields = ("code", "name")


@admin.register(ConfigurationAsset)
class ConfigurationAssetHidden(_HiddenAdmin):
    search_fields = ("label", "original_filename", "storage_url")


@admin.register(ConfigurationAssetEvent)
class ConfigurationAssetEventHidden(_HiddenAdmin):
    search_fields = ("event_type", "routing_key", "last_error")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


@admin.register(Contract)
class ContractHidden(_HiddenAdmin):
    search_fields = ("contract_code",)


@admin.register(ContractDocument)
class ContractDocumentHidden(_HiddenAdmin):
    search_fields = ("name", "file")


@admin.register(ContractMembership)
class ContractMembershipHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "user__username", "user__email")


@admin.register(ContractInvitation)
class ContractInvitationHidden(_HiddenAdmin):
    search_fields = ("contract__contract_code", "email", "token")


@admin.register(AgencyMembership)
class AgencyMembershipHidden(_HiddenAdmin):
    list_display = (
        "agency",
        "user",
        "role",
        "status",
        "source",
        "last_synced_at",
        "revoked_at",
    )
    list_filter = ("status", "source", "role", "agency")
    readonly_fields = (
        "created_at",
        "updated_at",
        "last_synced_at",
        "last_sync_error",
        "keycloak_group_path",
        "keycloak_user_id",
        "revoked_at",
    )
    search_fields = (
        "agency__name",
        "agency__agency_key",
        "user__username",
        "user__email",
        "keycloak_group_path",
        "keycloak_user_id",
    )

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)


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


@admin.register(IntegrationPrincipal)
class IntegrationPrincipalHidden(_HiddenAdmin):
    list_display = (
        "keycloak_client_id",
        "company",
        "environment",
        "status",
        "client_secret_updated_at",
        "last_secret_rotation_at",
    )
    list_filter = ("status", "environment", "company")
    readonly_fields = (
        "created_at",
        "updated_at",
        "client_secret_updated_at",
        "last_secret_rotation_at",
    )
    exclude = ("client_secret_ciphertext",)
    search_fields = ("keycloak_client_id", "keycloak_client_uuid", "company__name")

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)


@admin.register(IntegrationGrant)
class IntegrationGrantHidden(_HiddenAdmin):
    list_display = (
        "principal",
        "contract",
        "action",
        "data_category",
        "status",
        "valid_from",
        "valid_to",
    )
    list_filter = ("status", "action", "contract", "principal__company")
    readonly_fields = ("created_at", "updated_at")
    search_fields = (
        "principal__keycloak_client_id",
        "contract__contract_code",
        "data_category",
    )

    def get_model_perms(self, request):
        return admin.ModelAdmin.get_model_perms(self, request)
