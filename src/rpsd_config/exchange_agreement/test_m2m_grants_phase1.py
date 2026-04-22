# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import Agency, Company, Contract, IntegrationGrant, IntegrationPrincipal, Lot


class IntegrationGrantConstraintsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username="m2m-test-user",
            email="m2m-test@example.com",
            password="test-password",
        )
        self.agency = Agency.objects.create(name="Agenzia Test", agency_key="agenzia-test")
        self.company = Company.objects.create(name="Azienda Test")
        self.lot = Lot.objects.create(description="Lotto test")
        self.contract = Contract.objects.create(
            contract_code="CTR-9000",
            client_agency=self.agency,
            contractor_company=self.company,
            start_date=date.today(),
            lot=self.lot,
        )
        self.principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="default",
            environment=IntegrationPrincipal.Environment.PROD,
            keycloak_client_id="azienda-test-default-prod",
            created_by=self.user,
        )

    def test_active_grant_with_category_must_be_unique(self):
        IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            data_category="netex",
            status=IntegrationGrant.Status.ACTIVE,
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IntegrationGrant.objects.create(
                    principal=self.principal,
                    contract=self.contract,
                    action=IntegrationGrant.Action.INGEST_WRITE,
                    data_category="netex",
                    status=IntegrationGrant.Status.ACTIVE,
                    created_by=self.user,
                )

    def test_active_grant_without_category_must_be_unique(self):
        IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            data_category=None,
            status=IntegrationGrant.Status.ACTIVE,
            created_by=self.user,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                IntegrationGrant.objects.create(
                    principal=self.principal,
                    contract=self.contract,
                    action=IntegrationGrant.Action.INGEST_WRITE,
                    data_category=None,
                    status=IntegrationGrant.Status.ACTIVE,
                    created_by=self.user,
                )

    def test_disabled_duplicate_is_allowed(self):
        IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            data_category="siri-pt",
            status=IntegrationGrant.Status.DISABLED,
            created_by=self.user,
        )
        IntegrationGrant.objects.create(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            data_category="siri-pt",
            status=IntegrationGrant.Status.DISABLED,
            created_by=self.user,
        )

    def test_validity_window_must_be_coherent(self):
        grant = IntegrationGrant(
            principal=self.principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
            status=IntegrationGrant.Status.ACTIVE,
            created_by=self.user,
            valid_from=timezone.now(),
            valid_to=timezone.now() - timedelta(hours=1),
        )
        with self.assertRaises(ValidationError):
            grant.full_clean()
