# SPDX-FileCopyrightText: 2026 AGENZIA TPL BACINO CITTA' METROPOLITANA MILANO, MONZA E BRIANZA, LODI, PAVIA
# SPDX-License-Identifier: EUPL-1.2
"""Presentation-only field vocabulary shared by admin and binding forms."""

from dataclasses import dataclass

from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _


@dataclass(frozen=True)
class FieldGuide:
    """Explain a visible field without changing its domain metadata."""

    label: str
    help: str
    group: str = "Configurazione"


def guide(label: str, help_text: str, group: str = "Configurazione") -> FieldGuide:
    """Mark editorial copy for translation."""
    return FieldGuide(_(label), _(help_text), _(group))


IMPORT_POLICY_HELP = _(
    "reject_import rifiuta il file; warn mantiene l’import con un avviso; "
    "le regole indicatore si associano separatamente alla versione indicatore. "
    "Un errore tecnico del validatore "
    "non equivale a una violazione dei dati."
)
IMPACT_HELP = _(
    "calculation: le entità non conformi non contribuiscono al calcolo. "
    "dimension: il totale rimane possibile, ma si perdono le "
    "disaggregazioni indicate. L’impatto non cambia la politica di import."
)
DIMENSIONS_HELP = _(
    "Per dimension indicare le disaggregazioni perse; calculation non ammette "
    "dimensioni. Il file è rifiutato solo se la politica dataset è reject_import. "
    "Queste sono le dimensioni interessate dal KO della regola, non quelle "
    "richieste a un indicatore prerequisito."
)

# Common names share meaning; model-specific differences are explicit below.
FIELDS = {
    "id": guide(
        "ID interno",
        "Identificativo assegnato dal database; non è un codice di business.",
        "Audit e provenienza",
    ),
    "code": guide(
        "Codice",
        "Identificativo tecnico per riferimenti e API. Usare un codice stabile e "
        "univoco; non una descrizione.",
        "Identità e versione",
    ),
    "name": guide(
        "Nome",
        "Nome leggibile per riconoscere l’oggetto negli elenchi; distinto dal codice "
        "tecnico.",
        "Identità e versione",
    ),
    "label": guide(
        "Etichetta",
        "Nome leggibile dell’asset o profilo. Se vuoto, il profilo file mostra il "
        "nome del file.",
        "Identità e versione",
    ),
    "description": guide(
        "Descrizione",
        "Descrivere scopo e ambito. Quando facoltativa, se vuota non aggiunge "
        "vincoli di "
        "validazione.",
        "Identità e versione",
    ),
    "version": guide(
        "Versione",
        "Identifica questa configurazione rispetto alle altre versioni. Dopo "
        "pubblicazione creare una nuova versione per cambiare la configurazione.",
        "Identità e versione",
    ),
    "status": guide(
        "Stato editoriale",
        "draft: bozza modificabile; published: configurazione pubblicata e "
        "congelata; deprecated/withdrawn: non selezionabile per nuove composizioni. "
        "Usare le azioni di transizione. Lo stato non attesta esecuzione dei "
        "processi.",
        "Stato e validità",
    ),
    "created_at": guide(
        "Creazione",
        "Data e ora registrate dal sistema alla creazione; non compilare manualmente.",
        "Audit e provenienza",
    ),
    "updated_at": guide(
        "Ultimo aggiornamento",
        "Data e ora aggiornate dal sistema al salvataggio; non sono la data di "
        "decorrenza.",
        "Audit e provenienza",
    ),
    "created_at_human": guide(
        "Creazione",
        "Data e ora di creazione, mostrate nel fuso orario dell’applicazione.",
        "Audit e provenienza",
    ),
    "updated_at_human": guide(
        "Ultimo aggiornamento",
        "Data e ora dell’ultimo salvataggio, nel fuso orario dell’applicazione.",
        "Audit e provenienza",
    ),
    "published_by": guide(
        "Pubblicata da",
        "Utente registrato dalla pubblicazione. Vuoto prima della pubblicazione; non "
        "indica l’esecutore Prefect.",
        "Audit e provenienza",
    ),
    "published_at": guide(
        "Pubblicazione",
        "Istante registrato dalla pubblicazione; non è la data di avvio del "
        "contratto né un risultato di esecuzione.",
        "Audit e provenienza",
    ),
    "created_by": guide(
        "Creata da",
        "Utente che ha creato l’associazione o la revisione. Nei servizi è "
        "registrato dall’utente autenticato; può essere assente nei dati storici.",
        "Audit e provenienza",
    ),
    "from_status": guide(
        "Stato precedente",
        "Stato prima della transizione registrata; vuoto per l’evento iniziale. È "
        "evidenza di audit.",
        "Audit e provenienza",
    ),
    "to_status": guide(
        "Nuovo stato",
        "Stato risultante dalla transizione registrata; non modificare gli eventi di "
        "audit.",
        "Audit e provenienza",
    ),
    "changed_by": guide(
        "Modificata da",
        "Utente responsabile della transizione; può essere assente per operazioni di "
        "sistema.",
        "Audit e provenienza",
    ),
    "changed_at": guide(
        "Data della transizione",
        "Istante registrato dal servizio per questo evento; distinto dalla decorrenza.",
        "Audit e provenienza",
    ),
    "reason": guide(
        "Motivazione",
        "Spiegazione della transizione registrata. Se vuota non è stata fornita una "
        "motivazione aggiuntiva.",
        "Audit e provenienza",
    ),
    "dataset": guide(
        "Dataset logico",
        "Famiglia dei dati (es. NeTEx). La specifica tecnica e le regole dipendono "
        "dalla versione del dataset.",
        "Identità e versione",
    ),
    "dataset_specification": guide(
        "Versione del dataset",
        "Specifica tecnica esatta del file cui si applica la configurazione. Non "
        "sostituire con una versione diversa per aggiornare una composizione "
        "pubblicata.",
        "Configurazione",
    ),
    "indicator": guide(
        "Indicatore logico",
        "Identità dell’indicatore; algoritmi, schemi e dipendenze appartengono alla "
        "versione.",
        "Identità e versione",
    ),
    "indicator_version": guide(
        "Versione dell’indicatore",
        "Versione esatta cui appartiene questa configurazione. Le sue regole e gli "
        "input includono quelli delle dipendenze transitive.",
        "Configurazione",
    ),
    "format": guide(
        "Formato del dataset",
        "Formato dei file trasferiti: XML, CSV, Excel XLSX o TXT. Determina gli "
        "interpreti compatibili; non è il tipo degli asset tecnici associati.",
        "Configurazione",
    ),
    "validation_type_version": guide(
        "Tipo di validazione e versione del linguaggio",
        "Selezionare una coppia del catalogo supportato. Definisce sintassi e "
        "compatibilità della regola, non certifica che il deployment esterno sia "
        "disponibile. Config non esegue la validazione.",
        "Configurazione",
    ),
    "profile_users": guide(
        "Utilizzato dai profili tecnici",
        "Versioni di profilo che selezionano questo processo. I collegamenti ai "
        "profili autorizzati sono disponibili sopra; modificare la composizione "
        "dalla bozza del profilo, non da questa sezione inversa.",
    ),
    "required_dimensions_display": guide(
        "Dimensioni richieste",
        "Disaggregazioni del prerequisito necessarie all'indicatore dipendente.",
    ),
    "owner_link": guide(
        "Oggetto/versione",
        "Configurazione cui si riferisce l'evento; il collegamento è mostrato "
        "solo se l'utente può consultarne il dettaglio.",
        "Audit e provenienza",
    ),
    "metadata": guide(
        "Metadati della specifica",
        "Oggetto JSON facoltativo per informazioni aggiuntive, ad esempio la "
        "provenienza. Per il formato usare il campo dedicato, non la chiave format.",
        "Configurazione",
    ),
    "formula_description": guide(
        "Descrizione del calcolo",
        "Spiegare formula e unità del risultato; è documentazione, non codice "
        "eseguito da Django.",
        "Configurazione",
    ),
    "input_schema": guide(
        "Schema input",
        "Oggetto JSON che descrive i dati ricevuti dal processo di calcolo. Non è un "
        "contratto amministrativo e non contiene i valori dei parametri della "
        "revisione.",
        "Schemi e configurazione",
    ),
    "output_schema": guide(
        "Schema output",
        "Oggetto JSON che descrive il risultato del processo di calcolo; non è un "
        "risultato già calcolato. schema_version=2 dichiara metrics con unità, grana, "
        "dimensioni e aggregazioni ammesse per le soglie; penalty_executor è una "
        "capability tecnica versionata.",
        "Schemi e configurazione",
    ),
    "parameter_schema": guide(
        "Schema dei parametri",
        "Descrive i valori ammessi per questa versione: schema_version=1, "
        "properties, required, allow_extra e tipi scalari "
        "string/boolean/integer/number. {} non impone vincoli sui parametri. I "
        "valori sono nella revisione, separati per ogni dipendenza. schema_version=2 "
        "aggiunge liste omogenee con items/min_items/max_items/unique_items e "
        "reference_namespace per gli ID tecnici. Non inferisce i numeri pubblici "
        "delle linee.",
        "Schemi e configurazione",
    ),
    "execution_engine": guide(
        "Motore di calcolo",
        "Motore dichiarato per il calcolo dell’indicatore. Conservare il valore "
        "tecnico previsto; la pubblicazione verifica i riferimenti locali, non avvia "
        "il motore.",
        "Processi e riferimenti",
    ),
    "execution_reference": guide(
        "Processo di calcolo Prefect",
        "Riferimento flow/deployment del processo di calcolo (es. "
        "indicators/corse-pde). Richiesto per pubblicare la versione; Django "
        "gestisce il catalogo, senza verificare o eseguire il deployment esterno.",
        "Processi e riferimenti",
    ),
    "artifact_identifier": guide(
        "Identificativo dell’artefatto",
        "Riferimento riproducibile al codice del processo (es. "
        "git:rpsd-flows@revisione). Deve identificare un artefatto reale prima "
        "dell’uso operativo; non carica un file nell’admin.",
        "Processi e riferimenti",
    ),
    "engine": guide(
        "Motore del flusso",
        "Motore dichiarato del flusso. Config registra il riferimento; l’esecuzione "
        "avviene nel servizio esterno.",
        "Processi e riferimenti",
    ),
    "deployment_name": guide(
        "Deployment del flusso",
        "Nome flow/deployment (es. validators/netex-default). Richiesto dalla "
        "pubblicazione; non prova che il deployment esterno sia disponibile.",
        "Processi e riferimenti",
    ),
    "input_flow_version": guide(
        "Flusso di importazione",
        "Flusso pubblicato per la versione del dataset selezionata. L’importazione e "
        "la validazione del file avverranno nel servizio esterno.",
        "Processi e riferimenti",
    ),
    "orchestration_flow_version": guide(
        "Flusso di orchestrazione",
        "Versione pubblicata del processo che coordina la lavorazione del profilo; "
        "non attende implicitamente tutti i trasferimenti per validare un singolo "
        "file.",
        "Processi e riferimenti",
    ),
    "processing_profile_version": guide(
        "Versione del profilo tecnico",
        "Composizione versionata di input, flussi e indicatori ammessi. Selezionare "
        "un profilo pubblicato per la revisione contrattuale.",
        "Configurazione",
    ),
    "proposed_by_default": guide(
        "Proposto per default",
        "Preseleziona l’indicatore nella creazione della bozza. Non lo rende "
        "obbligatorio; la revisione registra la scelta effettiva.",
        "Configurazione",
    ),
    "configuration_asset": guide(
        "Asset di configurazione",
        "File o bundle versionato di supporto alla specifica. Collegare l’asset "
        "esatto, con provenienza e checksum; non sostituisce una regola di "
        "validazione.",
        "Configurazione",
    ),
    "required": guide(
        "Asset obbligatorio",
        "Risorsa già associata indispensabile alle lavorazioni che la utilizzano "
        "(es. XSD o mapper); un manuale può essere accessorio. Non individua "
        "associazioni mancanti e non decide il rifiuto del dataset. Config richiede "
        "un asset attivo per pubblicare la specifica e trasmette il flag al "
        "consumer; i controlli runtime su file persi o corrotti spettano al "
        "sistema esecutivo e non sono eseguiti qui.",
    ),
    "rule": guide(
        "Regola logica",
        "Identità condivisa della regola; definizione e processo appartengono alla "
        "versione, riusabile fra più dataset e indicatori.",
        "Identità e versione",
    ),
    "rule_version": guide(
        "Versione della regola",
        "Definizione esatta pubblicata da applicare. Una bozza non è associabile; il "
        "riferimento viene congelato nella configurazione approvata.",
        "Configurazione",
    ),
    "validation_type": guide(
        "Tipo di validazione",
        "Interprete: xpath e xsd_bundle per xml; csv_expression per csv; "
        "spreadsheet_expression per xlsx; text_expression per txt. Sono contratti di "
        "configurazione del validator esterno; application_state non è disponibile.",
        "Definizione della regola",
    ),
    "definition": guide(
        "Definizione della regola",
        "Stringa completa per l’interprete scelto: XPath seleziona i nodi non "
        "conformi; gli altri tipi usano i descrittori JSON mostrati negli esempi. "
        "Config controlla il contratto dichiarato, senza eseguire la regola sul "
        "dataset.",
        "Definizione della regola",
    ),
    "language_version": guide(
        "Versione del linguaggio",
        "xpath: 1.0, 2.0 o 3.1; xsd_bundle: 1.0; CSV/XLSX/TXT: 1. Usare una "
        "combinazione supportata dal registro e dal futuro validator.",
        "Definizione della regola",
    ),
    "options": guide(
        "Opzioni dell’interprete",
        "Oggetto JSON con le sole chiavi supportate. XPath: namespaces e "
        "empty_context (pass/violation/not_applicable). Per CSV/XLSX/TXT tutte le "
        "opzioni mostrate negli esempi sono esplicite e obbligatorie; xsd_bundle usa "
        "{}.",
        "Definizione della regola",
    ),
    "result_contract": guide(
        "Contratto del risultato",
        "violating_entities: collezione di entità non conformi, vuota = pass. "
        "xsd_bundle usa structured_report. boolean_assertion non è supportato dal "
        "registro corrente. Errori tecnici e violazioni devono restare distinti; la "
        "parzialità dipende dalle entità restituite.",
        "Definizione della regola",
    ),
    "failure_policy": FieldGuide(_("Politica di import"), IMPORT_POLICY_HELP),
    "impact": FieldGuide(_("Impatto del KO sull’indicatore"), IMPACT_HELP),
    "dimensions": FieldGuide(_("Dimensioni interessate"), DIMENSIONS_HELP),
    "dependent": guide(
        "Indicatore dipendente (A)",
        "A dipende dal prerequisito B. A deve essere in bozza per cambiare la "
        "relazione; eredita transitivamente input e regole di B. Vietati "
        "autoriferimenti e cicli.",
        "Configurazione",
    ),
    "prerequisite": guide(
        "Indicatore prerequisito (B)",
        "Versione pubblicata di B usata da A. I parametri di B sono configurati "
        "separatamente nella revisione e non copiati da A.",
        "Configurazione",
    ),
    "dependency": guide(
        "Dipendenza A → B",
        "Relazione diretta fra versione dipendente A e prerequisito B; qui si "
        "dichiarano le dimensioni necessarie di B.",
        "Configurazione",
    ),
    "dimension": guide(
        "Dimensione richiesta al prerequisito",
        "Disaggregazione di B necessaria ad A. Se manca per le entità non conformi, "
        "A non è calcolabile per quelle entità. Distinta dalle dimensioni "
        "interessate da una singola regola.",
        "Configurazione",
    ),
    "contract": guide(
        "Contratto",
        "Contratto amministrativo cui appartiene il dato. Le configurazioni tecniche "
        "e i valori sono versionati nelle sue revisioni.",
        "Identità e versione",
    ),
    "revision": guide(
        "Revisione contrattuale",
        "Configurazione tecnica del contratto valida da una data. I valori si "
        "modificano nel workflow web della bozza; dopo approvazione creare una nuova "
        "revisione.",
        "Identità e versione",
    ),
    "configuration_revision": guide(
        "Revisione pubblicata",
        "Revisione approvata da cui è derivata questa pubblicazione; lo snapshot "
        "storico non cambia con il catalogo.",
        "Identità e versione",
    ),
    "revision_number": guide(
        "Numero della revisione",
        "Progressivo della configurazione nel contratto; non è una versione "
        "dell’indicatore.",
        "Identità e versione",
    ),
    "valid_from": guide(
        "Decorrenza della revisione",
        "Data di inizio validità dentro il periodo contrattuale. L’approvazione è "
        "immediata anche se la decorrenza è futura; il termine è derivato dalla "
        "revisione successiva e dalla fine del contratto.",
        "Stato e validità",
    ),
    "change_reason": guide(
        "Motivazione della revisione",
        "Descrivere perché cambia la configurazione. La bozza è modificabile; la "
        "motivazione viene conservata dopo approvazione.",
        "Configurazione",
    ),
    "replaces_revision": guide(
        "Revisione sostituita",
        "Revisione futura approvata che questa bozza intende sostituire; "
        "facoltativa, non è una cancellazione dello storico.",
        "Stato e validità",
    ),
    "snapshot_schema_version": guide(
        "Formato dello snapshot",
        "Versione tecnica dello schema serializzato (es. canonical-json-v2); "
        "assegnata dal servizio, distinta dalla versione del contratto.",
        "Snapshot e audit",
    ),
    "configuration_snapshot": guide(
        "Snapshot approvato",
        "Configurazione completa congelata all’approvazione: input, chiusura degli "
        "indicatori, regole e valori. Vuoto in bozza. Consultazione, non un "
        "risultato di validazione del dataset.",
        "Snapshot e audit",
    ),
    "snapshot": guide(
        "Snapshot della pubblicazione",
        "Payload storico immutabile, generato dalla pubblicazione. Non modificarlo "
        "per aggiornare la configurazione; creare una nuova revisione/pubblicazione.",
        "Snapshot e audit",
    ),
    "snapshot_checksum": guide(
        "Checksum dello snapshot",
        "Digest deterministico generato dal servizio per controllare integrità e "
        "riproducibilità del payload; non compilare manualmente.",
        "Snapshot e audit",
    ),
    "approved_by": guide(
        "Approvata da",
        "Utente registrato dal servizio di approvazione; vuoto finché la revisione è "
        "in bozza.",
        "Audit e provenienza",
    ),
    "approved_at": guide(
        "Approvazione",
        "Istante dell’approvazione; una revisione approvata con decorrenza futura "
        "non ritorna in bozza.",
        "Audit e provenienza",
    ),
    "withdrawn_by": guide(
        "Ritirata da",
        "Utente registrato dal ritiro della revisione futura; vuoto se non ritirata.",
        "Audit e provenienza",
    ),
    "withdrawn_at": guide(
        "Ritiro",
        "Istante del ritiro registrato; il ritiro conserva snapshot e storico.",
        "Audit e provenienza",
    ),
    "withdrawal_reason": guide(
        "Motivazione del ritiro",
        "Motivazione obbligatoria del ritiro di una revisione futura, registrata dal "
        "workflow autorizzato.",
        "Audit e provenienza",
    ),
    "processing_profile_indicator_version": guide(
        "Indicatore ammesso dal profilo",
        "Associazione fra profilo tecnico e versione dell’indicatore, coerente con "
        "la revisione che seleziona la versione.",
        "Configurazione",
    ),
    "processing_profile_input_flow": guide(
        "Input ammesso dal profilo",
        "Input e flusso di importazione del profilo della revisione. Coprire anche i "
        "dataset necessari alle dipendenze degli indicatori.",
        "Configurazione",
    ),
    "thresholds": guide(
        "Soglie della revisione",
        "Oggetto JSON con le soglie specifiche di questo indicatore nel contratto. "
        "{} indica nessuna soglia aggiuntiva. Le chiavi dipendono dal processo di "
        "calcolo, non dal catalogo globale.",
        "Valori contrattuali",
    ),
    "parameters": guide(
        "Parametri della revisione",
        "Valori JSON conformi al parameter_schema della versione. I valori dei "
        "prerequisiti sono indipendenti da quelli dell’indicatore padre; {} è "
        "ammesso solo se lo schema non richiede valori.",
        "Valori contrattuali",
    ),
    "aggregation": guide(
        "Aggregazione della revisione",
        "Oggetto JSON di configurazione dell’aggregazione per il processo. {} indica "
        "nessuna configurazione aggiuntiva; non definisce una nuova sintassi "
        "universale.",
        "Valori contrattuali",
    ),
    "penalties": guide(
        "Penali della revisione",
        "Oggetto JSON di configurazione delle penali contrattuali per il processo. "
        "{} indica nessuna configurazione aggiuntiva; non è un importo già calcolato.",
        "Valori contrattuali",
    ),
    "publication_version": guide(
        "Numero della pubblicazione",
        "Progressivo assegnato alla pubblicazione append-only del contratto. Non "
        "sovrascrive pubblicazioni precedenti.",
        "Identità e versione",
    ),
    "contract_code": guide(
        "Codice del contratto",
        "Identificativo di business univoco utilizzato anche nelle API. Conservare "
        "lo stesso codice nei riferimenti al contratto.",
        "Identità e versione",
    ),
    "contract_type": guide(
        "Tipo del contratto",
        "start o renewal, assegnato automaticamente alla creazione in base alla "
        "sequenza contrattuale; non compilabile.",
        "Identità e versione",
    ),
    "contract_type_label": guide(
        "Tipo del contratto",
        "Etichetta del tipo start/renewal assegnato automaticamente.",
        "Identità e versione",
    ),
    "client_agency": guide(
        "Agenzia committente",
        "Agenzia titolare del contratto e del relativo perimetro di accesso.",
        "Parti e perimetro",
    ),
    "contractor_company": guide(
        "Impresa contraente",
        "Impresa che conferisce i dataset previsti dal contratto.",
        "Parti e perimetro",
    ),
    "governing_authority": guide(
        "Ente competente",
        "Ente cui è attribuito il contratto; facoltativo. Le membership dell’ente "
        "regolano la consultazione prevista dal workflow.",
        "Parti e perimetro",
    ),
    "lot": guide(
        "Lotto di servizio",
        "Lotto cui si riferisce il contratto; deve essere coerente con l’agenzia "
        "committente.",
        "Parti e perimetro",
    ),
    "start_date": guide(
        "Inizio del contratto",
        "Prima data di validità del contratto. Le decorrenze delle revisioni devono "
        "cadere nel periodo contrattuale.",
        "Stato e validità",
    ),
    "end_date": guide(
        "Fine del contratto",
        "Ultima data di validità, non precedente all’inizio; limita la validità "
        "delle revisioni.",
        "Stato e validità",
    ),
    "is_active_today": guide(
        "Attivo oggi",
        "Valore derivato da stato active e periodo contrattuale corrente; non "
        "coincide con l’approvazione di una revisione futura.",
        "Stato e validità",
    ),
    "closed_at": guide(
        "Chiusura",
        "Istante della chiusura del contratto; richiesto per lo stato closed.",
        "Stato e validità",
    ),
    "closed_reason": guide(
        "Motivazione della chiusura",
        "Spiegazione della chiusura; obbligatoria per un contratto closed.",
        "Stato e validità",
    ),
    "replaced_by": guide(
        "Contratto sostitutivo",
        "Contratto che sostituisce quello chiuso; facoltativo e distinto dalla "
        "sostituzione di una revisione tecnica.",
        "Stato e validità",
    ),
    "tender_id": guide(
        "Identificativo di gara",
        "Riferimento amministrativo della gara; facoltativo e non usato come codice "
        "del contratto.",
        "Documenti",
    ),
    "contract_program_file": guide(
        "Programma contrattuale",
        "Documento facoltativo del programma del contratto; non è un dataset "
        "trasferito per la validazione.",
        "Documenti",
    ),
    "file": guide(
        "File",
        "File conservato per questo oggetto; usare un formato ammesso dal campo. "
        "L’upload non certifica la calcolabilità degli indicatori.",
        "Documenti",
    ),
    "agency_key": guide(
        "Chiave dell’agenzia",
        "Chiave stabile normalizzata per URL e perimetri dell’agenzia. Se assente "
        "viene derivata dal nome secondo le regole esistenti.",
        "Identità e versione",
    ),
    "agency": guide(
        "Agenzia titolare",
        "Agenzia che possiede il lotto. Facoltativa sui dati storici; necessaria per "
        "attribuirlo al perimetro operativo corretto.",
        "Parti e perimetro",
    ),
    "short_description": guide(
        "Codice del lotto",
        "Codice stabile: lettere maiuscole, cifre e trattini, senza trattino "
        "iniziale/finale. Univoco nell’agenzia, normalizzato al salvataggio.",
        "Identità e versione",
    ),
    "geographic_extent": guide(
        "Estensione geografica",
        "Multipoligono WGS84 (SRID 4326) dell’ente, inseribile nella mappa; "
        "facoltativo. Non concede accessi geografici aggiuntivi.",
        "Parti e perimetro",
    ),
    "authority_type": guide(
        "Tipo di ente",
        "region, municipality o other. Distingue enti omonimi; non è un ruolo "
        "dell’utente.",
        "Parti e perimetro",
    ),
    "authority": guide(
        "Ente",
        "Ente cui è attribuita questa membership; abilita il perimetro di "
        "consultazione previsto, non l’amministrazione della piattaforma.",
        "Parti e perimetro",
    ),
    "user": guide(
        "Utente",
        "Account umano a cui è attribuita l’associazione. Non è un’identità di "
        "servizio né un client Keycloak.",
        "Accessi",
    ),
    "is_active": guide(
        "Attivo",
        "Abilita l’utilizzo corrente di questa associazione o risorsa secondo le "
        "regole del modello. Non indica un risultato di validazione.",
        "Stato e validità",
    ),
    "role": guide(
        "Ruolo sul contratto",
        "contract_reader consulta; contract_editor modifica entro il perimetro "
        "previsto; contract_admin amministra il contratto. Non attribuisce privilegi "
        "superuser o platform admin.",
        "Accessi",
    ),
    "role_to_assign": guide(
        "Ruolo da assegnare",
        "Ruolo sul contratto da attribuire dopo l’accettazione dell’invito. Un "
        "invito non equivale a una membership già attiva.",
        "Accessi",
    ),
    "email": guide(
        "Email del destinatario",
        "Indirizzo cui è destinato l’invito; quando specificato deve corrispondere "
        "all’identità "
        "verificata durante l’accettazione.",
        "Accessi",
    ),
    "token": guide(
        "Token dell’invito",
        "Identificativo generato automaticamente per l’invito. Non modificarlo né "
        "copiarlo in documentazione pubblica.",
        "Audit e provenienza",
    ),
    "expires_at": guide(
        "Scadenza dell’invito",
        "Termine entro cui l’invito pending può essere accettato; un invito scaduto "
        "non concede accesso.",
        "Stato e validità",
    ),
    "invited_by": guide(
        "Invitato da",
        "Utente che ha emesso l’invito nel perimetro contrattuale.",
        "Audit e provenienza",
    ),
    "accepted_by": guide(
        "Accettato da",
        "Utente che ha accettato l’invito; vuoto prima dell’accettazione.",
        "Audit e provenienza",
    ),
    "rejected_by": guide(
        "Rifiutato da",
        "Utente che ha rifiutato l’invito; vuoto se non rifiutato.",
        "Audit e provenienza",
    ),
    "accepted_at": guide(
        "Accettazione",
        "Istante dell’accettazione registrato dal workflow; vuoto prima "
        "dell’accettazione.",
        "Audit e provenienza",
    ),
    "rejected_at": guide(
        "Rifiuto",
        "Istante del rifiuto registrato dal workflow; vuoto se non rifiutato.",
        "Audit e provenienza",
    ),
    "profile_type": guide(
        "Tipo di profilo SIRI",
        "Categoria tecnica SIRI (es. siri-vm). Può esserci un solo profilo file "
        "attivo per categoria.",
        "Identità e versione",
    ),
    "asset_type": guide(
        "Tipo di asset",
        "Schema XSD, bundle XSD, schema JSON, documento, archivio o altro file "
        "tecnico. NeTEx/SIRI restano tipi di compatibilità. Non è un conferimento "
        "TPL né un file esecutivo dell’indicatore.",
        "Identità e versione",
    ),
    "what": guide(
        "Codice asset",
        "Codice scelto esplicitamente, indipendente da filename e dataset "
        "(es. netex-ita-lev5). Tipo, codice e versione identificano il file; "
        "asset_code nel descrittore XSD usa questo codice.",
        "Identità e versione",
    ),
    "storage_url": guide(
        "Riferimento di storage",
        "Riferimento all’oggetto conservato nello storage configurato; non inserire "
        "credenziali o URL temporanei con token.",
        "Storage e bundle",
    ),
    "storage_provider": guide(
        "Provider di storage",
        "Backend che conserva l’asset. Il riferimento non comporta un download "
        "durante la consultazione dell’admin.",
        "Storage e bundle",
    ),
    "storage_key": guide(
        "Chiave di storage",
        "Chiave dell’oggetto nel backend; deve corrispondere ai byte caricati, non a "
        "una copia diversa.",
        "Storage e bundle",
    ),
    "original_filename": guide(
        "Nome originale del file",
        "Nome libero registrato all’upload, distinto dal codice asset. "
        "Non determina la versione né il checksum.",
        "Storage e bundle",
    ),
    "content_type": guide(
        "Tipo MIME",
        "Tipo del contenuto registrato all’upload (es. application/zip). Non "
        "sostituisce il controllo del bundle.",
        "Storage e bundle",
    ),
    "checksum_sha256": guide(
        "SHA-256 del contenuto",
        "Digest dei byte originali; per un bundle deve coincidere con bundle_sha256 "
        "del manifest e del descrittore della regola.",
        "Storage e bundle",
    ),
    "size_bytes": guide(
        "Dimensione in byte",
        "Dimensione dei byte caricati; metadato di provenienza, non numero di record "
        "del dataset.",
        "Storage e bundle",
    ),
    "bundle_manifest": guide(
        "Manifest del bundle XSD",
        "Oggetto generato dall’ispezione dello ZIP: schema_version, entrypoint, "
        "bundle_sha256 e files ordinati con path/sha256/size_bytes. Le dipendenze "
        "XSD devono risolversi dentro il bundle. {} per asset senza bundle; non "
        "inventare digest reali.",
        "Storage e bundle",
    ),
    "uploaded_by": guide(
        "Caricato da",
        "Utente responsabile dell’upload dell’asset; può essere assente per "
        "operazioni di sistema.",
        "Audit e provenienza",
    ),
    "uploaded_at": guide(
        "Caricamento",
        "Istante registrato dal caricamento dell’asset.",
        "Audit e provenienza",
    ),
    "activated_by": guide(
        "Attivato da",
        "Utente responsabile dell’attivazione dell’asset; vuoto se non attivato.",
        "Audit e provenienza",
    ),
    "activated_at": guide(
        "Attivazione",
        "Istante dell’attivazione; non è la decorrenza di una revisione contrattuale.",
        "Audit e provenienza",
    ),
    "archived_at": guide(
        "Archiviazione",
        "Istante dell’archiviazione; vuoto se l’asset non è archiviato.",
        "Audit e provenienza",
    ),
    "publish_status": guide(
        "Stato della notifica",
        "Stato dell’invio dell’evento dell’asset al trasporto. Non attesta "
        "validazione del dataset né provisioning Prefect.",
        "Audit e provenienza",
    ),
    "last_publish_error": guide(
        "Ultimo errore di notifica",
        "Dettaglio dell’ultimo errore di trasporto; vuoto se non registrato. Non è "
        "una violazione XPath.",
        "Audit e provenienza",
    ),
    "asset": guide(
        "Asset dell’evento",
        "Risorsa di configurazione cui si riferisce questa notifica; non è il "
        "dataset da validare.",
        "Audit e provenienza",
    ),
    "event_type": guide(
        "Tipo di evento",
        "Evento della risorsa registrato nell’outbox (es. attivazione); non un "
        "risultato di calcolo.",
        "Audit e provenienza",
    ),
    "routing_key": guide(
        "Chiave di instradamento",
        "Destinazione logica del messaggio nel trasporto; preservare il valore "
        "prodotto dal servizio.",
        "Audit e provenienza",
    ),
    "payload": guide(
        "Payload dell’evento",
        "Oggetto JSON generato dal servizio per la notifica; readonly. Non "
        "modificarlo per ritentare l’invio.",
        "Audit e provenienza",
    ),
    "attempts": guide(
        "Tentativi di invio",
        "Contatore dei tentativi del publisher; non indica quanti dataset sono stati "
        "validati.",
        "Audit e provenienza",
    ),
    "last_error": guide(
        "Ultimo errore",
        "Errore dell’ultimo tentativo di trasporto; vuoto se non registrato.",
        "Audit e provenienza",
    ),
}

OVERRIDES = {
    ("ContractRevisionIndicator", "processing_profile_indicator_version"): guide(
        "Versione indicatore ammessa dal profilo",
        "Seleziona una versione appartenente al profilo tecnico di questa revisione. "
        "L’indicatore logico deriva dalla versione; la scelta e i valori valgono "
        "solo per questa revisione. Una sola versione per indicatore logico.",
        "Configurazione",
    ),
    ("ValidationRule", "code"): guide(
        "Codice della regola",
        "Codice stabile e univoco, immutabile dopo creazione. Per variare la logica "
        "creare una nuova versione della stessa regola.",
        "Identità e versione",
    ),
    ("IndicatorDimension", "code"): guide(
        "Codice della dimensione",
        "Identità stabile e univoca della disaggregazione (es. line); immutabile "
        "dopo creazione.",
        "Identità e versione",
    ),
    ("ValidationRuleVersion", "execution_reference"): guide(
        "Processo di validazione Prefect",
        "Riferimento flow/deployment del validator (es. validators/netex-default), "
        "distinto dal calcolo dell’indicatore. Obbligatorio per pubblicare; Django "
        "verifica il riferimento localmente, senza avviare o contattare Prefect.",
        "Processi e riferimenti",
    ),
    ("IndicatorVersionInput", "dataset_specification"): guide(
        "Input richiesto: versione del dataset",
        "Dataset pubblicato necessario al calcolo anche se non ha regole. L’input "
        "viene ereditato dai dipendenti; non attendere tutti gli input per "
        "controllare il trasferimento corrente.",
    ),
    ("DatasetSpecificationAsset", "role"): guide(
        "Ruolo dell’asset",
        "validation_schema per il bundle XSD referenziato dalla regola; constraint, "
        "documentation, example o other per altri supporti. Non è un ruolo di "
        "accesso.",
    ),
    ("Contract", "status"): guide(
        "Stato del contratto",
        "draft: bozza; active: contratto attivo; closed: contratto chiuso e "
        "congelato. Distinto dallo stato della revisione e dalla validità temporale "
        "della configurazione.",
        "Stato e validità",
    ),
    ("Contract", "version"): guide(
        "Versione del contratto",
        "Progressivo amministrativo assegnato automaticamente alla creazione; "
        "distinto dal numero di revisione tecnica.",
        "Identità e versione",
    ),
    ("ContractConfigurationRevision", "status"): guide(
        "Stato della revisione",
        "draft: modificabile; approved: snapshot congelato, anche se la decorrenza è "
        "futura; withdrawn: revisione futura ritirata. Per cambiare un’approvata "
        "creare una nuova bozza.",
        "Stato e validità",
    ),
    ("ContractInvitation", "status"): guide(
        "Stato dell’invito",
        "pending, accepted, rejected o expired: descrive il workflow dell’invito, "
        "non la validità del contratto.",
        "Stato e validità",
    ),
    ("Dataset", "status"): guide(
        "Stato del dataset logico",
        "active o deprecated: disponibilità della famiglia di dati. Non è lo stato "
        "editoriale delle sue specifiche tecniche.",
        "Stato e validità",
    ),
    ("Indicator", "status"): guide(
        "Stato dell’indicatore logico",
        "active o deprecated: disponibilità dell’identità dell’indicatore. Le versioni "
        "hanno un proprio stato editoriale.",
        "Stato e validità",
    ),
    ("ConfigurationAsset", "new_version"): guide(
        "Nuova versione",
        "Apri il caricamento con tipo e codice già selezionati; il nuovo file "
        "riceve una versione distinta senza sostituire il contenuto precedente.",
        "Identità e versione",
    ),
    ("ConfigurationAsset", "dataset_links"): guide(
        "Versioni dataset associate",
        "Specifiche che usano questa versione esatta dell’asset, con il ruolo "
        "assegnato in ciascuna associazione. L’attivazione non cambia questi usi.",
        "Associazioni",
    ),
    ("ConfigurationAsset", "status"): guide(
        "Stato dell’asset",
        "stored, active o archived: ciclo della risorsa di configurazione, distinto "
        "dalla pubblicazione del catalogo e dall’esito di validazione del file.",
        "Stato e validità",
    ),
    ("ConfigurationAssetEvent", "status"): guide(
        "Stato dell’invio",
        "pending, published o failed: stato dell’evento nel trasporto. Non è l’esito "
        "del validator.",
        "Audit e provenienza",
    ),
}


LIBRARY_FIELD_NOTES = {
    "ConfigurationAsset": {
        **dict.fromkeys(
            (
                "storage_url",
                "storage_provider",
                "storage_key",
                "original_filename",
                "content_type",
                "size_bytes",
            ),
            _("(rpsd-storage: salvataggio e recupero del file e dei suoi metadati)."),
        ),
        **dict.fromkeys(
            ("checksum_sha256", "bundle_manifest"),
            _(
                "(rpsd-storage: conserva il file; digest SHA-256 e manifest sono "
                "calcolati e verificati da Config)."
            ),
        ),
        **dict.fromkeys(
            ("publish_status", "last_publish_error"),
            _("(rpsd-transport: invio delle notifiche tramite RabbitMQ)."),
        ),
    },
    "ConfigurationAssetEvent": dict.fromkeys(
        (
            "asset",
            "event_type",
            "routing_key",
            "payload",
            "status",
            "attempts",
            "last_error",
            "published_at",
        ),
        _(
            "(rpsd-transport: trasporto RabbitMQ; Config registra il messaggio "
            "e l’esito dei tentativi)."
        ),
    ),
}


EVALUATION_LABELS = {
    "contract_revision_indicator": "Indicatore della revisione",
    "metric_code": "Metrica valutata",
    "quantity_metric_code": "Quantità economica",
    "aggregation_method": "Aggregazione",
    "quantity_aggregation_method": "Aggregazione della quantità",
    "group_by_dimensions": "Raggruppamento per dimensioni",
    "violation_operator": "Condizione di violazione",
    "limit_value": "Valore limite",
    "severity": "Livello di segnalazione",
    "missing_data_policy": "Gestione dati mancanti",
    "period_type": "Periodo di valutazione",
    "period_start_date": "Data iniziale inclusa",
    "period_end_date": "Data finale inclusa",
    "period_days": "Numero di giorni",
    "evaluation_timezone": "Fuso orario",
    "partial_period_policy": "Gestione dei periodi parziali",
    "activation_threshold": "Soglia di attivazione",
    "calculation_method": "Modalità di quantificazione",
    "allowance_quantity": "Franchigia",
    "fixed_amount": "Importo fisso",
    "unit_amount": "Importo unitario",
    "currency": "Valuta",
    "maximum_amount": "Massimale per applicazione",
    "amount_rounding_mode": "Arrotondamento finale",
    "external_execution_reference": "Riferimento esecutore esterno",
    "external_artifact_identifier": "Versione del codice esterno",
    "external_parameter_schema": "Schema parametri dell'esecutore",
    "external_parameters": "Parametri dell'esecutore",
}


def field_guide(model: type, name: str) -> FieldGuide | None:
    """Resolve explicit semantics for a concrete model or a proxy."""
    model_name = model._meta.concrete_model.__name__
    info = OVERRIDES.get((model_name, name), FIELDS.get(name))
    if info is None and model_name in {
        "IndicatorEvaluationThreshold",
        "IndicatorPenalty",
    }:
        from django.core.exceptions import FieldDoesNotExist

        try:
            field = model._meta.get_field(name)
        except FieldDoesNotExist:
            pass
        else:
            if field.help_text:
                info = guide(
                    EVALUATION_LABELS.get(
                        name, str(field.verbose_name).replace("_", " ").capitalize()
                    ),
                    str(field.help_text),
                )
    if model_name == "ContractRevisionIndicator" and name == "evaluation_links":
        info = guide(
            "Soglie e penali",
            (
                "Apri gli editor delle condizioni dell'indicatore "
                "della revisione; solo le bozze nel tuo perimetro "
                "sono modificabili."
            ),
        )
    note = LIBRARY_FIELD_NOTES.get(model_name, {}).get(name)
    if name == "configuration_asset":
        note = _(
            "(rpsd-storage: il file dell’asset collegato è gestito dallo storage)."
        )
    if info and note:
        return FieldGuide(info.label, format_lazy("{} {}", info.help, note), info.group)
    return info
