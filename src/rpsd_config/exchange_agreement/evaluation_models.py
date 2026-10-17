# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Revision-owned evaluation conditions; no operational execution or results."""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.signals import m2m_changed, pre_delete
from django.dispatch import receiver

from rpsd_config.exchange_agreement.models import (
    ContractConfigurationRevision,
    ContractRevisionIndicator,
    TimeStampedModel,
)


class EvaluationQuerySet(models.QuerySet):
    """Require validated, revision-locked writes, including through models."""

    def update(self, **kwargs):
        raise ValidationError("Use validated evaluation saves.")

    @transaction.atomic
    def bulk_create(self, objs, **kwargs):
        if self.model.OWNER_FIELD == "contract_revision_indicator":
            raise ValidationError("Create evaluation rows individually.")
        if kwargs.get("update_conflicts"):
            raise ValidationError("Through upserts are unsupported.")
        rows = list(objs)
        for row in rows:
            row.save()
        return rows

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Use validated evaluation saves.")


class EvaluationGuard(TimeStampedModel):
    """Serialize all mutations with revision approval and prohibit owner moves."""

    objects = EvaluationQuerySet.as_manager()
    OWNER_FIELD = "contract_revision_indicator"

    class Meta:
        abstract = True

    def owner_id(self):
        if self.OWNER_FIELD == "contract_revision_indicator":
            return self.contract_revision_indicator_id
        target = getattr(self, self.OWNER_FIELD)
        return (
            type(target)
            .objects.values_list("contract_revision_indicator_id", flat=True)
            .get(pk=target.pk)
        )

    def lock_owner(self):
        owner = ContractRevisionIndicator.objects.get(pk=self.owner_id())
        revision = ContractConfigurationRevision.objects.select_for_update().get(
            pk=owner.revision_id
        )
        if revision.status != "draft":
            raise ValidationError("Evaluations can change only in a draft revision.")
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if original.owner_id() != owner.pk:
                raise ValidationError("An evaluation cannot move between indicators.")
        return owner

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.lock_owner()
        if hasattr(self, "period_days") and isinstance(self.period_days, bool):
            raise ValidationError({"period_days": "A boolean is not a day count."})
        self.full_clean()
        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        self.lock_owner()
        return super().delete(*args, **kwargs)


class EvaluationPeriod(models.Model):
    """A business aggregation window, never an execution schedule."""

    class Period(models.TextChoices):
        DAILY = "daily", "Giorno di calendario"
        WEEKLY = "weekly", "Settimana ISO (lunedì–domenica)"
        MONTHLY = "monthly", "Mese di calendario"
        YEARLY = "yearly", "Anno di calendario"
        CONTRACT = "contract", "Intero contratto"
        RANGE = "custom_range", "Dalla data X alla data Y"
        END = "custom_to_contract_end", "Da una data a fine contratto"
        DAYS = "custom_duration_days", "Da una data per N giorni"

    class Partial(models.TextChoices):
        EVALUATE = "evaluate_partial", "Valuta la parte coperta, senza riproporzionare"
        COMPLETE = "complete_only", "Valutabile solo se il periodo è completo"

    period_type = models.CharField(
        max_length=32,
        choices=Period.choices,
        blank=True,
        help_text=(
            "Finestra di aggregazione. Le finestre custom sono singole, non ricorrenti."
        ),
    )
    period_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Data iniziale inclusa, solo per periodi personalizzati.",
    )
    period_end_date = models.DateField(
        null=True, blank=True, help_text="Data finale inclusa, solo per intervallo X–Y."
    )
    period_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="N giorni di calendario: fine = inizio + N − 1.",
    )
    evaluation_timezone = models.CharField(
        max_length=64,
        blank=True,
        help_text=(
            "Fuso IANA esplicito, per esempio Europe/Rome; non modifica lo scheduling."
        ),
    )
    partial_period_policy = models.CharField(
        max_length=24,
        choices=Partial.choices,
        blank=True,
        help_text=(
            "Scelta esplicita per periodi parziali al cambio di "
            "revisione; nessuna soglia riproporzionata."
        ),
    )

    class Meta:
        abstract = True


AGGREGATION_CHOICES = [
    ("sum", "Somma"),
    ("average", "Media"),
    ("minimum", "Minimo"),
    ("maximum", "Massimo"),
    ("count_distinct", "Conteggio distinto"),
    ("already_aggregated", "Risultato già aggregato"),
]


class IndicatorEvaluationThreshold(EvaluationPeriod, EvaluationGuard):
    """One evaluation requirement belonging to a selected revision indicator."""

    contract_revision_indicator = models.ForeignKey(
        ContractRevisionIndicator,
        on_delete=models.CASCADE,
        related_name="evaluation_thresholds",
        help_text=(
            "Indicatore della specifica revisione contrattuale; "
            "non la versione tecnica globale."
        ),
    )
    code = models.SlugField(
        max_length=96, help_text="Codice univoco per questo indicatore della revisione."
    )
    name = models.CharField(max_length=160, help_text="Nome leggibile della soglia.")
    description = models.TextField(
        blank=True, help_text="Significato e riferimento alla clausola contrattuale."
    )
    metric_code = models.CharField(
        max_length=96,
        blank=True,
        help_text=(
            "Metrica numerica dichiarata nell'output dell'esatta versione indicatore."
        ),
    )
    aggregation_method = models.CharField(
        max_length=24,
        choices=AGGREGATION_CHOICES,
        blank=True,
        help_text=(
            "Solo aggregazioni ammesse dalla metrica; una media "
            "di medie non è implicita."
        ),
    )
    group_by_dimensions = models.ManyToManyField(
        "exchange_agreement.IndicatorDimension",
        through="EvaluationThresholdDimension",
        blank=True,
        help_text=(
            "Dimensioni valutate separatamente; vuoto = ambito "
            "complessivo dei parametri."
        ),
    )
    violation_operator = models.CharField(
        max_length=3,
        blank=True,
        choices=[
            ("gt", ">"),
            ("gte", ">="),
            ("lt", "<"),
            ("lte", "<="),
            ("eq", "="),
            ("ne", "!="),
        ],
        help_text="Condizione di violazione: massimo ammesso 3 corrisponde a > 3.",
    )
    limit_value = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Limite nella stessa unità della metrica. Nessuna conversione implicita."
        ),
    )
    severity = models.CharField(
        max_length=8,
        choices=[("warning", "Warning"), ("alert", "Alert")],
        blank=True,
        help_text=(
            "Segnalazione del superamento; non rifiuta dataset né"
            " genera automaticamente una penale."
        ),
    )
    missing_data_policy = models.CharField(
        max_length=16,
        choices=[("not_evaluable", "Non valutabile"), ("anomaly", "Segnala anomalia")],
        blank=True,
        help_text="Un risultato assente non equivale a zero.",
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "Soglia dell'indicatore contrattuale"
        verbose_name_plural = "Soglie degli indicatori contrattuali"
        constraints = [
            models.UniqueConstraint(
                fields=["contract_revision_indicator", "code"],
                name="unique_indicator_evaluation_threshold",
            ),
            models.CheckConstraint(
                condition=models.Q(period_days__isnull=True)
                | models.Q(period_days__gte=1),
                name="threshold_positive_period_days",
            ),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            validate_evaluation,
        )

        validate_evaluation(self, complete=False)


class IndicatorPenalty(EvaluationPeriod, EvaluationGuard):
    """A declared economic condition, not an invoice or calculated result."""

    contract_revision_indicator = models.ForeignKey(
        ContractRevisionIndicator,
        on_delete=models.CASCADE,
        related_name="evaluation_penalties",
        help_text="Indicatore della revisione cui si applica la clausola economica.",
    )
    code = models.SlugField(
        max_length=96,
        help_text="Codice univoco della penale nell'indicatore della revisione.",
    )
    name = models.CharField(
        max_length=160, help_text="Nome leggibile della clausola economica."
    )
    description = models.TextField(
        blank=True, help_text="Descrizione e riferimento al capitolato."
    )
    activation_threshold = models.ForeignKey(
        IndicatorEvaluationThreshold,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activated_penalties",
        help_text=(
            "Una soglia dello stesso indicatore. Periodo e "
            "dimensioni sono ereditati; vuoto = nessuna "
            "attivazione tramite soglia."
        ),
    )
    calculation_method = models.CharField(
        max_length=16,
        choices=[
            ("fixed_amount", "Importo fisso"),
            ("per_unit", "Importo per unità"),
            ("external", "Calcolo esterno"),
        ],
        blank=True,
        help_text="Seleziona la modalità: i campi incompatibili devono restare vuoti.",
    )
    quantity_metric_code = models.CharField(
        max_length=96,
        blank=True,
        help_text=(
            "Quantità economica, anche diversa dalla metrica di "
            "attivazione; stesso periodo e dimensioni."
        ),
    )
    quantity_aggregation_method = models.CharField(
        max_length=24,
        choices=AGGREGATION_CHOICES,
        blank=True,
        help_text="Aggregazione della quantità ammessa dalla versione indicatore.",
    )
    allowance_quantity = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Franchigia: quantità addebitabile = max(0, quantità "
            "− franchigia). Inserire 0 se assente."
        ),
    )
    fixed_amount = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Importo fisso una volta per gruppo/periodo "
            "applicabile; solo modalità fissa."
        ),
    )
    unit_amount = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Euro per unità oltre la franchigia; solo modalità per unità.",
    )
    currency = models.CharField(
        max_length=3,
        choices=[("EUR", "EUR")],
        blank=True,
        help_text="Valuta esplicita; nessuna conversione valutaria automatica.",
    )
    maximum_amount = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        null=True,
        blank=True,
        help_text=(
            "Massimo per singolo periodo/gruppo, non massimale "
            "complessivo del contratto."
        ),
    )
    amount_rounding_mode = models.CharField(
        max_length=16,
        choices=[("half_up", "Commerciale ai centesimi, dopo il massimale")],
        blank=True,
        help_text="Arrotondamento dell'importo finale dopo applicazione del cap.",
    )
    external_execution_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text=(
            "Riferimento dichiarativo al processo esterno, solo "
            "modalità external; non prova la disponibilità "
            "runtime."
        ),
    )
    external_artifact_identifier = models.CharField(
        max_length=512,
        blank=True,
        help_text="Identità versionata del codice dell'esecutore esterno.",
    )
    external_parameter_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Schema chiuso dei parametri del processo esterno, "
            "governato dall'operatore tecnico."
        ),
    )
    external_parameters = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Valori dichiarativi validati rispetto allo schema "
            "dell'esecutore; niente codice eseguibile."
        ),
    )
    group_by_dimensions = models.ManyToManyField(
        "exchange_agreement.IndicatorDimension",
        through="EvaluationPenaltyDimension",
        blank=True,
        help_text="Solo senza soglia: con soglia il raggruppamento è ereditato.",
    )

    class Meta:
        ordering = ["code"]
        verbose_name = "Penale dell'indicatore contrattuale"
        verbose_name_plural = "Penali degli indicatori contrattuali"
        constraints = [
            models.UniqueConstraint(
                fields=["contract_revision_indicator", "code"],
                name="unique_indicator_penalty",
            ),
            models.CheckConstraint(
                condition=models.Q(period_days__isnull=True)
                | models.Q(period_days__gte=1),
                name="penalty_positive_period_days",
            ),
            *[
                models.CheckConstraint(
                    condition=models.Q(**{f"{name}__isnull": True})
                    | models.Q(**{f"{name}__gte": 0}),
                    name=f"penalty_nonnegative_{name}",
                )
                for name in (
                    "fixed_amount",
                    "unit_amount",
                    "allowance_quantity",
                    "maximum_amount",
                )
            ],
        ]

    def __str__(self):
        return self.code

    def clean(self):
        super().clean()
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            validate_evaluation,
        )

        validate_evaluation(self, complete=False)


class EvaluationThresholdDimension(EvaluationGuard):
    """Guard direct through writes as well as the native M:N manager."""

    OWNER_FIELD = "threshold"
    threshold = models.ForeignKey(
        IndicatorEvaluationThreshold, on_delete=models.CASCADE
    )
    dimension = models.ForeignKey(
        "exchange_agreement.IndicatorDimension", on_delete=models.PROTECT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["threshold", "dimension"], name="unique_threshold_dimension"
            )
        ]

    def clean(self):
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            validate_dimensions,
        )

        validate_dimensions(self.threshold, [self.dimension.code])


class EvaluationPenaltyDimension(EvaluationGuard):
    """Explicit through model preserving the same owner lock and invariants."""

    OWNER_FIELD = "penalty"
    penalty = models.ForeignKey(IndicatorPenalty, on_delete=models.CASCADE)
    dimension = models.ForeignKey(
        "exchange_agreement.IndicatorDimension", on_delete=models.PROTECT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["penalty", "dimension"], name="unique_penalty_dimension"
            )
        ]

    def clean(self):
        from rpsd_config.exchange_agreement.services.indicator_evaluations import (
            validate_dimensions,
        )

        validate_dimensions(self.penalty, [self.dimension.code])


@receiver(pre_delete)
def protect_evaluation_deletion(sender, instance, **kwargs):
    if isinstance(instance, EvaluationGuard):
        instance.lock_owner()


@receiver(m2m_changed, sender=EvaluationThresholdDimension)
@receiver(m2m_changed, sender=EvaluationPenaltyDimension)
def protect_evaluation_dimensions(sender, instance, action, reverse, pk_set, **kwargs):
    if not action.startswith("pre_"):
        return
    from rpsd_config.exchange_agreement.services.indicator_evaluations import (
        validate_dimensions,
    )

    is_threshold = sender is EvaluationThresholdDimension
    target_model = IndicatorEvaluationThreshold if is_threshold else IndicatorPenalty
    link_name = "threshold" if is_threshold else "penalty"
    if reverse:
        ids = (
            pk_set
            if pk_set is not None
            else sender.objects.filter(dimension=instance).values_list(
                f"{link_name}_id", flat=True
            )
        )
        targets = target_model.objects.filter(pk__in=ids).order_by(
            "contract_revision_indicator__revision_id", "pk"
        )
    else:
        targets = [instance]
    for target in targets:
        target.lock_owner()
        if action == "pre_add":
            from rpsd_config.exchange_agreement.models import IndicatorDimension

            codes = (
                [instance.code]
                if reverse
                else list(
                    IndicatorDimension.objects.filter(pk__in=pk_set).values_list(
                        "code", flat=True
                    )
                )
            )
            validate_dimensions(target, codes)
