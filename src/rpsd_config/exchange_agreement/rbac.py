# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import re
from dataclasses import dataclass

from allauth.socialaccount.models import SocialAccount
from django.conf import settings

from rpsd_config.server.socialaccount_adapter import _extract_groups_from_extra_data

from .models import AgencyMembership


@dataclass(frozen=True)
class AgencyScope:
    is_platform_admin: bool
    admin_agency_keys: frozenset[str]
    editor_agency_keys: frozenset[str]
    reader_agency_keys: frozenset[str]

    def can_manage_agency(self, agency_key: str) -> bool:
        return self.is_platform_admin or agency_key in self.admin_agency_keys


def group_root_path() -> str:
    raw = getattr(settings, "KEYCLOAK_ADMIN_GROUP_ROOT", "/rpsd") or "/rpsd"
    normalized = "/" + "/".join([segment for segment in raw.split("/") if segment])
    return normalized if normalized != "/" else "/rpsd"


def platform_admin_group_path() -> str:
    return f"{group_root_path()}/admin"


def _agency_group_regex() -> re.Pattern[str]:
    root = re.escape(group_root_path())
    return re.compile(
        rf"^{root}/([a-z0-9](?:[a-z0-9-]{{1,38}}[a-z0-9]))/(admin|editor|reader)$"
    )


def extract_user_groups(user) -> set[str]:
    social = (
        SocialAccount.objects.filter(user=user)
        .order_by("-last_login", "-date_joined")
        .first()
    )
    if social is None:
        return set()
    extra_data = social.extra_data if isinstance(social.extra_data, dict) else {}
    return _extract_groups_from_extra_data(extra_data)


def resolve_user_agency_scope(user) -> AgencyScope:
    if getattr(user, "is_superuser", False):
        return AgencyScope(
            is_platform_admin=True,
            admin_agency_keys=frozenset(),
            editor_agency_keys=frozenset(),
            reader_agency_keys=frozenset(),
        )

    groups = extract_user_groups(user)
    regex = _agency_group_regex()

    admin_keys: set[str] = set()
    editor_keys: set[str] = set()
    reader_keys: set[str] = set()

    for group in groups:
        match = regex.match(group)
        if not match:
            continue
        agency_key = match.group(1)
        role_suffix = match.group(2)
        if role_suffix == "admin":
            admin_keys.add(agency_key)
        elif role_suffix == "editor":
            editor_keys.add(agency_key)
        else:
            reader_keys.add(agency_key)

    return AgencyScope(
        is_platform_admin=platform_admin_group_path() in groups,
        admin_agency_keys=frozenset(admin_keys),
        editor_agency_keys=frozenset(editor_keys),
        reader_agency_keys=frozenset(reader_keys),
    )


def agency_role_to_group_suffix(role: str) -> str:
    mapping = {
        AgencyMembership.Role.AGENCY_ADMIN: "admin",
        AgencyMembership.Role.AGENCY_EDITOR: "editor",
        AgencyMembership.Role.AGENCY_READER: "reader",
    }
    if role not in mapping:
        raise ValueError(f"Unsupported agency role: {role}")
    return mapping[role]


def agency_group_suffix_to_role(suffix: str) -> str:
    mapping = {
        "admin": AgencyMembership.Role.AGENCY_ADMIN,
        "editor": AgencyMembership.Role.AGENCY_EDITOR,
        "reader": AgencyMembership.Role.AGENCY_READER,
    }
    if suffix not in mapping:
        raise ValueError(f"Unsupported agency group suffix: {suffix}")
    return mapping[suffix]


def agency_role_to_group_path(*, agency_key: str, role: str) -> str:
    suffix = agency_role_to_group_suffix(role)
    return f"{group_root_path()}/{agency_key}/{suffix}"


def iter_agency_group_assignments(groups: set[str] | list[str] | tuple[str, ...]):
    regex = _agency_group_regex()
    for group in groups:
        if not isinstance(group, str):
            continue
        match = regex.match(group)
        if not match:
            continue
        yield {
            "group_path": group,
            "agency_key": match.group(1),
            "role": agency_group_suffix_to_role(match.group(2)),
        }
