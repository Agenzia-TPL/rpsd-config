# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Show owned draft associations on Django's normal deletion confirmation."""

from django.db import transaction


class DraftDeletionAdminMixin:
    def get_deleted_objects(self, objs, request):
        from rpsd_config.exchange_agreement.services.draft_cleanup import (
            draft_deletion_plan,
        )

        rows = list(objs)
        if any(getattr(obj, "status", None) != "draft" for obj in rows):
            return super().get_deleted_objects(rows, request)
        objects, blockers = {}, []
        for obj in rows:
            owned, protected = draft_deletion_plan(obj, actor=request.user)
            objects.update({(row._meta.label_lower, row.pk): row for row in owned})
            blockers.extend(protected)
        counts = {}
        for row in objects.values():
            name = str(row._meta.verbose_name_plural)
            counts[name] = counts.get(name, 0) + 1
        return (
            [str(row) for row in objects.values()],
            counts,
            set(),
            sorted(set(blockers)),
        )

    def delete_model(self, request, obj):
        from rpsd_config.exchange_agreement.services.draft_cleanup import delete_draft

        delete_draft(obj, actor=request.user)

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        for obj in queryset:
            self.delete_model(request, obj)
