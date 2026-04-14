# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
from rpsd_config.exchange_agreement.models import Lot


class LotAdminProxy(Lot):
    class Meta:
        proxy = True
        app_label = "admin_service_net"
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
