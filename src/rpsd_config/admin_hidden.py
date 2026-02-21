from django.contrib import admin

from rpsd_config.exchange_agreement.models import (
    Agency,
    Authority,
    Company,
    Contract,
    ContractDocument,
    ContractInvitation,
    ContractIndicator,
    ContractMembership,
    Dataset,
    IndicatorDef,
    Lot,
    Route,
    Stop,
    Structure,
    Trip,
)


class _HiddenAdmin(admin.ModelAdmin):
    """Registered only to enable autocomplete; hidden from index."""
    search_fields = ("id",)
    def get_model_perms(self, request):
        return {}

@admin.register(Agency)
class AgencyHidden(_HiddenAdmin):
    search_fields = ("name",)

@admin.register(Company)
class CompanyHidden(_HiddenAdmin):
    search_fields = ("name",)

@admin.register(Authority)
class AuthorityHidden(_HiddenAdmin):
    search_fields = ("name",)

@admin.register(Lot)
class LotHidden(_HiddenAdmin):
    search_fields = ("description",)

@admin.register(Route)
class RouteHidden(_HiddenAdmin):
    search_fields = ("code", "name")

@admin.register(Stop)
class StopHidden(_HiddenAdmin):
    search_fields = ("code", "name")

@admin.register(Trip)
class TripHidden(_HiddenAdmin):
    search_fields = ("code", "name")

@admin.register(Dataset)
class DatasetHidden(_HiddenAdmin):
    search_fields = ("slug", "name")

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
