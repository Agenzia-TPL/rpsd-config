import uuid
from datetime import date, timedelta

# models.py (EN version)
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import F, Func
from django.db.models.functions import Now  # for db_default in Django 5.x
from django.utils import timezone
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


# -----------------------------------------------
# Consider adding a model here that defines access keys and specific URLs to
# allow third-party systems to upload datasets into the system.
# -----------------------------------------------



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



# ====================================================================================
# Da valutare se fare un modello per stoccare le chiavi api per la singola azienda
# ====================================================================================





# ==========================
# Service net: Lots, Lines, Stops, Trips
# ==========================

class Lot(TimeStampedModel):
    id = models.BigAutoField(primary_key=True)
    short_description = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional short label for compact displays",
    )
    description = models.CharField(max_length=255)
    # valutare se aggiunger il poligono del lotto

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ["id"]

    def __str__(self) -> str:
        short = f" ({self.short_description})" if self.short_description else ""
        return f"Lot {self.id}{short} - {self.description}"


# -----------------------------------------------
# Consider that file validation cannot rely on the presence of all lines in
# every transmission, because a partial upload may have been sent.
# -----------------------------------------------

class Route(TimeStampedModel):
    # This allows multiple lots with different authorities, but each line can have only one authority.
    code = models.CharField(max_length=64, help_text="Route identifier (unique within the lot)")
    name = models.CharField(max_length=255)
    authority = models.ForeignKey(
        Authority, on_delete=models.PROTECT, related_name="routes",
        help_text="Authority associated to the route (1:N)"
    )
    lot = models.ForeignKey(
        Lot, on_delete=models.PROTECT, related_name="routes",
        help_text="The route belongs to a lot (1:N)"
    )

    class Meta:
        verbose_name = "Route"
        verbose_name_plural = "Routes"
        indexes = [models.Index(fields=["lot"]), models.Index(fields=["code"])]
        constraints = [
        #    models.UniqueConstraint(fields=["authority"], name="unique_line_authority")
            models.UniqueConstraint(fields=['code', 'lot'], name='unique_route_lot_identifier')
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
    route = models.ForeignKey(Route, on_delete=models.PROTECT, related_name="trips")
    geom = gis_models.LineStringField(
        srid=4326, null=True, blank=True,
        help_text="Trip path (polyline in WGS84)"
    )
    # Ordered relation to stops (through)
    stops = models.ManyToManyField(Stop, through="TripStop", related_name="trips")

    class Meta:
        verbose_name = "Trip"
        verbose_name_plural = "Trips"
        indexes = [models.Index(fields=["route"]), models.Index(fields=["code"])]

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
    """
    Legacy helper kept for migration compatibility with old FileField storage.
    """
    return f"catalog/structures/{instance.id}/validation/{filename}"


class Dataset(TimeStampedModel):
    slug = models.SlugField(unique=True, help_text="e.g. netex, siri_pt, siri_vm, ...")
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    # valutare se aggiungere lo specifico validation schema .xsd del dataset
    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"
        ordering = ["slug"]

    def __str__(self) -> str:
        return f"{self.name} ({self.slug})"


class Structure(TimeStampedModel):
    """
    Logical dataset section used by indicators.

    Instead of storing validation files, this model keeps a JSONB definition
    describing where data is located (e.g. XPath selector) and which fields
    are mandatory for merit/quality calculations.
    """
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="structures")
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Structured mandatory-field definition used by external processors. "
            "Example: {'xpath': '//EstimatedVehicleJourney', 'fields': ['LineRef', 'DirectionRef']}.\n\n"
            "Technical note: '//' in XPath means descendant-or-self and matches nodes at any depth."
        ),
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

    def get_mandatory_fields(self):
        """Return required field names from JSON definition."""
        if not isinstance(self.definition, dict):
            return []
        fields = self.definition.get("fields", [])
        return fields if isinstance(fields, list) else []

    def get_xpath_selector(self):
        """Return XPath selector from JSON definition."""
        if not isinstance(self.definition, dict):
            return ""
        xpath = self.definition.get("xpath", "")
        return xpath if isinstance(xpath, str) else ""


# ==========================
# Indicators (definitions) & Contract association
# ==========================

class IndicatorType(models.TextChoices):
    QUALITY = "QUALITY", _("Quality")
    QUANTITY = "QUANTITY", _("Quantity")
    PUNCTUALITY = "PUNCTUALITY", _("Punctuality")
    OTHER = "OTHER", _("Other")

class IndicatorDef(TimeStampedModel):
    """
    Contract indicator definition.

    This model stores merit/monitoring guidance metadata used by external
    processing pipelines. SQL fields are references/documentation only:
    - `sql_procedure_name` is the stable reference to the external procedure.
    - `sql_snippet` is optional documentation and is not executed by Django.
    """
    code = models.CharField(max_length=64, unique=True)
    type = models.CharField(max_length=16, choices=IndicatorType.choices)
    name = models.CharField(max_length=255, help_text="Indicator name")
    description = models.TextField(blank=True)
    formula = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    sql_procedure_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Stable reference to the external SQL procedure/function.",
    )
    sql_snippet = models.TextField(
        blank=True,
        help_text="Optional SQL documentation snippet (not executed by this service).",
    )
    structures = models.ManyToManyField(
        Structure,
        related_name="indicators",
        help_text="Which dataset structures/segments are required",
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


def _add_years_safe(value: date, years: int) -> date:
    """Add full years to a date, clamping leap-day to Feb 28 when needed."""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _default_invitation_expiration():
    return timezone.now() + timedelta(days=7)


class Contract(TimeStampedModel):
    """
    Contract lifecycle model.

    - A contract belongs to exactly one lot, one client agency and one contractor company.
    - `version` and `contract_type` are auto-managed on create:
      first contract for the tuple (lot, agency, company) => version 0 + start,
      next contracts => incremental version + renewal.
    - If `end_date` is omitted, it defaults to `start_date + 6 years`.
    - Overlaps on the same lot are forbidden.
    - Closed contracts are immutable (except automatic audit timestamps).
    """
    class ContractType(models.TextChoices):
        START = "start", _("Start")
        RENEWAL = "renewal", _("Renewal")

    class ContractStatus(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        CLOSED = "closed", _("Closed")

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
        help_text="Auto progressive serial for (lot, client_agency, contractor_company)"
    )

    # Program (es. NetEx)
    contract_program_file = models.FileField(
        upload_to=contract_program_path, blank=True, null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xml", "zip"])],
        help_text="NetEx file (XML/ZIP) with the contractual program"
    )

    lot = models.ForeignKey(Lot, on_delete=models.PROTECT, related_name="contracts")
    status = models.CharField(
        max_length=16,
        choices=ContractStatus.choices,
        default=ContractStatus.DRAFT,
    )
    closed_at = models.DateTimeField(blank=True, null=True)
    closed_reason = models.CharField(max_length=255, blank=True)
    replaced_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="replaces",
    )

    class Meta:
        verbose_name = "Contract"
        verbose_name_plural = "Contracts"
        constraints = [
            models.UniqueConstraint(
                fields=["lot", "client_agency", "contractor_company", "version"],
                name="unique_contract_version_per_lot_pair",
            ),
            models.CheckConstraint(
                check=models.Q(end_date__gte=models.F("start_date")) | models.Q(end_date__isnull=True),
                name="contract_date_range_ok",
            ),
            ExclusionConstraint(
                name="exclude_contract_overlap_per_lot",
                expressions=[
                    ("lot", RangeOperators.EQUAL),
                    (
                        Func(
                            F("start_date"),
                            F("end_date"),
                            function="daterange",
                            template="%(function)s(%(expressions)s, '[]')",
                            output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
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
        t = date.today()
        return (
            self.status == self.ContractStatus.ACTIVE
            and self.start_date <= t
            and (self.end_date is None or self.end_date >= t)
        )

    def clean(self):
        errors = {}
        replaced_by_id = getattr(self, "replaced_by_id", None)
        lot_id = getattr(self, "lot_id", None)
        effective_end_date = self.end_date
        if effective_end_date is None and self.start_date is not None:
            effective_end_date = _add_years_safe(self.start_date, 6)

        if effective_end_date is not None and effective_end_date < self.start_date:
            errors["end_date"] = _("End date must be greater than or equal to start date.")

        if self.status == self.ContractStatus.CLOSED:
            if self.closed_at is None:
                errors["closed_at"] = _("Closed contracts must have a closing timestamp.")
            if not self.closed_reason:
                errors["closed_reason"] = _("Closed contracts must include a closing reason.")
        else:
            if self.closed_at is not None:
                errors["closed_at"] = _("closed_at must be empty unless contract is closed.")
            if self.closed_reason:
                errors["closed_reason"] = _("closed_reason must be empty unless contract is closed.")
            if replaced_by_id is not None:
                errors["replaced_by"] = _("Only closed contracts can reference a replacement.")

        if replaced_by_id is not None and self.pk is not None and replaced_by_id == self.pk:
            errors["replaced_by"] = _("A contract cannot replace itself.")

        if lot_id and self.start_date and effective_end_date:
            overlaps = type(self).objects.filter(
                lot_id=lot_id,
                start_date__lte=effective_end_date,
            )
            overlaps = overlaps.filter(
                models.Q(end_date__isnull=True) | models.Q(end_date__gte=self.start_date)
            )
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                errors["lot"] = _(
                    "Another contract already exists for this lot in the selected period. "
                    "Close/update the existing contract first."
                )

        if errors:
            raise ValidationError(errors)

    def _enforce_closed_immutability(self):
        if not self.pk:
            return

        original = type(self).objects.get(pk=self.pk)
        if original.status != self.ContractStatus.CLOSED:
            return

        protected_fields = {
            "contract_code",
            "client_agency_id",
            "contractor_company_id",
            "start_date",
            "end_date",
            "tender_id",
            "contract_type",
            "version",
            "contract_program_file",
            "lot_id",
            "status",
            "closed_at",
            "closed_reason",
            "replaced_by_id",
        }

        changed_fields = []
        for field_name in protected_fields:
            current_value = getattr(self, field_name)
            original_value = getattr(original, field_name)
            if current_value != original_value:
                changed_fields.append(field_name)

        if changed_fields:
            raise ValidationError(
                _("Closed contracts are immutable (except automatic audit timestamps).")
            )

    def _set_auto_version_and_type_for_new_contract(self):
        if self.pk:
            return
        lot_id = getattr(self, "lot_id", None)
        client_agency_id = getattr(self, "client_agency_id", None)
        contractor_company_id = getattr(self, "contractor_company_id", None)
        if not (lot_id and client_agency_id and contractor_company_id):
            return

        existing_qs = type(self).objects.filter(
            lot_id=lot_id,
            client_agency_id=client_agency_id,
            contractor_company_id=contractor_company_id,
        )
        latest = existing_qs.order_by("-version").first()
        if latest is None:
            self.version = 0
            self.contract_type = self.ContractType.START
        else:
            self.version = latest.version + 1
            self.contract_type = self.ContractType.RENEWAL

    def _enforce_auto_fields_immutability(self):
        if not self.pk:
            return

        original = type(self).objects.get(pk=self.pk)
        if self.version != original.version:
            raise ValidationError({"version": _("Version is auto-managed and cannot be edited.")})
        if self.contract_type != original.contract_type:
            raise ValidationError(
                {"contract_type": _("Contract type is auto-managed and cannot be edited.")}
            )

    def save(self, *args, **kwargs):
        self._set_auto_version_and_type_for_new_contract()
        if self.end_date is None and self.start_date is not None:
            self.end_date = _add_years_safe(self.start_date, 6)

        self._enforce_auto_fields_immutability()
        self._enforce_closed_immutability()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.contract_code} ({self.contract_type_label})"



# 2do
# evaluate how to associate, to a contract, the users/emails that will be allowed to access the contract’s admin sections
# evaluate possible integrations with IAM to provision the new users


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


class ContractMembership(TimeStampedModel):
    """
    RBAC assignment scoped to a single contract.

    Superusers keep global access, while non-superusers are authorized via
    contract memberships.
    """

    class Role(models.TextChoices):
        CONTRACT_ADMIN = "contract_admin", _("Contract admin")
        CONTRACT_READER = "contract_reader", _("Contract reader")

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contract_memberships"
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_memberships_created",
    )

    class Meta:
        verbose_name = "Contract membership"
        verbose_name_plural = "Contract memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "user"], name="unique_contract_membership_user"
            )
        ]
        indexes = [
            models.Index(fields=["contract", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.contract.contract_code} - {self.user} ({self.role})"

    @property
    def can_manage_contract(self) -> bool:
        return self.role == self.Role.CONTRACT_ADMIN


class ContractInvitation(TimeStampedModel):
    """
    Invitation token to assign a role on a specific contract.

    The system only generates and stores tokens; invitation delivery is handled
    manually outside the application.

    Invitation modes:
    - Targeted invitation: `email` is set, and only a user with the same email
      can accept the token.
    - Open invitation: `email` is empty, and the first user who accepts the
      token consumes it.
    """

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        EXPIRED = "expired", _("Expired")
        REVOKED = "revoked", _("Revoked")

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField(
        blank=True,
        null=True,
        help_text=_(
            "Optional target email. If empty, the invitation is open and can be used "
            "by the first user who accepts the token."
        ),
    )
    role_to_assign = models.CharField(max_length=32, choices=ContractMembership.Role.choices)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_invitations_created",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_invitations_accepted",
    )
    expires_at = models.DateTimeField(default=_default_invitation_expiration)
    accepted_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        verbose_name = "Contract invitation"
        verbose_name_plural = "Contract invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "email", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=False),
                name="unique_pending_contract_invitation_per_email_role",
            ),
            models.UniqueConstraint(
                fields=["contract", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=True),
                name="unique_pending_open_contract_invitation_per_role",
            )
        ]
        indexes = [
            models.Index(fields=["contract", "status"]),
            models.Index(fields=["email"]),
            models.Index(fields=["token"]),
        ]

    def clean(self):
        errors = {}

        if self.status == self.Status.ACCEPTED:
            if self.accepted_at is None:
                errors["accepted_at"] = _("Accepted invitations must have accepted_at.")
            if self.accepted_by is None:
                errors["accepted_by"] = _("Accepted invitations must have accepted_by.")
            if self.email and self.accepted_by is not None:
                accepted_email = getattr(self.accepted_by, "email", "")
                if accepted_email.lower() != self.email.lower():
                    errors["accepted_by"] = _(
                        "Accepted user email does not match the invitation target email."
                    )
        else:
            if self.accepted_at is not None:
                errors["accepted_at"] = _(
                    "accepted_at must be empty unless invitation status is accepted."
                )
            if self.accepted_by is not None:
                errors["accepted_by"] = _(
                    "accepted_by must be empty unless invitation status is accepted."
                )

        if self.status == self.Status.PENDING and self.expires_at <= timezone.now():
            errors["expires_at"] = _("Pending invitations must expire in the future.")

        if errors:
            raise ValidationError(errors)

    def is_valid(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()

    def __str__(self) -> str:
        target = self.email or "open-invite"
        return f"{self.contract.contract_code} -> {target} ({self.role_to_assign})"
