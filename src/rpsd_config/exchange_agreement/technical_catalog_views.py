# SPDX-FileCopyrightText: 2025-2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Server-rendered product UI for platform technical catalogs."""

from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import modelform_factory
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from rpsd_config.exchange_agreement.services.validation_bindings import (
    save_dataset_rule,
)
from rpsd_config.exchange_agreement.services.validation_catalog import (
    save_validation_rule,
    save_validation_rule_version,
    transition_validation_rule,
)

from .models import (
    ConfigurationAsset,
    Dataset,
    DatasetSpecification,
    DatasetSpecificationAsset,
    DatasetVersionRule,
    DependencyRequiredDimension,
    FragmentValidationRule,
    Indicator,
    IndicatorDimension,
    IndicatorVersion,
    IndicatorVersionDependency,
    IndicatorVersionInput,
    IndicatorVersionRule,
    InputFlowVersion,
    OrchestrationFlowVersion,
    ProcessingProfileIndicatorVersion,
    ProcessingProfileInputFlow,
    ProcessingProfileVersion,
    RequirementFragment,
    ValidationRule,
    ValidationRuleVersion,
)
from .rbac import resolve_user_agency_scope
from .services.dataset_catalog import (
    deprecate_dataset_specification,
    publish_dataset_specification,
    withdraw_dataset_specification,
)
from .services.flow_catalog import (
    deprecate_input_flow_version,
    deprecate_orchestration_flow_version,
    publish_input_flow_version,
    publish_orchestration_flow_version,
    withdraw_input_flow_version,
    withdraw_orchestration_flow_version,
)
from .services.indicator_catalog import (
    deprecate_indicator_version,
    publish_indicator_version,
    withdraw_indicator_version,
)
from .services.processing_profiles import (
    deprecate_processing_profile,
    publish_processing_profile,
    withdraw_processing_profile,
)
from .services.requirement_fragments import (
    deprecate_requirement_fragment,
    publish_requirement_fragment,
    withdraw_requirement_fragment,
)


class RequirementFragmentCatalogForm(forms.ModelForm):
    locator_path = forms.CharField(
        required=False,
        label="Percorso XPath",
        help_text="Percorso dell'elemento, per esempio //netex:ServiceJourney.",
    )
    namespaces = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Namespace XPath",
        help_text=(
            "Una riga per namespace nel formato prefisso=URI. L'URI identifica "
            "univocamente il vocabolario XML: non e' un link da aprire."
        ),
    )
    table_resource = forms.CharField(
        required=False,
        label="Tabella o risorsa",
        help_text="Nome della tabella/file per locator tabellari, per esempio trips.",
    )
    table_columns = forms.CharField(
        required=False,
        label="Colonna o colonne",
        help_text="Nomi separati da virgola.",
    )

    class Meta:
        model = RequirementFragment
        fields = (
            "dataset_specification",
            "code",
            "name",
            "description",
            "locator_type",
            "result_kind",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        definition = self.instance.locator_definition or {}
        if self.instance.locator_type == RequirementFragment.LocatorType.XPATH:
            self.fields["locator_path"].initial = definition.get("path", "")
            self.fields["namespaces"].initial = "\n".join(
                f"{prefix}={uri}"
                for prefix, uri in definition.get("namespaces", {}).items()
            )
        else:
            self.fields["table_resource"].initial = definition.get("resource", "")
            columns = definition.get("columns", [])
            if definition.get("column"):
                columns = [definition["column"]]
            self.fields["table_columns"].initial = ", ".join(columns)

    def clean(self):
        cleaned = super().clean()
        locator_type = cleaned.get("locator_type")
        result_kind = cleaned.get("result_kind")
        if locator_type == RequirementFragment.LocatorType.XPATH:
            namespaces = {}
            for line in (cleaned.get("namespaces") or "").splitlines():
                if not line.strip():
                    continue
                if "=" not in line:
                    self.add_error(
                        "namespaces", "Usa il formato prefisso=URI su ogni riga."
                    )
                    continue
                prefix, uri = line.split("=", 1)
                namespaces[prefix.strip()] = uri.strip()
            self.instance.locator_definition = {
                "path": (cleaned.get("locator_path") or "").strip(),
                "namespaces": namespaces,
            }
        else:
            columns = [
                item.strip()
                for item in (cleaned.get("table_columns") or "").split(",")
                if item.strip()
            ]
            definition = {"resource": (cleaned.get("table_resource") or "").strip()}
            if result_kind == RequirementFragment.ResultKind.SCALAR_VALUES:
                definition["column"] = columns[0] if columns else ""
            elif columns:
                definition["columns"] = columns
            self.instance.locator_definition = definition
        return cleaned


DatasetForm = modelform_factory(
    Dataset,
    fields=("code", "name", "description", "status"),
)
DatasetSpecificationForm = modelform_factory(
    DatasetSpecification,
    fields=("dataset", "code", "version", "description"),
)
IndicatorForm = modelform_factory(
    Indicator,
    fields=("code", "name", "description", "status"),
)
IndicatorVersionForm = modelform_factory(
    IndicatorVersion,
    fields=(
        "indicator",
        "code",
        "version",
        "description",
        "formula_description",
        "input_schema",
        "output_schema",
        "parameter_schema",
        "execution_engine",
        "execution_reference",
        "artifact_identifier",
    ),
)
InputFlowVersionForm = modelform_factory(
    InputFlowVersion,
    fields=(
        "dataset_specification",
        "code",
        "version",
        "name",
        "description",
        "engine",
        "deployment_name",
        "artifact_identifier",
    ),
)
OrchestrationFlowVersionForm = modelform_factory(
    OrchestrationFlowVersion,
    fields=(
        "code",
        "version",
        "name",
        "description",
        "engine",
        "deployment_name",
        "artifact_identifier",
    ),
)
ProcessingProfileVersionForm = modelform_factory(
    ProcessingProfileVersion,
    fields=(
        "code",
        "version",
        "name",
        "description",
        "orchestration_flow_version",
    ),
)


class IndicatorRuleCatalogForm(forms.ModelForm):
    dimensions = forms.ModelMultipleChoiceField(
        queryset=IndicatorDimension.objects.all(),
        required=False,
        label="Dimensioni interessate",
        help_text=(
            "Obbligatorie per dimension; vietate per calculation. Il KO "
            "non rifiuta il file salvo reject_import."
        ),
    )

    class Meta:
        model = IndicatorVersionRule
        fields = ("indicator_version", "dataset_version_rule", "impact", "dimensions")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["dimensions"].initial = self.instance.affected_dimensions.all()

    def clean(self):
        values = super().clean()
        if bool(values.get("dimensions")) != (values.get("impact") == "dimension"):
            raise ValidationError(
                "dimension richiede dimensioni; calculation non ne ammette."
            )
        return values

    def save(self, commit=True):
        from django.db import transaction

        from rpsd_config.exchange_agreement.models import IndicatorVersionRuleDimension

        if not commit:
            return super().save(commit=False)
        with transaction.atomic():
            binding = super().save(commit=False)
            if binding.pk:
                binding.dimension_links.all().delete()
            binding.save()
            for dimension in self.cleaned_data["dimensions"]:
                IndicatorVersionRuleDimension.objects.create(
                    binding=binding, dimension=dimension
                )
            binding.validate_complete()
            return binding


CATALOGS = {
    "datasets": {
        "label": "Dataset",
        "model": Dataset,
        "form": DatasetForm,
        "description": "Famiglie logiche stabili, come netex o siri-vm.",
    },
    "dataset-specifications": {
        "label": "Specifiche dataset",
        "model": DatasetSpecification,
        "form": DatasetSpecificationForm,
        "description": "Versioni tecniche dei dataset e relativi asset.",
        "transitions": {
            "publish": publish_dataset_specification,
            "deprecate": deprecate_dataset_specification,
            "withdraw": withdraw_dataset_specification,
        },
    },
    "fragments": {
        "label": "Frammenti richiesti",
        "model": RequirementFragment,
        "form": RequirementFragmentCatalogForm,
        "description": "Parti del dataset richieste dagli indicatori.",
        "transitions": {
            "publish": publish_requirement_fragment,
            "deprecate": deprecate_requirement_fragment,
            "withdraw": withdraw_requirement_fragment,
        },
    },
    "indicators": {
        "label": "Indicatori",
        "model": Indicator,
        "form": IndicatorForm,
        "description": "Identita logiche degli indicatori monitorati.",
    },
    "indicator-versions": {
        "label": "Versioni indicatore",
        "model": IndicatorVersion,
        "form": IndicatorVersionForm,
        "description": "Definizioni tecniche e frammenti necessari.",
        "transitions": {
            "publish": publish_indicator_version,
            "deprecate": deprecate_indicator_version,
            "withdraw": withdraw_indicator_version,
        },
    },
    "input-flows": {
        "label": "Flow di input",
        "model": InputFlowVersion,
        "form": InputFlowVersionForm,
        "description": "Riferimenti ai deployment che trattano una specifica.",
        "transitions": {
            "publish": publish_input_flow_version,
            "deprecate": deprecate_input_flow_version,
            "withdraw": withdraw_input_flow_version,
        },
    },
    "orchestration-flows": {
        "label": "Flow orchestratori",
        "model": OrchestrationFlowVersion,
        "form": OrchestrationFlowVersionForm,
        "description": "Riferimenti agli orchestratori generali di contratto.",
        "transitions": {
            "publish": publish_orchestration_flow_version,
            "deprecate": deprecate_orchestration_flow_version,
            "withdraw": withdraw_orchestration_flow_version,
        },
    },
    "processing-profiles": {
        "label": "Profili tecnici",
        "model": ProcessingProfileVersion,
        "form": ProcessingProfileVersionForm,
        "description": "Perimetri di input e indicatori tecnicamente compatibili.",
        "transitions": {
            "publish": publish_processing_profile,
            "deprecate": deprecate_processing_profile,
            "withdraw": withdraw_processing_profile,
        },
    },
}

CATALOGS.update(
    {
        "validation-rules": {
            "label": "Regole di validazione",
            "model": ValidationRule,
            "form": modelform_factory(
                ValidationRule, fields=("code", "name", "description")
            ),
            "description": (
                "Identità riusabili delle regole; le definizioni "
                "appartengono alle versioni."
            ),
        },
        "validation-rule-versions": {
            "label": "Versioni delle regole",
            "model": ValidationRuleVersion,
            "form": modelform_factory(
                ValidationRuleVersion,
                fields=(
                    "rule",
                    "version",
                    "name",
                    "description",
                    "validation_type",
                    "definition",
                    "language_version",
                    "options",
                    "result_contract",
                    "execution_reference",
                ),
            ),
            "description": (
                "Definizione completa, interprete e deployment Prefect "
                "della validazione."
            ),
            "transitions": {"publish": None, "deprecate": None, "withdraw": None},
        },
        "dataset-rule-bindings": {
            "label": "Regole delle versioni dataset",
            "model": DatasetVersionRule,
            "form": modelform_factory(
                DatasetVersionRule,
                fields=("dataset_specification", "rule_version", "import_policy"),
            ),
            "description": (
                "reject_import rifiuta il trasferimento; warn avvisa; "
                "indicator_only vale solo per gli indicatori scelti."
            ),
        },
        "indicator-rule-bindings": {
            "label": "Requisiti degli indicatori",
            "model": IndicatorVersionRule,
            "form": IndicatorRuleCatalogForm,
            "description": (
                "calculation impedisce il calcolo sulle entità coinvolte; "
                "dimension perde la sola disaggregazione."
            ),
        },
        "indicator-dimensions": {
            "label": "Dimensioni degli indicatori",
            "model": IndicatorDimension,
            "form": modelform_factory(
                IndicatorDimension, fields=("code", "name", "description")
            ),
            "description": "Capacità di disaggregazione, ad esempio Linea e Contratto.",
        },
        "indicator-inputs": {
            "label": "Input delle versioni indicatore",
            "model": IndicatorVersionInput,
            "form": modelform_factory(
                IndicatorVersionInput,
                fields=("indicator_version", "dataset_specification"),
            ),
            "description": (
                "Input necessari anche quando non hanno regole di validazione."
            ),
        },
        "indicator-dependencies": {
            "label": "Dipendenze degli indicatori",
            "model": IndicatorVersionDependency,
            "form": modelform_factory(
                IndicatorVersionDependency, fields=("dependent", "prerequisite")
            ),
            "description": (
                "Prerequisiti necessari, a versione esplicita. Nessun ciclo "
                "o autoriferimento."
            ),
        },
        "dependency-dimensions": {
            "label": "Dimensioni richieste dai dipendenti",
            "model": DependencyRequiredDimension,
            "form": modelform_factory(
                DependencyRequiredDimension, fields=("dependency", "dimension")
            ),
            "description": (
                "Senza righe, il dipendente usa il totale; non tutte le dimensioni."
            ),
        },
    }
)


COMPOSITION_ACTIONS = {
    "add-asset",
    "remove-asset",
    "add-rule",
    "remove-rule",
    "add-fragment",
    "remove-fragment",
    "add-input",
    "remove-input",
    "add-indicator",
    "remove-indicator",
}


def _require_platform_admin(user) -> None:
    scope = resolve_user_agency_scope(user)
    if not (user.is_superuser or scope.is_platform_admin):
        raise PermissionDenied(
            "Solo platform admin o superuser possono gestire i cataloghi."
        )


def _catalog(slug: str) -> dict:
    try:
        return CATALOGS[slug]
    except KeyError as exc:
        raise Http404("Catalogo tecnico non trovato.") from exc


def _style_form(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs.setdefault("class", "form-check-input")
        else:
            field.widget.attrs.setdefault("class", "form-control")
    return form


def _is_editable(instance) -> bool:
    if hasattr(instance, "check_editable"):
        from django.db import transaction

        try:
            with transaction.atomic():
                instance.check_editable()
        except ValidationError:
            return False
    status = getattr(instance, "status", None)
    draft = getattr(getattr(instance, "Status", None), "DRAFT", None)
    return draft is None or status == draft


def _detail_context(slug: str, instance) -> dict:
    context: dict = {}
    if hasattr(instance, "status_events"):
        context["status_events"] = instance.status_events.select_related(
            "changed_by"
        ).order_by("-changed_at", "-id")
    if slug == "dataset-specifications":
        context["asset_links"] = instance.asset_links.select_related(
            "configuration_asset"
        )
        context["available_assets"] = ConfigurationAsset.objects.filter(
            what=instance.dataset.code
        ).order_by("-version")
        context["asset_roles"] = DatasetSpecificationAsset.Role.choices
    elif slug == "fragments":
        context["validation_rules"] = instance.validation_rules.all()
        context["rule_types"] = FragmentValidationRule.RuleType.choices
        context["rule_severities"] = FragmentValidationRule.Severity.choices
    elif slug == "validation-rule-versions":
        context["rule_definition"] = instance.definition
    elif slug == "indicator-versions":
        from rpsd_config.exchange_agreement.services.indicator_dependencies import (
            resolve_indicator_closure,
        )

        try:
            context["indicator_closure"] = resolve_indicator_closure([instance])
        except ValidationError as exc:
            context["closure_error"] = "; ".join(exc.messages)
        context["indicator_bindings"] = instance.rule_bindings.select_related(
            "dataset_version_rule__rule_version__rule",
            "dataset_version_rule__dataset_specification",
        ).prefetch_related("affected_dimensions")
        context["declared_inputs"] = instance.dataset_inputs.select_related(
            "dataset_specification"
        )
        context["required_fragments"] = instance.required_fragments.select_related(
            "dataset_specification"
        )
        context["available_fragments"] = RequirementFragment.objects.filter(
            status=RequirementFragment.Status.PUBLISHED
        ).select_related("dataset_specification")
    elif slug == "processing-profiles":
        context["profile_inputs"] = instance.input_flow_links.select_related(
            "dataset", "input_flow_version__dataset_specification"
        )
        context["available_input_flows"] = InputFlowVersion.objects.filter(
            status=InputFlowVersion.Status.PUBLISHED
        ).select_related("dataset_specification__dataset")
        context["profile_indicators"] = instance.indicator_version_links.select_related(
            "indicator_version__indicator"
        )
        context["available_indicator_versions"] = IndicatorVersion.objects.filter(
            status=IndicatorVersion.Status.PUBLISHED
        ).select_related("indicator")
    return context


def _rule_parameters(request: HttpRequest, rule_type: str) -> dict:
    if rule_type == FragmentValidationRule.RuleType.EXISTS:
        return {}
    if rule_type == FragmentValidationRule.RuleType.NON_EMPTY:
        return {"trim": request.POST.get("trim") == "on"}
    value_keys = {
        FragmentValidationRule.RuleType.ALL_VALUES_IN_SET: "allowed_values",
        FragmentValidationRule.RuleType.CONTAINS_ALL_VALUES: "required_values",
        FragmentValidationRule.RuleType.SET_EQUALS: "expected_values",
    }
    if rule_type not in value_keys:
        raise ValidationError("Tipo di regola non supportato.")
    key = value_keys[rule_type]
    values = [
        value.strip()
        for value in (request.POST.get("rule_values") or "")
        .replace("\n", ",")
        .split(",")
        if value.strip()
    ]
    return {
        key: values,
        "case_sensitive": request.POST.get("case_sensitive") == "on",
        "trim": request.POST.get("trim") == "on",
    }


def _handle_composition_action(request: HttpRequest, slug: str, instance) -> bool:
    action = request.POST.get("action", "")
    if slug == "dataset-specifications" and action == "add-asset":
        DatasetSpecificationAsset.objects.create(
            dataset_specification=instance,
            configuration_asset=get_object_or_404(
                ConfigurationAsset, pk=request.POST.get("asset_id")
            ),
            role=request.POST.get("role"),
            required=request.POST.get("required") == "on",
        )
    elif slug == "dataset-specifications" and action == "remove-asset":
        get_object_or_404(instance.asset_links, pk=request.POST.get("link_id")).delete()
    elif slug == "fragments" and action == "add-rule":
        rule_type = request.POST.get("rule_type", "")
        FragmentValidationRule.objects.create(
            requirement_fragment=instance,
            rule_type=rule_type,
            rule_version=1,
            parameters=_rule_parameters(request, rule_type),
            severity=request.POST.get("severity"),
        )
    elif slug == "fragments" and action == "remove-rule":
        get_object_or_404(
            instance.validation_rules, pk=request.POST.get("rule_id")
        ).delete()
    elif slug == "indicator-versions" and action == "add-fragment":
        fragment = get_object_or_404(
            RequirementFragment, pk=request.POST.get("fragment_id")
        )
        instance.required_fragments.add(fragment)
    elif slug == "indicator-versions" and action == "remove-fragment":
        instance.required_fragments.remove(request.POST.get("fragment_id"))
    elif slug == "processing-profiles" and action == "add-input":
        flow = get_object_or_404(
            InputFlowVersion.objects.select_related("dataset_specification__dataset"),
            pk=request.POST.get("input_flow_id"),
        )
        ProcessingProfileInputFlow.objects.create(
            processing_profile_version=instance,
            dataset=flow.dataset_specification.dataset,
            input_flow_version=flow,
        )
    elif slug == "processing-profiles" and action == "remove-input":
        get_object_or_404(
            instance.input_flow_links, pk=request.POST.get("link_id")
        ).delete()
    elif slug == "processing-profiles" and action == "add-indicator":
        ProcessingProfileIndicatorVersion.objects.create(
            processing_profile_version=instance,
            indicator_version=get_object_or_404(
                IndicatorVersion, pk=request.POST.get("indicator_version_id")
            ),
            proposed_by_default=request.POST.get("proposed_by_default") == "on",
        )
    elif slug == "processing-profiles" and action == "remove-indicator":
        get_object_or_404(
            instance.indicator_version_links, pk=request.POST.get("link_id")
        ).delete()
    else:
        return False
    return True


@login_required
def technical_catalog_index_page(request: HttpRequest) -> HttpResponse:
    _require_platform_admin(request.user)
    cards = [
        {
            "slug": slug,
            "label": config["label"],
            "description": config["description"],
            "count": config["model"].objects.count(),
        }
        for slug, config in CATALOGS.items()
    ]
    return render(
        request,
        "exchange_agreement/technical_catalog_index.html",
        {"catalog_cards": cards},
    )


@login_required
@require_http_methods(["GET", "POST"])
def technical_catalog_list_page(
    request: HttpRequest, catalog_slug: str
) -> HttpResponse:
    _require_platform_admin(request.user)
    config = _catalog(catalog_slug)
    form = _style_form(config["form"](request.POST or None))
    if request.method == "POST" and form.is_valid():
        try:
            instance = form.save(commit=False)
            if isinstance(instance, ValidationRuleVersion):
                instance = save_validation_rule_version(instance, actor=request.user)
            elif isinstance(instance, ValidationRule):
                instance = save_validation_rule(instance, actor=request.user)
            elif isinstance(instance, DatasetVersionRule):
                instance = save_dataset_rule(instance, actor=request.user)
            else:
                instance = form.save()
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect(
                "exchange_agreement:technical-catalog-detail",
                catalog_slug=catalog_slug,
                object_id=instance.pk,
            )
    return render(
        request,
        "exchange_agreement/technical_catalog_list.html",
        {
            "catalog_slug": catalog_slug,
            "catalog": config,
            "objects": config["model"].objects.all(),
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def technical_catalog_detail_page(
    request: HttpRequest,
    catalog_slug: str,
    object_id: int,
) -> HttpResponse:
    _require_platform_admin(request.user)
    config = _catalog(catalog_slug)
    instance = get_object_or_404(config["model"], pk=object_id)
    error_message = ""
    success_message = ""
    form = _style_form(config["form"](instance=instance))

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "save":
                if not _is_editable(instance):
                    raise ValidationError(
                        "L'oggetto pubblicato e' immutabile: crea una nuova versione."
                    )
                form = _style_form(config["form"](request.POST, instance=instance))
                if form.is_valid():
                    if catalog_slug == "validation-rule-versions":
                        instance = save_validation_rule_version(
                            form.save(commit=False), actor=request.user
                        )
                    elif catalog_slug == "validation-rules":
                        instance = save_validation_rule(
                            form.save(commit=False), actor=request.user
                        )
                    elif catalog_slug == "dataset-rule-bindings":
                        instance = save_dataset_rule(
                            form.save(commit=False), actor=request.user
                        )
                    else:
                        instance = form.save()
                    success_message = "Modifiche salvate."
                else:
                    error_message = "Correggi i campi evidenziati."
            elif catalog_slug == "validation-rule-versions" and action in config.get(
                "transitions", {}
            ):
                instance = transition_validation_rule(
                    instance,
                    target_status={
                        "publish": "published",
                        "deprecate": "deprecated",
                        "withdraw": "withdrawn",
                    }[action],
                    actor=request.user,
                    reason=request.POST.get("reason", ""),
                )
                success_message = "Stato aggiornato correttamente."
            elif action in config.get("transitions", {}):
                instance = config["transitions"][action](instance, actor=request.user)
                success_message = "Stato aggiornato correttamente."
            elif action in COMPOSITION_ACTIONS and not _is_editable(instance):
                raise ValidationError(
                    "L'oggetto pubblicato e' immutabile: crea una nuova versione."
                )
            elif _handle_composition_action(request, catalog_slug, instance):
                success_message = "Composizione aggiornata."
            else:
                raise ValidationError("Azione catalogo non supportata.")
        except (ValidationError, ValueError) as exc:
            error_message = " ".join(getattr(exc, "messages", [str(exc)]))
        instance.refresh_from_db()
        if not error_message:
            form = _style_form(config["form"](instance=instance))

    return render(
        request,
        "exchange_agreement/technical_catalog_detail.html",
        {
            "catalog_slug": catalog_slug,
            "catalog": config,
            "object": instance,
            "form": form,
            "is_editable": _is_editable(instance),
            "error_message": error_message,
            "success_message": success_message,
            **_detail_context(catalog_slug, instance),
        },
    )
