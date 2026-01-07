import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests  # noqa: F401  # se vuoi l’alternativa HTTP
from dapr.clients import DaprClient
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from rpsd_config.admin_agreements.proxies import ContractAdminProxy

from .models import Contract

logger = logging.getLogger(__name__)


_executor = ThreadPoolExecutor(max_workers=2)

def _publish_contract_event(payload):
    try:
        serialized_payload = json.dumps(payload).encode("utf-8")

        with DaprClient() as client:
            client.publish_event(
                pubsub_name="pubsub",
                topic_name="contracts.created",
                data=serialized_payload,
                data_content_type="application/json",
            )
        # Richiesta HTTP alternativa (lasciata commentata come riferimento)
        # requests.post(
        #     "http://127.0.0.1:3500/v1.0/publish/pubsub/contracts.created",
        #     data=serialized_payload,
        #     headers={"Content-Type": "application/json"},
        #     timeout=5,
        # )
    except Exception as exc:
        logger.exception("Errore durante l'invio del contratto a Dapr: %s", exc)

@receiver(post_save, sender=Contract)
@receiver(post_save, sender=ContractAdminProxy)
def notify_new_contract(sender, instance, created, **kwargs):
    if not created:
        return

    payload = {
        "contract_code": instance.contract_code,
        "client_agency": instance.client_agency_id,
        "contractor_company": instance.contractor_company_id,
        "start_date": instance.start_date.isoformat(),
        "end_date": instance.end_date.isoformat() if instance.end_date else None,
    }
    # 2do - modificare con la libreria dapr per postare il segnale
    print(f"[Contract created] {payload}")
    transaction.on_commit(lambda: _executor.submit(_publish_contract_event, payload))
