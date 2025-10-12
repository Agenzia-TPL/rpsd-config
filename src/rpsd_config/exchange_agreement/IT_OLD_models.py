# models.py
from django.contrib.gis.db import models as gis_models
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Now  # Per db_default in Django 5.x
from django.utils.translation import gettext_lazy as _

# ==========================
# Anagrafiche principali
# ==========================

class TimeStampedModel(models.Model):
    """
    Modello astratto per aggiungere campi di timestamp automatici.
    Usa Now() e db_default per l'ottimizzazione in Django 5.x.
    """
    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, db_default=Now()
    )
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    class Meta:
        abstract = True


class Agenzia(TimeStampedModel):
    nome = models.CharField(max_length=255, unique=True)
    descrizione = models.TextField(blank=True)

    class Meta:
        verbose_name = "Agenzia"
        verbose_name_plural = "Agenzie"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome


class Azienda(TimeStampedModel):
    nome = models.CharField(max_length=255, unique=True)
    descrizione = models.TextField(blank=True)

    class Meta:
        verbose_name = "Azienda"
        verbose_name_plural = "Aziende"
        ordering = ["nome"]

    def __str__(self) -> str:
        return self.nome


class Ente(TimeStampedModel):
    class EnteType(models.TextChoices):
        REGIONE = "regione", "Regione"
        COMUNE  = "comune", "Comune"
        ALTRO   = "altro", "Altro"

    nome = models.CharField(max_length=255)
    descrizione = models.TextField(blank=True)
    estensione_geografica = gis_models.MultiPolygonField(
        null=True, blank=True, srid=4326,
        help_text="Estensione geografica in WGS84"
    )
    tipo_ente = models.CharField(max_length=20, choices=EnteType.choices)

    class Meta:
        verbose_name = "Ente"
        verbose_name_plural = "Enti"
        constraints = [
            models.UniqueConstraint(fields=["nome", "tipo_ente"], name="uniq_ente_nome_tipo"),
        ]
        ordering = ["nome"]

    def __str__(self) -> str:
        # Evita get_tipo_ente_display() (non tipizzato per Pylance)
        try:
            label = self.EnteType(self.tipo_ente).label
        except ValueError:
            label = self.tipo_ente or ""
        return f"{self.nome} ({label})"


# ==========================
# Lotto, Linee, Fermate, Corse
# ==========================

class Lotto(TimeStampedModel):
    id = models.BigAutoField(primary_key=True)
    descrizione = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Lotto"
        verbose_name_plural = "Lotti"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Lotto {self.id} - {self.descrizione}"


class Linea(TimeStampedModel):
    codice = models.CharField(max_length=64, unique=True, help_text="ID univoco linea")
    descr = models.CharField(max_length=255)
    ente = models.OneToOneField(
        Ente, on_delete=models.PROTECT, related_name="linea",
        help_text="Ente associato alla linea (1:1)"
    )
    lotto = models.ForeignKey(
        Lotto, on_delete=models.PROTECT, related_name="linee",
        help_text="La linea appartiene a un lotto (1:N)"
    )

    class Meta:
        verbose_name = "Linea"
        verbose_name_plural = "Linee"
        indexes = [models.Index(fields=["lotto"]), models.Index(fields=["codice"])]
        # Vincolo per assicurare che 'ente' sia davvero unico tra tutte le linee
        constraints = [
            models.UniqueConstraint(fields=["ente"], name="unique_linea_ente")
        ]

    def __str__(self) -> str:
        return f"{self.codice} - {self.descr}"


class Fermata(TimeStampedModel):
    codice = models.CharField(max_length=64, unique=True, help_text="ID univoco fermata")
    descr = models.CharField(max_length=255, blank=True)
    geom = gis_models.PointField(srid=4326, help_text="Coordinate WGS84 (lon/lat)")

    class Meta:
        verbose_name = "Fermata"
        verbose_name_plural = "Fermate"
        indexes = [models.Index(fields=["codice"])]

    def __str__(self) -> str:
        return self.codice


class Corsa(TimeStampedModel):
    codice = models.CharField(max_length=64, unique=True, help_text="ID univoco corsa")
    descr = models.CharField(max_length=255, blank=True)
    linea = models.ForeignKey(Linea, on_delete=models.PROTECT, related_name="corse")
    geom = gis_models.LineStringField(
        srid=4326, null=True, blank=True,
        help_text="Percorso della corsa (polilinea WGS84)"
    )
    # Relazione con fermate in ordine: through con sequenza
    fermate = models.ManyToManyField(Fermata, through="CorsaFermata", related_name="corse")

    class Meta:
        verbose_name = "Corsa"
        verbose_name_plural = "Corse"
        indexes = [models.Index(fields=["linea"]), models.Index(fields=["codice"])]

    def __str__(self) -> str:
        return self.codice


class CorsaFermata(models.Model):
    corsa = models.ForeignKey(Corsa, on_delete=models.CASCADE)
    fermata = models.ForeignKey(Fermata, on_delete=models.PROTECT)
    sequenza = models.PositiveIntegerField(help_text="Ordine della fermata nella corsa")

    class Meta:
        verbose_name = "Fermata della Corsa"
        verbose_name_plural = "Fermate della Corsa"
        # Utilizza un singolo UniqueConstraint invece di unique_together
        constraints = [
            models.UniqueConstraint(
                fields=["corsa", "fermata"],
                name="unique_corsa_fermata"
            ),
            models.UniqueConstraint(
                fields=["corsa", "sequenza"],
                name="unique_corsa_sequenza"
            ),
        ]
        ordering = ["corsa__id", "sequenza"] # Meglio usare __id

    def __str__(self) -> str:
        # Usa il campo repr della foreign key per una descrizione più significativa
        return f"{self.corsa.codice}:{self.sequenza} -> {self.fermata.codice}"


# ==========================
# Dataset & Strutture
# ==========================

def struttura_validazione_path(instance, filename):
    return f"catalogo/strutture/{instance.id}/validazione/{filename}"

class Dataset(TimeStampedModel):
    slug = models.SlugField(unique=True, help_text="es. netex, siri_pt, siri_vm, ...")
    nome = models.CharField(max_length=128)
    descr = models.TextField(blank=True)

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Dataset"
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.nome} ({self.slug})"


class Struttura(TimeStampedModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="strutture")
    nome = models.CharField(max_length=128)
    descr = models.TextField(blank=True)
    validazione_struttura = models.FileField(
        upload_to=struttura_validazione_path, blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xsd", "xml", "json", "yaml", "yml"])],
        help_text="Schema di validazione della sezione (XSD/XML/JSON/YAML)"
    )

    class Meta:
        verbose_name = "Struttura"
        verbose_name_plural = "Strutture"
        # Utilizza UniqueConstraint invece di unique_together
        constraints = [
            models.UniqueConstraint(fields=["dataset", "nome"], name="unique_struttura_dataset_nome")
        ]
        ordering = ["dataset__slug", "nome"]

    def __str__(self) -> str:
        return f"{self.dataset.slug}:{self.nome}"


# ==========================
# Indicatori (definizioni) & Associazione a Contratto
# ==========================

class TipoIndicatore(models.TextChoices):
    QUALITA    = "QUALITA", _("Qualità")
    QUANTITA   = "QUANTITA", _("Quantità")
    PUNTUALITA = "PUNTUALITA", _("Puntualità")
    ALTRO      = "ALTRO", _("Altro")

class IndicatoreDef(TimeStampedModel):
    codice = models.CharField(max_length=64, unique=True)
    tipo = models.CharField(max_length=16, choices=TipoIndicatore.choices)
    indicatore = models.CharField(max_length=255, help_text="Nome dell'indicatore")
    descrizione = models.TextField(blank=True)
    formula_calcolo = models.TextField(blank=True)
    note = models.TextField(blank=True)
    struttura = models.ForeignKey(
        Struttura, on_delete=models.PROTECT, related_name="indicatori",
        help_text="Quali spezzoni/strutture del dataset servono"
    )

    class Meta:
        verbose_name = "Definizione Indicatore"
        verbose_name_plural = "Definizioni Indicatori"
        ordering = ["codice"]

    def __str__(self) -> str:
        return f"[{self.codice}] {self.indicatore}"


# ==========================
# Contratti
# ==========================

def contratto_programma_path(instance, filename):
    # Usa codice_contratto per la cartella
    return f"contratti/{instance.codice_contratto}/programma/{filename}"

def contratto_doc_path(instance, filename):
    # CORREZIONE: Usa il codice del contratto collegato
    return f"contratti/{instance.contract.codice_contratto}/documenti/{filename}"


class Contract(TimeStampedModel):
    class ContractType(models.TextChoices):
        AVVIO   = "avvio", "Avvio"
        RINNOVO = "rinnovo", "Rinnovo"

    # RINOMINATO: codice_contratto è più chiaro di id_contratto
    codice_contratto = models.CharField(max_length=64, unique=True)
    committente = models.ForeignKey(
        Agenzia, on_delete=models.PROTECT, related_name="contratti_committente",
        help_text="Agenzia committente"
    )
    appaltante = models.ForeignKey(
        Azienda, on_delete=models.PROTECT, related_name="contratti_appaltante",
        help_text="Azienda appaltante"
    )
    data_inizio = models.DateField()
    data_fine = models.DateField(blank=True, null=True)

    gara_id = models.CharField(
        max_length=64, blank=True,
        help_text="Identificativo della gara associata (opzionale, no tabella gara)"
    )

    tipo_contratto = models.CharField(max_length=7, choices=ContractType.choices)
    versione = models.PositiveIntegerField(
        help_text="Progressivo per la coppia (committente, appaltante)"
    )

    # Programma da contratto (NetEx)
    programma_da_contratto_file = models.FileField(
        upload_to=contratto_programma_path, blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xml", "zip"])],
        help_text="File NetEx (XML/ZIP) del programma"
    )

    lotto = models.ForeignKey(Lotto, on_delete=models.PROTECT, related_name="contratti")

    class Meta:
        verbose_name = "Contratto"
        verbose_name_plural = "Contratti"
        constraints = [
            models.UniqueConstraint(
                fields=["committente", "appaltante", "versione"],
                name="unique_contract_version_per_pair",
            ),
            models.CheckConstraint(
                check=models.Q(data_fine__gte=models.F("data_inizio")), # Semplificato il Check
                name="contract_date_range_ok"
            ),
        ]
        indexes = [
            models.Index(fields=["committente", "appaltante"]),
            models.Index(fields=["lotto", "data_inizio"]),
        ]
        ordering = ["-data_inizio", "codice_contratto"]

    @property
    def tipo_contratto_display(self) -> str:
        """Etichetta umana del tipo_contratto, robusta per il type checker."""
        try:
            return self.ContractType(self.tipo_contratto).label
        except ValueError:
            # In caso di valore non previsto (o None), restituisco l'originale o stringa vuota
            return self.tipo_contratto or ""


    @property
    def attivo_oggi(self) -> bool:
        from datetime import date
        t = date.today()
        return self.data_inizio <= t and (self.data_fine is None or self.data_fine >= t)

    def __str__(self) -> str:
        return f"{self.codice_contratto} ({self.tipo_contratto_display})"


class ContractDocument(TimeStampedModel):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="documenti")
    name = models.CharField(max_length=255, blank=True)
    file = models.FileField(
        upload_to=contratto_doc_path, # Usa la funzione corretta
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx", "odt", "zip"])]
    )

    class Meta:
        verbose_name = "Documento del contratto"
        verbose_name_plural = "Documenti del contratto"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or self.file.name.split('/')[-1] # Mostra solo il nome file

class ContractIndicatore(models.Model):
    """Associazione Contratto ↔ IndicatoreDef con eventuali parametri."""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="indicatori")
    indicatore = models.ForeignKey(IndicatoreDef, on_delete=models.PROTECT, related_name="contratti")
    parametri = models.JSONField(blank=True, null=True, help_text="Pesi/soglie/configurazioni specifiche")

    class Meta:
        verbose_name = "Indicatore del contratto"
        verbose_name_plural = "Indicatori del contratto"
        # Utilizza UniqueConstraint invece di unique_together
        constraints = [
            models.UniqueConstraint(fields=["contract", "indicatore"], name="unique_contract_indicatore")
        ]

    def __str__(self) -> str:
        # Usa il codice del contratto (rinominato)
        return f"{self.contract.codice_contratto}:{self.indicatore.codice}"
