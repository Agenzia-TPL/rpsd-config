# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
import uuid
from datetime import date, timedelta
from pathlib import Path

# models.py (EN version)
from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, RegexValidator
from django.db import models
from django.db.models import F, Func
from django.db.models.functions import Now  # for db_default in Django 5.x
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

# ==========================
# Common base
# ==========================


class TimeStampedModel(models.Model):
    """
    Abstract base model adding automatic timestamp fields.
    Uses Now() + db_default for better write performance on Django 5.x.
    """

    created_at = models.DateTimeField(
        auto_now_add=True, db_index=True, db_default=Now()
    )
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


# ==========================
# Stakeholders
# ==========================


class Agency(TimeStampedModel):
    AGENCY_KEY_REGEX = r"^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$"
    agency_key_validator = RegexValidator(
        regex=AGENCY_KEY_REGEX,
        message=_(
            "Agency key must match ^[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])$ "
            "(lowercase letters, digits, hyphen)."
        ),
    )

    name = models.CharField(max_length=255, unique=True)
    agency_key = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        validators=[agency_key_validator],
        help_text=_(
            "Stable immutable key used for IAM group paths (example: atpl-milano)."
        ),
    )
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Agency"
        verbose_name_plural = "Agencies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def normalize_agency_key(cls, raw_value: str) -> str:
        normalized = slugify((raw_value or "").strip(), allow_unicode=False)
        normalized = normalized.strip("-")
        if not normalized:
            normalized = "agency"
        if len(normalized) < 3:
            normalized = f"{normalized}-agency"
        if len(normalized) > 40:
            normalized = normalized[:40].rstrip("-")
        if len(normalized) < 3:
            normalized = (normalized + "000")[:3]
        return normalized

    def _build_unique_agency_key(self) -> str:
        base = self.normalize_agency_key(self.name or self.agency_key or "")
        candidate = base
        suffix = 2
        qs = type(self).objects.all()
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        while qs.filter(agency_key=candidate).exists():
            suffix_part = f"-{suffix}"
            trimmed = base[: 40 - len(suffix_part)].rstrip("-")
            if not trimmed:
                trimmed = "agency"
            candidate = f"{trimmed}{suffix_part}"
            suffix += 1
        return candidate

    def clean(self):
        super().clean()
        errors = {}
        if not self.agency_key:
            self.agency_key = self._build_unique_agency_key()
        if self.agency_key != self.agency_key.lower():
            errors["agency_key"] = _("agency_key must be lowercase.")
        if self.pk:
            current_key = (
                type(self)
                .objects.filter(pk=self.pk)
                .values_list("agency_key", flat=True)
                .first()
            )
            if current_key and current_key != self.agency_key:
                errors["agency_key"] = _("agency_key is immutable once set.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.agency_key:
            self.agency_key = self._build_unique_agency_key()
        self.full_clean()
        return super().save(*args, **kwargs)


class Company(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = "Company"
        verbose_name_plural = "Companies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def _platform_initialization_file_path(*, category: str, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    return f"platform/initialization/{category}/{uuid.uuid4().hex}{extension}"


def netex_profile_upload_path(instance, filename):
    return _platform_initialization_file_path(category="netex", filename=filename)


def siri_profile_upload_path(instance, filename):
    return _platform_initialization_file_path(category="siri", filename=filename)


def indicator_profile_upload_path(instance, filename):
    return _platform_initialization_file_path(category="indicators", filename=filename)


class NetexValidationProfile(TimeStampedModel):
    label = models.CharField(max_length=128, blank=True, default="")
    file = models.FileField(
        upload_to=netex_profile_upload_path,
        max_length=512,
        validators=[FileExtensionValidator(allowed_extensions=["xsd"])],
        help_text="Validation profile file (.xsd).",
    )
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "Netex validation profile"
        verbose_name_plural = "Netex validation profiles"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="uniq_active_netex_validation_profile",
            )
        ]

    def __str__(self) -> str:
        if self.label:
            return self.label
        return Path(self.file.name).name


class SiriValidationProfile(TimeStampedModel):
    class ProfileType(models.TextChoices):
        PT = "siri-pt", _("SIRI PT")
        SX = "siri-sx", _("SIRI SX")
        VM = "siri-vm", _("SIRI VM")
        SM = "siri-sm", _("SIRI SM")

    profile_type = models.CharField(
        max_length=32,
        choices=ProfileType.choices,
        default=ProfileType.PT,
    )
    label = models.CharField(max_length=128, blank=True, default="")
    file = models.FileField(
        upload_to=siri_profile_upload_path,
        max_length=512,
        validators=[FileExtensionValidator(allowed_extensions=["xsd", "xml"])],
        help_text="SIRI validation profile file (.xsd/.xml).",
    )
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "SIRI validation profile"
        verbose_name_plural = "SIRI validation profiles"
        ordering = ["profile_type", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["profile_type"],
                condition=models.Q(is_active=True),
                name="uniq_active_siri_profile_by_type",
            )
        ]

    def __str__(self) -> str:
        if self.label:
            return f"{self.profile_type} - {self.label}"
        return f"{self.profile_type} - {Path(self.file.name).name}"


class IndicatorProfile(TimeStampedModel):
    label = models.CharField(max_length=128, blank=True, default="")
    file = models.FileField(
        upload_to=indicator_profile_upload_path,
        max_length=512,
        validators=[FileExtensionValidator(allowed_extensions=["yml", "yaml"])],
        help_text="Indicator definition file (.yml/.yaml).",
    )
    is_active = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "Indicator profile"
        verbose_name_plural = "Indicator profiles"
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        if self.label:
            return self.label
        return Path(self.file.name).name


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
        null=True, blank=True, srid=4326, help_text="Geographic extent in WGS84"
    )
    authority_type = models.CharField(max_length=20, choices=AuthorityType.choices)

    class Meta:
        verbose_name = "Authority"
        verbose_name_plural = "Authorities"
        constraints = [
            models.UniqueConstraint(
                fields=["name", "authority_type"], name="uniq_authority_name_type"
            ),
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
# Consider whether to add a model to store per-company API keys.
# ====================================================================================


# ==========================
# Service net: Lots
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
    # Consider adding the lot polygon geometry in a future iteration.

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ["id"]

    def __str__(self) -> str:
        short = f" ({self.short_description})" if self.short_description else ""
        return f"Lot {self.id}{short} - {self.description}"


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

    # Consider storing a dataset-level validation schema reference (e.g. XSD).
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

    dataset = models.ForeignKey(
        Dataset, on_delete=models.PROTECT, related_name="structures"
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    definition = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Structured mandatory-field definition used by external processors. "
            "Example: {'xpath': '//EstimatedVehicleJourney', 'fields': "
            "['LineRef', 'DirectionRef']}.\n\n"
            "Technical note: '//' in XPath means descendant-or-self"
            " and matches nodes at any depth."
        ),
    )

    class Meta:
        verbose_name = "Structure"
        verbose_name_plural = "Structures"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "name"], name="unique_structure_dataset_name"
            )
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


class FlowProfile(TimeStampedModel):
    """
    Reusable operational flow configuration assigned to contracts.

    `options` stores structured flow configuration blocks (planned master,
    ingestion, retention, ...). Validation is intentionally minimal and checks
    only the required top-level sections and core field types.
    """

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    schema_version = models.CharField(max_length=16, default="1.0")
    options = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Flow profile"
        verbose_name_plural = "Flow profiles"
        ordering = ["code"]
        indexes = [models.Index(fields=["is_active"])]

    def __str__(self) -> str:
        return f"{self.code} ({self.schema_version})"

    def clean(self):
        super().clean()
        if not isinstance(self.options, dict):
            raise ValidationError({"options": _("options must be a JSON object.")})

        required_keys = [
            "general_profile",
            "planned_master",
            "data_ingestion",
            "data_retention",
        ]
        option_errors: list[str] = []
        for key in required_keys:
            if key not in self.options:
                option_errors.append(f"Missing required key: {key}")

        if option_errors:
            raise ValidationError({"options": option_errors})

        general_profile = self.options.get("general_profile")
        option_errors = []
        if not isinstance(general_profile, str) or not general_profile.strip():
            option_errors.append("general_profile must be a non-empty string.")

        for block_key in ["planned_master", "data_ingestion"]:
            block = self.options.get(block_key)
            if not isinstance(block, dict):
                option_errors.append(f"{block_key} must be a JSON object.")
                continue
            for item_key, item in block.items():
                if not isinstance(item, dict):
                    option_errors.append(
                        f"{block_key}.{item_key} must be a JSON object."
                    )
                    continue
                if not isinstance(item.get("active"), bool):
                    option_errors.append(
                        f"{block_key}.{item_key}.active must be a boolean."
                    )
                if (
                    not isinstance(item.get("flow"), str)
                    or not item.get("flow", "").strip()
                ):
                    option_errors.append(
                        f"{block_key}.{item_key}.flow must be a non-empty string."
                    )
                if not isinstance(item.get("description"), str):
                    option_errors.append(
                        f"{block_key}.{item_key}.description must be a string."
                    )

        retention = self.options.get("data_retention")
        if not isinstance(retention, dict):
            option_errors.append("data_retention must be a JSON object.")
        else:
            for item_key, item in retention.items():
                if not isinstance(item, dict):
                    option_errors.append(
                        f"data_retention.{item_key} must be a JSON object."
                    )
                    continue
                days = item.get("days")
                if not isinstance(days, int) or days < 0:
                    option_errors.append(
                        f"data_retention.{item_key}.days must be an integer >= 0."
                    )
                if (
                    not isinstance(item.get("flow"), str)
                    or not item.get("flow", "").strip()
                ):
                    option_errors.append(
                        f"data_retention.{item_key}.flow must be a non-empty string."
                    )
                if not isinstance(item.get("description"), str):
                    option_errors.append(
                        f"data_retention.{item_key}.description must be a string."
                    )

        if option_errors:
            raise ValidationError({"options": option_errors})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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

    - A contract belongs to exactly one lot, one client agency and one
      contractor company.
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
        Agency,
        on_delete=models.PROTECT,
        related_name="contracts_as_client",
        help_text="Client agency",
    )
    contractor_company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="contracts_as_contractor",
        help_text="Contractor company",
    )
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)

    tender_id = models.CharField(
        max_length=64,
        blank=True,
        help_text=(
            "Associated tender/procurement identifier (optional; no dedicated table)"
        ),
    )

    contract_type = models.CharField(max_length=7, choices=ContractType.choices)
    version = models.PositiveIntegerField(
        help_text="Auto progressive serial for (lot, client_agency, contractor_company)"
    )

    # Program (es. NetEx)
    contract_program_file = models.FileField(
        upload_to=contract_program_path,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["xml", "zip"])],
        help_text="NetEx file (XML/ZIP) with the contractual program",
    )
    flow_profile = models.ForeignKey(
        FlowProfile,
        on_delete=models.PROTECT,
        related_name="contracts",
        blank=True,
        null=True,
        help_text="Operational flow profile associated to this contract.",
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
                check=models.Q(end_date__gte=models.F("start_date"))
                | models.Q(end_date__isnull=True),
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
            errors["end_date"] = _(
                "End date must be greater than or equal to start date."
            )

        if self.status == self.ContractStatus.CLOSED:
            if self.closed_at is None:
                errors["closed_at"] = _(
                    "Closed contracts must have a closing timestamp."
                )
            if not self.closed_reason:
                errors["closed_reason"] = _(
                    "Closed contracts must include a closing reason."
                )
        else:
            if self.closed_at is not None:
                errors["closed_at"] = _(
                    "closed_at must be empty unless contract is closed."
                )
            if self.closed_reason:
                errors["closed_reason"] = _(
                    "closed_reason must be empty unless contract is closed."
                )
            if replaced_by_id is not None:
                errors["replaced_by"] = _(
                    "Only closed contracts can reference a replacement."
                )

        if (
            replaced_by_id is not None
            and self.pk is not None
            and replaced_by_id == self.pk
        ):
            errors["replaced_by"] = _("A contract cannot replace itself.")

        if lot_id and self.start_date and effective_end_date:
            overlaps = type(self).objects.filter(
                lot_id=lot_id,
                start_date__lte=effective_end_date,
            )
            overlaps = overlaps.filter(
                models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=self.start_date)
            )
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                errors["lot"] = _(
                    "Another contract already exists for this lot"
                    " in the selected period. "
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
            "flow_profile_id",
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
            raise ValidationError(
                {"version": _("Version is auto-managed and cannot be edited.")}
            )
        if self.contract_type != original.contract_type:
            raise ValidationError(
                {
                    "contract_type": _(
                        "Contract type is auto-managed and cannot be edited."
                    )
                }
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
# evaluate how to associate, to a contract, the users/emails that will be
# allowed to access the contract’s admin sections
# evaluate possible integrations with IAM to provision the new users


class ContractDocument(TimeStampedModel):
    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="documents"
    )
    name = models.CharField(max_length=255, blank=True)
    file = models.FileField(
        upload_to=contract_doc_path,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "doc", "docx", "odt", "zip"]
            )
        ],
    )

    class Meta:
        verbose_name = "Contract document"
        verbose_name_plural = "Contract documents"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name or self.file.name.split("/")[-1]


class ContractPublication(TimeStampedModel):
    """
    Immutable publication snapshot for a contract.

    Each publication stores a versioned JSON snapshot of the contract aggregate
    as it existed at publication time.
    """

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="publications",
    )
    publication_version = models.PositiveIntegerField()
    published_at = models.DateTimeField(default=timezone.now, db_index=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_publications_created",
    )
    snapshot_schema_version = models.CharField(max_length=16, default="1.0")
    snapshot = models.JSONField(default=dict)
    snapshot_checksum = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = "Contract publication"
        verbose_name_plural = "Contract publications"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "publication_version"],
                name="unique_contract_publication_version",
            )
        ]
        indexes = [
            models.Index(fields=["contract", "-published_at"]),
            models.Index(fields=["snapshot_checksum"]),
        ]
        ordering = ["-published_at", "-publication_version"]

    def clean(self):
        super().clean()
        errors = {}
        if self.publication_version is None or self.publication_version < 1:
            errors["publication_version"] = _("Publication version must be >= 1.")
        if not isinstance(self.snapshot, dict):
            errors["snapshot"] = _("Snapshot must be a JSON object.")
        if not self.snapshot_schema_version:
            errors["snapshot_schema_version"] = _(
                "Snapshot schema version is required."
            )
        if self.snapshot_checksum and len(self.snapshot_checksum) != 64:
            errors["snapshot_checksum"] = _(
                "Snapshot checksum must be a SHA256 hex string."
            )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.contract.contract_code} v{self.publication_version}"


class ContractIndicator(models.Model):
    """
    Contract ↔ IndicatorDef association with optional JSON parameters
    (thresholds/weights/etc.).
    """

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="indicators"
    )
    indicator = models.ForeignKey(
        IndicatorDef, on_delete=models.PROTECT, related_name="contracts"
    )
    params = models.JSONField(
        blank=True,
        null=True,
        help_text="Thresholds/weights/domain-specific configuration",
    )

    class Meta:
        verbose_name = "Contract indicator"
        verbose_name_plural = "Contract indicators"
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "indicator"], name="unique_contract_indicator"
            )
        ]

    def __str__(self) -> str:
        return f"{self.contract.contract_code}:{self.indicator.code}"


class IntegrationPrincipal(TimeStampedModel):
    """Technical M2M client associated with a transport company."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        SUSPENDED = "suspended", _("Suspended")
        REVOKED = "revoked", _("Revoked")

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="integration_principals",
    )
    name = models.CharField(max_length=128)
    environment = models.CharField(max_length=8, default="prod", db_index=True)
    keycloak_client_id = models.CharField(max_length=255, unique=True)
    keycloak_client_uuid = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    last_secret_rotation_at = models.DateTimeField(blank=True, null=True, db_index=True)
    client_secret_ciphertext = models.TextField(blank=True, default="")
    client_secret_key_id = models.CharField(max_length=64, blank=True, default="")
    client_secret_updated_at = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integration_principals_created",
    )

    class Meta:
        verbose_name = "Integration principal"
        verbose_name_plural = "Integration principals"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name", "environment"],
                name="unique_integration_principal_per_company_name_env",
            )
        ]
        indexes = [
            models.Index(fields=["company", "environment"]),
            models.Index(fields=["company", "status"]),
        ]

    def clean(self):
        super().clean()
        self.environment = (self.environment or "prod").strip().lower()
        self.keycloak_client_id = (self.keycloak_client_id or "").strip()
        self.keycloak_client_uuid = (self.keycloak_client_uuid or "").strip()
        self.name = (self.name or "").strip()
        if not self.name:
            raise ValidationError({"name": _("Name is required.")})
        if not self.keycloak_client_id:
            raise ValidationError(
                {"keycloak_client_id": _("Keycloak client id is required.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.keycloak_client_id} ({self.company})"


class IntegrationGrant(TimeStampedModel):
    """Contract-scoped permission assigned to an M2M integration principal."""

    class Action(models.TextChoices):
        INGEST_WRITE = "ingest:write", _("Ingest write")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DISABLED = "disabled", _("Disabled")

    principal = models.ForeignKey(
        IntegrationPrincipal,
        on_delete=models.CASCADE,
        related_name="grants",
    )
    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="integration_grants",
    )
    action = models.CharField(
        max_length=64,
        choices=Action.choices,
        default=Action.INGEST_WRITE,
        db_index=True,
    )
    data_category = models.CharField(max_length=64, blank=True, null=True)
    valid_from = models.DateTimeField(blank=True, null=True, db_index=True)
    valid_to = models.DateTimeField(blank=True, null=True, db_index=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="integration_grants_created",
    )

    class Meta:
        verbose_name = "Integration grant"
        verbose_name_plural = "Integration grants"
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(valid_from__isnull=True)
                    | models.Q(valid_to__isnull=True)
                    | models.Q(valid_to__gte=models.F("valid_from"))
                ),
                name="integration_grant_valid_window",
            ),
            models.UniqueConstraint(
                fields=["principal", "contract", "action"],
                condition=models.Q(data_category__isnull=True, status="active"),
                name="uniq_active_integration_grant_no_category",
            ),
            models.UniqueConstraint(
                fields=["principal", "contract", "action", "data_category"],
                condition=models.Q(data_category__isnull=False, status="active"),
                name="uniq_active_integration_grant_with_category",
            ),
        ]
        indexes = [
            models.Index(
                fields=["principal", "status", "action"],
                name="ix_igr_pri_stat_act",
            ),
            models.Index(
                fields=["principal", "contract", "status"],
                name="ix_igr_pri_ctr_stat",
            ),
            models.Index(
                fields=["contract", "status", "action"],
                name="ix_igr_ctr_stat_act",
            ),
        ]

    def clean(self):
        super().clean()
        self.action = (self.action or self.Action.INGEST_WRITE).strip()
        normalized_category = (self.data_category or "").strip().lower()
        self.data_category = normalized_category or None
        errors = {}
        if self.action not in {choice[0] for choice in self.Action.choices}:
            errors["action"] = _("Unsupported integration grant action.")
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            errors["valid_to"] = _(
                "valid_to must be greater than or equal to valid_from."
            )
        principal_company_id = getattr(self.principal, "company_id", None)
        contract_company_id = getattr(self.contract, "contractor_company_id", None)
        if principal_company_id and contract_company_id:
            if principal_company_id != contract_company_id:
                errors["contract"] = _(
                    "Integration grant contract must belong to the principal company."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        category = self.data_category or "*"
        return (
            f"{self.principal.keycloak_client_id} -> "
            f"{self.contract.contract_code} {self.action} {category}"
        )


class ContractMembership(TimeStampedModel):
    """
    RBAC assignment scoped to a single contract.

    Superusers keep global access, while non-superusers are authorized via
    contract memberships.
    """

    class Role(models.TextChoices):
        CONTRACT_ADMIN = "contract_admin", _("Contract admin")
        CONTRACT_EDITOR = "contract_editor", _("Contract editor")
        CONTRACT_READER = "contract_reader", _("Contract reader")

    contract = models.ForeignKey(
        Contract, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="contract_memberships",
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

    @classmethod
    def role_rank(cls, role: str) -> int:
        order = {
            cls.Role.CONTRACT_READER: 0,
            cls.Role.CONTRACT_EDITOR: 1,
            cls.Role.CONTRACT_ADMIN: 2,
        }
        return order.get(role, -1)

    @property
    def can_manage_contract(self) -> bool:
        return self.role in {self.Role.CONTRACT_ADMIN, self.Role.CONTRACT_EDITOR}


class AgencyMembership(TimeStampedModel):
    """RBAC assignment scoped to an agency."""

    class Role(models.TextChoices):
        AGENCY_ADMIN = "agency_admin", _("Agency admin")
        AGENCY_EDITOR = "agency_editor", _("Agency editor")
        AGENCY_READER = "agency_reader", _("Agency reader")

    agency = models.ForeignKey(
        Agency, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agency_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_memberships_created",
    )

    class Meta:
        verbose_name = "Agency membership"
        verbose_name_plural = "Agency memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["agency", "user"], name="unique_agency_membership_user"
            )
        ]
        indexes = [
            models.Index(fields=["agency", "role"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self) -> str:
        return f"{self.agency.agency_key} - {self.user} ({self.role})"

    @classmethod
    def role_rank(cls, role: str) -> int:
        order = {
            cls.Role.AGENCY_READER: 0,
            cls.Role.AGENCY_EDITOR: 1,
            cls.Role.AGENCY_ADMIN: 2,
        }
        return order.get(role, -1)

    @property
    def can_manage_agency(self) -> bool:
        return self.role == self.Role.AGENCY_ADMIN


class AgencyInvitation(TimeStampedModel):
    """Invitation token to assign an agency-scoped role."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        REJECTED = "rejected", _("Rejected")
        EXPIRED = "expired", _("Expired")
        REVOKED = "revoked", _("Revoked")

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    agency = models.ForeignKey(
        Agency, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField(
        blank=True,
        null=True,
        help_text=_(
            "Optional target email. If empty, the invitation is open and can be used "
            "by the first user who accepts the token."
        ),
    )
    role_to_assign = models.CharField(
        max_length=32, choices=AgencyMembership.Role.choices
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_invitations_created",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_invitations_accepted",
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_invitations_rejected",
    )
    expires_at = models.DateTimeField(default=_default_invitation_expiration)
    accepted_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )

    class Meta:
        verbose_name = "Agency invitation"
        verbose_name_plural = "Agency invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["agency", "email", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=False),
                name="unique_pending_agency_invitation_per_email_role",
            ),
            models.UniqueConstraint(
                fields=["agency", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=True),
                name="unique_pending_open_agency_invitation_per_role",
            ),
        ]
        indexes = [
            models.Index(fields=["agency", "status"]),
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
                        "Accepted user email does not match"
                        " the invitation target email."
                    )
            if self.rejected_at is not None:
                errors["rejected_at"] = _(
                    "rejected_at must be empty unless invitation status is rejected."
                )
            if self.rejected_by is not None:
                errors["rejected_by"] = _(
                    "rejected_by must be empty unless invitation status is rejected."
                )
        elif self.status == self.Status.REJECTED:
            if self.rejected_at is None:
                errors["rejected_at"] = _("Rejected invitations must have rejected_at.")
            if self.rejected_by is None:
                errors["rejected_by"] = _("Rejected invitations must have rejected_by.")
            if self.email and self.rejected_by is not None:
                rejected_email = getattr(self.rejected_by, "email", "")
                if rejected_email.lower() != self.email.lower():
                    errors["rejected_by"] = _(
                        "Rejected user email does not match"
                        " the invitation target email."
                    )
            if self.accepted_at is not None:
                errors["accepted_at"] = _(
                    "accepted_at must be empty unless invitation status is accepted."
                )
            if self.accepted_by is not None:
                errors["accepted_by"] = _(
                    "accepted_by must be empty unless invitation status is accepted."
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
            if self.rejected_at is not None:
                errors["rejected_at"] = _(
                    "rejected_at must be empty unless invitation status is rejected."
                )
            if self.rejected_by is not None:
                errors["rejected_by"] = _(
                    "rejected_by must be empty unless invitation status is rejected."
                )
        if self.status == self.Status.PENDING and self.expires_at <= timezone.now():
            errors["expires_at"] = _("Pending invitations must expire in the future.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def is_valid(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()

    def __str__(self) -> str:
        target = self.email or "open-invite"
        return f"{self.agency.agency_key} -> {target} ({self.role_to_assign})"


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
        REJECTED = "rejected", _("Rejected")
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
    role_to_assign = models.CharField(
        max_length=32, choices=ContractMembership.Role.choices
    )
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
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_invitations_rejected",
    )
    expires_at = models.DateTimeField(default=_default_invitation_expiration)
    accepted_at = models.DateTimeField(blank=True, null=True)
    rejected_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )

    class Meta:
        verbose_name = "Contract invitation"
        verbose_name_plural = "Contract invitations"
        constraints = [
            models.CheckConstraint(
                check=models.Q(
                    role_to_assign__in=[
                        ContractMembership.Role.CONTRACT_EDITOR,
                        ContractMembership.Role.CONTRACT_READER,
                    ]
                ),
                name="contract_invitation_role_editor_or_reader_only",
            ),
            models.UniqueConstraint(
                fields=["contract", "email", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=False),
                name="unique_pending_contract_invitation_per_email_role",
            ),
            models.UniqueConstraint(
                fields=["contract", "role_to_assign"],
                condition=models.Q(status="pending", email__isnull=True),
                name="unique_pending_open_contract_invitation_per_role",
            ),
        ]
        indexes = [
            models.Index(fields=["contract", "status"]),
            models.Index(fields=["email"]),
            models.Index(fields=["token"]),
        ]

    def clean(self):
        errors = {}

        if self.role_to_assign == ContractMembership.Role.CONTRACT_ADMIN:
            errors["role_to_assign"] = _(
                "Contract invitations can assign only"
                " contract_editor or contract_reader."
            )

        if self.status == self.Status.ACCEPTED:
            if self.accepted_at is None:
                errors["accepted_at"] = _("Accepted invitations must have accepted_at.")
            if self.accepted_by is None:
                errors["accepted_by"] = _("Accepted invitations must have accepted_by.")
            if self.email and self.accepted_by is not None:
                accepted_email = getattr(self.accepted_by, "email", "")
                if accepted_email.lower() != self.email.lower():
                    errors["accepted_by"] = _(
                        "Accepted user email does not match"
                        " the invitation target email."
                    )
            if self.rejected_at is not None:
                errors["rejected_at"] = _(
                    "rejected_at must be empty unless invitation status is rejected."
                )
            if self.rejected_by is not None:
                errors["rejected_by"] = _(
                    "rejected_by must be empty unless invitation status is rejected."
                )
        elif self.status == self.Status.REJECTED:
            if self.rejected_at is None:
                errors["rejected_at"] = _("Rejected invitations must have rejected_at.")
            if self.rejected_by is None:
                errors["rejected_by"] = _("Rejected invitations must have rejected_by.")
            if self.email and self.rejected_by is not None:
                rejected_email = getattr(self.rejected_by, "email", "")
                if rejected_email.lower() != self.email.lower():
                    errors["rejected_by"] = _(
                        "Rejected user email does not match"
                        " the invitation target email."
                    )
            if self.accepted_at is not None:
                errors["accepted_at"] = _(
                    "accepted_at must be empty unless invitation status is accepted."
                )
            if self.accepted_by is not None:
                errors["accepted_by"] = _(
                    "accepted_by must be empty unless invitation status is accepted."
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
            if self.rejected_at is not None:
                errors["rejected_at"] = _(
                    "rejected_at must be empty unless invitation status is rejected."
                )
            if self.rejected_by is not None:
                errors["rejected_by"] = _(
                    "rejected_by must be empty unless invitation status is rejected."
                )

        if self.status == self.Status.PENDING and self.expires_at <= timezone.now():
            errors["expires_at"] = _("Pending invitations must expire in the future.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def is_valid(self) -> bool:
        return self.status == self.Status.PENDING and self.expires_at > timezone.now()

    def __str__(self) -> str:
        target = self.email or "open-invite"
        return f"{self.contract.contract_code} -> {target} ({self.role_to_assign})"
