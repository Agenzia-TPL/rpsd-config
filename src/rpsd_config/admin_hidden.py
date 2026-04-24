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
    IndicatorDef,
    IndicatorProfile,
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
    search_fields = (
        "agency__name",
        "agency__agency_key",
        "user__username",
        "user__email",
    )


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
