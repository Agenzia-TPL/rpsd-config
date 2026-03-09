import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests  # noqa: F401  # kept for optional HTTP publish fallback
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from rpsd_config.admin_agreements.proxies import ContractAdminProxy

from .models import Contract

logger = logging.getLogger(__name__)


_executor = ThreadPoolExecutor(max_workers=2)


def _publish_contract_event(payload):
    try:
        _serialized_payload = json.dumps(payload).encode("utf-8")

        # Alternative HTTP request (kept commented as reference)
        # requests.post(
        #     "http://127.0.0.1:3500/v1.0/publish/pubsub/contracts.created",
        #     data=serialized_payload,
        #     headers={"Content-Type": "application/json"},
        #     timeout=5,
        # )
    except Exception as exc:
        logger.exception("Error while sending contract event to PubSub: %s", exc)


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
    # TODO: replace the debug print with PubSub-based signaling only.
    print(f"[Contract created] {payload}")
    transaction.on_commit(lambda: _executor.submit(_publish_contract_event, payload))
