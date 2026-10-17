# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Shared guided asset upload for the platform UI and Django admin."""

from django import forms
from django.conf import settings

from rpsd_config.exchange_agreement.models import ConfigurationAsset
from rpsd_config.exchange_agreement.services.configuration_assets import (
    inspect_configuration_asset_upload,
)


class ConfigurationAssetUploadForm(forms.Form):
    """Collect explicit identity and file; generated storage metadata is readonly."""

    asset_type = forms.ChoiceField(
        label="Tipo di asset",
        choices=ConfigurationAsset.AssetType.choices,
        help_text="Il tipo bundle XSD attiva i controlli XSD; un archivio generico no.",
    )
    what = forms.CharField(
        label="Codice asset",
        max_length=64,
        help_text="Codice stabile indipendente dal nome del file e dal dataset. "
        "Lettere minuscole, numeri, trattini e underscore.",
    )
    label = forms.CharField(label="Etichetta", max_length=128, required=False)
    uploaded_file = forms.FileField(
        label="File tecnico",
        help_text="Risorsa di configurazione, non un conferimento TPL "
        "o un allegato contrattuale (rpsd-storage).",
    )
    activate = forms.BooleanField(
        label="Attiva questa versione",
        required=False,
        help_text="Versione preferita per nuovi usi; le associazioni esistenti "
        "restano sulla versione selezionata. Notifica tramite eventi (rpsd-transport).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[
            "uploaded_file"
        ].help_text += f" Limite: {settings.CONFIG_ASSETS_MAX_UPLOAD_BYTES} byte."

    def clean(self) -> dict:
        """Validate file semantics before any DB or storage write."""
        data = super().clean()
        if all(data.get(key) for key in ("asset_type", "what", "uploaded_file")):
            inspect_configuration_asset_upload(
                data["uploaded_file"], asset_type=data["asset_type"], what=data["what"]
            )
        return data
