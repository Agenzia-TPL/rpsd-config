# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Read-only audit browsing with a separate authorized notification operation."""

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from rpsd_config.admin_audit import proxies
from rpsd_config.admin_guidance import GuidedAdminMixin
from rpsd_config.exchange_agreement.services.configuration_assets import (
    retry_asset_event,
)


class EventAdmin(GuidedAdminMixin, admin.ModelAdmin):
    """Protect manual writes while preserving standard Django view permissions."""

    owner_field = ""

    def has_view_permission(self, request, obj=None):
        from rpsd_config.exchange_agreement.rbac import resolve_user_agency_scope

        if (
            self.owner_field == "rule_version"
            and resolve_user_agency_scope(request.user).is_platform_admin
        ):
            return True
        return super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + ("owner_link",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                self.owner_field,
                *(["rule_version__rule"] if self.owner_field == "rule_version" else []),
            )
        )

    def get_list_display(self, request):
        return (
            self.owner_field,
            "from_status",
            "to_status",
            "changed_by",
            "changed_at",
        )

    def render_change_form(
        self, request, context, add=False, change=False, form_url="", obj=None
    ):
        owner = getattr(obj, self.owner_field, None) if obj else None
        from rpsd_config.admin_dataset_exchange import proxies as catalog

        proxy_name = (type(owner).__name__ if owner else "") + "AdminProxy"
        target = getattr(catalog, proxy_name, None)
        target_admin = self.admin_site._registry.get(target)
        if owner and target_admin and target_admin.has_view_permission(request, owner):
            context["config_event_owner_url"] = reverse(
                f"admin:{target._meta.app_label}_{target._meta.model_name}_change",
                args=[owner.pk],
            )
        return super().render_change_form(request, context, add, change, form_url, obj)

    @admin.display(description="Oggetto/versione")
    def owner_link(self, obj):
        return str(getattr(obj, self.owner_field))


class AssetNotificationAdmin(EventAdmin):
    owner_field = "asset"
    ordering = ("-created_at", "-pk")
    date_hierarchy = "created_at"
    list_filter = ("status", "event_type", "created_at")
    search_fields = ("asset__what", "routing_key", "last_error")
    actions = ("retry_selected",)

    def get_list_display(self, request):
        return ("asset", "event_type", "status", "attempts", "last_error", "created_at")

    def has_retry_permission(self, request):
        return self.has_view_permission(request) and request.user.has_perm(
            "admin_audit.retry_configurationassetevent"
        )

    @admin.action(description="Ritenta invio", permissions=["retry"])
    def retry_selected(self, request, queryset):
        if not self.has_retry_permission(request):
            raise PermissionDenied
        if not settings.CONFIG_ASSETS_RABBITMQ_ENABLED:
            self.message_user(
                request,
                "Pubblicazione disabilitata: nessun invio effettuato.",
                messages.WARNING,
            )
            return
        counts = {"published": 0, "failed": 0, "skipped": 0}
        for pk in queryset.values_list("pk", flat=True):
            event = retry_asset_event(pk)
            if event is None:
                counts["skipped"] += 1
                continue
            counts[event.status] += 1
            self.log_change(request, event, f"Notification retry: {event.status}")
        self.message_user(
            request,
            f"Inviati: {counts['published']}; falliti: {counts['failed']}; "
            f"saltati: {counts['skipped']}.",
        )


admin.site.register(proxies.ConfigurationAssetEventAdminProxy, AssetNotificationAdmin)

admin.site.register(
    proxies.DatasetSpecificationStatusEventAdminProxy,
    type(
        "DatasetSpecificationStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "dataset_specification",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": ("dataset_specification__code",),
        },
    ),
)

admin.site.register(
    proxies.IndicatorVersionStatusEventAdminProxy,
    type(
        "IndicatorVersionStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "indicator_version",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": ("indicator_version__code",),
        },
    ),
)

admin.site.register(
    proxies.InputFlowVersionStatusEventAdminProxy,
    type(
        "InputFlowVersionStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "input_flow_version",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": ("input_flow_version__code",),
        },
    ),
)

admin.site.register(
    proxies.OrchestrationFlowVersionStatusEventAdminProxy,
    type(
        "OrchestrationFlowVersionStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "orchestration_flow_version",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": ("orchestration_flow_version__code",),
        },
    ),
)

admin.site.register(
    proxies.ProcessingProfileVersionStatusEventAdminProxy,
    type(
        "ProcessingProfileVersionStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "processing_profile_version",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": ("processing_profile_version__code",),
        },
    ),
)

admin.site.register(
    proxies.ValidationRuleStatusEventAdminProxy,
    type(
        "ValidationRuleStatusEventAdmin",
        (EventAdmin,),
        {
            "owner_field": "rule_version",
            "ordering": ("-changed_at", "-pk"),
            "date_hierarchy": "changed_at",
            "list_filter": ("to_status", "changed_by", "changed_at"),
            "search_fields": (
                "rule_version__rule__code",
                "rule_version__version",
            ),
        },
    ),
)
