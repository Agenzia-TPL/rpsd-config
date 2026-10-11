# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Versioned rule catalog with application-level immutable writes."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.utils import timezone

from rpsd_config.exchange_agreement.models import TimeStampedModel
from rpsd_config.exchange_agreement.services.validation_registry import (
    validate_prefect_reference,
    validate_rule_definition,
)


def current_related(instance, field_name):
    """Refresh related state, locking it inside a composition transaction."""
    field = instance._meta.get_field(field_name)
    queryset = field.related_model.objects.all()
    if connection.in_atomic_block:
        queryset = queryset.select_for_update()
    return queryset.get(pk=getattr(instance, field.attname))


class RuleIdentityQuerySet(models.QuerySet):
    """Keep stable rule codes from being changed through bulk operations."""

    def update(self, **kwargs):
        if "code" in kwargs:
            raise ValidationError(
                "Rule codes are immutable.", code="immutable_rule_code"
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if "code" in fields:
            raise ValidationError(
                "Rule codes are immutable.", code="immutable_rule_code"
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)


class ValidationRule(TimeStampedModel):
    """Stable logical identity of a validation rule."""

    code = models.SlugField(max_length=96, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    objects = RuleIdentityQuerySet.as_manager()

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code

    def clean(self):
        super().clean()
        if (
            self.pk
            and type(self).objects.filter(pk=self.pk).exclude(code=self.code).exists()
        ):
            raise ValidationError({"code": "Rule codes are immutable."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            type(self).objects.select_for_update().get(pk=self.pk)
        self.full_clean()
        return super().save(*args, **kwargs)


class RuleVersionQuerySet(models.QuerySet):
    """Reject bulk writes that bypass validation, freeze or lifecycle audit."""

    def update(self, **kwargs):
        raise ValidationError("Use the rule catalog service.", code="immutable_version")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk rule updates are not supported.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Create rule versions individually through validation.")

    @transaction.atomic
    def delete(self):
        if any(v.status != "draft" for v in self.select_for_update()):
            raise ValidationError(
                "Only draft rules can be deleted.", code="immutable_version"
            )
        return super().delete()


class ValidationRuleVersion(TimeStampedModel):
    """A complete rule definition pinned to one editorial version."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        DEPRECATED = "deprecated", "Deprecated"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class ResultContract(models.TextChoices):
        VIOLATING_ENTITIES = (
            "violating_entities",
            "Non-conforming entities (empty = pass)",
        )
        BOOLEAN_ASSERTION = "boolean_assertion", "Boolean assertion"
        STRUCTURED_REPORT = "structured_report", "Structured report"

    rule = models.ForeignKey(
        ValidationRule, on_delete=models.PROTECT, related_name="versions"
    )
    version = models.CharField(max_length=32)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    validation_type = models.CharField(max_length=32)
    definition = models.TextField(blank=True)
    language_version = models.CharField(max_length=16, blank=True)
    options = models.JSONField(default=dict, blank=True)
    result_contract = models.CharField(
        max_length=32,
        choices=ResultContract.choices,
        default=ResultContract.VIOLATING_ENTITIES,
    )
    execution_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Prefect flow/deployment for validation, distinct from calculation."
        ),
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="validation_rules_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    objects = RuleVersionQuerySet.as_manager()
    SEMANTIC_FIELDS = (
        "rule_id",
        "version",
        "name",
        "description",
        "validation_type",
        "definition",
        "language_version",
        "options",
        "result_contract",
        "execution_reference",
    )

    class Meta:
        ordering = ["rule__code", "version"]
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "version"], name="uniq_validation_rule_version"
            )
        ]
        indexes = [
            models.Index(fields=["rule", "status"], name="ix_validation_rule_status")
        ]

    def __str__(self) -> str:
        return f"{self.rule.code}@{self.version}"

    def validate_for_publication(self) -> None:
        """Check the declared interpreter and Prefect reference locally."""
        validate_rule_definition(
            validation_type=self.validation_type,
            definition=self.definition,
            language_version=self.language_version,
            options=self.options,
            result_contract=self.result_contract,
        )
        validate_prefect_reference(self.execution_reference)

    def clean(self):
        super().clean()
        if not isinstance(self.options, dict):
            raise ValidationError({"options": "Options must be an object."})
        if not self.pk:
            if (
                self.status != self.Status.DRAFT
                or self.published_at is not None
                or self.published_by_id is not None
            ):
                raise ValidationError({"status": "New versions must start as draft."})
            return
        original = type(self).objects.get(pk=self.pk)
        if (
            self.status != original.status
            or self.published_at != original.published_at
            or self.published_by_id != original.published_by_id
        ):
            raise ValidationError("Use the audited lifecycle service.")
        if original.status != self.Status.DRAFT and any(
            getattr(self, key) != getattr(original, key) for key in self.SEMANTIC_FIELDS
        ):
            raise ValidationError(
                "Published rules are immutable.", code="immutable_version"
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            type(self).objects.select_for_update().get(pk=self.pk)
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        if (
            type(self).objects.select_for_update().get(pk=self.pk).status
            != self.Status.DRAFT
        ):
            raise ValidationError(
                "Only draft rules can be deleted.", code="immutable_version"
            )
        return super().delete(*args, **kwargs)


class RuleAuditQuerySet(models.QuerySet):
    """Audit rows are append-only through normal application entry points."""

    def update(self, **kwargs):
        raise ValidationError("Rule audit events are immutable.")

    def delete(self):
        raise ValidationError("Rule audit events are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Rule audit events are immutable.")


class ValidationRuleStatusEvent(models.Model):
    """Append-only transition evidence."""

    rule_version = models.ForeignKey(
        ValidationRuleVersion, on_delete=models.PROTECT, related_name="status_events"
    )
    from_status = models.CharField(max_length=16)
    to_status = models.CharField(
        max_length=16, choices=ValidationRuleVersion.Status.choices
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT
    )
    changed_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField(blank=True)
    objects = RuleAuditQuerySet.as_manager()

    class Meta:
        ordering = ["changed_at", "pk"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Rule audit events are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Rule audit events are immutable.")


@receiver(pre_delete, sender=ValidationRuleVersion)
def protect_frozen_rule_delete(sender, instance, **kwargs):
    """Cover cascades and admin bulk deletion as well as instance deletion."""
    if instance.status != ValidationRuleVersion.Status.DRAFT:
        raise ValidationError("Only draft rules can be deleted.")


@receiver(pre_delete, sender=ValidationRuleStatusEvent)
def protect_rule_audit_delete(sender, instance, **kwargs):
    """Keep evidence even when a collector tries a cascade."""
    raise ValidationError("Rule audit events are immutable.")


class CompositionQuerySet(models.QuerySet):
    """Make validated instance services the only composition write boundary."""

    def update(self, **kwargs):
        raise ValidationError("Use validated composition services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Bulk composition creation bypasses validation.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Bulk composition updates bypass validation.")

    @transaction.atomic
    def delete(self):
        # Signals also cover collector-driven cascades.
        for instance in self.select_for_update():
            instance.check_editable()
        return super().delete()


class FrozenComposition(models.Model):
    """Validate and freeze child rows against the actual locked owner's status."""

    objects = CompositionQuerySet.as_manager()
    OWNER_FIELD = "indicator_version"

    class Meta:
        abstract = True

    def check_editable(self) -> None:
        owner_field = self._meta.get_field(self.OWNER_FIELD)
        owner_model = owner_field.related_model
        ids = {getattr(self, owner_field.attname)}
        if self.pk:
            old_id = (
                type(self)
                .objects.values_list(owner_field.attname, flat=True)
                .get(pk=self.pk)
            )
            ids.add(old_id)
        for owner in (
            owner_model.objects.select_for_update().filter(pk__in=ids).order_by("pk")
        ):
            if owner.status != "draft":
                raise ValidationError(
                    "Published composition is immutable.", code="immutable_binding"
                )

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.check_editable()
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        self.check_editable()
        return super().delete(*args, **kwargs)


class DatasetVersionRule(FrozenComposition):
    """Rule applicability and admission policy for one technical dataset version."""

    class ImportPolicy(models.TextChoices):
        REJECT_IMPORT = "reject_import", "Reject the transfer"
        WARN = "warn", "Accept with dataset warning"
        INDICATOR_ONLY = "indicator_only", "Run only for selected indicators"

    OWNER_FIELD = "dataset_specification"
    dataset_specification = models.ForeignKey(
        "exchange_agreement.DatasetSpecification",
        on_delete=models.PROTECT,
        related_name="rule_bindings",
    )
    rule_version = models.ForeignKey(
        ValidationRuleVersion, on_delete=models.PROTECT, related_name="dataset_bindings"
    )
    import_policy = models.CharField(max_length=16, choices=ImportPolicy.choices)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_dataset_rule_bindings",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_specification", "rule_version"],
                name="uniq_dataset_version_rule",
            )
        ]
        ordering = [
            "dataset_specification__code",
            "rule_version__rule__code",
            "rule_version__version",
        ]

    def check_editable(self) -> None:
        # Append-only applicability does not change a published dataset's base policy.
        specification = (
            self._meta.get_field("dataset_specification")
            .related_model.objects.select_for_update()
            .get(pk=self.dataset_specification_id)
        )
        if (
            not self.pk
            and specification.status == "published"
            and self.import_policy == self.ImportPolicy.INDICATOR_ONLY
            and current_related(self, "rule_version").status == "published"
        ):
            return
        super().check_editable()

    def clean(self):
        super().clean()
        if not self.rule_version_id or not self.dataset_specification_id:
            return
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if (
                self.created_by_id != original.created_by_id
                or self.created_at != original.created_at
            ):
                raise ValidationError(
                    "Binding creation provenance is immutable.",
                    code="immutable_binding",
                )
        spec = current_related(self, "dataset_specification")
        rule = current_related(self, "rule_version")
        if rule.status != "published":
            raise ValidationError(
                "Only published rules can be associated.", code="unpublished_rule"
            )
        rule.validate_for_publication()
        from rpsd_config.exchange_agreement.services.validation_registry import (
            CAPABILITIES,
        )

        fmt = spec.metadata.get("format") if isinstance(spec.metadata, dict) else None
        if fmt is None and (
            spec.dataset.code == "netex" or spec.dataset.code.startswith("siri-")
        ):
            fmt = "xml"
        if fmt not in CAPABILITIES[rule.validation_type].file_formats:
            raise ValidationError(
                "Rule interpreter does not support this dataset format.",
                code="unsupported_rule_format",
            )

        if rule.validation_type == "xsd_bundle":
            from rpsd_config.exchange_agreement.services.schema_bundles import (
                validate_bundle_rule_asset,
            )

            validate_bundle_rule_asset(spec, rule)


class DimensionIdentityQuerySet(models.QuerySet):
    """Protect codes referenced by published bindings and frozen snapshots."""

    def update(self, **kwargs):
        if "code" in kwargs:
            raise ValidationError(
                "Dimension codes are immutable.", code="immutable_dimension_code"
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if "code" in fields:
            raise ValidationError(
                "Dimension codes are immutable.", code="immutable_dimension_code"
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)


class IndicatorDimension(models.Model):
    """Named analytical capability, not a warehouse result."""

    code = models.SlugField(max_length=96, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    objects = DimensionIdentityQuerySet.as_manager()

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        super().clean()
        if (
            self.pk
            and type(self).objects.filter(pk=self.pk).exclude(code=self.code).exists()
        ):
            raise ValidationError({"code": "Dimension codes are immutable."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            type(self).objects.select_for_update().get(pk=self.pk)
        self.full_clean()
        return super().save(*args, **kwargs)


class IndicatorVersionRule(FrozenComposition):
    """A consumer-specific consequence of a failed dataset rule."""

    class Impact(models.TextChoices):
        CALCULATION = "calculation", "These entities cannot contribute to calculation"
        DIMENSION = "dimension", "Total possible; named disaggregations unavailable"

    indicator_version = models.ForeignKey(
        "exchange_agreement.IndicatorVersion",
        on_delete=models.PROTECT,
        related_name="rule_bindings",
    )
    dataset_version_rule = models.ForeignKey(
        DatasetVersionRule, on_delete=models.PROTECT, related_name="indicator_bindings"
    )
    impact = models.CharField(
        max_length=16,
        choices=Impact.choices,
        help_text=(
            "Indicator failure does not reject the file unless the dataset "
            "policy is reject_import."
        ),
    )
    affected_dimensions = models.ManyToManyField(
        IndicatorDimension,
        through="IndicatorVersionRuleDimension",
        related_name="rule_bindings",
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["indicator_version", "dataset_version_rule"],
                name="uniq_indicator_version_rule",
            )
        ]

    def clean(self):
        super().clean()
        if not self.dataset_version_rule_id:
            return
        dataset_rule = current_related(self, "dataset_version_rule")
        if current_related(dataset_rule, "dataset_specification").status != "published":
            raise ValidationError(
                "The dataset specification must be published.",
                code="unpublished_dataset_specification",
            )
        dataset_rule.full_clean()
        if (
            self.pk
            and self.impact == self.Impact.CALCULATION
            and self.dimension_links.exists()
        ):
            raise ValidationError(
                "Calculation impact must not specify dimensions.",
                code="invalid_impact_dimensions",
            )

    def validate_complete(self) -> None:
        """Validate a complete binding after transactional dimension editing."""
        self.full_clean()
        if self.impact == self.Impact.DIMENSION and not self.dimension_links.exists():
            raise ValidationError(
                "Dimension impact requires affected dimensions.",
                code="invalid_impact_dimensions",
            )


class IndicatorVersionRuleDimension(FrozenComposition):
    binding = models.ForeignKey(
        IndicatorVersionRule, on_delete=models.CASCADE, related_name="dimension_links"
    )
    dimension = models.ForeignKey(
        IndicatorDimension, on_delete=models.PROTECT, related_name="rule_links"
    )
    OWNER_FIELD = "binding"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["binding", "dimension"], name="uniq_indicator_rule_dimension"
            )
        ]

    def check_editable(self) -> None:
        bindings = {self.binding_id}
        if self.pk:
            bindings.add(type(self).objects.get(pk=self.pk).binding_id)
        for binding in IndicatorVersionRule.objects.filter(pk__in=bindings):
            binding.check_editable()

    def clean(self):
        if not self.binding_id:
            return
        if self.binding.impact != "dimension":
            raise ValidationError(
                "Only dimension impacts can name dimensions.",
                code="invalid_impact_dimensions",
            )


class IndicatorVersionInput(FrozenComposition):
    """A required dataset input, even when it has no validation rules."""

    indicator_version = models.ForeignKey(
        "exchange_agreement.IndicatorVersion",
        on_delete=models.PROTECT,
        related_name="dataset_inputs",
    )
    dataset_specification = models.ForeignKey(
        "exchange_agreement.DatasetSpecification",
        on_delete=models.PROTECT,
        related_name="indicator_inputs",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["indicator_version", "dataset_specification"],
                name="uniq_indicator_version_input",
            )
        ]

    def clean(self):
        if not self.dataset_specification_id:
            return
        if current_related(self, "dataset_specification").status != "published":
            raise ValidationError(
                "Indicator inputs require published specifications.",
                code="unpublished_dataset_specification",
            )


@receiver(pre_delete)
def protect_frozen_composition_delete(sender, instance, **kwargs):
    """Protect collector cascades; other domain models are unaffected."""
    if isinstance(instance, FrozenComposition):
        instance.check_editable()


class IndicatorVersionDependency(FrozenComposition):
    """Necessary, version-specific calculation prerequisite."""

    OWNER_FIELD = "dependent"
    dependent = models.ForeignKey(
        "exchange_agreement.IndicatorVersion",
        on_delete=models.PROTECT,
        related_name="dependency_links",
    )
    prerequisite = models.ForeignKey(
        "exchange_agreement.IndicatorVersion",
        on_delete=models.PROTECT,
        related_name="dependent_links",
    )
    required_dimensions = models.ManyToManyField(
        IndicatorDimension, through="DependencyRequiredDimension", blank=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dependent", "prerequisite"], name="uniq_indicator_dependency"
            ),
            models.CheckConstraint(
                condition=~models.Q(dependent=models.F("prerequisite")),
                name="no_indicator_self_dependency",
            ),
        ]

    def check_editable(self) -> None:
        from rpsd_config.exchange_agreement.services.indicator_dependencies import (
            lock_indicator_graph,
        )

        lock_indicator_graph()
        super().check_editable()

    def clean(self):
        super().clean()
        if not self.dependent_id or not self.prerequisite_id:
            return
        if self.dependent_id == self.prerequisite_id:
            raise ValidationError(
                "An indicator cannot depend on itself.",
                code="cyclic_indicator_dependency",
            )
        if current_related(self, "prerequisite").status != "published":
            raise ValidationError(
                "A prerequisite must be published.", code="unpublished_prerequisite"
            )
        from rpsd_config.exchange_agreement.services.indicator_dependencies import (
            would_create_cycle,
        )

        if would_create_cycle(
            self.dependent_id, self.prerequisite_id, exclude_pk=self.pk
        ):
            raise ValidationError(
                "Indicator dependencies must be acyclic.",
                code="cyclic_indicator_dependency",
            )


class DependencyRequiredDimension(FrozenComposition):
    dependency = models.ForeignKey(
        IndicatorVersionDependency,
        on_delete=models.CASCADE,
        related_name="dimension_links",
    )
    dimension = models.ForeignKey(IndicatorDimension, on_delete=models.PROTECT)
    OWNER_FIELD = "dependency"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dependency", "dimension"], name="uniq_dependency_dimension"
            )
        ]

    def check_editable(self) -> None:
        ids = {self.dependency_id}
        if self.pk:
            ids.add(type(self).objects.get(pk=self.pk).dependency_id)
        for dependency in IndicatorVersionDependency.objects.filter(pk__in=ids):
            dependency.check_editable()


class ContractDependencyConfiguration(FrozenComposition):
    """Own revision values for an implicit indicator, without a fake contract link."""

    OWNER_FIELD = "revision"
    revision = models.ForeignKey(
        "exchange_agreement.ContractConfigurationRevision",
        on_delete=models.CASCADE,
        related_name="dependency_configurations",
    )
    indicator_version = models.ForeignKey(
        "exchange_agreement.IndicatorVersion",
        on_delete=models.PROTECT,
        related_name="dependency_configurations",
    )
    thresholds = models.JSONField(default=dict, blank=True)
    parameters = models.JSONField(default=dict, blank=True)
    aggregation = models.JSONField(default=dict, blank=True)
    penalties = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["revision", "indicator_version"],
                name="uniq_revision_dependency_config",
            )
        ]

    def clean(self):
        from rpsd_config.exchange_agreement.services.revision_registry import (
            validate_business_configuration,
        )

        for field in ("thresholds", "parameters", "aggregation", "penalties"):
            validate_business_configuration(getattr(self, field), field_name=field)
        if not self.revision_id or not self.indicator_version_id:
            return
        from rpsd_config.exchange_agreement.services.indicator_dependencies import (
            resolve_indicator_closure,
        )

        roots = [
            config.processing_profile_indicator_version.indicator_version
            for config in self.revision.indicator_configurations.select_related(
                "processing_profile_indicator_version__indicator_version"
            )
        ]
        closure = resolve_indicator_closure(roots)
        effective = {version.pk for version in closure["versions"]}
        if self.indicator_version_id not in effective - closure["root_ids"]:
            raise ValidationError(
                "Only implicit indicators belong in dependency configuration.",
                code="invalid_dependency_configuration",
            )
