# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Two concurrent imports share the graph lock and cannot duplicate versions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TransactionTestCase

from rpsd_config.exchange_agreement.models import IndicatorVersion
from rpsd_config.exchange_agreement.services.catalog_import import apply_catalog
from tests_integration.exchange_agreement.test_formal_indicators import generic_package


class CatalogImportConcurrencyTests(TransactionTestCase):
    def test_concurrent_import_creates_once_then_reuses(self):
        actor = get_user_model().objects.create_user(
            username="concurrent-catalog-admin", is_superuser=True, is_staff=True
        )
        package = generic_package()
        barrier = Barrier(2)

        def apply():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                return apply_catalog(package, actor=user)["counts"]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(apply) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum("create" in result for result in results), 1)
        self.assertEqual(IndicatorVersion.objects.count(), 2)
