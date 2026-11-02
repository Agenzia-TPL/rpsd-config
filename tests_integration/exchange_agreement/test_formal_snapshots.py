# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Formal metadata are frozen and require a compatible, authorized consumer."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from rpsd_config.exchange_agreement.models import IntegrationGrant, IntegrationPrincipal
from rpsd_config.exchange_agreement.services.contract_revisions import (
    create_revision_draft,
)
from rpsd_config.exchange_agreement.services.formal_definitions import (
    LANGUAGE_VERSION,
    validate_frozen_formal_metadata,
    verify_definition,
)
from rpsd_config.exchange_agreement.services.indicator_catalog import (
    publish_indicator_version,
)
from rpsd_config.exchange_agreement.services.ingest_resolution import (
    IngestResolutionError,
)
from rpsd_config.server.m2m_auth import M2MAuthContext
from tests_integration.exchange_agreement.test_contract_configuration_revisions import (
    _ContractRevisionFixtureMixin,
)


class FormalSnapshotTests(_ContractRevisionFixtureMixin, TestCase):
    def setUp(self):
        def publish(version, **kwargs):
            version.indicator.formula_symbol = "DISTANCE"
            version.indicator.save()
            version.definition_kind = "base"
            version.formula_language_version = LANGUAGE_VERSION
            version.save()
            version = verify_definition(version, actor=kwargs["actor"])
            return publish_indicator_version(version, **kwargs)

        with patch(
            "tests_integration.exchange_agreement.test_contract_configuration_revisions.publish_indicator_version",
            side_effect=publish,
        ):
            super().setUp()
        self.revision = self._revision(number=1, valid_from=self.contract.start_date)
        owner = self.revision.indicator_configurations.get()
        owner.thresholds = {}
        owner.penalties = {}
        owner.save()

    def test_v5_returns_formal_snapshot_and_v4_refuses_downcast(self):
        revision = self._approve_first_revision(self.revision)
        self.assertEqual(revision.snapshot_schema_version, "canonical-json-v4")
        frozen = deepcopy(revision.configuration_snapshot)
        with self.assertNumQueries(0):
            validate_frozen_formal_metadata(frozen)
        tampered = deepcopy(frozen)
        item = next(iter(tampered["formal_metadata"].values()))
        item["definitions"][0]["formula_description"] = "Changed"
        with self.assertRaises(IngestResolutionError):
            validate_frozen_formal_metadata(tampered)
        principal = IntegrationPrincipal.objects.create(
            company=self.company,
            name="033-client",
            environment="dev",
            keycloak_client_id="033-client",
            keycloak_client_uuid="033-uuid",
        )
        grant = IntegrationGrant.objects.create(
            principal=principal,
            contract=self.contract,
            action=IntegrationGrant.Action.INGEST_WRITE,
        )
        context = M2MAuthContext(
            principal=principal, client_id="033-client", claims={"azp": "033-client"}
        )
        with patch(
            "rpsd_config.server.m2m_auth.authenticate_m2m_token", return_value=context
        ):
            for version, expected in ((3, 409), (4, 409), (5, 200)):
                path = (
                    f"/exchange_agreement/api/m2m/v{version}/contracts/"
                    f"{self.contract.contract_code}/validation-plan?data_category=netex"
                )
                response = self.client.get(path, HTTP_AUTHORIZATION="Bearer test")
                self.assertEqual(response.status_code, expected, response.content[:500])
                if version == 5:
                    self.assertEqual(
                        response.json()["schema_version"], "validation-plan-v3"
                    )
                    self.assertEqual(
                        response.json()["formal_metadata"], frozen["formal_metadata"]
                    )
            grant.delete()
            self.assertEqual(
                self.client.get(path, HTTP_AUTHORIZATION="Bearer test").status_code, 403
            )
        self.client.force_login(self.user)
        url = reverse(
            "exchange_agreement:indicator-evaluations",
            args=[
                self.contract.contract_code,
                revision.pk,
                revision.indicator_configurations.get().pk,
            ],
        )
        self.assertContains(self.client.get(url), "DISTANCE")
        clone = create_revision_draft(
            self.contract,
            self.profile,
            revision.valid_from + timedelta(days=1),
            self.user,
            replaces_revision=revision,
        )
        self.assertEqual(clone.status, "draft")
        self.assertFalse(clone.configuration_snapshot)
        self.assertEqual(
            clone.indicator_configurations.get().processing_profile_indicator_version_id,
            revision.indicator_configurations.get().processing_profile_indicator_version_id,
        )
