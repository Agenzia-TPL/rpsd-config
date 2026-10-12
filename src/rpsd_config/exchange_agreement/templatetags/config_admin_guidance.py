# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Scoped readonly association labels without domain or permission changes."""

from django import template
from django.contrib.admin.helpers import AdminReadonlyField
from django.contrib.admin.utils import lookup_field
from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import conditional_escape

from rpsd_config.admin_guidance import relation_label

register = template.Library()


@register.simple_tag
def guided_readonly(field: AdminReadonlyField) -> str:
    """Keep Django contents except for associations with otherwise opaque labels."""
    try:
        value = lookup_field(
            field.field["field"], field.form.instance, field.model_admin
        )[2]
    except (AttributeError, ValueError, ObjectDoesNotExist):
        return field.contents()
    if (
        value is not None
        and hasattr(value, "_meta")
        and value._meta.concrete_model.__name__
        in {
            "DatasetVersionRule",
            "IndicatorVersionDependency",
            "ProcessingProfileInputFlow",
            "ProcessingProfileIndicatorVersion",
        }
    ):
        return conditional_escape(relation_label(value))
    return field.contents()
