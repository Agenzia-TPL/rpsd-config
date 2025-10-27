# models.py (EN version)
from django.contrib.gis.db import models as gis_models
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.functions import Now  # for db_default in Django 5.x
from django.utils.translation import gettext_lazy as _

# ==========================
# Common base
# ==========================

class TimeStampedModel(models.Model):
    """
    Abstract base model adding automatic timestamp fields.
    Uses Now() + db_default for better write performance on Django 5.x.
    """
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_default=Now())
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


# ==========================
# Stakeholders
# ==========================

class Agency(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Agency"
        verbose_name_plural = "Agencies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Company(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Authority(TimeStampedModel):
    class AuthorityType(models.TextChoices):
        REGION = "region", _("Region")
        MUNICIPALITY = "municipality", _("Municipality")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    geographic_extent = gis_models.MultiPolygonField(
        null=True, blank=True, srid=4326,
        help_text="Geographic extent in WGS84"
    )
    authority_type = models.CharField(max_length=20, choices=AuthorityType.choices)

    class Meta:
        verbose_name = "Authority"
        verbose_name_plural = "Authorities"
        constraints = [
            models.UniqueConstraint(fields=["name", "authority_type"], name="uniq_authority_name_type"),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        # Avoid get_*_display for better type checking
        try:
            label = self.AuthorityType(self.authority_type).label
        except ValueError:
            label = self.authority_type or ""
        return f"{self.name} ({label})"


# ==========================
# Service net: Lots, Lines, Stops, Trips
# ==========================

class Lot(TimeStampedModel):
    id = models.BigAutoField(primary_key=True)
    description = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ["id"]

    def __str__(self) -> str:
        return f"Lot {self.id} - {self.description}"


class Line(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True, help_text="Unique line identifier")
    name = models.CharField(max_length=255)
    authority = models.ForeignKey(
        Authority, on_delete=models.PROTECT, related_name="lines",
        help_text="Authority associated to the line (1:N)"
    )
    lot = models.ForeignKey(
        Lot, on_delete=models.PROTECT, related_name="lines",
        help_text="The line belongs to a lot (1:N)"
    )

    class Meta:
        verbose_name = "Line"
        verbose_name_plural = "Lines"
        indexes = [models.Index(fields=["lot"]), models.Index(fields=["code"])]
        constraints = [
        #    models.UniqueConstraint(fields=["authority"], name="unique_line_authority")
            models.UniqueConstraint(fields=['code', 'lot'], name='unique_line_lot_identifier')
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class Stop(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True, help_text="Unique stop identifier")
    name = models.CharField(max_length=255, blank=True)
    geom = gis_models.PointField(srid=4326, help_text="WGS84 coordinates (lon/lat)")

    class Meta:
        verbose_name = "Stop"
        verbose_name_plural = "Stops"
        indexes = [models.Index(fields=["code"])]

    def __str__(self) -> str:
        return self.code


class Trip(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True, help_text="Unique trip identifier")
    name = models.CharField(max_length=255, blank=True)
    line = models.ForeignKey(Line, on_delete=models.PROTECT, related_name="trips")
    geom = gis_models.LineStringField(
        srid=4326, null=True, blank=True,
        help_text="Trip path (polyline in WGS84)"
    )
    # Ordered relation to stops (through)
    stops = models.ManyToManyField(Stop, through="TripStop", related_name="trips")

    class Meta:
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
        indexes = [models.Index(fields=["line"]), models.Index(fields=["code"])]

    def __str__(self) -> str:
        return self.code


class TripStop(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    stop = models.ForeignKey(Stop, on_delete=models.PROTECT)
    sequence = models.PositiveIntegerField(help_text="Stop order within the trip")

    class Meta:
        verbose_name = "Trip stop"
        verbose_name_plural = "Trip stops"
        constraints = [
            models.UniqueConstraint(fields=["trip", "stop"], name="unique_trip_stop"),
            models.UniqueConstraint(fields=["trip", "sequence"], name="unique_trip_sequence"),
        ]
        ordering = ["trip__id", "sequence"]

    def __str__(self) -> str:
        return f"{self.trip.code}:{self.sequence} -> {self.stop.code}"


# ==========================
# Dataset & Structures
# ==========================

def structure_validation_path(instance, filename):
    return f"catalog/structures/{instance.id}/validation/{filename}"

class Dataset(TimeStampedModel):
    slug = models.SlugField(unique=True, help_text="e.g. netex, siri_pt, siri_vm, ...")
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Structure(TimeStampedModel):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="structures")
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    validation_schema = models.FileField(
        upload_to=structure_validation_path, blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xsd", "xml", "json", "yaml", "yml"])],
        help_text="Validation schema for the section (XSD/XML/JSON/YAML)"
    )

    class Meta:
        verbose_name = "Structure"
        verbose_name_plural = "Structures"
        constraints = [
            models.UniqueConstraint(fields=["dataset", "name"], name="unique_structure_dataset_name")
        ]
        ordering = ["dataset__slug", "name"]

    def __str__(self) -> str:
        return f"{self.dataset.slug}:{self.name}"


# ==========================
# Indicators (definitions) & Contract association
# ==========================

class IndicatorType(models.TextChoices):
    QUALITY = "QUALITY", _("Quality")
    QUANTITY = "QUANTITY", _("Quantity")
    PUNCTUALITY = "PUNCTUALITY", _("Punctuality")
    OTHER = "OTHER", _("Other")

class IndicatorDef(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True)
    type = models.CharField(max_length=16, choices=IndicatorType.choices)
    name = models.CharField(max_length=255, help_text="Indicator name")
    description = models.TextField(blank=True)
    formula = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    structure = models.ForeignKey(
        Structure, on_delete=models.PROTECT, related_name="indicators",
        help_text="Which dataset structures/segments are required"
    )

    class Meta:
        verbose_name = "Indicator definition"
        verbose_name_plural = "Indicator definitions"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"[{self.code}] {self.name}"


# ==========================
# Contracts
# ==========================

def contract_program_path(instance, filename):
    # Use contract_code for folder
    return f"contracts/{instance.contract_code}/program/{filename}"

def contract_doc_path(instance, filename):
    # Use related contract code
    return f"contracts/{instance.contract.contract_code}/documents/{filename}"


class Contract(TimeStampedModel):
    class ContractType(models.TextChoices):
        START = "start", _("Start")
        RENEWAL = "renewal", _("Renewal")

    # renamed: contract_code clearer than id_contratto
    contract_code = models.CharField(max_length=64, unique=True)
    client_agency = models.ForeignKey(
        Agency, on_delete=models.PROTECT, related_name="contracts_as_client",
        help_text="Client agency"
    )
    contractor_company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name="contracts_as_contractor",
        help_text="Contractor company"
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    tender_id = models.CharField(
        max_length=64, blank=True,
        help_text="Associated tender/procurement identifier (optional; no dedicated table)"
    )

    contract_type = models.CharField(max_length=7, choices=ContractType.choices)
    version = models.PositiveIntegerField(
        help_text="Progressive serial for the pair (client_agency, contractor_company)"
    )

    # Program (NetEx)
    contract_program_file = models.FileField(
        upload_to=contract_program_path, blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xml", "zip"])],
        help_text="NetEx file (XML/ZIP) with the contractual program"
    )

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="contracts")

    class Meta:
        verbose_name = "Contract"
        verbose_name_plural = "Contracts"
        constraints = [
            models.UniqueConstraint(
                fields=["client_agency", "contractor_company", "version"],
                name="unique_contract_version_per_pair",
            ),
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")) | models.Q(end_date__isnull=True),
                name="contract_date_range_ok",
            ),
        ]
        indexes = [
            models.Index(fields=["client_agency", "contractor_company"]),
            models.Index(fields=["lot", "start_date"]),
        ]
        ordering = ["-start_date", "contract_code"]

    @property
    def contract_type_label(self) -> str:
        """Human-readable label for contract_type, robust for type checkers."""
        try:
            return self.ContractType(self.contract_type).label
        except ValueError:
            return self.contract_type or ""

    @property
    def is_active_today(self) -> bool:
        from datetime import date
        t = date.today()
        return self.start_date <= t and (self.end_date is None or self.end_date >= t)

    def __str__(self) -> str:
        return f"{self.contract_code} ({self.contract_type_label})"


class ContractDocument(TimeStampedModel):
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="documents")
    name = models.CharField(max_length=255, blank=True)
    file = models.FileField(
        upload_to=contract_doc_path,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx", "odt", "zip"])]
    )

    class Meta:
        verbose_name = "Contract document"
        verbose_name_plural = "Contract documents"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or self.file.name.split("/")[-1]


class ContractIndicator(models.Model):
    """
    Contract ↔ IndicatorDef association with optional JSON parameters (thresholds/weights/etc.).
    """
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="indicators")
    indicator = models.ForeignKey(IndicatorDef, on_delete=models.PROTECT, related_name="contracts")
    params = models.JSONField(blank=True, null=True, help_text="Thresholds/weights/domain-specific configuration")

    class Meta:
        verbose_name = "Contract indicator"
        verbose_name_plural = "Contract indicators"
        constraints = [
            models.UniqueConstraint(fields=["contract", "indicator"], name="unique_contract_indicator")
        ]

    def __str__(self) -> str:
        return f"{self.contract.contract_code}:{self.indicator.code}"
