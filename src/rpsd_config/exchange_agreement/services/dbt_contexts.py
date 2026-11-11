# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Editorial context for people writing dbt tests; never executable instructions."""

import json

from django.core.exceptions import ValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic import ValidationError as DocumentError

DBT_CONTEXT_HELP = (
    "Contesto documentale per la scrittura dei test di trasformazione. "
    "Config non genera né esegue il test. La versione 1 identifica il formato "
    "del documento, non la versione del software dbt."
)


class DbtContext(BaseModel):
    """Validate only the document envelope, preserving the source's metadata."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    schema_version: str
    requirement: dict
    rule: dict
    relations: list[dict] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_document(self):
        if self.schema_version != "dbt-context-v1":
            raise ValueError("Versione del formato documentale non supportata.")
        for section in (self.requirement, self.rule):
            for name in ("code", "description"):
                value = section.get(name)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"Dichiarare {name} nel requisito e nella regola.")
        if self.rule.get("requirement", self.rule["code"]) != self.requirement["code"]:
            raise ValueError("Il codice del requisito non coincide con la regola.")
        if self.rule.get("engine") != "dbt":
            raise ValueError("Il contesto deve descrivere una regola dbt.")
        codes = [r.get("code") for r in self.relations]
        if any(not isinstance(c, str) or not c for c in codes):
            raise ValueError("Ogni relazione documentale deve avere un codice.")
        if len(codes) != len(set(codes)):
            raise ValueError("Relazioni documentali duplicate.")
        for section in (self.requirement, self.rule):
            refs = section.get("relations", [])
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or ref not in codes for ref in refs
            ):
                raise ValueError("Includere le dichiarazioni delle relazioni citate.")
        return self


def load_dbt_context(content: str) -> DbtContext:
    """Reject malformed JSON without evaluating paths, conditions, or SQL."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Chiave JSON duplicata: {key}.")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError(f"Numero JSON non finito: {value}.")

    try:
        data = json.loads(content, object_pairs_hook=unique, parse_constant=nonfinite)
        return DbtContext.model_validate(data)
    except (ValueError, TypeError, DocumentError) as exc:
        raise ValidationError(
            f"Definizione del contesto dbt non valida: {exc}",
            code="invalid_dbt_context",
        ) from exc
