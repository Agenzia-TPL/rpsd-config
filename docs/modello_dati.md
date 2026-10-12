# Modello dati RPSD Config — stato consolidato

Data aggiornamento: 12 ottobre 2026.

Questo documento descrive il modello implementato in `rpsd-config` al termine
delle feature Config 019–023/025–026, sulla baseline 008–018. Il diagramma ER è disponibile in
[`modello_dati.mmd`](./modello_dati.mmd); per l'anteprima integrata di VS Code
si può aprire [`modello_dati_preview.md`](./modello_dati_preview.md) e usare
“Markdown: Open Preview”.

## 1. Perimetro

`rpsd-config` governa soggetti, lotti, contratti, accessi applicativi, cataloghi
tecnici versionati, regole di validazione e dipendenze degli indicatori, revisioni complete
della configurazione contrattuale e snapshot immutabili.

Non riceve o conserva i conferimenti operativi, non esegue la validazione, non
calcola né conserva risultati e non distribuisce o pianifica deployment Prefect.
Conserva il grafo aciclico delle dipendenze fra versioni indicatore e ne risolve
la chiusura e l’ordine di esecuzione dichiarato. Queste responsabilità restano a ingest, validator,
orchestratore e sistemi ETL/warehouse esterni.

Il percorso Config è verificato su database di test. Il 12 ottobre 2026 il
provider locale è stato aggiornato, il DB di sviluppo migrato senza reset e i
cataloghi XML/CSV target caricati; i contratti preesistenti conservano snapshot v1. L’integrazione del piano di validazione nei
consumer e il runtime Prefect sono consegne successive, non certificate qui.

## 2. Principi

1. Contratto, dataset e indicatore hanno identità logiche stabili.
2. Specifiche dataset, regole, indicatori tecnici, flow e profili sono versionati.
3. Ogni revisione contrattuale è uno snapshot completo, non una differenza.
4. Gli oggetti pubblicati non vengono modificati distruttivamente.
5. Una configurazione nuova richiede una nuova revisione con `valid_from`.
6. L'API operativa risolve soltanto la revisione corrente usando la data del
   server; il chiamante non può fornire date per scegliere passato o futuro.
7. La fine di una revisione è derivata dalla decorrenza della successiva e non è
   persistita.
8. Frequenza e scheduling dei flow non appartengono a Config.

## 3. Stakeholder, territorio e accessi

### `Agency`

Agenzia TPL committente. Crea i propri lotti e contratti e ne governa la
configurazione tramite utenti associati in `AgencyMembership`.

### `Company`

Azienda TPL affidataria. È collegata al contratto e ai principal tecnici M2M.
Gli accessi umani restano espliciti e perimetrati; l'appartenenza aziendale non
concede implicitamente accesso a tutti i contratti.

### `Authority` (GoverningAuthority nel dominio)

Autorità di governo associata al contratto. I suoi utenti sono registrati con
`AuthorityMembership` e possono consultare i contratti visibili, senza creare,
modificare o approvare la configurazione.

### `Lot`

Suddivisione logica del territorio creata da una sola agenzia. È collegata
direttamente al contratto, non alla revisione tecnica. Può essere riutilizzata
da contratti successivi, ma i periodi efficaci di contratti sullo stesso lotto
non devono sovrapporsi.

### Accesso umano e tecnico

- `AgencyMembership`: ruolo organizzativo nel perimetro agenzia.
- `AuthorityMembership`: appartenenza all'autorità con visibilità read-only.
- `ContractMembership`: permesso esplicito sul singolo contratto.
- `AgencyInvitation` e `ContractInvitation`: onboarding con token.
- `IntegrationPrincipal`: identità tecnica M2M appartenente a una company.
- `IntegrationGrant`: autorizzazione esplicita del principal su un contratto.

## 4. Contratto

### `Contract`

Identità giuridica e di monitoraggio stabile. Collega agenzia committente,
azienda affidataria, autorità di governo, lotto della stessa agenzia, codice
univoco, periodo contrattuale e stato.

Il contratto non contiene un profilo tecnico corrente. Il lotto resta stabile
per tutta la sua vita; le variazioni tecniche passano dalle revisioni.

### `ContractDocument`

Documento amministrativo associato al contratto. Non rappresenta un input del
processo di ingest.

## 5. Dataset, asset e regole

### `Dataset` e `DatasetSpecification`

`Dataset` è l’identità logica (es. `netex`); il suo codice è il valore di routing.
`DatasetSpecification` è la versione tecnica (es. `netex-ita_v001`), con metadata,
formato e ciclo `draft`, `published`, `deprecated`, `withdrawn`.

### `ConfigurationAsset` e `DatasetSpecificationAsset`

Gli asset persistiti ammettono solo `netex_xsd` e `siri_profile`, anche tramite
vincolo DB. Contengono storage, checksum e metadati; la tabella ponte assegna
ruolo e obbligatorietà alla specifica dataset. Un bundle XSD è un archivio ZIP
con entrypoint, manifest dei file, riferimenti locali e checksum: non un nuovo
modello `SchemaBundle`. Non sono ammessi include/import remoti o path insicuri.
Gli asset YAML degli indicatori e `IndicatorProfile` sono rimossi.

### `ValidationRule` e `ValidationRuleVersion`

`ValidationRule` identifica la regola con un codice stabile univoco.
`ValidationRuleVersion` appartiene a una sola regola; la coppia regola/versione
è univoca. Contiene `validation_type`, `definition`, `language_version`,
`options`, `result_contract`, `execution_reference`, stato e audit pubblicazione.
La stessa versione può essere associata a più specifiche dataset.

La definizione è completa: un confronto tra due strutture XML non richiede due
frammenti. Ad esempio NX-005 può usare:

```xpath
//n:DayTypeAssignment/n:OperatingPeriodRef[not(@ref = //n:operatingPeriods/*/@id)]
```

Il namespace `n` è dichiarato in `options.namespaces`. Il target wildcard
riproduce la regola del corpus, senza restringerla implicitamente a un solo tipo.
Il risultato `violating_entities` identifica i nodi non conformi; sequenza vuota
significa successo secondo il contratto dell’interprete. Config controlla la
configurazione, senza valutare l’XPath sul dataset trasferito.

Il registry degli interpreti è codice, non una tabella. I contratti configurabili
sono: XPath XML 1.0/2.0/3.1, bundle XSD 1.0, colonne obbligatorie CSV/XLSX e
pattern TXT. Le definizioni tabellari/testuali sono JSON dichiarativi versionati,
non codice Python arbitrario. `application_state` è escluso finché non siano
note fonte e fase dell’approvazione EA. Il manifest dichiara
`external_not_verified`: non certifica deployment disponibili.

### `DatasetVersionRule`

Associa una specifica dataset a una versione regola; coppia univoca. La politica
si trova sull’associazione, non sulla definizione condivisa:

| `import_policy` | Conseguenza prevista nel consumer |
| --- | --- |
| `reject_import` | Violazione: trasferimento non ammesso all’import |
| `warn` | Controllo sempre applicabile; violazione: avviso dataset |
| `indicator_only` | Controllo solo se richiesto dagli indicatori effettivi |

Le regole di base si compongono nella bozza della specifica. Su una specifica
pubblicata si possono aggiungere nuove applicabilità `indicator_only`; non si
modificano le politiche già pubblicate. Gli snapshot approvati restano congelati.

## 6. Indicatori, input e dipendenze

### `Indicator` e `IndicatorVersion`

`Indicator` è l’identità logica stabile. `IndicatorVersion` contiene formula,
`input_schema`, `output_schema`, `parameter_schema`, riferimento al processo di
calcolo e provenienza `artifact_identifier`. Il ciclo è
`draft`, `published`, `deprecated`, `withdrawn`.
La pubblicazione è gestita da Django: richiede un riferimento Prefect completo
configurato, senza interrogare Prefect o verificarne la raggiungibilità.
Il processo di calcolo è distinto dal riferimento di validazione della regola.
Non esiste una tabella separata per metodi di calcolo o file YAML indicatori.

### `IndicatorVersionInput`

Associa gli input dataset necessari a una versione indicatore, anche quando
non ci sono regole. Coppia indicatore-versione/specifica univoca. Gli input
richiesti includono anche le specifiche delle regole associate.

### `IndicatorVersionRule` e dimensioni

Associa una versione indicatore a `DatasetVersionRule`, non direttamente a un
frammento. Coppia univoca, nessun booleano `mandatory`.

- `impact=calculation`: le entità non conformi non contribuiscono al calcolo.
- `impact=dimension`: il totale può essere calcolabile, ma le disaggregazioni
  indicate non sono disponibili per quelle entità.

`IndicatorDimension` è il catalogo delle dimensioni. La relazione M:N passa da
`IndicatorVersionRuleDimension`: almeno una dimensione per impatto dimension,
nessuna per calculation. Il KO indicatore non rigetta il file, salvo una
politica dataset `reject_import`. Config definisce questi impatti; il servizio
esterno conserverà gli esiti e le entità interessate.

### `IndicatorVersionDependency`

Ogni versione può dipendere da zero o più versioni precise. La coppia
`dependent`/`prerequisite` è univoca; autodependenza e cicli sono vietati.
Le dipendenze devono essere pubblicate. Le modifiche concorrenti al grafo sono
serializzate per impedire cicli introdotti da transazioni simultanee.
`DependencyRequiredDimension` specifica le dimensioni necessarie del prerequisito.
La chiusura transitiva raccoglie indicatori, input, regole e percorsi di provenienza;
un prerequisito condiviso viene risolto una volta. L’ordine topologico è metadata
per il consumer, non una pianificazione effettuata da Config.

## 7. Flow e profili di elaborazione

### `InputFlowVersion`

Riferimento versionato al flow capace di trattare una
`DatasetSpecification`. Registra codice/versione, `deployment_name`,
`artifact_identifier` ed engine. Il tipo di dato accettato deriva dalla
`DatasetSpecification` collegata; il contratto del messaggio runtime e la
compatibilità derivabile non sono duplicati in campi JSON configurabili. Non
contiene frequenza o scheduling.

### `OrchestrationFlowVersion`

Riferimento versionato al flow generale che coordina import, consolidamento e
calcoli. La topologia resta nel codice/deployment esterno, non nel database
Django.

### `ProcessingProfileVersion`

Perimetro relazionale di compatibilità certificato dal platform admin. Collega un
`OrchestrationFlowVersion` a uno `ProcessingProfileInputFlow` per ciascun
`Dataset` ammesso e a uno o più `ProcessingProfileIndicatorVersion`.

Il profilo non impone tutti gli elementi alla revisione: l'operatore può
scegliere un sottoinsieme degli indicatori ammessi. `proposed_by_default`
determina soltanto la preselezione iniziale. Gli input e le regole degli
indicatori scelti e della loro chiusura transitiva determinano gli input obbligatori; gli altri input del
profilo possono essere aggiunti come opzionali.

Il profilo ha ciclo di vita `draft`, `published`, `deprecated`, `withdrawn`.
Solo un profilo pubblicato può essere scelto per una nuova revisione. Un profilo
in uso non si modifica: si pubblica una nuova versione.

## 8. Revisione della configurazione contrattuale

### `ContractConfigurationRevision`

Snapshot completo applicabile al contratto da `valid_from`. Contiene contratto,
numero e codice, `ProcessingProfileVersion`, motivazione, revisione sostituita
opzionale, stato, audit di approvazione/ritiro, `configuration_snapshot`,
versione schema e checksum SHA-256.

`scheduled`, `active`, `expired` e `valid_to` non sono persistiti. Per una
revisione approvata, la fine efficace è il giorno precedente alla successiva
revisione approvata oppure la fine del contratto. `withdrawn` indica un ritiro
esplicito e conserva audit e provenienza; non è il normale termine temporale.

La bozza è modificabile da agency/contract admin ed editor nel proprio
perimetro. L'approvazione spetta all'`Agency admin` titolare o al
`Contract admin`; il platform admin ha già certificato la parte tecnica
pubblicando il profilo e non costituisce un passaggio obbligatorio. Il sistema
verifica coerenza e componenti pubblicati e congela snapshot e checksum. Una
revisione approvata o ritirata non può essere modificata o cancellata.

### `ContractInputSelection`

Seleziona i `ProcessingProfileInputFlow` effettivamente usati dalla revisione.
Ogni selezione deve appartenere allo stesso profilo della revisione.

### `ContractRevisionIndicator`

Seleziona direttamente nella revisione un
`ProcessingProfileIndicatorVersion` dello stesso profilo. Memorizza JSON
validati per soglie, aggregazione, penalità e parametri. La frequenza non è un
campo del modello.

### `ContractDependencyConfiguration`

Conserva soglie, parametri, aggregazione e penalità della singola versione
indicatore implicita nella revisione. Coppia revisione/versione univoca.
Non crea una selezione principale per le dipendenze e non eredita i valori
dal padre. Il `parameter_schema` appartiene alla versione; i valori effettivi
appartengono alla revisione. I parametri obbligatori sono verificati per tutta
la chiusura all’approvazione.

### Risoluzione current-only

La chiamata operativa è concettualmente:

```text
(who=contract_code, what=dataset.code)
  -> ultima revisione approved con valid_from <= oggi
  -> profilo e input selezionato
  -> DatasetSpecification e InputFlowVersion
  -> descrittore runtime e artifact identifier
```

Non sono ammessi `reference_date`, `service_day` o altri parametri temporali per
scegliere una revisione. Il periodo dichiarato nel file può essere validato dal
flow esterno, ma non modifica la configurazione risolta da Config.

Le API v1 rimangono come proiezioni compatibili del nuovo modello. I nomi
storici nei payload non corrispondono più a tabelle legacy. La v2 espone
esplicitamente la risoluzione corrente. La v3 espone:

```text
GET /exchange_agreement/api/m2m/v3/contracts/{contract_code}/validation-plan?data_category=netex
```

La risposta `validation-plan-v1` deriva solo dallo snapshot `canonical-json-v2`
approvato, senza rileggerne le definizioni dai cataloghi live. Comprende regole
base dataset e regole degli indicatori selezionati/dipendenze, filtrate sul solo
dataset arrivato, con impatti e provenienza. Non attende altri trasferimenti e
non certifica la calcolabilità globale. Pin, esecuzione, retry e callback sono
responsabilità del futuro consumer. Gli snapshot v1 restano leggibili dalle
API compatibili, ma non producono implicitamente un piano v3 target.

## 9. Snapshot e pubblicazioni

### `ContractPublication`

Pubblicazione append-only di una revisione approvata e corrente. Copia senza
reinterpretazioni `configuration_snapshot`, versione schema e checksum della
revisione e aggiunge progressivo e audit. È immutabile.

Lo snapshot canonico identifica contratto, revisione, profilo, orchestratore,
input, specifiche dataset, asset e bundle, indicatori effettivi, dipendenze,
regole, applicabilità, impatti, valori contrattuali e riferimenti esecutivi.
Le nuove approvazioni usano `canonical-json-v2`. Le relazioni guidano la bozza; lo snapshot congelato rende la
configurazione approvata verificabile e riproducibile.

## 10. Cicli di vita

Per specifiche dataset, versioni regola, versioni indicatore, flow e profili:

- `draft`: modificabile e non utilizzabile in una configurazione approvata;
- `published`: validato e selezionabile;
- `deprecated`: non selezionabile per nuovi usi, ma conservato per quelli
  esistenti;
- `withdrawn`: ritirato senza cancellare storia e audit.

Le transizioni producono eventi di stato append-only. Gli oggetti non draft
sono protetti da modifica e cancellazione distruttiva.

## 11. Esempio sintetico

Il contratto `ATM_2026_LOTTO_1` usa dal 1 gennaio 2026 una prima revisione con
profilo NeTEx/SIRI versione 1. Dal 1 luglio 2028 deve adottare una nuova versione
NeTEx:

1. il platform admin pubblica specifica, regole, indicatori con le dipendenze, input flow e
   profilo compatibili;
2. l'operatore dell'agenzia crea una nuova revisione completa con
   `valid_from=2028-07-01`;
3. l'agency admin o il contract admin la approva dal dettaglio della revisione;
4. fino al 30 giugno le API risolvono la prima revisione;
5. dal 1 luglio risolvono la seconda, senza modificare la prima;
6. ingest continua a inviare soltanto `who=ATM_2026_LOTTO_1` e `what=netex`.

La storia resta leggibile per audit, ma l'ingest ordinario non può forzare una
configurazione storica.

## 12. Persistenza legacy rimossa

I modelli `Structure`, `IndicatorDef`, `OperationalFlow`, `FlowProfile` e il
campo `Contract.flow_profile` sono stati rimossi. Anche
`ContractIndicator` è rimosso; selezioni e valori appartengono alla revisione
più. Gli adapter API v1 leggono esclusivamente il modello consolidato.

Le migrazioni terminali 0046/0047 e admin 0011/0012 rimuovono inoltre frammenti,
regole su frammenti, mapping di conversione e profili YAML degli indicatori.
Le migrazioni storiche e gli helper necessari a caricarle restano nel codice.
I metadati YAML obsoleti vengono eliminati senza cancellare file nello storage.
Per lo sviluppo non è richiesto recuperare i dati esistenti; reset e seed sono
operazioni separate con target esplicito. Consultare
[`USAGE.md`](../USAGE.md) per i comandi.

## 13. Stato di verifica e limiti

Il diagramma rappresenta il dominio tecnico e contrattuale, omettendo tabelle
di eventi, accessi, membership, inviti, documenti amministrativi e profili
di validazione della configurazione piattaforma. Cardinalità e nomi sono
allineati ai modelli Django; i vincoli ulteriori sono descritti sopra.

Il corpus CORSE_PDE conserva 15 righe: 14 controlli file configurabili e WF-001
esclusa con motivazione. La QA isolata XPath/XSD non è uno smoke Prefect.
Config non conserva risultati `passed/violations/execution_error`, non attiva
job e non verifica ammissione operativa dei trasferimenti. Il repository e
i deployment del validator verranno definiti successivamente.

Aggiornamento 029: una sola versione per indicatore logico in ciascuna revisione;
nessuna associazione autonoma contratto/indicatore. La versione è ricavata dalla
voce del profilo tecnico selezionata.
