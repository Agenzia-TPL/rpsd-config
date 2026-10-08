# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Operations on contract dates and disposable configuration drafts."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError

from rpsd_config.exchange_agreement.models import (
    Contract,
    ContractConfigurationRevision,
)
from rpsd_config.exchange_agreement.services.contract_revision_permissions import (
    require_revision_approver,
    require_revision_preparer,
)


@transaction.atomic
def update_draft_contract_dates(contract, *, start_date, end_date, actor):
    locked = Contract.objects.select_for_update().get(pk=contract.pk)
    require_revision_approver(user=actor, contract=locked)
    if locked.status != Contract.ContractStatus.DRAFT:
        raise ValidationError("Le date sono modificabili solo per contratti in bozza.")
    revisions = locked.configuration_revisions.select_for_update()
    if revisions.exclude(status=ContractConfigurationRevision.Status.DRAFT).exists():
        raise ValidationError(
            "Le date sono fissate da revisioni già approvate o ritirate."
        )
    if locked.publications.exists():
        raise ValidationError("Un contratto già pubblicato non può cambiare date.")
    if not start_date or not end_date or end_date < start_date:
        raise ValidationError("Inserisci un periodo valido per il contratto.")
    for revision in revisions:
        if revision.valid_from and (
            revision.valid_from < start_date or revision.valid_from > end_date
        ):
            raise ValidationError(
                f"La decorrenza della bozza {revision.code} è fuori dal nuovo periodo. "
                "Elimina la bozza e ricreala con la decorrenza corretta."
            )
    locked.start_date = start_date
    locked.end_date = end_date
    locked.save(update_fields=["start_date", "end_date", "updated_at"])
    contract.refresh_from_db()
    return locked


@transaction.atomic
def delete_revision_draft(revision, *, actor):
    # Use the same lock order as approval to avoid deleting a newly approved row.
    contract = Contract.objects.select_for_update().get(pk=revision.contract_id)
    require_revision_preparer(user=actor, contract=contract)
    locked = ContractConfigurationRevision.objects.select_for_update().get(
        pk=revision.pk, contract=contract
    )
    if locked.status != ContractConfigurationRevision.Status.DRAFT:
        raise ValidationError("Si possono eliminare soltanto revisioni in bozza.")
    try:
        locked.delete()
    except ProtectedError as exc:
        raise ValidationError(
            "La bozza è referenziata da altri record e non può essere eliminata."
        ) from exc
