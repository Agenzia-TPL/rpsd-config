from __future__ import annotations

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from rpsd_config.exchange_agreement.models import (
    Agency,
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
    IndicatorType,
    Lot,
    Structure,
)
from rpsd_config.exchange_agreement.services.publication import (
    PublishContractError,
    publish_contract,
)


class Command(BaseCommand):
    help = "Create coherent dummy data across exchange_agreement models."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=42, help="Random seed.")
        parser.add_argument(
            "--lots", type=int, default=3, help="How many lots/contracts to create."
        )
        parser.add_argument(
            "--indicators", type=int, default=6, help="Number of indicator definitions."
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing data before seeding.",
        )
        parser.add_argument(
            "--publish-contracts",
            action="store_true",
            help="Publish seeded contracts after creating memberships and indicators.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])

        if options["reset"]:
            self._reset_data()

        admin_user, reader_user = self._ensure_users()
        agencies = self._ensure_agencies()
        companies = self._ensure_companies()
        authorities = self._ensure_authorities()
        lots = self._ensure_lots(options["lots"])

        datasets = self._ensure_datasets()
        structures = self._ensure_structures(datasets)
        indicators = self._ensure_indicators(structures, options["indicators"])
        flow_profiles = self._ensure_flow_profiles()

        contracts = self._ensure_contracts(lots, agencies, companies, flow_profiles)
        self._ensure_contract_files(contracts)
        self._ensure_contract_docs(contracts)
        self._ensure_contract_indicators(contracts, indicators)
        self._ensure_memberships(contracts, admin_user, reader_user)
        self._ensure_invitations(contracts, admin_user)
        published_count = 0
        if options["publish_contracts"]:
            published_count = self._ensure_publications(contracts, admin_user)

        self.stdout.write(
            self.style.SUCCESS(
                "Dummy data created:"
                f" agencies={len(agencies)}, companies={len(companies)},"
                f" authorities={len(authorities)}, lots={len(lots)},"
                f" datasets={len(datasets)}, structures={len(structures)},"
                f" indicators={len(indicators)}, flow_profiles={len(flow_profiles)},"
                f" contracts={len(contracts)}, publications={published_count}"
            )
        )

    def _reset_data(self):
        ContractInvitation.objects.all().delete()
        ContractMembership.objects.all().delete()
        ContractPublication.objects.all().delete()
        ContractIndicator.objects.all().delete()
        ContractDocument.objects.all().delete()
        Contract.objects.all().delete()

        IndicatorDef.objects.all().delete()
        FlowProfile.objects.all().delete()
        Structure.objects.all().delete()
        Dataset.objects.all().delete()

        Lot.objects.all().delete()
        Authority.objects.all().delete()
        Agency.objects.all().delete()
        Company.objects.all().delete()

    def _ensure_users(self):
        user_model = get_user_model()
        admin_user, _ = user_model.objects.get_or_create(
            username="dummy_admin",
            defaults={
                "email": "dummy_admin@example.com",
                "is_staff": True,
            },
        )
        admin_user.set_password("dummy_admin")
        admin_user.save(update_fields=["password"])

        reader_user, _ = user_model.objects.get_or_create(
            username="dummy_reader",
            defaults={
                "email": "dummy_reader@example.com",
            },
        )
        reader_user.set_password("dummy_reader")
        reader_user.save(update_fields=["password"])
        return admin_user, reader_user

    def _ensure_agencies(self):
        names = ["Agency Nord", "Agency Centro", "Agency Sud"]
        items = []
        for name in names:
            obj, _ = Agency.objects.get_or_create(
                name=name,
                defaults={"description": f"Dummy agency {name}"},
            )
            items.append(obj)
        return items

    def _ensure_companies(self):
        names = ["Company Alpha", "Company Beta", "Company Gamma"]
        items = []
        for name in names:
            obj, _ = Company.objects.get_or_create(
                name=name,
                defaults={"description": f"Dummy company {name}"},
            )
            items.append(obj)
        return items

    def _ensure_authorities(self):
        names = [
            ("Regione Lombardia", Authority.AuthorityType.REGION),
            ("Comune Milano", Authority.AuthorityType.MUNICIPALITY),
            ("Comune Bergamo", Authority.AuthorityType.MUNICIPALITY),
        ]
        items = []
        for name, authority_type in names:
            obj, _ = Authority.objects.get_or_create(
                name=name,
                authority_type=authority_type,
                defaults={"description": f"Dummy authority {name}"},
            )
            items.append(obj)
        return items

    def _ensure_lots(self, count: int):
        items = []
        for i in range(1, count + 1):
            obj, _ = Lot.objects.get_or_create(
                short_description=f"L{i}",
                description=f"Lot dummy {i}",
            )
            items.append(obj)
        return items

    def _ensure_datasets(self):
        specs = [
            ("netex", "NeTEx"),
            ("siri_pt", "SIRI PT"),
            ("siri_vm", "SIRI VM"),
        ]
        items = []
        for slug, name in specs:
            obj, _ = Dataset.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": f"Dummy dataset {name}"},
            )
            items.append(obj)
        return items

    def _ensure_structures(self, datasets):
        items = []
        for dataset in datasets:
            for idx in range(1, 3):
                name = f"{dataset.slug}_structure_{idx}"
                definition = {
                    "xpath": f"//{dataset.slug}/node_{idx}",
                    "fields": ["id", "timestamp", f"value_{idx}"],
                }
                obj, _ = Structure.objects.get_or_create(
                    dataset=dataset,
                    name=name,
                    defaults={
                        "description": f"Dummy structure {name}",
                        "definition": definition,
                    },
                )
                items.append(obj)
        return items

    def _ensure_indicators(self, structures, count: int):
        indicator_types = [
            IndicatorType.QUALITY,
            IndicatorType.QUANTITY,
            IndicatorType.PUNCTUALITY,
            IndicatorType.OTHER,
        ]
        items = []
        for i in range(1, count + 1):
            code = f"IND_{i:03d}"
            indicator, _ = IndicatorDef.objects.get_or_create(
                code=code,
                defaults={
                    "type": indicator_types[(i - 1) % len(indicator_types)],
                    "name": f"Indicatore {i}",
                    "description": f"Indicatore dummy {i}",
                    "formula": "a / b",
                    "notes": "Dummy notes",
                    "sql_procedure_name": f"sp_indicator_{i:03d}",
                    "sql_snippet": f"SELECT * FROM calc_indicator_{i:03d}();",
                },
            )
            selected = random.sample(structures, k=min(3, len(structures)))
            indicator.structures.set(selected)
            items.append(indicator)
        return items

    def _ensure_flow_profiles(self):
        profiles = [
            {
                "code": "standard-it-v1",
                "name": "Standard IT v1",
                "description": "Profilo standard per import e retention base.",
                "schema_version": "1.0",
                "options": {
                    "general_profile": "it",
                    "planned_master": {
                        "netex": {
                            "active": True,
                            "flow": "master-001",
                            "description": (
                                "Carica il programmato master in formato NeTEx."
                            ),
                        },
                        "gtfs": {
                            "active": True,
                            "flow": "master-002",
                            "description": "Importa GTFS e lo converte in NeTEx.",
                        },
                    },
                    "data_ingestion": {
                        "netex": {
                            "active": True,
                            "flow": "plnd-001",
                            "description": "Carica il programmato da NeTEx.",
                        },
                        "gtfs": {
                            "active": False,
                            "flow": "plnd-002",
                            "description": "Carica GTFS con step di trasformazione.",
                        },
                        "siri_pt": {
                            "active": True,
                            "flow": "rltm-spt-001",
                            "description": "Acquisisce real time SIRI PT.",
                        },
                    },
                    "data_retention": {
                        "plnd": {
                            "days": 100,
                            "flow": "plnd-clr-001",
                            "description": "Pulizia storico programmato.",
                        },
                        "rltm": {
                            "days": 3,
                            "flow": "rltm-clr-001",
                            "description": "Pulizia storico real time.",
                        },
                    },
                },
            },
            {
                "code": "lightweight-it-v1",
                "name": "Lightweight IT v1",
                "description": "Profilo leggero con ridotte sorgenti attive.",
                "schema_version": "1.0",
                "options": {
                    "general_profile": "it",
                    "planned_master": {
                        "netex": {
                            "active": True,
                            "flow": "master-010",
                            "description": "Master NeTEx base.",
                        }
                    },
                    "data_ingestion": {
                        "netex": {
                            "active": True,
                            "flow": "plnd-010",
                            "description": "Ingest programmato NeTEx.",
                        },
                        "siri_pt": {
                            "active": False,
                            "flow": "rltm-spt-010",
                            "description": "Canale SIRI PT disabilitato.",
                        },
                    },
                    "data_retention": {
                        "plnd": {
                            "days": 30,
                            "flow": "plnd-clr-010",
                            "description": "Pulizia programmato breve.",
                        },
                        "rltm": {
                            "days": 1,
                            "flow": "rltm-clr-010",
                            "description": "Pulizia real time giornaliera.",
                        },
                    },
                },
            },
        ]

        items = []
        for spec in profiles:
            obj, _ = FlowProfile.objects.get_or_create(
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "schema_version": spec["schema_version"],
                    "options": spec["options"],
                    "is_active": True,
                },
            )
            items.append(obj)
        return items

    def _ensure_contracts(self, lots, agencies, companies, flow_profiles):
        items = []
        today = timezone.now().date()
        for i, lot in enumerate(lots, start=1):
            contract_code = f"CTR-{i:03d}"
            client_agency = agencies[(i - 1) % len(agencies)]
            contractor_company = companies[(i - 1) % len(companies)]
            contract, _ = Contract.objects.get_or_create(
                contract_code=contract_code,
                defaults={
                    "client_agency": client_agency,
                    "contractor_company": contractor_company,
                    "start_date": today - timedelta(days=30),
                    "status": Contract.ContractStatus.ACTIVE,
                    "tender_id": f"TENDER-{i:03d}",
                    "lot": lot,
                    "flow_profile": flow_profiles[(i - 1) % len(flow_profiles)]
                    if flow_profiles
                    else None,
                },
            )
            if flow_profiles and contract.flow_profile is None:
                contract.flow_profile = flow_profiles[(i - 1) % len(flow_profiles)]
                contract.save(update_fields=["flow_profile", "updated_at"])
            items.append(contract)
        return items

    def _ensure_contract_files(self, contracts):
        for contract in contracts:
            if not contract.contract_program_file:
                payload = (
                    f"<Program contract='{contract.contract_code}'>"
                    "<Dummy>true</Dummy>"
                    "</Program>"
                )
                contract.contract_program_file.save(
                    f"{contract.contract_code.lower()}_program.xml",
                    ContentFile(payload.encode("utf-8")),
                    save=True,
                )

    def _ensure_contract_docs(self, contracts):
        for contract in contracts:
            name = f"Documento {contract.contract_code}"
            existing = ContractDocument.objects.filter(
                contract=contract, name=name
            ).first()
            if existing:
                continue
            doc = ContractDocument(contract=contract, name=name)
            doc.file.save(
                f"{contract.contract_code.lower()}_doc.pdf",
                ContentFile(b"%PDF-1.4\n% Dummy PDF content\n"),
                save=True,
            )

    def _ensure_contract_indicators(self, contracts, indicators):
        for contract in contracts:
            selected = random.sample(indicators, k=min(4, len(indicators)))
            for indicator in selected:
                ContractIndicator.objects.get_or_create(
                    contract=contract,
                    indicator=indicator,
                    defaults={
                        "params": {
                            "weight": round(random.uniform(0.1, 1.0), 2),
                            "threshold": random.randint(60, 95),
                        }
                    },
                )

    def _ensure_memberships(self, contracts, admin_user, reader_user):
        for contract in contracts:
            ContractMembership.objects.get_or_create(
                contract=contract,
                user=admin_user,
                defaults={
                    "role": ContractMembership.Role.CONTRACT_ADMIN,
                    "created_by": admin_user,
                },
            )
            ContractMembership.objects.get_or_create(
                contract=contract,
                user=reader_user,
                defaults={
                    "role": ContractMembership.Role.CONTRACT_READER,
                    "created_by": admin_user,
                },
            )

    def _ensure_invitations(self, contracts, admin_user):
        for contract in contracts:
            ContractInvitation.objects.get_or_create(
                contract=contract,
                email="invited_user@example.com",
                role_to_assign=ContractMembership.Role.CONTRACT_READER,
                status=ContractInvitation.Status.PENDING,
                defaults={
                    "invited_by": admin_user,
                    "expires_at": timezone.now() + timedelta(days=7),
                },
            )
            ContractInvitation.objects.get_or_create(
                contract=contract,
                email=None,
                role_to_assign=ContractMembership.Role.CONTRACT_ADMIN,
                status=ContractInvitation.Status.PENDING,
                defaults={
                    "invited_by": admin_user,
                    "expires_at": timezone.now() + timedelta(days=7),
                },
            )

    def _ensure_publications(self, contracts, admin_user):
        count = 0
        for contract in contracts:
            if ContractPublication.objects.filter(contract=contract).exists():
                continue
            try:
                publish_contract(contract=contract, user=admin_user)
            except PublishContractError as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipping publish for {contract.contract_code}: {exc.message}"
                    )
                )
                continue
            count += 1
        return count
