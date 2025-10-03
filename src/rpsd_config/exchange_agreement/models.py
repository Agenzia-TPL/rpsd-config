from django.contrib.gis.db import models as gis_models
from django.db import models


class Ente(models.Model):
    class EnteType(models.TextChoices):
        REGIONE = "regione", "Regione"
        COMUNE = "comune", "Comune"
        AGENZIA = "agenzia", "Agenzia"
        AZIENDA = "azienda", "Azienda"
        ALTRO = "altro", "Altro"

    nome = models.CharField(max_length=255)
    descrizione = models.TextField(blank=True)
    estensione_geografica = gis_models.MultiPolygonField(
        null=True,
        blank=True,
        srid=4326,
        help_text="Estensione geografica dell'ente in formato WGS84",
    )
    tipo_ente = models.CharField(max_length=20, choices=EnteType.choices)

    class Meta:
        verbose_name = "Ente"
        verbose_name_plural = "Enti"

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.nome


class Lotto(models.Model):
    descrizione = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Lotto"
        verbose_name_plural = "Lotti"

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.descrizione


class Contract(models.Model):
    class ContractType(models.TextChoices):
        AVVIO = "avvio", "Avvio"
        RINNOVO = "rinnovo", "Rinnovo"

    id_contratto = models.CharField(max_length=64, unique=True)
    committente = models.ForeignKey(
        Ente,
        on_delete=models.PROTECT,
        related_name="contratti_committente",
        help_text="Ente committente (agenzia)",
    )
    appaltante = models.ForeignKey(
        Ente,
        on_delete=models.PROTECT,
        related_name="contratti_appaltante",
        help_text="Ente appaltante (azienda)",
    )
    data_inizio = models.DateField()
    data_fine = models.DateField(blank=True, null=True)
    gara_id = models.CharField(
        max_length=64,
        blank=True,
        help_text="Identificativo della gara associata",
    )
    tipo_contratto = models.CharField(max_length=7, choices=ContractType.choices)
    versione = models.PositiveIntegerField(
        help_text=(
            "Numero di versione progressivo per la coppia committente/appaltante"
        )
    )
    programma_da_contratto_stato = models.BooleanField(
        default=False,
        help_text="Indica se è presente un servizio di programma",
    )
    programma_da_contratto_file = models.FileField(
        upload_to="contratti/programmi/",
        blank=True,
        null=True,
        help_text="File XML del programma associato",
    )
    lotto = models.ForeignKey(
        Lotto,
        on_delete=models.PROTECT,
        related_name="contratti",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Contratto"
        verbose_name_plural = "Contratti"
        constraints = [
            models.UniqueConstraint(
                fields=["committente", "appaltante", "versione"],
                name="unique_contract_version_per_pair",
            )
        ]

    @property
    def tipo_contratto_display(self) -> str:
        """Return human readable label for the contract type."""
        try:
            return self.ContractType(self.tipo_contratto).label
        except ValueError:
            return self.tipo_contratto or ""

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return f"{self.id_contratto} ({self.tipo_contratto_display})"


class ContractDocument(models.Model):
    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="documenti",
    )
    name = models.CharField(max_length=255, blank=True)
    file = models.FileField(upload_to="contratti/documenti/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Documento del contratto"
        verbose_name_plural = "Documenti del contratto"

    def __str__(self) -> str:  # pragma: no cover - simple repr
        return self.name or self.file.name


class ContractIndicator(models.Model):
    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="indicatori",
    )
    codice = models.CharField(max_length=64)
    descrizione = models.CharField(max_length=255, blank=True)
    valore = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Indicatore del contratto"
        verbose_name_plural = "Indicatori del contratto"
        unique_together = ("contract", "codice")

    def __str__(self) -> str:  # pragma: no cover - simple repr
        contract_ref = getattr(self, "contract_id", None) or "n/a"
        return f"{self.codice} ({contract_ref})"
