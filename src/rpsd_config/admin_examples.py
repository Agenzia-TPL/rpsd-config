# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Copyable examples of the existing local configuration contracts."""

import json

from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

CORSE_BUNDLE_SHA256 = "025b31af23d04f672488eef7c1d70867af4ca4d8d40e57c6ebd4b14fa45e9f2f"
CORSE_ENTRYPOINT = "NeTEx_publication_Lev5.xsd"

CORSE_BUNDLE_MANIFEST = {
    "schema_version": 1,
    "entrypoint": "NeTEx_publication_Lev5.xsd",
    "bundle_sha256": "025b31af23d04f672488eef7c1d70867af4ca4d8d40e57c6ebd4b14fa45e9f2f",
    "files": [
        {
            "path": "NeTEx_publication_Lev5.xsd",
            "sha256": (
                "6eebe21336890871c3396940a7ad9b54908705e015b0a16982cdb3edde514a30"
            ),
            "size_bytes": 425367,
        },
        {
            "path": "_content_NeTEx_EPIP.xsd",
            "sha256": (
                "9aaf85bc6030e49c98bcc45c9d05a22be661298b83b151d827dbfb203ebed5a7"
            ),
            "size_bytes": 465170,
        },
        {
            "path": "_content_NeTEx_Lev2_ext.xsd",
            "sha256": (
                "091715a0d2df5764020478d370d6dd5cdae0562588405b3fd17dd936578e58e7"
            ),
            "size_bytes": 226539,
        },
        {
            "path": "_content_NeTEx_Lev3_ext.xsd",
            "sha256": (
                "aab6bf0a4550e55924bbc071453a2b9bf900ea036e341d422bc01f171a5dcfde"
            ),
            "size_bytes": 73387,
        },
        {
            "path": "_content_NeTEx_Lev4_ext.xsd",
            "sha256": (
                "65de31a2e4bc60f48672c5ff75cfe27cb9a04fa85574062e7ba25777fbfc3b7d"
            ),
            "size_bytes": 33971,
        },
        {
            "path": "_content_NeTEx_Lev5_ext.xsd",
            "sha256": (
                "56158b3ac6d606bb581c895d09623919ea5efb342c58b2f6a6bf9c6581d42b94"
            ),
            "size_bytes": 52950,
        },
        {
            "path": "gml_combo_v3_2_1_simplified.xsd",
            "sha256": (
                "0152aa5edf9008211e1e403615dfc4bf34d2504f6dae5d5fe12daa8335f4c13e"
            ),
            "size_bytes": 15297,
        },
        {
            "path": "manifest.json",
            "sha256": (
                "d6dad52a91256198ec72eab5c39d5591bad2ed8796b1740bb1ff82762b7b1e88"
            ),
            "size_bytes": 44,
        },
    ],
}

RULE_EXAMPLES = (
    {
        "validation_type": "xpath",
        "language_version": "1.0",
        "definition": "//n:ServiceJourney[not(n:DayTypeRef)]",
        "options": {
            "namespaces": {"n": "http://www.netex.org.uk/netex"},
            "empty_context": "pass",
        },
        "result_contract": "violating_entities",
    },
    {
        "validation_type": "xsd_bundle",
        "language_version": "1.0",
        "definition": json.dumps(
            {
                "asset_code": "netex",
                "asset_version": "1",
                "entrypoint": CORSE_ENTRYPOINT,
                "bundle_sha256": CORSE_BUNDLE_SHA256,
            }
        ),
        "options": {},
        "result_contract": "structured_report",
    },
    {
        "validation_type": "csv_expression",
        "language_version": "1",
        "definition": json.dumps(
            {"predicate": "required_columns", "columns": ["journey_id"]}
        ),
        "options": {"delimiter": ";", "encoding": "utf-8", "header": True},
        "result_contract": "violating_entities",
    },
    {
        "validation_type": "spreadsheet_expression",
        "language_version": "1",
        "definition": json.dumps(
            {"predicate": "required_columns", "columns": ["journey_id"]}
        ),
        "options": {"sheet": "Corse", "header_row": 1},
        "result_contract": "violating_entities",
    },
    {
        "validation_type": "text_expression",
        "language_version": "1",
        "definition": json.dumps(
            {"predicate": "matches", "pattern": "^ID=.+$", "scope": "line"}
        ),
        "options": {"encoding": "utf-8"},
        "result_contract": "violating_entities",
    },
)

PARAMETER_SCHEMA = {
    "schema_version": 1,
    "properties": {
        "minimum_journeys": {
            "type": "integer",
            "minimum": 1,
            "description": "Numero minimo di corse",
        }
    },
    "required": ["minimum_journeys"],
    "allow_extra": False,
}
JSON_EXAMPLES = {
    "metadata": {"format": "csv"},
    "input_schema": {"datasets": ["netex"]},
    "output_schema": {
        "type": "object",
        "properties": {"journey_count": {"type": "integer"}},
    },
    "parameter_schema": PARAMETER_SCHEMA,
    "parameters": {"minimum_journeys": 1},
    "thresholds": {},
    "aggregation": {},
    "penalties": {},
}


def example_block(title: str, value: object, note: str = "") -> str:
    """Render trusted headings and escaped example data, without JavaScript."""
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, indent=2, ensure_ascii=False)
    )
    return format_html(
        '<details class="config-example"><summary>{}</summary><p>{}</p>'
        '<pre tabindex="0"><code>{}</code></pre></details>',
        title,
        note,
        text,
    )


def field_examples(model: type, name: str) -> str:
    """Return only examples relevant to the visible field."""
    model_name = model._meta.concrete_model.__name__
    if model_name == "ValidationRuleVersion" and name in {"definition", "options"}:
        blocks = []
        for example in RULE_EXAMPLES:
            note = _(
                "Esempio di configurazione; non viene salvato o eseguito. Copiare la "
                "sola definizione nel campo Definizione e le opzioni nel campo "
                "Opzioni."
            )
            if example["validation_type"] == "xsd_bundle":
                note = _(
                    "Fixture CORSE_PDE: digest reale di "
                    "tests_integration/exchange_agreement/fixtures/corse_pde/upstream"
                    "/netex.zip. Richiede quel bundle attivo, associato alla "
                    "specifica con ruolo validation_schema, codice netex e versione "
                    "1. Adattare codice/versione all’asset effettivo. Il deployment "
                    "esterno va predisposto separatamente."
                )
            blocks.append(
                example_block(
                    f"{_('Esempio')} {example['validation_type']}",
                    example if name == "definition" else example["options"],
                    note,
                )
            )
        return format_html_join("", "{}", ((block,) for block in blocks))
    if model_name == "ConfigurationAsset" and name == "bundle_manifest":
        return example_block(
            _("Manifest della fixture CORSE_PDE"),
            CORSE_BUNDLE_MANIFEST,
            _(
                "Manifest reale del bundle della fixture di test. In produzione "
                "viene generato dai byte caricati; non copiarlo per un archivio "
                "diverso."
            ),
        )
    if name in JSON_EXAMPLES:
        note = _(
            "Esempio consultabile: adattare al proprio processo, senza inserimento "
            "automatico."
        )
        if name == "parameters":
            note = _(
                "Valori validi per lo schema minimum_journeys mostrato nella "
                "versione dell’indicatore. Usare lo schema della versione effettiva, "
                "anche per ogni prerequisito."
            )
        elif name in {"thresholds", "aggregation", "penalties"}:
            note = _(
                "Oggetto vuoto valido: nessuna configurazione aggiuntiva. Le chiavi "
                "non vuote richiedono un accordo con il processo esterno; Config non "
                "definisce una DSL universale."
            )
        return example_block(_("Esempio JSON"), JSON_EXAMPLES[name], note)
    return ""
