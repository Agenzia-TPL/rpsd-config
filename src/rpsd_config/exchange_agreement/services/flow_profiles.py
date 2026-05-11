# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction

from rpsd_config.exchange_agreement.models import FlowProfile, OperationalFlow


STANDARD_TPL_PROFILE_CODE = "standard-tpl-programmato-realtime"
NETEX_ONLY_PROFILE_CODE = "solo-programmato-netex"


@dataclass(frozen=True)
class StandardOperationalFlow:
    code: str
    deployment_name: str
    supported_what: str
    description: str
    version: str = "001"
    engine: str = OperationalFlow.Engine.PREFECT
    status: str = OperationalFlow.Status.ACTIVE


@dataclass(frozen=True)
class StandardFlowProfile:
    code: str
    name: str
    description: str
    schema_version: str
    options: dict[str, Any]
    is_active: bool = True


CANONICAL_SIRI_WHATS = (
    "siri-pt",
    "siri-et",
    "siri-st",
    "siri-sm",
    "siri-vm",
    "siri-ct",
    "siri-cm",
    "siri-gm",
    "siri-fm",
    "siri-sx",
)


STANDARD_OPERATIONAL_FLOWS: tuple[StandardOperationalFlow, ...] = (
    StandardOperationalFlow(
        code="netex_001",
        deployment_name="validators/netex-default",
        supported_what="netex",
        description="Validazione e ingest programmato NeTEx.",
    ),
    *(
        StandardOperationalFlow(
            code=f"{what}_001",
            deployment_name=f"validators/{what}-default",
            supported_what=what,
            description=f"Validazione e ingest {what.upper()}.",
        )
        for what in CANONICAL_SIRI_WHATS
    ),
)


def _siri_ingestion_options(*, active: bool) -> dict[str, dict[str, Any]]:
    return {
        what: {
            "active": active,
            "flow": f"{what}_001",
            "description": (
                f"Invio real time {what.upper()}."
                if active
                else f"Real time {what.upper()} non abilitato per questo profilo."
            ),
        }
        for what in CANONICAL_SIRI_WHATS
    }


STANDARD_FLOW_PROFILES: tuple[StandardFlowProfile, ...] = (
    StandardFlowProfile(
        code=STANDARD_TPL_PROFILE_CODE,
        name="Standard TPL - Programmato + Real time",
        description=(
            "Profilo standard per contratti TPL con dati programmati NeTEx "
            "e flussi real time SIRI."
        ),
        schema_version="1.0",
        options={
            "general_profile": "standard-tpl",
            "planned_master": {
                "netex": {
                    "active": True,
                    "flow": "netex_001",
                    "description": "Programma di esercizio contrattuale NeTEx.",
                }
            },
            "data_ingestion": {
                "netex": {
                    "active": True,
                    "flow": "netex_001",
                    "description": "Invio dati programmati NeTEx.",
                },
                **_siri_ingestion_options(active=True),
            },
            "data_retention": {
                "planned": {
                    "days": 365,
                    "flow": "retention-planned",
                    "description": "Conservazione dati programmati.",
                },
                "realtime": {
                    "days": 90,
                    "flow": "retention-realtime",
                    "description": "Conservazione dati real time.",
                },
            },
        },
    ),
    StandardFlowProfile(
        code=NETEX_ONLY_PROFILE_CODE,
        name="Solo Programmato NeTEx",
        description="Profilo minimale per contratti che prevedono solo invio programmato NeTEx.",
        schema_version="1.0",
        options={
            "general_profile": "planned-netex-only",
            "planned_master": {
                "netex": {
                    "active": True,
                    "flow": "netex_001",
                    "description": "Programma di esercizio contrattuale NeTEx.",
                }
            },
            "data_ingestion": {
                "netex": {
                    "active": True,
                    "flow": "netex_001",
                    "description": "Invio dati programmati NeTEx.",
                },
                **_siri_ingestion_options(active=False),
            },
            "data_retention": {
                "planned": {
                    "days": 365,
                    "flow": "retention-planned",
                    "description": "Conservazione dati programmati.",
                }
            },
        },
    ),
)


def ensure_standard_operational_flows() -> list[OperationalFlow]:
    ensured: list[OperationalFlow] = []
    with transaction.atomic():
        for definition in STANDARD_OPERATIONAL_FLOWS:
            flow, created = OperationalFlow.objects.get_or_create(
                code=definition.code,
                defaults={
                    "engine": definition.engine,
                    "deployment_name": definition.deployment_name,
                    "supported_what": definition.supported_what,
                    "status": definition.status,
                    "description": definition.description,
                    "version": definition.version,
                },
            )
            if not created and not flow.is_referenced_by_flow_profiles():
                flow.engine = definition.engine
                flow.deployment_name = definition.deployment_name
                flow.supported_what = definition.supported_what
                flow.status = definition.status
                flow.description = definition.description
                flow.version = definition.version
                flow.save()
            ensured.append(flow)
    return ensured


def summarize_flow_profile_options(
    options: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    options = options if isinstance(options, dict) else {}

    def summarize_block(block_key: str) -> list[dict[str, Any]]:
        block = options.get(block_key)
        if not isinstance(block, dict):
            return []
        rows = []
        for data_category, config in sorted(block.items()):
            if not isinstance(config, dict):
                continue
            rows.append(
                {
                    "data_category": data_category,
                    "active": bool(config.get("active")),
                    "flow": config.get("flow") or "",
                    "description": config.get("description") or "",
                }
            )
        return rows

    return {
        "planned_master": summarize_block("planned_master"),
        "data_ingestion": summarize_block("data_ingestion"),
        "data_retention": [
            {
                "data_category": data_category,
                "active": True,
                "flow": config.get("flow") or "",
                "description": config.get("description") or "",
                "days": config.get("days"),
            }
            for data_category, config in sorted(
                (options.get("data_retention") or {}).items()
            )
            if isinstance(config, dict)
        ]
        if isinstance(options.get("data_retention"), dict)
        else [],
    }


def ensure_standard_flow_profiles() -> list[FlowProfile]:
    ensure_standard_operational_flows()
    ensured: list[FlowProfile] = []
    with transaction.atomic():
        for definition in STANDARD_FLOW_PROFILES:
            profile, created = FlowProfile.objects.get_or_create(
                code=definition.code,
                defaults={
                    "name": definition.name,
                    "description": definition.description,
                    "schema_version": definition.schema_version,
                    "options": definition.options,
                    "is_active": definition.is_active,
                },
            )
            if not created and not profile.contracts.exists():
                profile.name = definition.name
                profile.description = definition.description
                profile.schema_version = definition.schema_version
                profile.options = definition.options
                profile.is_active = definition.is_active
                profile.save()
            ensured.append(profile)
    return ensured


def get_default_flow_profile() -> FlowProfile | None:
    profile = FlowProfile.objects.filter(
        code=STANDARD_TPL_PROFILE_CODE,
        is_active=True,
    ).first()
    if profile is not None:
        return profile
    return FlowProfile.objects.filter(is_active=True).order_by("code").first()
