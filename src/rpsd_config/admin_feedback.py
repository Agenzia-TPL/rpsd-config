# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Readable, escaped lifecycle diagnostics with links to the affected record."""

from django.core.exceptions import ValidationError
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from rpsd_config.admin_relations import admin_change_url
from rpsd_config.exchange_agreement.field_guidance import field_guide

ERROR_TEXT = {
    "The logical indicator is not active.": _("L’indicatore logico non è attivo."),
    "The dataset specification must be published first.": _(
        "Pubblicare prima la versione del dataset."
    ),
    "The dataset specification must be published.": _(
        "La versione del dataset deve essere pubblicata."
    ),
    "The orchestration flow version must be published.": _(
        "Pubblicare prima la versione dell’orchestratore."
    ),
    "Only published rules can be associated.": _(
        "È possibile associare soltanto regole pubblicate."
    ),
    "Use the audited lifecycle service.": _(
        "Usare le azioni di pubblicazione o ritiro previste dal catalogo."
    ),
    "Invalid rule lifecycle transition.": _(
        "Il passaggio di stato richiesto non è consentito."
    ),
    "A reason is required for deprecation or withdrawal.": _(
        "Indicare la motivazione per deprecare o ritirare la versione."
    ),
    "Use a flow/deployment Prefect reference.": _(
        "Usare un riferimento Prefect nel formato flow/deployment."
    ),
    "Rule interpreter does not support this dataset format.": _(
        "Il tipo di validazione non supporta il formato del dataset."
    ),
    (
        "Published versions with an execution engine require both "
        "execution_reference and artifact_identifier."
    ): _(
        "Completare riferimento e artefatto del motore dichiarato oppure "
        "lasciare vuoto l’intero gruppo esecutivo."
    ),
    "The processing profile must contain at least one input flow.": _(
        "Associare almeno un flusso di input al profilo tecnico."
    ),
    "The processing profile must contain at least one indicator version.": _(
        "Associare almeno una versione di indicatore al profilo tecnico."
    ),
}


def error_messages(error, model):
    """Preserve field names and messages without printing exception reprs."""
    if isinstance(error, ValidationError) and hasattr(error, "message_dict"):
        output = []
        for name, messages in error.message_dict.items():
            info = field_guide(model, name)
            label = info.label if info else name
            output.extend(
                f"{label}: {ERROR_TEXT.get(message, _(message))}"
                if name != "__all__"
                else ERROR_TEXT.get(message, _(message))
                for message in messages
            )
        return output
    messages = error.messages if isinstance(error, ValidationError) else [str(error)]
    return [ERROR_TEXT.get(message, _(message)) for message in messages]


def publication_feedback(admin_object, obj, error):
    """Display identity, actionable details and a link, without changing policy."""
    identity = (
        getattr(obj, "code", None) or getattr(obj, "contract_code", None) or str(obj)
    )
    text = " ".join(
        str(message) for message in error_messages(error, obj._meta.concrete_model)
    )
    details = ""
    if getattr(error, "code", None) == "unresolved_catalog_requirements":
        limits = getattr(obj, "formal_verification", {}).get("limitations", [])
        rows = [
            (
                item.get("rule") or item.get("parameter") or item.get("code", ""),
                item.get("reason", ""),
            )
            for item in limits
        ]
        details = format_html(
            "<ul>{}</ul>", format_html_join("", "<li><code>{}</code>: {}</li>", rows)
        )
    link = admin_change_url(admin_object.admin_site, obj)
    return format_html(
        '{}: {} <a href="{}">{}</a>{}',
        identity,
        text,
        link,
        _("Apri il record e i dettagli da correggere"),
        details,
    )
