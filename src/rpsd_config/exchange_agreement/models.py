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
from django.db import models, transaction
from django.db.models import F, Func
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Lower, Now  # for db_default in Django 5.x
from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from rpsd_config.exchange_agreement.services.flow_catalog_registry import (
    ENGINE_PREFECT,
    validate_flow_executable_references,
    validate_input_compatibility,
    validate_invocation_contract,
)
from rpsd_config.exchange_agreement.services.fragment_registry import (
    LOCATOR_TABLE,
    LOCATOR_XPATH,
    RESULT_PRESENCE,
    RESULT_SCALAR_VALUES,
    RULE_ALL_VALUES_IN_SET,
    RULE_CONTAINS_ALL_VALUES,
    RULE_EXISTS,
    RULE_NON_EMPTY,
    RULE_SET_EQUALS,
    validate_locator_definition,
    validate_rule_parameters,
)
from rpsd_config.exchange_agreement.services.indicator_registry import (
    EXECUTION_DBT,
    EXECUTION_EXTERNAL,
    EXECUTION_PREFECT,
    validate_execution_reference_fields,
    validate_technical_contract,
)
from rpsd_config.exchange_agreement.services.revision_registry import (
    validate_business_configuration,
)

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


CANONICAL_VALIDATION_WHATS = (
    "netex",
    "siri-pt",
    "siri-et",
    "siri-st",
    "siri-sm",
    "siri-vm",
    "siri-ct",
    "siri-cm",
    "siri-gm",
    "siri-fm",
    "siri-sx",
)


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


class ConfigurationAsset(TimeStampedModel):
    class AssetType(models.TextChoices):
        NETEX_XSD = "netex_xsd", _("NeTEx XSD")
        SIRI_PROFILE = "siri_profile", _("SIRI profile")
        INDICATOR_YAML = "indicator_yaml", _("Indicator YAML")

    class Status(models.TextChoices):
        STORED = "stored", _("Stored")
        ACTIVE = "active", _("Active")
        ARCHIVED = "archived", _("Archived")

    ASSET_TYPE_EXTENSIONS = {
        AssetType.NETEX_XSD: {"xsd"},
        AssetType.SIRI_PROFILE: {"xsd", "xml"},
        AssetType.INDICATOR_YAML: {"yml", "yaml"},
    }

    asset_type = models.CharField(
        max_length=32,
        choices=AssetType.choices,
        db_index=True,
    )
    what = models.CharField(max_length=64, blank=True, default="", db_index=True)
    label = models.CharField(max_length=128, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.STORED,
        db_index=True,
    )
    is_active = models.BooleanField(default=False, db_index=True)
    storage_url = models.CharField(max_length=1024)
    storage_provider = models.CharField(max_length=32)
    storage_key = models.CharField(max_length=512, blank=True, default="")
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128, blank=True, default="")
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="configuration_assets_uploaded",
    )
    uploaded_at = models.DateTimeField(default=timezone.now, db_index=True)
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="configuration_assets_activated",
    )
    activated_at = models.DateTimeField(blank=True, null=True, db_index=True)
    archived_at = models.DateTimeField(blank=True, null=True, db_index=True)
    publish_status = models.CharField(max_length=16, blank=True, default="")
    last_publish_error = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Configuration asset"
        verbose_name_plural = "Configuration assets"
        ordering = ["asset_type", "what", "-version", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["asset_type", "what", "version"],
                name="uniq_config_asset_type_what_version",
            ),
            models.UniqueConstraint(
                fields=["asset_type", "what"],
                condition=models.Q(is_active=True),
                name="uniq_active_config_asset_type_what",
            ),
        ]
        indexes = [
            models.Index(
                fields=["asset_type", "what", "status"],
                name="exchange_ag_asset__0b9d8a_idx",
            ),
            models.Index(
                fields=["is_active", "asset_type", "what"],
                name="exchange_ag_is_act_0a33d7_idx",
            ),
        ]

    def __str__(self) -> str:
        target = self.what or self.asset_type
        return f"{target} v{self.version} ({self.status})"

    @classmethod
    def normalize_what_from_filename(cls, filename: str) -> str:
        return Path(filename or "").name.rsplit(".", 1)[0].strip().lower()

    @classmethod
    def validate_filename_for_type(cls, asset_type: str, filename: str) -> str:
        name = Path(filename or "").name.strip()
        suffix = Path(name).suffix.lower().lstrip(".")
        if not name or not suffix:
            raise ValidationError(_("Asset filename must include an extension."))
        allowed = cls.ASSET_TYPE_EXTENSIONS.get(asset_type)
        if allowed is None or suffix not in allowed:
            raise ValidationError(_("Asset filename extension is not supported."))

        what = cls.normalize_what_from_filename(name)
        if asset_type == cls.AssetType.NETEX_XSD and name.lower() != "netex.xsd":
            raise ValidationError(_("NeTEx validation asset must be named netex.xsd."))
        if asset_type == cls.AssetType.SIRI_PROFILE and what not in {
            item for item in CANONICAL_VALIDATION_WHATS if item.startswith("siri-")
        }:
            raise ValidationError(
                _("SIRI asset filename must use a canonical name like siri-pt.xsd.")
            )
        if asset_type == cls.AssetType.INDICATOR_YAML:
            what = "indicators"
        return what

    def clean(self):
        super().clean()
        errors = {}
        try:
            expected_what = self.validate_filename_for_type(
                self.asset_type,
                self.original_filename,
            )
            if self.what and self.what != expected_what:
                errors["what"] = _("what does not match the canonical filename stem.")
            self.what = expected_what
        except ValidationError as exc:
            errors["original_filename"] = exc.messages

        if self.is_active:
            self.status = self.Status.ACTIVE
            if self.activated_at is None:
                self.activated_at = timezone.now()
        elif self.status == self.Status.ACTIVE:
            self.is_active = True
            if self.activated_at is None:
                self.activated_at = timezone.now()
        if self.status == self.Status.ARCHIVED and self.archived_at is None:
            self.archived_at = timezone.now()

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ConfigurationAssetEvent(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        PUBLISHED = "published", _("Published")
        FAILED = "failed", _("Failed")

    asset = models.ForeignKey(
        ConfigurationAsset,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    routing_key = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        verbose_name = "Configuration asset event"
        verbose_name_plural = "Configuration asset events"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["status", "event_type"],
                name="exchange_ag_status_b0c3a4_idx",
            ),
            models.Index(
                fields=["asset", "status"],
                name="exchange_ag_asset_i_b487ba_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} asset={self.asset_id} ({self.status})"


class NetexValidationProfile(TimeStampedModel):
    label = models.CharField(max_length=128, blank=True, default="")
    file = models.FileField(
        upload_to=netex_profile_upload_path,
        max_length=512,
        validators=[FileExtensionValidator(allowed_extensions=["xsd"])],
        help_text="Validation profile file (.xsd).",
    )
    is_active = models.BooleanField(default=False, db_index=True)
    configuration_asset = models.ForeignKey(
        ConfigurationAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="netex_profiles",
    )

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
        ET = "siri-et", _("SIRI ET")
        ST = "siri-st", _("SIRI ST")
        CT = "siri-ct", _("SIRI CT")
        CM = "siri-cm", _("SIRI CM")
        GM = "siri-gm", _("SIRI GM")
        FM = "siri-fm", _("SIRI FM")
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
    configuration_asset = models.ForeignKey(
        ConfigurationAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="siri_profiles",
    )

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
    configuration_asset = models.ForeignKey(
        ConfigurationAsset,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="indicator_profiles",
    )

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


class AuthorityMembership(TimeStampedModel):
    """Human user allowed to consult contracts assigned to an authority."""

    authority = models.ForeignKey(
        Authority,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authority_memberships",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authority_memberships_created",
    )

    class Meta:
        verbose_name = "Authority membership"
        verbose_name_plural = "Authority memberships"
        ordering = ["authority__name", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["authority", "user"],
                name="unique_authority_membership_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.authority.name} - {self.user}"


# ====================================================================================
# Consider whether to add a model to store per-company API keys.
# ====================================================================================


# ==========================
# Service net: Lots
# ==========================


class Lot(TimeStampedModel):
    LOT_CODE_REGEX = r"^[A-Z0-9](?:[A-Z0-9-]{0,62}[A-Z0-9])?$"
    lot_code_validator = RegexValidator(
        regex=LOT_CODE_REGEX,
        message=_(
            "Lot code must contain only uppercase letters, digits and hyphens, "
            "and cannot start or end with a hyphen."
        ),
    )

    id = models.BigAutoField(primary_key=True)
    short_description = models.CharField(
        max_length=64,
        db_index=True,
        validators=[lot_code_validator],
        help_text=_("Stable lot code used in business identifiers."),
    )
    agency = models.ForeignKey(
        Agency,
        on_delete=models.PROTECT,
        related_name="lots",
        blank=True,
        null=True,
        help_text=_("Agency that owns this service lot."),
    )
    description = models.CharField(max_length=255)
    # Consider adding the lot polygon geometry in a future iteration.

    class Meta:
        verbose_name = "Lot"
        verbose_name_plural = "Lots"
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                Lower("short_description"),
                "agency",
                name="unique_lot_short_description_per_agency_ci",
            )
        ]

    def __str__(self) -> str:
        return f"Lot {self.short_description} - {self.description}"

    @classmethod
    def normalize_short_description(cls, raw_value: str) -> str:
        normalized = slugify((raw_value or "").strip(), allow_unicode=False).upper()
        return normalized[:64].strip("-")

    def clean(self):
        super().clean()
        self.short_description = self.normalize_short_description(
            self.short_description
        )
        if not self.short_description:
            raise ValidationError({"short_description": _("Lot code is required.")})

    def save(self, *args, **kwargs):
        self.short_description = self.normalize_short_description(
            self.short_description
        )
        super().save(*args, **kwargs)


# ==========================
# Dataset & Structures
# ==========================


def structure_validation_path(instance, filename):
    """
    Legacy helper kept for migration compatibility with old FileField storage.
    """
    return f"catalog/structures/{instance.id}/validation/{filename}"


class Dataset(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DEPRECATED = "deprecated", _("Deprecated")

    CODE_REGEX = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    code_validator = RegexValidator(
        regex=CODE_REGEX,
        message=_(
            "Dataset code must contain lowercase letters, digits and hyphens "
            "(examples: netex, siri-vm)."
        ),
    )

    code = models.SlugField(
        unique=True,
        validators=[code_validator],
        help_text="Canonical TransportMessage.what value, e.g. netex or siri-vm.",
    )
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        verbose_name = "Dataset"
        verbose_name_plural = "Datasets"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip().lower()

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class DatasetSpecification(TimeStampedModel):
    """Versioned technical specification of a logical dataset."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        DEPRECATED = "deprecated", _("Deprecated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="specifications",
    )
    code = models.CharField(max_length=96, unique=True)
    version = models.CharField(max_length=32)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    metadata = models.JSONField(default=dict, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dataset_specifications_published",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    assets = models.ManyToManyField(
        ConfigurationAsset,
        through="DatasetSpecificationAsset",
        related_name="dataset_specifications",
        blank=True,
    )

    class Meta:
        verbose_name = "Dataset specification"
        verbose_name_plural = "Dataset specifications"
        ordering = ["dataset__code", "version", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "version"],
                name="uniq_dataset_specification_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["dataset", "status"],
                name="ix_dataset_spec_dataset_status",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.status})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.version = (self.version or "").strip()
        errors = {}
        if not self.code:
            errors["code"] = _("Specification code is required.")
        if not self.version:
            errors["version"] = _("Specification version is required.")
        if not isinstance(self.metadata, dict):
            errors["metadata"] = _("Metadata must be a JSON object.")

        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the dataset specification lifecycle service to "
                        "change status."
                    )
                if original.status != self.Status.DRAFT:
                    semantic_fields = (
                        "dataset_id",
                        "code",
                        "version",
                        "description",
                        "metadata",
                    )
                    changed = [
                        field
                        for field in semantic_fields
                        if getattr(self, field) != getattr(original, field)
                    ]
                    if changed:
                        errors["__all__"] = _(
                            "Published, deprecated or withdrawn specifications are "
                            "immutable; create a new version instead."
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                _("Only draft dataset specifications can be deleted.")
            )
        return super().delete(*args, **kwargs)


class DatasetSpecificationAsset(models.Model):
    class Role(models.TextChoices):
        VALIDATION_SCHEMA = "validation_schema", _("Validation schema")
        CONSTRAINT = "constraint", _("Constraint")
        DOCUMENTATION = "documentation", _("Documentation")
        EXAMPLE = "example", _("Example")
        OTHER = "other", _("Other")

    dataset_specification = models.ForeignKey(
        DatasetSpecification,
        on_delete=models.CASCADE,
        related_name="asset_links",
    )
    configuration_asset = models.ForeignKey(
        ConfigurationAsset,
        on_delete=models.PROTECT,
        related_name="dataset_specification_links",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    required = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Dataset specification asset"
        verbose_name_plural = "Dataset specification assets"
        ordering = ["role", "configuration_asset_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_specification", "configuration_asset", "role"],
                name="uniq_dataset_spec_asset_role",
            )
        ]

    def __str__(self) -> str:
        return f"{self.dataset_specification.code}:{self.role}"

    def clean(self):
        super().clean()
        specification = self.dataset_specification
        asset = self.configuration_asset
        current_status = specification.status
        if specification.pk:
            current_status = DatasetSpecification.objects.values_list(
                "status", flat=True
            ).get(pk=specification.pk)
        if current_status != DatasetSpecification.Status.DRAFT:
            raise ValidationError(
                _("Assets can be changed only while the specification is draft.")
            )
        if asset.what != specification.dataset.code:
            raise ValidationError(
                {
                    "configuration_asset": _(
                        "Asset what must match the logical dataset code."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = DatasetSpecification.objects.values_list(
            "status", flat=True
        ).get(pk=self.dataset_specification_id)
        if current_status != DatasetSpecification.Status.DRAFT:
            raise ValidationError(
                _("Assets can be changed only while the specification is draft.")
            )
        return super().delete(*args, **kwargs)


class DatasetSpecificationStatusEvent(models.Model):
    dataset_specification = models.ForeignKey(
        DatasetSpecification,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(
        max_length=16,
        choices=DatasetSpecification.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dataset_specification_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Dataset specification status event"
        verbose_name_plural = "Dataset specification status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return (
            f"{self.dataset_specification.code}:"
            f"{self.from_status or '-'}->{self.to_status}"
        )


class RequirementFragment(TimeStampedModel):
    """Declarative, version-specific location of data required by indicators."""

    class LocatorType(models.TextChoices):
        XPATH = LOCATOR_XPATH, _("XPath")
        TABLE = LOCATOR_TABLE, _("Table")

    class ResultKind(models.TextChoices):
        PRESENCE = RESULT_PRESENCE, _("Presence")
        SCALAR_VALUES = RESULT_SCALAR_VALUES, _("Scalar values")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        DEPRECATED = "deprecated", _("Deprecated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    dataset_specification = models.ForeignKey(
        DatasetSpecification,
        on_delete=models.PROTECT,
        related_name="requirement_fragments",
    )
    code = models.SlugField(max_length=96)
    name = models.CharField(max_length=128)
    description = models.TextField()
    locator_type = models.CharField(max_length=16, choices=LocatorType.choices)
    result_kind = models.CharField(max_length=24, choices=ResultKind.choices)
    locator_definition = models.JSONField(default=dict)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    class Meta:
        verbose_name = "Requirement fragment"
        verbose_name_plural = "Requirement fragments"
        ordering = ["dataset_specification__code", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_specification", "code"],
                name="uniq_requirement_fragment_spec_code",
            )
        ]
        indexes = [
            models.Index(
                fields=["dataset_specification", "status"],
                name="ix_fragment_spec_status",
            )
        ]

    def __str__(self) -> str:
        return f"{self.dataset_specification.code}:{self.code}"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.name = (self.name or "").strip()
        self.description = (self.description or "").strip()
        errors = {}
        if not self.name:
            errors["name"] = _("Fragment name is required.")
        if not self.description:
            errors["description"] = _("Fragment description is required.")
        try:
            self.locator_definition = validate_locator_definition(
                self.locator_type,
                self.result_kind,
                self.locator_definition,
            )
        except ValidationError as exc:
            errors["locator_definition"] = exc.messages

        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the requirement fragment lifecycle service to "
                        "change status."
                    )
                if original.status != self.Status.DRAFT:
                    semantic_fields = (
                        "dataset_specification_id",
                        "code",
                        "name",
                        "description",
                        "locator_type",
                        "result_kind",
                        "locator_definition",
                    )
                    if any(
                        getattr(self, field) != getattr(original, field)
                        for field in semantic_fields
                    ):
                        errors["__all__"] = _(
                            "Published, deprecated or withdrawn fragments are "
                            "immutable."
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = self.status
        if self.pk:
            current_status = (
                type(self).objects.values_list("status", flat=True).get(pk=self.pk)
            )
        if current_status != self.Status.DRAFT:
            raise ValidationError(_("Only draft requirement fragments can be deleted."))
        return super().delete(*args, **kwargs)


class FragmentValidationRule(models.Model):
    class RuleType(models.TextChoices):
        EXISTS = RULE_EXISTS, _("Exists")
        NON_EMPTY = RULE_NON_EMPTY, _("Non-empty")
        ALL_VALUES_IN_SET = RULE_ALL_VALUES_IN_SET, _("All values in set")
        CONTAINS_ALL_VALUES = RULE_CONTAINS_ALL_VALUES, _("Contains all values")
        SET_EQUALS = RULE_SET_EQUALS, _("Set equals")

    class Severity(models.TextChoices):
        ERROR = "error", _("Error")
        WARNING = "warning", _("Warning")

    requirement_fragment = models.ForeignKey(
        RequirementFragment,
        on_delete=models.CASCADE,
        related_name="validation_rules",
    )
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    rule_version = models.PositiveIntegerField(default=1)
    parameters = models.JSONField(default=dict, blank=True)
    severity = models.CharField(
        max_length=16,
        choices=Severity.choices,
        default=Severity.ERROR,
    )

    class Meta:
        verbose_name = "Fragment validation rule"
        verbose_name_plural = "Fragment validation rules"
        ordering = ["rule_type", "rule_version", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["requirement_fragment", "rule_type"],
                name="uniq_fragment_validation_rule_type",
            )
        ]

    def __str__(self) -> str:
        return f"{self.requirement_fragment}: {self.rule_type}/v{self.rule_version}"

    def clean(self):
        super().clean()
        fragment = self.requirement_fragment
        current_status = fragment.status
        if fragment.pk:
            current_status = RequirementFragment.objects.values_list(
                "status", flat=True
            ).get(pk=fragment.pk)
        if current_status != RequirementFragment.Status.DRAFT:
            raise ValidationError(
                _("Rules can be changed only while the fragment is draft.")
            )
        try:
            self.parameters = validate_rule_parameters(
                self.rule_type,
                self.rule_version,
                fragment.result_kind,
                self.parameters,
            )
        except ValidationError as exc:
            raise ValidationError({"parameters": exc.messages}) from exc

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = RequirementFragment.objects.values_list(
            "status", flat=True
        ).get(pk=self.requirement_fragment_id)
        if current_status != RequirementFragment.Status.DRAFT:
            raise ValidationError(
                _("Rules can be changed only while the fragment is draft.")
            )
        return super().delete(*args, **kwargs)


class RequirementFragmentStatusEvent(models.Model):
    requirement_fragment = models.ForeignKey(
        RequirementFragment,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(
        max_length=16,
        choices=RequirementFragment.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requirement_fragment_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Requirement fragment status event"
        verbose_name_plural = "Requirement fragment status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return (
            f"{self.requirement_fragment}:{self.from_status or '-'}->{self.to_status}"
        )


class Indicator(TimeStampedModel):
    """Stable business identity of a monitored indicator."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DEPRECATED = "deprecated", _("Deprecated")

    CODE_REGEX = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
    code = models.SlugField(
        max_length=96,
        unique=True,
        validators=[
            RegexValidator(
                regex=CODE_REGEX,
                message=_(
                    "Indicator code must contain lowercase letters, digits and hyphens."
                ),
            )
        ],
    )
    name = models.CharField(max_length=128)
    description = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )

    class Meta:
        verbose_name = "Indicator"
        verbose_name_plural = "Indicators"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.name = (self.name or "").strip()
        self.description = (self.description or "").strip()
        errors = {}
        if not self.name:
            errors["name"] = _("Indicator name is required.")
        if not self.description:
            errors["description"] = _("Indicator description is required.")
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class IndicatorVersion(TimeStampedModel):
    """Immutable published technical definition of an indicator."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        DEPRECATED = "deprecated", _("Deprecated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    class ExecutionEngine(models.TextChoices):
        NONE = "", _("No execution reference")
        PREFECT = EXECUTION_PREFECT, _("Prefect")
        DBT = EXECUTION_DBT, _("dbt")
        EXTERNAL = EXECUTION_EXTERNAL, _("External")

    indicator = models.ForeignKey(
        Indicator,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    code = models.CharField(max_length=96, unique=True)
    version = models.CharField(max_length=32)
    description = models.TextField()
    formula_description = models.TextField()
    input_contract = models.JSONField(default=dict, blank=True)
    output_contract = models.JSONField(default=dict, blank=True)
    execution_engine = models.CharField(
        max_length=16,
        choices=ExecutionEngine.choices,
        blank=True,
        default=ExecutionEngine.NONE,
    )
    execution_reference = models.CharField(max_length=255, blank=True)
    artifact_identifier = models.CharField(max_length=512, blank=True)
    required_fragments = models.ManyToManyField(
        RequirementFragment,
        related_name="indicator_versions",
        blank=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="indicator_versions_published",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Indicator version"
        verbose_name_plural = "Indicator versions"
        ordering = ["indicator__code", "version", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["indicator", "version"],
                name="uniq_indicator_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["indicator", "status"],
                name="ix_indicator_version_status",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.status})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.version = (self.version or "").strip()
        self.description = (self.description or "").strip()
        self.formula_description = (self.formula_description or "").strip()
        errors = {}
        if not self.code:
            errors["code"] = _("Indicator version code is required.")
        if not self.version:
            errors["version"] = _("Indicator version is required.")
        if not self.description:
            errors["description"] = _("Indicator version description is required.")
        if not self.formula_description:
            errors["formula_description"] = _("Formula description is required.")
        for field_name in ("input_contract", "output_contract"):
            try:
                setattr(
                    self,
                    field_name,
                    validate_technical_contract(
                        getattr(self, field_name),
                        field_name=field_name,
                    ),
                )
            except ValidationError as exc:
                errors[field_name] = exc.messages
        try:
            (
                self.execution_reference,
                self.artifact_identifier,
            ) = validate_execution_reference_fields(
                engine=self.execution_engine,
                execution_reference=self.execution_reference,
                artifact_identifier=self.artifact_identifier,
                require_complete=self.status == self.Status.PUBLISHED,
            )
        except ValidationError as exc:
            errors["execution_engine"] = exc.messages

        if not self.pk and self.status != self.Status.DRAFT:
            errors["status"] = _(
                "New indicator versions must start as draft and use the "
                "lifecycle service."
            )
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the indicator version lifecycle service to change status."
                    )
                if original.status != self.Status.DRAFT:
                    semantic_fields = (
                        "indicator_id",
                        "code",
                        "version",
                        "description",
                        "formula_description",
                        "input_contract",
                        "output_contract",
                        "execution_engine",
                        "execution_reference",
                        "artifact_identifier",
                    )
                    if any(
                        getattr(self, field) != getattr(original, field)
                        for field in semantic_fields
                    ):
                        errors["__all__"] = _(
                            "Published, deprecated or withdrawn indicator versions "
                            "are immutable."
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = self.status
        if self.pk:
            current_status = (
                type(self).objects.values_list("status", flat=True).get(pk=self.pk)
            )
        if current_status != self.Status.DRAFT:
            raise ValidationError(_("Only draft indicator versions can be deleted."))
        return super().delete(*args, **kwargs)


class IndicatorVersionStatusEvent(models.Model):
    indicator_version = models.ForeignKey(
        IndicatorVersion,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(
        max_length=16,
        choices=IndicatorVersion.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="indicator_version_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Indicator version status event"
        verbose_name_plural = "Indicator version status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return f"{self.indicator_version}:{self.from_status or '-'}->{self.to_status}"


@receiver(m2m_changed, sender=IndicatorVersion.required_fragments.through)
def protect_indicator_version_fragments(
    sender, instance, action, reverse, pk_set, **kwargs
):
    if action not in {"pre_add", "pre_remove", "pre_clear"}:
        return
    if reverse:
        versions = (
            instance.indicator_versions.all()
            if pk_set is None
            else IndicatorVersion.objects.filter(pk__in=pk_set)
        )
        if versions.exclude(status=IndicatorVersion.Status.DRAFT).exists():
            raise ValidationError(
                _("Required fragments of non-draft indicator versions are immutable.")
            )
    elif instance.status != IndicatorVersion.Status.DRAFT:
        raise ValidationError(
            _("Required fragments can be changed only while the version is draft.")
        )


@receiver(pre_delete, sender=RequirementFragment)
def protect_published_indicator_fragment_reference(sender, instance, **kwargs):
    protected_versions = instance.indicator_versions.exclude(
        status=IndicatorVersion.Status.DRAFT
    )
    if protected_versions.exists():
        raise ProtectedError(
            "Requirement fragment is referenced by a non-draft indicator version.",
            protected_versions,
        )


class FlowCatalogVersionBase(TimeStampedModel):
    """Shared catalog metadata; executable workflow details remain in Prefect."""

    class Engine(models.TextChoices):
        PREFECT = ENGINE_PREFECT, _("Prefect")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        DEPRECATED = "deprecated", _("Deprecated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    code = models.CharField(max_length=96, unique=True)
    version = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    description = models.TextField()
    engine = models.CharField(
        max_length=16,
        choices=Engine.choices,
        default=Engine.PREFECT,
    )
    deployment_name = models.CharField(max_length=255, blank=True)
    artifact_identifier = models.CharField(max_length=512, blank=True)
    invocation_contract = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_versions_published",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return f"{self.code} ({self.status})"

    def semantic_field_names(self) -> tuple[str, ...]:
        return (
            "code",
            "version",
            "name",
            "description",
            "engine",
            "deployment_name",
            "artifact_identifier",
            "invocation_contract",
        )

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.version = (self.version or "").strip()
        self.name = (self.name or "").strip()
        self.description = (self.description or "").strip()
        errors = {}
        for field_name, message in (
            ("code", _("Flow catalog code is required.")),
            ("version", _("Flow catalog version is required.")),
            ("name", _("Flow name is required.")),
            ("description", _("Flow description is required.")),
        ):
            if not getattr(self, field_name):
                errors[field_name] = message
        try:
            self.invocation_contract = validate_invocation_contract(
                self.invocation_contract,
                allow_empty=self.status == self.Status.DRAFT,
            )
        except ValidationError as exc:
            errors["invocation_contract"] = exc.messages
        try:
            (
                self.deployment_name,
                self.artifact_identifier,
            ) = validate_flow_executable_references(
                engine=self.engine,
                deployment_name=self.deployment_name,
                artifact_identifier=self.artifact_identifier,
                require_complete=self.status == self.Status.PUBLISHED,
            )
        except ValidationError as exc:
            errors["deployment_name"] = exc.messages

        if not self.pk and self.status != self.Status.DRAFT:
            errors["status"] = _(
                "New flow versions must start as draft and use the lifecycle service."
            )
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the flow catalog lifecycle service to change status."
                    )
                if original.status != self.Status.DRAFT and any(
                    getattr(self, field) != getattr(original, field)
                    for field in self.semantic_field_names()
                ):
                    errors["__all__"] = _(
                        "Published, deprecated or withdrawn flow versions are "
                        "immutable."
                    )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = self.status
        if self.pk:
            current_status = (
                type(self).objects.values_list("status", flat=True).get(pk=self.pk)
            )
        if current_status != self.Status.DRAFT:
            raise ValidationError(_("Only draft flow versions can be deleted."))
        return super().delete(*args, **kwargs)


class InputFlowVersion(FlowCatalogVersionBase):
    dataset_specification = models.ForeignKey(
        DatasetSpecification,
        on_delete=models.PROTECT,
        related_name="input_flow_versions",
    )
    compatibility = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Input flow version"
        verbose_name_plural = "Input flow versions"
        ordering = ["dataset_specification__code", "version", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_specification", "version"],
                name="uniq_input_flow_specification_version",
            )
        ]
        indexes = [
            models.Index(
                fields=["dataset_specification", "status"],
                name="ix_input_flow_spec_status",
            )
        ]

    def semantic_field_names(self) -> tuple[str, ...]:
        return super().semantic_field_names() + (
            "dataset_specification_id",
            "compatibility",
        )

    def clean(self):
        super().clean()
        if not self.dataset_specification_id:
            return
        try:
            self.compatibility = validate_input_compatibility(
                self.compatibility,
                expected_what=self.dataset_specification.dataset.code,
                allow_empty=self.status == self.Status.DRAFT,
            )
        except ValidationError as exc:
            raise ValidationError({"compatibility": exc.messages}) from exc


class OrchestrationFlowVersion(FlowCatalogVersionBase):
    class Meta:
        verbose_name = "Orchestration flow version"
        verbose_name_plural = "Orchestration flow versions"
        ordering = ["version", "code"]


class InputFlowVersionStatusEvent(models.Model):
    input_flow_version = models.ForeignKey(
        InputFlowVersion,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=InputFlowVersion.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="input_flow_version_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Input flow version status event"
        verbose_name_plural = "Input flow version status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return f"{self.input_flow_version}:{self.from_status or '-'}->{self.to_status}"


class OrchestrationFlowVersionStatusEvent(models.Model):
    orchestration_flow_version = models.ForeignKey(
        OrchestrationFlowVersion,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(
        max_length=16,
        choices=OrchestrationFlowVersion.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orchestration_flow_version_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Orchestration flow version status event"
        verbose_name_plural = "Orchestration flow version status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return (
            f"{self.orchestration_flow_version}:"
            f"{self.from_status or '-'}->{self.to_status}"
        )


class ProcessingProfileVersion(TimeStampedModel):
    """Immutable, platform-approved composition of processing capabilities."""

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PUBLISHED = "published", _("Published")
        DEPRECATED = "deprecated", _("Deprecated")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    code = models.CharField(max_length=96, unique=True)
    version = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    description = models.TextField()
    orchestration_flow_version = models.ForeignKey(
        OrchestrationFlowVersion,
        on_delete=models.PROTECT,
        related_name="processing_profile_versions",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processing_profile_versions_published",
    )
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Processing profile version"
        verbose_name_plural = "Processing profile versions"
        ordering = ["name", "version", "code"]
        indexes = [
            models.Index(fields=["status", "code"], name="ix_process_profile_status")
        ]

    def __str__(self) -> str:
        return f"{self.name} {self.version} ({self.status})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.version = (self.version or "").strip()
        self.name = (self.name or "").strip()
        self.description = (self.description or "").strip()
        errors = {}
        for field_name, message in (
            ("code", _("Processing profile code is required.")),
            ("version", _("Processing profile version is required.")),
            ("name", _("Processing profile name is required.")),
            ("description", _("Processing profile description is required.")),
        ):
            if not getattr(self, field_name):
                errors[field_name] = message
        if not self.pk and self.status != self.Status.DRAFT:
            errors["status"] = _(
                "New processing profile versions must start as draft and use "
                "the lifecycle service."
            )
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the processing profile lifecycle service to change status."
                    )
                if original.status != self.Status.DRAFT:
                    semantic_fields = (
                        "code",
                        "version",
                        "name",
                        "description",
                        "orchestration_flow_version_id",
                    )
                    if any(
                        getattr(self, field) != getattr(original, field)
                        for field in semantic_fields
                    ):
                        errors["__all__"] = _(
                            "Published, deprecated or withdrawn processing profiles "
                            "are immutable; duplicate the profile instead."
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        current_status = self.status
        if self.pk:
            current_status = (
                type(self).objects.values_list("status", flat=True).get(pk=self.pk)
            )
        if current_status != self.Status.DRAFT:
            raise ValidationError(_("Only draft processing profiles can be deleted."))
        return super().delete(*args, **kwargs)


class ProcessingProfileInputFlow(models.Model):
    processing_profile_version = models.ForeignKey(
        ProcessingProfileVersion,
        on_delete=models.CASCADE,
        related_name="input_flow_links",
    )
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.PROTECT,
        related_name="processing_profile_input_links",
    )
    input_flow_version = models.ForeignKey(
        InputFlowVersion,
        on_delete=models.PROTECT,
        related_name="processing_profile_input_links",
    )

    class Meta:
        verbose_name = "Processing profile input flow"
        verbose_name_plural = "Processing profile input flows"
        ordering = ["dataset__code", "input_flow_version__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["processing_profile_version", "dataset"],
                name="uniq_process_profile_dataset",
            )
        ]

    def __str__(self) -> str:
        return f"{self.processing_profile_version.code}:{self.dataset.code}"

    def clean(self):
        super().clean()
        errors = {}
        if self.pk:
            original_profile_id = (
                type(self)
                .objects.values_list("processing_profile_version_id", flat=True)
                .get(pk=self.pk)
            )
            original_status = ProcessingProfileVersion.objects.values_list(
                "status", flat=True
            ).get(pk=original_profile_id)
            if original_status != ProcessingProfileVersion.Status.DRAFT:
                errors["processing_profile_version"] = _(
                    "Input flows of a non-draft profile are immutable."
                )
        if self.processing_profile_version_id:
            status = ProcessingProfileVersion.objects.values_list(
                "status", flat=True
            ).get(pk=self.processing_profile_version_id)
            if status != ProcessingProfileVersion.Status.DRAFT:
                errors["processing_profile_version"] = _(
                    "Input flows can be changed only while the profile is draft."
                )
        if self.dataset_id and self.input_flow_version_id:
            flow_dataset_id = self.input_flow_version.dataset_specification.dataset_id
            if self.dataset_id != flow_dataset_id:
                errors["input_flow_version"] = _(
                    "The input flow specification must belong to the selected dataset."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            ProcessingProfileVersion.objects.select_for_update().get(
                pk=self.processing_profile_version_id
            )
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            status = (
                ProcessingProfileVersion.objects.select_for_update()
                .values_list("status", flat=True)
                .get(pk=self.processing_profile_version_id)
            )
            if status != ProcessingProfileVersion.Status.DRAFT:
                raise ValidationError(
                    _("Input flows can be changed only while the profile is draft.")
                )
            return super().delete(*args, **kwargs)


class ProcessingProfileIndicatorVersion(models.Model):
    processing_profile_version = models.ForeignKey(
        ProcessingProfileVersion,
        on_delete=models.CASCADE,
        related_name="indicator_version_links",
    )
    indicator_version = models.ForeignKey(
        IndicatorVersion,
        on_delete=models.PROTECT,
        related_name="processing_profile_links",
    )
    proposed_by_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Processing profile indicator version"
        verbose_name_plural = "Processing profile indicator versions"
        ordering = ["indicator_version__indicator__code", "indicator_version__version"]
        constraints = [
            models.UniqueConstraint(
                fields=["processing_profile_version", "indicator_version"],
                name="uniq_process_profile_indicator",
            )
        ]

    def __str__(self) -> str:
        return f"{self.processing_profile_version.code}:{self.indicator_version.code}"

    def clean(self):
        super().clean()
        if not self.processing_profile_version_id:
            return
        if self.pk:
            original_profile_id = (
                type(self)
                .objects.values_list("processing_profile_version_id", flat=True)
                .get(pk=self.pk)
            )
            original_status = ProcessingProfileVersion.objects.values_list(
                "status", flat=True
            ).get(pk=original_profile_id)
            if original_status != ProcessingProfileVersion.Status.DRAFT:
                raise ValidationError(
                    {
                        "processing_profile_version": _(
                            "Indicators of a non-draft profile are immutable."
                        )
                    }
                )
        status = ProcessingProfileVersion.objects.values_list("status", flat=True).get(
            pk=self.processing_profile_version_id
        )
        if status != ProcessingProfileVersion.Status.DRAFT:
            raise ValidationError(
                {
                    "processing_profile_version": _(
                        "Indicators can be changed only while the profile is draft."
                    )
                }
            )

    def save(self, *args, **kwargs):
        with transaction.atomic():
            ProcessingProfileVersion.objects.select_for_update().get(
                pk=self.processing_profile_version_id
            )
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            status = (
                ProcessingProfileVersion.objects.select_for_update()
                .values_list("status", flat=True)
                .get(pk=self.processing_profile_version_id)
            )
            if status != ProcessingProfileVersion.Status.DRAFT:
                raise ValidationError(
                    _("Indicators can be changed only while the profile is draft.")
                )
            return super().delete(*args, **kwargs)


class ProcessingProfileVersionStatusEvent(models.Model):
    processing_profile_version = models.ForeignKey(
        ProcessingProfileVersion,
        on_delete=models.PROTECT,
        related_name="status_events",
    )
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(
        max_length=16,
        choices=ProcessingProfileVersion.Status.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processing_profile_version_status_changes",
    )
    changed_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Processing profile version status event"
        verbose_name_plural = "Processing profile version status events"
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:
        return (
            f"{self.processing_profile_version}:"
            f"{self.from_status or '-'}->{self.to_status}"
        )


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
        ordering = ["dataset__code", "name"]

    def __str__(self) -> str:
        return f"{self.dataset.code}:{self.name}"

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


class OperationalFlow(TimeStampedModel):
    """Catalog entry for executable data-processing flows."""

    FLOW_CODE_REGEX = r"^[a-z0-9][a-z0-9-]*_[0-9]{3}(?:[a-z0-9-]*)?$"
    WHAT_CODE_REGEX = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

    class Engine(models.TextChoices):
        PREFECT = "prefect", _("Prefect")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        DEPRECATED = "deprecated", _("Deprecated")
        DISABLED = "disabled", _("Disabled")

    code = models.CharField(
        max_length=96,
        unique=True,
        validators=[
            RegexValidator(
                regex=FLOW_CODE_REGEX,
                message=_(
                    "Flow code must match ^[a-z0-9][a-z0-9-]*_[0-9]{3}(?:[a-z0-9-]*)?$."
                ),
            )
        ],
    )
    engine = models.CharField(
        max_length=32,
        choices=Engine.choices,
        default=Engine.PREFECT,
    )
    deployment_name = models.CharField(max_length=255)
    supported_what = models.CharField(
        max_length=64,
        validators=[
            RegexValidator(
                regex=WHAT_CODE_REGEX,
                message=_(
                    "Supported what must use canonical filename stem syntax "
                    "(example: netex or siri-pt)."
                ),
            )
        ],
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    description = models.TextField(blank=True)
    version = models.CharField(max_length=32, default="001")

    class Meta:
        verbose_name = "Operational flow"
        verbose_name_plural = "Operational flows"
        ordering = ["supported_what", "code"]
        indexes = [
            models.Index(fields=["status"], name="exchange_ag_status_8c0478_idx"),
            models.Index(
                fields=["supported_what"],
                name="exchange_ag_support_1da89f_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.engine})"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    def is_referenced_by_flow_profiles(self) -> bool:
        for profile in FlowProfile.objects.all().only("options"):
            data_ingestion = profile.options.get("data_ingestion")
            if not isinstance(data_ingestion, dict):
                continue
            for item in data_ingestion.values():
                if isinstance(item, dict) and item.get("flow") == self.code:
                    return True
        return False

    def clean(self):
        super().clean()
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None and original.is_referenced_by_flow_profiles():
                locked_fields = {
                    "code": original.code,
                    "engine": original.engine,
                    "deployment_name": original.deployment_name,
                    "supported_what": original.supported_what,
                }
                errors = {}
                for field_name, original_value in locked_fields.items():
                    if getattr(self, field_name) != original_value:
                        errors[field_name] = _(
                            "This field cannot be changed while the operational "
                            "flow is referenced by flow profiles. Create a new "
                            "flow version instead."
                        )
                if errors:
                    raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_referenced_by_flow_profiles():
            raise ValidationError(
                _("Operational flows referenced by flow profiles cannot be deleted.")
            )
        return super().delete(*args, **kwargs)


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
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None and original.contracts.exists():
                locked_fields = {
                    "code": original.code,
                    "schema_version": original.schema_version,
                    "options": original.options,
                }
                errors = {}
                for field_name, original_value in locked_fields.items():
                    if getattr(self, field_name) != original_value:
                        errors[field_name] = _(
                            "This field cannot be changed while the flow profile "
                            "is associated with contracts. Create a new version "
                            "instead."
                        )
                if errors:
                    raise ValidationError(errors)

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
                if block_key == "data_ingestion":
                    flow_code = item.get("flow")
                    flow = OperationalFlow.objects.filter(code=flow_code).first()
                    if flow is None:
                        option_errors.append(
                            f"{block_key}.{item_key}.flow references unknown "
                            f"operational flow: {flow_code}"
                        )
                    elif flow.supported_what != item_key:
                        option_errors.append(
                            f"{block_key}.{item_key}.flow supports "
                            f"{flow.supported_what}, not {item_key}."
                        )
                    elif flow.status == OperationalFlow.Status.DISABLED:
                        option_errors.append(
                            f"{block_key}.{item_key}.flow references disabled "
                            f"operational flow: {flow_code}"
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
    governing_authority = models.ForeignKey(
        Authority,
        on_delete=models.PROTECT,
        related_name="contracts",
        blank=True,
        null=True,
        help_text="Governing authority with read-only visibility of the contract.",
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
        client_agency_id = getattr(self, "client_agency_id", None)
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

        lot_agency_id = getattr(getattr(self, "lot", None), "agency_id", None)
        if lot_agency_id and client_agency_id and lot_agency_id != client_agency_id:
            errors["lot"] = _("Selected lot does not belong to the client agency.")

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
            "governing_authority_id",
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
    logical_indicator = models.ForeignKey(
        Indicator,
        on_delete=models.PROTECT,
        related_name="contract_links",
        blank=True,
        null=True,
        help_text=(
            "Stable target-model indicator. The legacy indicator definition is "
            "retained temporarily for API v1 compatibility."
        ),
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
            ),
            models.UniqueConstraint(
                fields=["contract", "logical_indicator"],
                condition=models.Q(logical_indicator__isnull=False),
                name="unique_contract_logical_indicator",
            ),
        ]

    def __str__(self) -> str:
        indicator_code = (
            self.logical_indicator.code
            if self.logical_indicator_id
            else self.indicator.code
        )
        return f"{self.contract.contract_code}:{indicator_code}"

    def clean(self):
        super().clean()
        if not self.pk:
            return
        original = type(self).objects.filter(pk=self.pk).first()
        if original is None:
            return
        protected = original.revision_configurations.exclude(
            revision__status=ContractConfigurationRevision.Status.DRAFT
        )
        if protected.exists() and (
            self.contract_id != original.contract_id
            or self.logical_indicator_id != original.logical_indicator_id
            or self.indicator_id != original.indicator_id
        ):
            raise ValidationError(
                _("Indicators referenced by approved revisions are immutable.")
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.revision_configurations.exclude(
            revision__status=ContractConfigurationRevision.Status.DRAFT
        ).exists():
            raise ValidationError(
                _("Indicators referenced by approved revisions cannot be deleted.")
            )
        return super().delete(*args, **kwargs)


class ContractConfigurationRevision(TimeStampedModel):
    """Complete temporal snapshot of a contract's technical configuration."""

    SNAPSHOT_SCHEMA_VERSION = "canonical-json-v1"

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        WITHDRAWN = "withdrawn", _("Withdrawn")

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="configuration_revisions",
    )
    revision_number = models.PositiveIntegerField()
    code = models.CharField(max_length=128, unique=True)
    processing_profile_version = models.ForeignKey(
        ProcessingProfileVersion,
        on_delete=models.PROTECT,
        related_name="contract_revisions",
    )
    valid_from = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    change_reason = models.TextField()
    replaces_revision = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="replacement_revisions",
        null=True,
        blank=True,
    )
    snapshot_schema_version = models.CharField(
        max_length=32,
        default=SNAPSHOT_SCHEMA_VERSION,
    )
    configuration_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_checksum = models.CharField(max_length=71, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_configuration_revisions_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_configuration_revisions_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="contract_configuration_revisions_withdrawn",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Contract configuration revision"
        verbose_name_plural = "Contract configuration revisions"
        ordering = ["contract__contract_code", "valid_from", "revision_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "revision_number"],
                name="unique_contract_revision_number",
            ),
            models.UniqueConstraint(
                fields=["contract", "valid_from"],
                condition=models.Q(status="approved"),
                name="unique_approved_contract_revision_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["contract", "status", "valid_from"],
                name="ix_contract_rev_resolution",
            )
        ]

    def __str__(self) -> str:
        return f"{self.contract.contract_code}:{self.code} ({self.status})"

    def clean(self):
        super().clean()
        self.code = (self.code or "").strip()
        self.change_reason = (self.change_reason or "").strip()
        errors = {}
        if not self.code:
            errors["code"] = _("Revision code is required.")
        if not self.change_reason:
            errors["change_reason"] = _("Change reason is required.")
        if self.replaces_revision_id:
            if self.replaces_revision_id == self.pk:
                errors["replaces_revision"] = _("A revision cannot replace itself.")
            elif self.replaces_revision.contract_id != self.contract_id:
                errors["replaces_revision"] = _(
                    "The replaced revision must belong to the same contract."
                )
        if not self.pk and self.status != self.Status.DRAFT:
            errors["status"] = _(
                "New revisions must start as draft and use the lifecycle service."
            )
        if self.status == self.Status.DRAFT:
            if self.configuration_snapshot:
                errors["configuration_snapshot"] = _(
                    "Draft revisions cannot store an approved snapshot."
                )
            if self.snapshot_checksum:
                errors["snapshot_checksum"] = _(
                    "Draft revisions cannot store an approved checksum."
                )
        if self.snapshot_checksum:
            checksum_value = self.snapshot_checksum.removeprefix("sha256:")
            if (
                not self.snapshot_checksum.startswith("sha256:")
                or len(checksum_value) != 64
                or any(
                    character not in "0123456789abcdef" for character in checksum_value
                )
            ):
                errors["snapshot_checksum"] = _(
                    "Snapshot checksum must use sha256:<64 lowercase hex characters>."
                )
        if self.status == self.Status.APPROVED:
            if (
                not isinstance(self.configuration_snapshot, dict)
                or not self.configuration_snapshot
            ):
                errors["configuration_snapshot"] = _(
                    "Approved revisions require a configuration snapshot."
                )
            if not self.snapshot_checksum:
                errors["snapshot_checksum"] = _(
                    "Approved revisions require a snapshot checksum."
                )
            if self.snapshot_schema_version != self.SNAPSHOT_SCHEMA_VERSION:
                errors["snapshot_schema_version"] = _(
                    "Unsupported revision snapshot schema version."
                )
            if self.approved_at is None:
                errors["approved_at"] = _(
                    "Approved revisions require an approval timestamp."
                )
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).first()
            if original is not None:
                if self.status != original.status:
                    errors["status"] = _(
                        "Use the contract revision lifecycle service to change status."
                    )
                if original.status != self.Status.DRAFT:
                    immutable_fields = (
                        "contract_id",
                        "revision_number",
                        "code",
                        "processing_profile_version_id",
                        "valid_from",
                        "change_reason",
                        "replaces_revision_id",
                        "snapshot_schema_version",
                        "configuration_snapshot",
                        "snapshot_checksum",
                    )
                    if any(
                        getattr(self, field) != getattr(original, field)
                        for field in immutable_fields
                    ):
                        errors["__all__"] = _(
                            "Approved or withdrawn revisions are immutable."
                        )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        status = self.status
        if self.pk:
            status = type(self).objects.values_list("status", flat=True).get(pk=self.pk)
        if status != self.Status.DRAFT:
            raise ValidationError(_("Only draft revisions can be deleted."))
        return super().delete(*args, **kwargs)


class ContractInputSelection(models.Model):
    revision = models.ForeignKey(
        ContractConfigurationRevision,
        on_delete=models.CASCADE,
        related_name="input_selections",
    )
    processing_profile_input_flow = models.ForeignKey(
        ProcessingProfileInputFlow,
        on_delete=models.PROTECT,
        related_name="contract_input_selections",
    )

    class Meta:
        verbose_name = "Contract input selection"
        verbose_name_plural = "Contract input selections"
        ordering = ["processing_profile_input_flow__dataset__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "processing_profile_input_flow"],
                name="unique_contract_revision_input",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.pk:
            original_revision_id = (
                type(self).objects.values_list("revision_id", flat=True).get(pk=self.pk)
            )
            original_status = ContractConfigurationRevision.objects.values_list(
                "status", flat=True
            ).get(pk=original_revision_id)
            if original_status != ContractConfigurationRevision.Status.DRAFT:
                errors["revision"] = _(
                    "Inputs of an approved or withdrawn revision are immutable."
                )
        if self.revision_id:
            revision_status = ContractConfigurationRevision.objects.values_list(
                "status", flat=True
            ).get(pk=self.revision_id)
            if revision_status != ContractConfigurationRevision.Status.DRAFT:
                errors["revision"] = _(
                    "Inputs can be changed only while the revision is draft."
                )
        if self.revision_id and self.processing_profile_input_flow_id:
            if (
                self.processing_profile_input_flow.processing_profile_version_id
                != self.revision.processing_profile_version_id
            ):
                errors["processing_profile_input_flow"] = _(
                    "The input must belong to the revision processing profile."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            ContractConfigurationRevision.objects.select_for_update().get(
                pk=self.revision_id
            )
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            status = (
                ContractConfigurationRevision.objects.select_for_update()
                .values_list("status", flat=True)
                .get(pk=self.revision_id)
            )
            if status != ContractConfigurationRevision.Status.DRAFT:
                raise ValidationError(
                    _("Inputs can be changed only while the revision is draft.")
                )
            return super().delete(*args, **kwargs)


class ContractIndicatorConfiguration(models.Model):
    revision = models.ForeignKey(
        ContractConfigurationRevision,
        on_delete=models.CASCADE,
        related_name="indicator_configurations",
    )
    contract_indicator = models.ForeignKey(
        ContractIndicator,
        on_delete=models.PROTECT,
        related_name="revision_configurations",
    )
    processing_profile_indicator_version = models.ForeignKey(
        ProcessingProfileIndicatorVersion,
        on_delete=models.PROTECT,
        related_name="contract_indicator_configurations",
    )
    thresholds = models.JSONField(default=dict, blank=True)
    aggregation = models.JSONField(default=dict, blank=True)
    penalties = models.JSONField(default=dict, blank=True)
    parameters = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Contract indicator configuration"
        verbose_name_plural = "Contract indicator configurations"
        ordering = ["contract_indicator__logical_indicator__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "contract_indicator"],
                name="unique_revision_contract_indicator",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.pk:
            original_revision_id = (
                type(self).objects.values_list("revision_id", flat=True).get(pk=self.pk)
            )
            original_status = ContractConfigurationRevision.objects.values_list(
                "status", flat=True
            ).get(pk=original_revision_id)
            if original_status != ContractConfigurationRevision.Status.DRAFT:
                errors["revision"] = _(
                    "Indicators of an approved or withdrawn revision are immutable."
                )
        for field_name in ("thresholds", "aggregation", "penalties", "parameters"):
            try:
                setattr(
                    self,
                    field_name,
                    validate_business_configuration(
                        getattr(self, field_name), field_name=field_name
                    ),
                )
            except ValidationError as exc:
                errors[field_name] = exc.messages
        if self.revision_id:
            revision_status = ContractConfigurationRevision.objects.values_list(
                "status", flat=True
            ).get(pk=self.revision_id)
            if revision_status != ContractConfigurationRevision.Status.DRAFT:
                errors["revision"] = _(
                    "Indicators can be changed only while the revision is draft."
                )
        if self.revision_id and self.contract_indicator_id:
            if self.contract_indicator.contract_id != self.revision.contract_id:
                errors["contract_indicator"] = _(
                    "The indicator link must belong to the revision contract."
                )
        if self.revision_id and self.processing_profile_indicator_version_id:
            profile_link = self.processing_profile_indicator_version
            if (
                profile_link.processing_profile_version_id
                != self.revision.processing_profile_version_id
            ):
                errors["processing_profile_indicator_version"] = _(
                    "The indicator version must belong to the revision profile."
                )
            logical_indicator_id = self.contract_indicator.logical_indicator_id
            if (
                logical_indicator_id
                and profile_link.indicator_version.indicator_id != logical_indicator_id
            ):
                errors["processing_profile_indicator_version"] = _(
                    "The technical version must match the contract indicator."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        with transaction.atomic():
            ContractConfigurationRevision.objects.select_for_update().get(
                pk=self.revision_id
            )
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            status = (
                ContractConfigurationRevision.objects.select_for_update()
                .values_list("status", flat=True)
                .get(pk=self.revision_id)
            )
            if status != ContractConfigurationRevision.Status.DRAFT:
                raise ValidationError(
                    _("Indicators can be changed only while the revision is draft.")
                )
            return super().delete(*args, **kwargs)


@receiver(pre_delete, sender=ContractConfigurationRevision)
def protect_non_draft_contract_revision_delete(sender, instance, **kwargs):
    status = ContractConfigurationRevision.objects.values_list("status", flat=True).get(
        pk=instance.pk
    )
    if status != ContractConfigurationRevision.Status.DRAFT:
        raise ValidationError(_("Only draft revisions can be deleted."))


@receiver(pre_delete, sender=ContractInputSelection)
@receiver(pre_delete, sender=ContractIndicatorConfiguration)
def protect_frozen_contract_revision_children(sender, instance, **kwargs):
    status = ContractConfigurationRevision.objects.values_list("status", flat=True).get(
        pk=instance.revision_id
    )
    if status != ContractConfigurationRevision.Status.DRAFT:
        raise ValidationError(
            _("Approved or withdrawn revision content cannot be deleted.")
        )


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

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        REVOKED = "revoked", _("Revoked")
        SYNC_ERROR = "sync_error", _("Sync error")

    class Source(models.TextChoices):
        INVITATION = "invitation", _("Invitation")
        BOOTSTRAP = "bootstrap", _("Bootstrap")
        KEYCLOAK_SYNC = "keycloak_sync", _("Keycloak sync")
        ADMIN_ACTION = "admin_action", _("Admin action")
        MANUAL_MIGRATION = "manual_migration", _("Manual migration")

    agency = models.ForeignKey(
        Agency, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agency_memberships",
    )
    role = models.CharField(max_length=32, choices=Role.choices)
    status = models.CharField(
        max_length=32, choices=Status.choices, default=Status.ACTIVE
    )
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        default=Source.MANUAL_MIGRATION,
    )
    keycloak_group_path = models.CharField(max_length=255, blank=True)
    keycloak_user_id = models.CharField(max_length=255, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_error = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_memberships_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_memberships_updated",
    )
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="agency_memberships_revoked",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)

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
            models.Index(fields=["agency", "status"]),
            models.Index(fields=["user"]),
            models.Index(fields=["user", "status"]),
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
        return self.status == self.Status.ACTIVE and self.role == self.Role.AGENCY_ADMIN

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


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
