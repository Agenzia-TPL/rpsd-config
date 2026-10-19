# Usage Guide

Operational guide for running and configuring `rpsd-config`.

---

## Running the Service

### Devcontainer (development)

Inside the VS Code devcontainer:

```bash
uv run devserver
```

Uses Django's built-in `runserver`. Reads `APP_HOST` and `APP_PORT` from settings.
Hot-reload is enabled. Not for production use.

### Docker (integration tests, staging, production)

The Docker image is built from `Dockerfile` (project root) and does not embed a default
command — each deployment config provides it.

**Required command in your compose / Swarm / K8s config:**

```yaml
command: ["gunicorn", "rpsd_config.server.asgi:application"]
```

Gunicorn auto-detects `gunicorn.conf.py` from the container's working directory (`/app/`).
No `-c` flag is needed.

**Example Docker Compose service:**

```yaml
rpsd-config:
  image: rpsd-config:local
  build:
    context: ./rpsd-config
    dockerfile: ./Dockerfile      # use project root Dockerfile, NOT .devcontainer/Dockerfile
  command: ["gunicorn", "rpsd_config.server.asgi:application"]
  ports:
    - "${APP_EXTERNAL_PORT:-20100}:${APP_PORT:-8000}"
  volumes:
    - ./rpsd-config/.env.base:/app/.env.base:ro
    - ./rpsd-config/.env:/app/.env:ro
```

---

## Configuration

Settings are managed via `.env.base` and `.env` files at the project root.

- `.env.base` — scenario defaults (checked in or per-deployment baseline)
- `.env` — local overrides (git-ignored)

`.env` takes precedence over `.env.base`. Both files are mounted into the container
as read-only volumes and are also read directly by Pydantic Settings.

### Available environment variables

| Variable | Default | Used by | Description |
|---|---|---|---|
| `APP_HOST` | `0.0.0.0` | Django devserver | Bind host for devserver |
| `APP_PORT` | `8000` | gunicorn, Django devserver | **Internal** bind port — where Gunicorn/Django listens inside the container. Rarely needs changing. |
| `APP_EXTERNAL_SCHEME` | `http` | Django | Scheme for CSRF trusted origins |
| `APP_EXTERNAL_HOST` | `localhost` | Django | External hostname |
| `APP_EXTERNAL_PORT` | `20100` | Django | **External** port users access in their browser. Drives CSRF trusted origins. Set this per deployment (e.g. `80`, `443`). |

> **NOTE — do not confuse `APP_PORT` and `APP_EXTERNAL_PORT`:**
> - `APP_PORT` is the port Gunicorn/Django binds to *inside the container*. The default (`8000`) is almost always correct — leave it alone unless you have a specific reason to change it.
> - `APP_EXTERNAL_PORT` is the port that appears in the URL users type in their browser. This is the one to customise per deployment scenario (e.g. `80` for intranet HTTP, `443` for HTTPS via an external gateway).
> - In the Docker Compose port mapping `HOST:CONTAINER`, `APP_EXTERNAL_PORT` goes on the **host side** and `APP_PORT` goes on the **container side**.
| `GUNICORN_WORKERS` | `2` | gunicorn | Number of worker processes per container |
| `GUNICORN_TIMEOUT` | `30` | gunicorn | Worker timeout in seconds |
| `DJANGO_SECRET_KEY` | insecure default | Django | **Set this in production** |
| `DEBUG` | `True` | Django | Set to `False` in production |

### Configuration flow

```
.env / .env.base
      │
      ├─→ Docker Compose (volumes) → Pydantic Settings → Django
      └─→ Docker Compose (env_file:) → container env vars → gunicorn.conf.py (os.getenv)
```

Both Gunicorn and Django read from the same source. No duplication of values.

---

## Database

Configure via environment variables using double-underscore nesting:

```
DATABASES__default__HOST=postgis
DATABASES__default__NAME=rpsd
DATABASES__default__USER=rpsd
DATABASES__default__PASSWORD=rpsd
DATABASES__default__PORT=5432
```

---

## Authentication

### Human users (OIDC / Keycloak)

Human users log in via OpenID Connect through Keycloak. This is handled by
`django-allauth` and requires no manual setup beyond the environment variables
described below.

| Variable | Default | Description |
|---|---|---|
| `OIDC_PROVIDER_ID` | `keycloak` | Provider identifier — must match the allauth provider record |
| `KEYCLOAK_DISCOVERY_URL` | `http://keycloak:8080/realms/rpsd/.well-known/openid-configuration` | OIDC discovery endpoint (server-to-server, must be container-reachable) |
| `OIDC_AUTHORIZATION_ENDPOINT_URL` | *(empty)* | Override the browser-facing authorization URL (must use `localhost`) |
| `OIDC_ISSUER_URL` | *(empty)* | Override the expected token issuer (must match Keycloak's `KC_HOSTNAME`) |
| `OIDC_CLIENT_ID` | `django` | OAuth2 client ID (must match Keycloak client config) |
| `OIDC_CLIENT_SECRET` | `django-secret` | OAuth2 client secret |
| `OIDC_FETCH_USERINFO` | `false` | Fetch userinfo endpoint after authentication |

### Service-to-service (JWT Bearer)

Other services authenticate by passing a Keycloak JWT as a Bearer token in the
`Authorization` header. The token is validated by `JWTBearerMiddleware` +
`JWTBearerBackend`, which maps the JWT's `sub` claim to a Django User via
allauth's `SocialAccount` model.

No additional settings are needed — the JWKS URL and issuer are derived from
`KEYCLOAK_DISCOVERY_URL` and `OIDC_ISSUER_URL`.

#### Keycloak setup (one-time per service)

1. In Keycloak Admin, go to the `rpsd` realm → **Clients** → **Create client**
2. Set **Client ID** (e.g., `rpsd-ingest`), **Client authentication** = On
3. Under **Capability config**: enable **Service accounts roles**, disable **Standard flow**
4. Save, then go to the **Credentials** tab and note the client secret
5. To find the service account's `sub` (UUID): go to the **Service accounts roles** tab
   and click the service account user link at the top — the **ID** field is the `sub`

#### Django setup (one-time per service)

1. In Django Admin, create a **User** for the service (e.g., username `service-rpsd-ingest`).
   Assign permissions and group memberships as needed.
2. Create a **Social Account** linked to that user:
   - **Provider**: `keycloak` (must match `OIDC_PROVIDER_ID`)
   - **Uid**: the UUID from Keycloak (the `sub` claim)

#### Usage

```bash
# Get a token
TOKEN=$(curl -s -X POST \
  http://localhost:19300/realms/rpsd/protocol/openid-connect/token \
  -d "grant_type=client_credentials&client_id=rpsd-ingest&client_secret=YOUR_SECRET" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Call the API
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:20100/exchange_agreement/api/v1/contracts
```

> **Tip:** During development, the default access token lifetime is 5 minutes.
> To increase it, go to Keycloak Admin → **Realm Settings** → **Tokens** →
> **Access Token Lifespan**. You can also override it per-client under
> **Clients** → select client → **Advanced** → **Access Token Lifespan**.

---

## Static Files

Static files are collected at build time (`RUN uv run manage collectstatic --noinput`
in the Dockerfile) and served from `/app/staticfiles/`.

For production, configure a reverse proxy (nginx, Traefik) to serve `/static/` directly
from that directory.

## Date dei contratti e revisioni in bozza

Nella pagina del contratto, un amministratore dell'agenzia o del contratto
(o un superuser) può modificare le date se il contratto è in bozza, non è
stato pubblicato e tutte le sue revisioni sono ancora in bozza. Le nuove date
rispettano i vincoli sul lotto e devono includere le decorrenze delle bozze
esistenti. Se una bozza cade fuori dal nuovo periodo, eliminarla e ricrearla
con la decorrenza corretta. Le revisioni approvate o ritirate bloccano questa
modifica delle date.

Nella pagina di una revisione in bozza, chi può preparare la configurazione
può usare **Elimina bozza**, selezionando la conferma prima di inviare il
modulo. Vengono eliminate la revisione e le sue selezioni; il contratto rimane.
Le revisioni approvate o ritirate non sono eliminabili con questa azione.

## Catalogo versionato delle regole di validazione (feature 019)

Django conserva le regole e ne gestisce la pubblicazione. Non esegue la
validazione dei file e non contatta Prefect durante salvataggio o pubblicazione.

Un platform admin (gruppo Keycloak `/rpsd/admin`) o un superuser può aprire
**Configurazione piattaforma → Cataloghi tecnici → Regole di validazione**,
creare un'identità e poi una voce in **Versioni delle regole**. Il codice
identifica stabilmente la regola e non è modificabile dopo la creazione.
Gli operatori delle agenzie non possono scrivere nel catalogo globale.
Le stesse restrizioni valgono nel Django admin.

Una versione nasce in `draft` e può essere incompleta. Prima di pubblicarla
compilare definizione, tipo, versione del linguaggio, opzioni, convenzione del
risultato e `execution_reference`, nel formato `flow/deployment`.
Il riferimento è una configurazione del futuro esecutore: la pubblicazione
non ne attesta l'esistenza su Prefect. Il processo di validazione è distinto
dal processo di calcolo dell'indicatore.

Per esempio, una regola XPath può contenere:

```text
//n:DayTypeAssignment/n:OperatingPeriodRef[not(@ref = //n:operatingPeriods/*/@id)]
```

Con `validation_type=xpath`, `language_version=1.0`,
`options={"namespaces":{"n":"http://www.netex.org.uk/netex"}}` e
`result_contract=violating_entities`. Il futuro validator deve interpretare
una sequenza vuota come successo e i nodi restituiti come violazioni.
Config verifica la struttura della configurazione e i namespace dichiarati;
non compila né esegue l'espressione XPath. Il percorso di sviluppo 026 rimuove
il catalogo dei frammenti e non converte le vecchie regole `exists`.

Le versioni `published`, `deprecated` e `withdrawn` sono immutabili e non
eliminabili. Per cambiare una definizione creare una nuova versione.
Le transizioni registrano attore, data e motivazione; deprecazione e ritiro
richiedono una motivazione. Lo storico nel Django admin è in sola lettura.
Solo `published` compare nel manifest per i nuovi requisiti di esecuzione:

```bash
uv run manage validation_execution_manifest > validation-execution-manifest.json
```

Il manifest contiene identità codice/versione, definizioni e capability locali,
senza primary key del database. Serve come input alla futura verifica del
runtime; non certifica la disponibilità dei deployment. I tipi elencati
nel registro sono contratti di configurazione, non esecutori installati.
Un tipo ignoto o opzioni incompatibili bloccano la pubblicazione.

## Applicabilità delle regole e impatto sugli indicatori (feature 020)

Una regola si associa a una **versione di dataset**, non al dataset logico.
La stessa versione di regola può essere riusata su più specifiche, se il suo
interprete supporta il formato dichiarato dalla specifica (campo obbligatorio «Formato del dataset»). `metadata` contiene soltanto
informazioni aggiuntive facoltative; non inserirvi la chiave `format`.

Ogni associazione dataset/regola ha una politica:

| Politica | Controlli da includere | Conseguenza prevista di una violazione |
|---|---|---|
| `reject_import` | Sempre per quel dataset | Il futuro validator deve rifiutare il trasferimento. |
| `warn` | Sempre per quel dataset | Il trasferimento può essere accettato con un warning. |

Il requisito indicatore collega direttamente indicatore-versione, specifica dataset
e regola-versione, senza passare dalla politica del dataset. Specifica la conseguenza:
`calculation` esclude le entità non conformi dal calcolo;
`dimension` conserva la possibilità del totale ma perde le disaggregazioni
indicate. Per `dimension` occorre almeno una dimensione; `calculation` non
ammette dimensioni. Non esiste un secondo campo `mandatory`.
Una politica dataset `reject_import` mantiene il proprio effetto anche se un
indicatore usa la stessa regola soltanto per una dimensione.

Gli **Input richiesti degli indicatori** dichiarano anche i dataset che servono
al calcolo senza avere controlli associati. Prima di pubblicare un profilo,
Django richiede l'esatta versione di ogni input: non sceglie automaticamente
l'ultima versione e non considera facoltativo un dataset privo di regole.
Il superamento dei controlli di un trasferimento non attesta la disponibilità
degli altri input necessari al calcolo.

Le regole dataset si modificano soltanto nella bozza della specifica.
I requisiti indicatore si modificano nella bozza dell'indicatore, senza alterare
le specifiche pubblicate né gli snapshot dei contratti già approvati.
L'autore e la data di creazione delle applicazioni sono conservati; i codici
delle dimensioni restano stabili.

I controlli condivisi mantengono un elenco di consumatori separati: indicatore,
impatto, dimensioni e percorsi di dipendenza. Config prepara questa
configurazione; esecuzione, persistenza degli esiti e decisioni effettive sul
trasferimento appartengono al futuro validator/ingest.


## Dipendenze degli indicatori e valori contrattuali (021)

Una versione di indicatore può dipendere da zero o più versioni esatte di altri
indicatori. Tutti i prerequisiti sono necessari (AND). Django rifiuta dipendenze
da sé stesso, duplicati, cicli e due versioni dello stesso indicatore nella
chiusura di un profilo. Le modifiche e la pubblicazione serializzano il grafo
tramite un lock transazionale PostgreSQL; i prerequisiti devono essere pubblicati.
Dipendenze e dimensioni richieste si modificano solo nella bozza del dipendente.

Il profilo include anche input e regole dei prerequisiti. Il piano conserva
indicatori selezionati e impliciti, tutti i percorsi e `indicator_execution_order`
con i prerequisiti prima dei dipendenti. Una dipendenza condivisa compare una
volta nell'ordine di calcolo, mantenendo i diversi percorsi che la richiedono.

La pubblicazione in Django verifica un descrittore di calcolo con
`execution_engine=prefect` e `execution_reference`, oltre alla provenienza
richiesta dal catalogo. Non contatta Prefect e non richiede che sia disponibile:
il riferimento serve al servizio esterno che effettuerà il calcolo. Le bozze
possono essere prive del riferimento. Non si inventano deployment per dati legacy.

`input_schema` e `output_schema` descrivono il formato tecnico del calcolo:
la migrazione 0043 rinomina le colonne conservando il JSON. Il serializer e
l'API del catalogo espongono anche `input_contract` e `output_contract` come
alias di compatibilità; gli snapshot storici conservano nomi e checksum originali.

`parameter_schema` descrive i parametri propri della versione indicatore.
Il formato supportato è un contratto locale, non l'intero standard JSON Schema:

```json
{
  "schema_version": 1,
  "properties": {"window_days": {"type": "integer", "minimum": 1}},
  "required": ["window_days"],
  "allow_extra": false
}
```

I tipi sono `string`, `boolean`, `integer`, `number`, con enum, limiti numerici
opzionali e descrizione. Ogni revisione conserva separatamente parametri,
soglie, aggregazione e penali per ciascun indicatore effettivo. Gli indicatori
selezionati usano la configurazione esistente; quelli impliciti usano
`ContractDependencyConfiguration`, unica per revisione/versione. Nessun valore
viene copiato dal padre. La pagina della revisione permette di modificare i
valori in bozza; dopo l'approvazione mostra i valori congelati nello snapshot.
I parametri obbligatori mancanti impediscono l'approvazione e l'errore riporta
indicatore e percorsi di dipendenza. Lo schema vuoto non impone parametri.

Il contratto di propagazione distingue perdita del calcolo e perdita delle
sole dimensioni richieste. Un insieme vuoto di dimensioni indica uso del totale.
Il futuro validator applicherà questi criteri alle entità mappate; se il mapping
manca, il risultato resta sconosciuto. Config non produce esiti o percentuali.

Il comando di sola lettura `uv run manage indicator_artifact_inventory` elenca
i riferimenti di calcolo e di provenienza delle versioni nel formato
`indicator-artifact-inventory-v2`. Il catalogo YAML degli indicatori è rimosso;
l’inventario non contiene più `legacy_indicator_files` e non elimina file.


## Bundle XSD e descrittori di validazione (023)

Gli asset NeTEx e SIRI accettano ZIP contenenti la cartella degli XSD. Con un
solo XSD l'entrypoint è individuato automaticamente; con più XSD aggiungere
`manifest.json` all'archivio:

```json
{"entrypoint": "schemas/root.xsd"}
```

All'upload Config genera un manifest versione 1 con entrypoint, SHA-256 dello
ZIP e, per ciascun file, percorso, dimensione e SHA-256. Gli XSD devono essere
UTF-8 (BOM consentito). Include, import e redefine devono avere una
schemaLocation risolvibile nel bundle; sono ammessi riferimenti `../` fra
cartelle interne, senza uscire dal bundle. Gli import senza posizione esplicita
sono respinti. Config ispeziona il bundle; non compila l'XSD né valida dataset.

Limiti: 4096 elementi ZIP, 128 MiB per archivio e contenuto totale non compresso,
8 MiB per file. Sono respinti percorsi assoluti/non canonici, duplicati, symlink,
file speciali, file cifrati, DTD, entità XML e dipendenze remote. Il bundle non
viene estratto sul filesystem. Metadati e posizione storage di un bundle
memorizzato non si modificano: per cambiarlo caricare una nuova versione.
Attivazione, archiviazione e label restano disponibili.

Collegare il bundle alla versione dataset con ruolo `validation_schema`.
Una regola `xsd_bundle`, lingua `1.0`, risultato `structured_report`, opzioni
vuote, usa questa definizione JSON (digest sostituito con quello dell'upload):

```json
{
  "asset_code": "netex",
  "asset_version": "1",
  "entrypoint": "schemas/root.xsd",
  "bundle_sha256": "<64 caratteri esadecimali minuscoli>"
}
```

L'associazione regola/dataset richiede un bundle collegato con versione,
entrypoint e digest coincidenti. Al download Config verifica nuovamente ZIP,
file e manifest. L'endpoint v3 restituisce 409 per integrità non valida e 404
per contenuto assente, con un codice di errore esplicito. Il piano della 022
congelerà queste identità; i checksum degli snapshot storici restano invariati.

Il registro locale descrive contratti di definizione, non interpreti installati.
`uv run manage validation_execution_manifest` espone
`definition_contract_version=1` e `runtime_status=external_not_verified`.
XPath accetta lingua 1.0/2.0/3.1, namespace espliciti e risultato
`violating_entities`; Config non verifica la compilazione XPath sul motore
esterno. Non trasforma espressioni relazionali in semplici controlli di presenza.
Per NX-005 conserva il target e il matching esatti dell'espressione fornita:
non sostituisce `operatingPeriods/*` con UicOperatingPeriod né aggiunge @version.

I contratti non XML iniziali sono limitati alle seguenti definizioni JSON nella
stringa `definition`; lingua `1`, risultato `violating_entities`:

| Tipo | Definizione | Opzioni esplicite richieste |
|---|---|---|
| `csv_expression` | `{"predicate":"required_columns","columns":["id","line"]}` | `{"delimiter":";","encoding":"utf-8","header":true}` |
| `spreadsheet_expression` | `{"predicate":"required_columns","columns":["id"]}` | `{"sheet":"Journeys","header_row":1}` |
| `text_expression` | `{"predicate":"matches","pattern":"^[0-9]+$","scope":"line"}` | `{"encoding":"utf-8"}` |

Sono validate struttura, colonne uniche, opzioni e sintassi regex locale.
Questi contratti non certificano esiti su CSV/Excel/TXT: il futuro validator
stabilirà lettura dati, trattamento celle vuote/tipi/formule, versione del
motore e limiti runtime. Non si eseguono formule, macro o controlli in Config.
`application_state` resta non supportato finché fonte e fase EA sono definite.


## Ricostruzione del modello in sviluppo (026)

Il percorso di sviluppo non converte i vecchi frammenti: i loro modelli,
collegamenti, editor e comando `migrate_validation_catalog` sono rimossi.
Le migrazioni storiche restano nella catena; le nuove migrazioni rimuovono
le tabelle obsolete anche quando si costruisce un database da zero.

Per identificare il target senza modificarlo:

```bash
uv run manage reset_config_database --show-target
```

Il reset cancella lo schema `public` del database configurato: usarlo solo sul
proprio ambiente di sviluppo, dopo aver verificato il target. Richiede
`DEBUG=True`, PostgreSQL, alias `default` e il nome esatto del database; i nomi
PostgreSQL di sistema sono respinti.

```bash
uv run manage reset_config_database --confirm-database NOME_DATABASE
```

Il comando applica le migrazioni e carica il seed target. `--skip-seed` applica
solo le migrazioni. Non modifica Keycloak o storage condiviso. Il seed da solo
non cancella dati né ricostruisce lo schema:

```bash
uv run manage seed_target_demo
```

Anche `seed_target_demo` richiede `DEBUG=True`: crea l’utente locale di sviluppo
`dummy_admin` con password `dummy_admin`, cataloghi NeTEx/SIRI e CSV, il profilo
`validation-demo_001` con indicatore composto e il contratto `DEMO-CONTRACT-001`.
La revisione approvata usa `canonical-json-v2`; padre e dipendenza conservano
parametri propri. Il secondo seed conserva snapshot, checksum e data di
approvazione. Un vecchio contratto demo con profilo/schema diverso viene
respinto e richiede una ricostruzione esplicita del target di sviluppo.

Per creare solo i cataloghi dimostrativi con un amministratore esistente:

```bash
uv run manage init_indicator_catalog --actor NOME_UTENTE
uv run manage seed_validation_demo --actor NOME_UTENTE
```

Il secondo comando crea i profili `validation-demo_001` (XML) e
`validation-csv-demo_001` (CSV), senza creare contratti. I seed respingono
versioni con definizioni diverse; non aggiornano le versioni pubblicate.
I riferimenti a processi sono fixture dichiarative: il provisioning e
l’esecuzione del futuro validator restano esterni a Config.

Le fixture CSV in `tests_integration/exchange_agreement/fixtures/` dichiarano:

| File | Caso da verificare nel futuro validator |
|---|---|
| `validation_csv_valid.csv` | Tutte le colonne richieste presenti |
| `validation_csv_missing_identity.csv` | Manca `journey_id`: regola `reject_import` |
| `validation_csv_missing_timestamp.csv` | Manca `source_timestamp`: regola `warn` |
| `validation_csv_missing_line.csv` | Manca `line`: compatibilità della dimensione Linea |

I test Config verificano catalogo, policy, dimensioni, idempotenza e coerenza
tra colonne delle fixture e definizioni; non certificano esiti di esecuzione.
Bundle XSD e capability XPath/CSV/Excel/TXT sono verificati nei rispettivi test;
restano da integrare il corpus CORSE_PDE completo e gli smoke del runtime esterno.

## Corpus CORSE_PDE (026)

La trascrizione versionata delle 15 righe dell’Excel del collega è in
`src/rpsd_config/exchange_agreement/data/corse_pde.json`, con SHA-256 della
fonte, classificazioni, ambiti, dimensioni e versioni XPath originali.
Il catalogo eseguibile sul file comprende NX-000 (XSD) e NX-001–013 (XPath).
WF-001 resta esclusa: fonte e fase dell’approvazione EA non sono definite.
Il profilo è una fixture dei requisiti del file, non una certificazione
completa del processo CORSE_PDE né un’implementazione del suo calcolo.

Il bundle e l’esempio 5T sono in
`tests_integration/exchange_agreement/fixtures/corse_pde/upstream/`.
Provengono dal checkout locale `5Tsrl/netex-italian-profile`, commit
`cecb0cde1820650af1d7b829107bef1ee8635ed7`; i contenuti originali conservano
le proprie note di copyright. Il bundle contiene i sette XSD della chiusura
include/import e `manifest.json` con entrypoint `NeTEx_publication_Lev5.xsd`.
Gli hash dei file e dello ZIP sono nel corpus. Non si scaricano XSD remoti.

Per caricare il catalogo su un target scelto:

1. Nell’interfaccia asset caricare lo ZIP come `netex.zip`, tipo NeTEx XSD,
   e attivarlo esplicitamente. Annotare l’ID dell’asset.
2. Eseguire con un amministratore di piattaforma:

```bash
uv run manage seed_corse_pde_catalog --actor NOME_UTENTE --schema-asset-id ID_ASSET
```

Il comando crea `netex-corse-pde_001`, l’indicatore fixture
`corse-pde-file-checks_001` e il profilo `corse-pde-file-demo_001`; non crea
contratti, utenti, deployment o risultati. Il seed richiede il bundle attivo
con il checksum esatto. Un asset diverso, una versione ritirata o una
composizione pubblicata incompleta/differente producono un errore, senza
completamenti silenziosi. La seconda esecuzione conserva le versioni pubblicate.

NX-000 è una regola dataset con `reject_import`; i 13 XPath sono requisiti
associati direttamente alla versione indicatore. Nel piano pubblico sono
rappresentati dal marker di compatibilità `indicator_only`. «Bloccante» nel
foglio significa impatto `calculation` sull’indicatore, non rifiuto del dataset.
Le altre regole hanno impatto `dimension`, con tutte le dimensioni della riga.
NX-006 dichiara anche il namespace `xs`; le versioni 1.0/2.0/3.1 sono conservate.
NX-005 mantiene il target originale `operatingPeriods/*`: il predicato non
restringe il tipo al solo UicOperatingPeriod. Gli XPath sono trascritti come
fixture del collega, senza certificazione aggiuntiva della semantica business.

La directory fixture include un XML positivo per i 13 XPath, 13 casi negativi,
un file con radice XSD errata e `cases.json` con gli esiti attesi. Il caso
NX-008 viola anche NX-010: gli esiti non vengono forzati a una sola regola.
Gli XML sintetici testano gli XPath; non sono esempi di documenti validi Lev5.
Per il positivo XSD si usa l’esempio originale 5T con checksum congelato.

Per ripetere il controllo delle fixture con dipendenze temporanee isolate:

```bash
uv run --no-project --with saxonche==12.9.0 --with lxml==6.0.2 \
  python scripts/verify_corse_pde_corpus.py
```

La verifica conferma: esempio 5T valido XSD, NX-004 con 1 violazione e NX-013
con 4; caso XPath positivo e tutti i casi negativi conformi agli attesi.
Il report indica lo scope «isolated engines; no Prefect or ingestion».
Il controllo usa SaxonC-HE 12.9 per tutti gli XPath e lxml 6.0.2 per l’XSD;
non attesta la compatibilità degli XPath 1.0 con altri motori. Le dipendenze
non sono aggiunte al servizio Django. [API Saxonica](https://www.saxonica.com/saxon-c/doc12/python/xpath_processor.html).

## Cataloghi e revisioni nell’interfaccia (025)

Il catalogo tecnico permette di consultare la definizione completa di una regola,
modificare le bozze e pubblicarle. Dal dettaglio di una versione pubblicata,
«Nuova versione» copia la definizione in una nuova bozza: la versione pubblicata
rimane immutabile. Per eliminare una bozza è richiesta la conferma nel form.
Queste operazioni sono riservate agli amministratori di piattaforma.

Nei collegamenti al dataset, «Blocco dell’import» (`reject_import`) e «Avviso
dataset» (`warn`) indicano controlli da applicare a ogni trasferimento di quel
dataset. I requisiti indicatore sono configurati separatamente e sono inclusi
solo per gli indicatori effettivi del contratto. Nei collegamenti agli indicatori, `calculation` significa
che le entità non conformi non contribuiscono al calcolo; `dimension` indica
la perdita delle disaggregazioni selezionate. L’impatto sull’indicatore non
modifica la politica di import del dataset.

Il dettaglio del profilo mostra indicatori selezionati, dipendenze implicite,
percorsi di provenienza e controlli per input. È un’anteprima della
configurazione: Config non esegue le regole e non produce esiti sui file.
«Schema input», «Schema output», «Processo di validazione Prefect» e «Processo
di calcolo Prefect» distinguono i rispettivi campi tecnici.

Nella revisione in bozza, gli editor autorizzati possono salvare parametri,
soglie, aggregazioni e penalità di ciascun indicatore selezionato o implicito.
I valori sono propri della revisione e non sono ereditati dall’indicatore padre.
Cambiare gli indicatori selezionati rimuove i valori delle dipendenze non più
necessarie. L’admin globale espone i valori delle dipendenze in sola lettura;
le modifiche passano dal flusso contrattuale autorizzato.

La revisione approvata distingue decorrenza futura, attuale o conclusa e mostra
valori e controlli dallo snapshot congelato, separando regole dataset e
compatibilità degli indicatori. Uno snapshot incoerente produce un messaggio
diagnostico. Eventuali snapshot v1 restano consultabili come JSON; gli editor
dei frammenti sono rimossi nel percorso di sviluppo 026.
Il permesso di amministrare i cataloghi non attribuisce l’approvazione dei
contratti: questa richiede il ruolo business nel relativo perimetro.

## Piano di validazione congelato (022)

Le nuove revisioni approvate conservano sempre uno snapshot `canonical-json-v2`. Include input e asset, catalogo deduplicato delle
regole, politiche di import, consumatori, dipendenze, ordine di calcolo e valori
contrattuali separati. L'approvazione ricontrolla configurazione e parametri e
calcola il checksum nella stessa transazione. Gli snapshot legacy rimangono v1:
non vengono riscritti o arricchiti leggendo il catalogo corrente.

Il consumer interroga:

```text
GET /exchange_agreement/api/m2m/v3/contracts/{contract_code}/validation-plan?data_category=netex
Authorization: Bearer <token>
```

È ammesso un solo parametro `data_category`; categorie non configurate non
producono un piano vuoto. La data è quella del server. L'autorizzazione M2M
richiede azienda titolare e grant ingest valido per contratto/categoria; il
servizio validator può usare un client esplicitamente autorizzato tramite
VALIDATION_M2M_ALLOWED_CLIENT_IDS. Un token valido da solo non concede accesso.

La risposta `validation-plan-v1` contiene il solo input richiesto e le sue
regole, con consumatori e provenienza, oltre alla chiusura degli indicatori e
alle configurazioni congelate. `scope=transfer` indica che descrive il
contributo di quel file; non attesta disponibilità degli altri input o
calcolabilità globale. Config non esegue le regole.

`configuration_revision_code`, `snapshot_schema_version` e `snapshot_checksum`
identificano lo snapshot completo. `plan_digest` è il SHA-256 del JSON canonico
del piano senza il proprio campo digest; non è il checksum dello snapshot
completo. Il consumer deve verificare questo digest e conservare contenuto e
identità del piano all'ammissione. I retry riusano quel contenuto: richiamare
l'endpoint current-only potrebbe restituire una revisione successiva. Config
non conserva job/transfer e non certifica la persistenza dei retry in ingest.

La serializzazione conserva le convenzioni v1: chiavi ordinate, UTF-8/Unicode,
null e liste vuote, interi e booleani; Decimal è una stringa decimale. I float
non sono ammessi nel JSON canonico. Il reader rifiuta strutture incomplete,
regole duplicate o mancanti, consumatori incoerenti, configurazioni incomplete
e ordine di calcolo non coerente. La lettura del piano non interroga cataloghi
live di indicatori/regole. Anche i metadati contratto/revisione sono verificati.

Gli errori usano l'envelope `error` con code, message e correlation_id:
401 authentication_failed, 403 ingest_not_authorized, 404 contract_not_found,
422 invalid_request, 503 configuration_service_unavailable e 409 per contratto
non efficace, configurazione non pronta/incoerente o categoria non configurata.
Per snapshot v1 il piano target restituisce `validation_plan_not_available`:
serve una nuova revisione target. Non deduce policy dalla severity legacy.
Gli endpoint operativi v1/v2 restano verificati con fixture contrattuali.
I campi `structures`, `fragments` e `required_fragments`, ove presenti nei
payload v1, sono elenchi vuoti; il catalogo `/v1/structures` è rimosso.
Gli input e gli indicatori che li richiedono derivano dai metadati congelati
`required_by_indicator_versions`; le regole complete sono esposte dal piano v3. Audit del piano include revisione, categoria, schema e checksum senza
registrare token, definizioni di regole o contenuto dei dataset.

## Dismissione dei file YAML indicatori (026)

Gli indicatori si definiscono nel catalogo tecnico versionato. La configurazione
piattaforma collega al catalogo e conta le versioni pubblicate per lo stato di
inizializzazione; non richiede più un file YAML attivo. Upload e attivazione dei
vecchi profili indicatori non sono supportati. Modello IndicatorProfile e proxy
admin sono rimossi. Gli asset configurazione ammettono soltanto NeTEx XSD e
profili SIRI: il controllo è applicato anche a livello database.

Le migrazioni admin 0012 / exchange_agreement 0047 rimuovono lo schema del
profilo YAML e i metadati ConfigurationAsset di tipo indicator_yaml, inclusi
collegamenti obsoleti e relativi eventi. Conservano gli asset dataset e i campi
execution_reference/artifact_identifier delle versioni indicatore. Non
eliminano file fisici, non contattano storage, broker, Keycloak o Prefect.
La funzione upload_to storica resta solo per applicare la migration 0019.

Il passo è riferito all’ambiente di sviluppo senza dati da conservare concordato.
La pulizia dei metadati è irreversibile: non si recupera lo schema precedente
semplicemente tornando al vecchio codice. Applicare le migrazioni al proprio
target verificato oppure usare la ricostruzione esplicita di sviluppo descritta
sopra. Questa consegna non ha migrato né resettato il database applicativo.

## Verifica finale provider Config (027)

Verificato il 12 ottobre 2026: 210 test di cataloghi, transazioni concorrenti,
binding, DAG, parametri, revisioni, snapshot, UI/RBAC, bundle, seed, cleanup e
API v1/v2/v3. Esecuzione nella copia isolata `/tmp/rpsd-validation-cutover-test`
con `PYTHONPATH` puntato ai suoi sorgenti e `UV_PROJECT_ENVIRONMENT=/app/.venv`:
La suite elencata nei task 027 è stata eseguita con `uv run --no-sync pytest`
e opzioni `--create-db --no-cov -q --tb=short -x`.
`--create-db` ricostruisce il database di test; non è un comando per aggiornare
il database applicativo. Django check e makemigrations --check --dry-run passati.

I documenti [modello dati](docs/modello_dati.md),
[diagramma ER](docs/modello_dati.mmd) e
[anteprima](docs/modello_dati_preview.md) descrivono il dominio attuale; il diagramma omette
esplicitamente audit/membership/inviti. Nomi e cardinalità delle 44 FK di 31
entità sono verificati contro i metadati Django.

La pubblicazione si svolge in Django e verifica il riferimento configurato;
non richiede una chiamata a Prefect. Il registry espone contratti degli interpreti
con runtime `external_not_verified`. Config non conserva esiti di trasferimento
né avvia i job. Il futuro container validator interrogherà il piano v3 e gli
asset autorizzati; ownership/repository, pin e persistenza del piano, esecuzione,
retry/callback, ammissione e smoke Prefect sono ancora handoff esterni.
La QA CORSE_PDE isolata non equivale allo smoke del servizio.

Non sono stati migrati o resettati i dati applicativi né attivato un rollout.
Per il percorso di sviluppo usare separatamente i comandi di migrazione,
reset e seed già documentati, verificando il target prima di operare.

## Attivazione locale del provider target — 12 ottobre 2026

Il container locale precedente conteneva sorgenti antecedenti alla 019; monta
soltanto `.env`, quindi le modifiche al workspace richiedono una nuova immagine.
È stato aggiornato esclusivamente Config sul target di sviluppo verificato
`rpsd@config-db:5432/public`, con `DEBUG=True`. Operazioni eseguite dal repo rpsd:

```bash
docker compose --profile config build rpsd-config
docker compose --profile config stop rpsd-config
docker compose --profile config run --rm --no-deps rpsd-config \
  uv run --no-sync manage migrate --noinput
docker compose --profile config run --rm --no-deps rpsd-config \
  uv run --no-sync manage seed_validation_demo --actor dummy_admin
docker compose --profile config up -d --force-recreate --no-deps rpsd-config
```

Applicate 11 migrazioni fino a exchange_agreement 0047 e admin_dataset_exchange
0012. Nessun reset dello schema: utenti, contratti e revisioni esistenti sono
conservati. Le tabelle obsolete di frammenti/mapping/profili YAML sono rimosse;
i file fisici non sono stati cancellati. Il controllo del target precede ogni
applicazione: questi comandi non identificano implicitamente un ambiente sicuro.

Il seed additivo ha pubblicato `validation-demo_001` (XML e indicatore composto)
e `validation-csv-demo_001` (CSV), con 6 versioni regola. La seconda esecuzione
ha conservato numero e contenuto delle versioni, stati e timestamp pubblicati.
Verificati: zero migrazioni pendenti, 4 utenti, 2 contratti, 4 revisioni con gli
stessi checksum precedenti, Django check positivo. HTTP locale: home/login 200,
API piano v3 senza token 401. Non è uno smoke autenticato del futuro validator.

I contratti precedenti restano su snapshot v1. Per adottare il target, creare
una nuova revisione con un profilo target e approvarla tramite il normale flusso
contrattuale; questo genera canonical-json-v2 e rende disponibile il piano v3.
La pubblicazione dei profili non riscrive le revisioni approvate. Il corpus
CORSE_PDE non è caricato sul DB locale: richiede il suo bundle XSD attivo esatto
tramite il comando dedicato documentato sopra. Nessun deployment è provisionato.

Le note precedenti «database applicativo non modificato» si riferiscono alle
verifiche isolate; questo passo ha applicato le migrazioni e il seed al database
locale di sviluppo. Non sono stati eseguiti rollout su altri ambienti.


## Guide contestuali dell’admin Django (028)

Nell’admin Config i campi hanno etichette e spiegazioni in italiano, anche quando
la versione è pubblicata o la revisione è approvata. Le sezioni distinguono
identità/versione, configurazione, processi, stato/validità e audit. I codici
tecnici, i valori degli enum e le chiavi JSON delle API restano gli stessi.

Aprire «Esempio» per consultare e copiare una definizione. Gli esempi non
compilano i campi e non vengono salvati automaticamente. Per una regola usare
la combinazione coerente di tipo, linguaggio, risultato, definizione e opzioni:
XPath/XML, bundle XSD/XML, CSV, XLSX o TXT. La guida del bundle CORSE_PDE indica
l’archivio e il digest reali della fixture: occorre collegare l’asset corrispondente,
non copiare quel manifest per un file diverso.

Le associazioni mostrano la versione del dataset, quella della regola e la
politica di import. L’impatto sull’indicatore distingue perdita di calcolabilità
per le entità non conformi e perdita delle dimensioni di disaggregazione.
Nelle dipendenze **A dipende da B**; le dimensioni richieste a B sono distinte
dalle dimensioni interessate dal KO di una regola.

Gli schemi input/output descrivono il processo; lo schema dei parametri descrive
valori ammessi e obbligatori. Parametri, soglie, aggregazione e penali effettivi
appartengono alla revisione contrattuale, separatamente per ogni indicatore e
prerequisito. Il dettaglio dei valori delle dipendenze resta in sola lettura:
«Apri il workflow web della revisione» compare solo per chi ha i permessi di
preparazione sul contratto. Una revisione approvata richiede una nuova bozza
per cambiare i valori; una decorrenza futura non la riporta allo stato draft.

I riferimenti Prefect descrivono i processi esterni di validazione, importazione,
orchestrazione o calcolo. La pubblicazione in Django verifica la configurazione
locale e non avvia né certifica la disponibilità di un deployment Prefect.
Stato editoriale, validità del contratto e stato dell’invio di un evento sono
spiegati separatamente. Provenienza automatica e identità dei bundle conservati
sono consultabili in sola lettura.

Gli aiuti degli inline sono testo apribile con `details/summary`, senza librerie
esterne o JavaScript aggiuntivo. Gli esempi lunghi hanno ritorno a capo e un
blocco selezionabile; la verifica visuale su tastiera e viewport ridotto resta
da completare perché nella sessione di implementazione non era disponibile
un browser collegato. Il rendering e i vincoli sono verificati sul DB di test.


Aggiornamento locale del 12 ottobre 2026: ricostruito e ricreato il solo container
Config. Login admin e CSS HTTP 200; API M2M anonima HTTP 401. Il confronto dei
conteggi applicativi e del digest degli snapshot conferma dati invariati.
La feature non richiede migrazioni o una nuova applicazione dei seed.

### Persistent configuration assets in local development

The platform Compose service mounts `rpsd-config/mnt/config-assets` at
`/tmp/rpsd-config-assets`. With `CONFIG_ASSETS_STORAGE_PROVIDER=fs` and
`CONFIG_ASSETS_STORAGE_FS_BASE_PATH=/tmp/rpsd-config-assets`, asset files and
their storage metadata survive container recreation. The host directory is
ignored by Git. Keep this path aligned with the mount when changing settings.
Before adding the mount to an existing installation, copy any files from the
old container directory to the host directory before recreating the container.
This development mount does not configure production storage; use persistent
storage or the existing S3 provider for production.

Admin field help identifies the integration in parentheses: `(rpsd-storage)`
for asset storage data and asset links, and `(rpsd-transport)` for RabbitMQ
notification data. SHA-256 and bundle manifests remain computed by Config;
these annotations do not change validators or model fields.

### Indicator selections belong to the contract revision (029)

Prepare a draft revision, select a published technical profile, then choose
indicator versions admitted by that profile. The admin inline is named
“Indicatori della revisione”; there is no separate “Contract indicators” menu.
Each ContractRevisionIndicator stores thresholds, aggregation, penalties and
parameters for that revision. The logical indicator is derived from the selected
profile entry. A new revision may add, remove or replace indicators without
changing earlier revisions. Approved and withdrawn selections remain immutable.
Only one version per logical indicator can be selected in a revision.

Migration 0048 audits historical selections, preserves their IDs/values and
frozen snapshot/checksum fields, and removes the redundant contract-level link.
It refuses inconsistent or duplicate selections. Do not reset or reseed the
application database to apply it; test the migration and retain a backup before
rollout. Returning to an older binary after the drop requires a matching database
restore. Existing API and snapshot schema versions are unchanged.

## Asset tecnici dataset generalizzati (feature 030)

Nella Configurazione Piattaforma aprire **Asset tecnici dataset** (`?tab=asset`).
Scegliere tipo, codice esplicito, etichetta e file. Il codice (massimo 64 caratteri,
lettere minuscole/numeri/trattini/underscore, primo carattere alfanumerico) è
indipendente dal nome originale e dal dataset. Il limite upload predefinito è 128 MiB, configurabile in ambiente.

Tipi: schema XSD singolo, bundle XSD ZIP, schema JSON, documento, archivio o altro
file tecnico. Gli archivi generici sono byte opachi; soltanto i bundle XSD e
gli ZIP dei tipi di compatibilità NeTEx/SIRI producono un manifest XSD. Config
controlla la sintassi JSON, non esegue il JSON Schema contro un dataset.

Nel dettaglio della specifica dataset in bozza scegliere **Aggiungi asset**,
ruolo e obbligatorietà. È possibile condividere lo stesso asset tra più
versioni dataset. Il file non è un conferimento TPL né un documento contrattuale.

Anche l'admin Django **Configuration assets** offre un upload guidato. I
metadati di storage e integrità sono generati e restano in sola lettura; si
modifica l'etichetta oppure si carica una nuova versione. Attivazione e
archiviazione passano dalle azioni dedicate. La versione attiva è preferita per
nuovi usi e non sostituisce le versioni già associate o congelate nei contratti.

La chiave API `what` resta il codice dell'asset. Il segmento storicamente
chiamato `dataset_code` in `/v3/validation-assets/{asset_type}/{dataset_code}/{version}/download`
risolve quel codice asset; le URL precedenti rimangono valide. I byte sono
conservati tramite `rpsd-storage`, gli eventi notificati tramite `rpsd-transport`.

Per esempi ripetibili, eseguire esplicitamente nel runtime Config:

```bash
uv run manage seed_dataset_asset_examples --actor dummy_admin
```

Il comando crea tre risorse deterministiche (bundle XSD, istruzioni TXT e
colonne CSV) condivise da due specifiche dataset demo in bozza. Non azzera dati,
non crea contratti e non pubblica specifiche o runtime. Riuso di contenuto
identico verificato; un conflitto richiede revisione esplicita e non viene
sovrascritto. Il comando non viene eseguito automaticamente dal bootstrap.

La migrazione `0049_generalize_configuration_assets` conserva identità e
riferimenti esistenti. Codici legacy vuoti/non validi producono un errore con
gli ID da revisionare, senza assegnare automaticamente nuove identità. Dopo
l'introduzione di asset di tipi generici, il vecchio binario non è compatibile:
il rollback richiede DB/storage coerenti o una correzione in avanti.

## Raffinamenti del modello e dell'admin (031)

Le versioni regola selezionano un solo «Tipo di validazione e versione del
linguaggio» dal catalogo Django precaricato (sette coppie). Definizione, opzioni,
formato e risultato continuano a essere controllati dal registry; Config non
verifica che i deployment esterni siano disponibili. API e snapshot mantengono
le chiavi tecniche tipo/versione, senza esporre ID locali del catalogo.

Nella versione indicatore gestire «Dataset richiesti» e «Indicatori prerequisiti»,
con le dimensioni richieste nella riga del prerequisito. Le relazioni usano M:N
Django attraverso le tabelle esistenti. Nel processo di input consultare i profili
utilizzatori; la composizione si modifica dalla bozza del profilo.

Nella revisione contrattuale gestire «Valori degli indicatori prerequisiti»:
valori indipendenti da quelli dell'indicatore padre, solo per prerequisiti effettivi.
Occorre poter preparare quel contratto; il solo ruolo platform admin non basta.
Dopo approvazione o ritiro, valori e composizioni restano consultabili e congelati.

Gli eventi sono nel gruppo admin «Storico e notifiche». Sono consultabili per
periodo/stato/autore ove presenti, con ricerca per codice e navigazione all'oggetto.
Non si creano, modificano o cancellano manualmente. «Ritenta invio» richiede il
permesso `admin_audit.retry_configurationassetevent` (oltre alla consultazione)
e tratta soltanto le notifiche pending/failed selezionate. Con publisher spento
non invia e lo segnala. I retry conservano ID/payload e possono richiedere una
consegna ripetuta se una precedente conferma è andata persa.

Il flag «Asset obbligatorio» riguarda una risorsa già associata, indispensabile
alla lavorazione (es. XSD/mapper), rispetto a un manuale accessorio. Non scopre
associazioni mancanti e non imposta la politica di rifiuto del conferimento.
Config oggi controlla lo stato attivo alla pubblicazione della specifica e
propaga il flag nel piano; i controlli runtime di recuperabilità/integrità e
l'eventuale blocco della lavorazione spettano al futuro consumer.

Le soglie tecniche si configurano in `.env` e sono descritte in `.env.example`:

| Impostazione | Default | Unità |
| --- | ---: | --- |
| CONFIG_ASSETS_MAX_UPLOAD_BYTES | 134217728 | byte caricati |
| CONFIG_ASSETS_XSD_MAX_TOTAL_BYTES | 134217728 | byte totali decompressi del bundle |
| CONFIG_ASSETS_XSD_MAX_FILE_BYTES | 8388608 | byte per elemento del bundle |
| CONFIG_ASSETS_XSD_MAX_FILES | 4096 | elementi nell'archivio ZIP |

Devono essere interi positivi. Sono limiti delle risorse del deployment, non dati
di dominio: per questo non esiste una tabella modificabile nell'admin. Riavviare
Config dopo una modifica. L'admin mostra i valori effettivi; eventuali limiti di
proxy/webserver possono essere inferiori. Ridurre le soglie può rendere non più
utilizzabili bundle precedentemente ammessi: pianificare la variazione rispetto
agli asset esistenti. Gli archivi generici non subiscono ispezione XSD.

I profili NeTEx/SIRI legacy e la scheda inizializzazione sono dismessi. I bookmark
`?tab=inizializzazione` portano agli asset; i quattro POST legacy restituiscono
400 senza effetti. Prima del drop, inventariare con
`uv run manage recover_legacy_validation_profiles`; se necessario eseguire con
`--apply` per recuperare i byte nel catalogo asset. Il recupero riusa contenuti
identici e non elimina i file originali né cambia le associazioni pubblicate.
La migrazione rifiuta il drop se un file non è verificabile nell'asset collegato.
Dopo il drop, il rollback richiede un ripristino DB coerente, non il solo binario.
Non è necessario eseguire reset o seed sul database applicativo per aggiornare.

## Indicator parameters, evaluation thresholds and penalties (032)

In a contract revision, open **Parametri, soglie e penali** for the selected
indicator. The technical IndicatorVersion declares the accepted parameters and
output metrics. Each contract revision supplies its own parameter values;
changing the included lines does not require another technical indicator version.
Parameters schema v1 remains readable. Schema v2 adds homogeneous scalar arrays,
min_items/max_items/unique_items and an optional reference_namespace describing
technical IDs. Numeric v2 parameters can use finite decimal strings, avoiding
floating-point serialization. Public line labels are not inferred from technical IDs.

Soglie and Penali are child records of ContractRevisionIndicator. Django admin
lists them in Agreements; contextual links are in the revision's indicator inline.
The admin lists offer Add followed by a selection of the draft revision indicator;
contextual links can preselect it with `?owner_id=<revision-indicator-id>`.
The revision indicator also has its own admin page with native threshold/penalty
inlines. Django permissions and contract scope are enforced in every path.
Evaluation forms and write services are shared with the web UI.
Only draft revisions can change; approved and withdrawn content is readonly.

A threshold selects an output metric, its supported aggregation, grouping,
violation operator, decimal limit, severity and missing-data policy. The
operator describes a violation: maximum 3 means `> 3`, from 10 inclusive means
`>= 10`. Missing results are never silently treated as zero. `average` is
permitted only when advertised by the metric; no automatic average of averages.

Periods are daily, ISO weekly, monthly, yearly, whole contract, or one custom
window. All dates are inclusive and use an explicit IANA timezone:

- custom_range: X through Y; X=Y is a single day;
- custom_to_contract_end: Z through the known contract end;
- custom_duration_days: K for N calendar days; last day is K + N - 1.

For example, 2026-10-10 for 3 days ends on 2026-10-12. N is a positive integer;
custom periods are not recurring jobs. Contract-wide/to-end windows need a known
end before approval. The snapshot freezes resolved dates and their contract
source. A later extension does not reinterpret historical snapshots. The explicit
partial-period choice is either evaluate_partial (same limit, no proration) or
complete_only (not evaluable when the revision covers only part of the window).
A runtime must stop attributing data to a revision at the next effective revision;
no implicit carry-over of occurrences between snapshots is allowed.

All penalties are **cumulative**. Daily and monthly clauses may both apply;
storni and negotiated agreements are outside RPSD. Supported configurations:

- fixed_amount: one fixed amount per applicable group/period;
- per_unit: max(0, aggregated quantity - allowance_quantity) × unit_amount;
- external: a versioned executor advertised in the published output contract.

Per-application maximum_amount is applied before final commercial ROUND_HALF_UP
rounding to EUR cents. Quantities, coefficients and limits have six decimal
places. The maximum is not a shared annual/contract cap. With an activation
threshold, the penalty inherits period, timezone and dimensions. Without one,
its own context is required. A different economic metric must support the same
grouping. A linked threshold cannot be deleted until its penalties are changed
or removed in the draft. Cloning remaps every threshold reference.

Output schema v2 uses `metrics` with code, numeric type, unit, grain, dimensions
and supported aggregations. count_distinct also requires distinct_key. External
penalty configuration is allowed only when the exact technical version declares
penalty_executor with execution_reference, artifact_identifier, parameter_schema
and result_contract=`monetary-report-v1`. The agency cannot substitute arbitrary
execution code or a different schema. Saving/approving never contacts Prefect.

### Snapshots and runtime API

Existing canonical-json-v1/v2 snapshots and their checksums are preserved. New
rules or parameter/output schemas v2 produce canonical-json-v3 with
`evaluation_configurations`, decimal strings, local rule codes, resolved contexts
and `penalty_combination_policy: cumulative`. The validation-aware consumer uses:

```text
GET /exchange_agreement/api/m2m/v4/contracts/{contract_code}/validation-plan?data_category=netex
```

Authentication/grant and current-date rules match v3. A v3 snapshot is exported
as validation-plan-v2, with its frozen evaluation configurations. The v4 endpoint
also accepts canonical-json-v2 and returns validation-plan-v1. Legacy v1 has no
frozen validation definitions and is not promoted to an executable plan.
Old v1/v2/v3 ingest/validation consumers receive 409
`unsupported_evaluation_configuration` on a v3 snapshot rather than a payload
that silently drops economic clauses. API publication/snapshot downloads remain
verbatim historical documents. Consumers must check schema versions and retain
snapshot checksum/plan digest for every job and retry.

Config stores configuration only. The external runtime must report the metric,
period/group, threshold violations, clause code, measured/admissible quantity,
raw/capped/rounded amount, currency, snapshot checksum and job/attempt identity.
It must distinguish missing/partial/provisional/error results from conforming
results, avoid duplicate charges on retries, and handle corrected/late data.
`monetary-report-v1` is a handoff contract, not evidence of a deployed executor.

### Inventory, examples and upgrade

```bash
uv run manage inventory_indicator_evaluations
uv run manage inventory_indicator_evaluations --check
uv run manage seed_indicator_evaluation_demo --actor YOUR_PLATFORM_ADMIN
```

The inventory is read-only and works before the new evaluation tables exist.
Non-empty legacy economic JSON is reported for explicit mapping, never guessed
or cleared. Old JSON columns remain for historical compatibility; ordinary
admin/web write paths use child tables and reject economic JSON changes.
Legacy dependency JSON is reported too; technical prerequisites do not inherit
penalties. Standard existing seeds remain compatible and write empty economic
JSON, while the new additive command supplies the complete typed examples.

The evaluation seed creates a published technical profile and two **draft** demo
contracts with different line lists, daily/monthly thresholds, all three custom
windows, and fixed/per-unit examples. Dates are explicit (2026), not today-based.
Re-running verifies definitions and refuses conflicts rather than overwriting
approved or divergent data. It does not deploy processes or approve contracts.
No seed or reset is implicit in migration/startup.

Before rollout, back up the DB, inventory legacy values and test migrations
0055/0056 plus Agreements proxy migration 0009 on a restored copy. Verify old
row digests and snapshot checksums, then use `uv run manage migrate --noinput`.
Rollback requires a matching binary/DB restoration plan: downgrading code alone
cannot make v3 snapshots readable to old runtime consumers. Do not drop the new
tables once they contain contractual data without a reviewed preservation plan.

### Gestione di soglie e penali nel Django admin

In **Agreements → Indicatori delle revisioni contrattuali**, aprire un indicatore
già selezionato nella revisione. La pagina raccoglie parametri e aggregazioni,
con due sezioni inline native Django: **Soglie di valutazione** e **Penali
cumulative**. Usare “Aggiungi” nella sezione desiderata e salvare la pagina.
Per associare una penale a una nuova soglia, salvare prima la soglia.

La stessa pagina è raggiungibile dall'inline degli indicatori di una revisione,
tramite **Gestisci indicatore, soglie e penali**. Contratto, revisione e versione
indicatore restano fissi: per cambiare la selezione si torna alla revisione.
Le modifiche sono consentite soltanto nelle bozze e secondo i permessi del
contratto; le configurazioni approvate o ritirate sono consultabili.
La migrazione admin `0010` registra solo il proxy e i relativi permessi:
non aggiunge tabelle di dominio e non esegue seeding.

È possibile iniziare anche dagli elenchi **Soglie degli indicatori contrattuali**
e **Penali degli indicatori contrattuali**: premere **Aggiungi**, scegliere un
indicatore di una revisione in bozza e premere **Continua**. La selezione iniziale
non salva dati. Il modulo successivo offre solo le metriche, dimensioni e soglie
compatibili con quell'indicatore. Il pulsante Aggiungi è disponibile agli utenti
autorizzati quando esiste almeno un indicatore contrattuale modificabile.

### Risorse iniziali NeTEx italiano livello 5

```bash
uv run manage seed_netex_italian_profile --actor NOME_UTENTE_ADMIN
```

Il comando aggiunge la specifica XML `netex-it-lev5_001` al dataset `netex`,
con tre configuration asset attivi:

- `netex-it-lev5-schema`: ZIP dei sette XSD richiesti dal punto d'ingresso
  `NeTEx_publication_Lev5.xsd`, ruolo `validation_schema`, obbligatorio;
- `netex-it-lev5-example`: XML di esempio KPI-ART livello 5, ruolo `example`,
  facoltativo;
- `netex-it-guidelines`: linee guida italiane 5.0.1 in PDF, ruolo
  `documentation`, facoltativo.

Le risorse sono incluse in `exchange_agreement/seed_data/netex_it_lev5` con
checksum e commit di provenienza in `sources.json`. Il bundle contiene gli stessi
XSD della fixture CORSE_PDE ma il comando non dipende dai test né da repository
esterni. Lo storage usa la configurazione rpsd-storage esistente. Ripetere il
comando riutilizza i file e i record esatti; contenuti diversi o asset archiviati
vengono segnalati come conflitti, senza sostituzioni automatiche.

La specifica e la regola `netex-it-lev5-xsd@001` nascono in bozza. Per rendere
operativa la validazione, configurare il riferimento reale al validatore nella
regola, pubblicarla e associarla alla specifica con politica `reject_import`,
quindi completare la pubblicazione della specifica. Il seed non inventa deployment
Prefect, non modifica profili/contratti esistenti e non trasferisce l'XML come
dataset operativo. Le esecuzioni successive mantengono l'eventuale riferimento
esecutivo inserito dall'amministratore.

### Bundle condiviso SIRI 2.1 e asset del profilo italiano

```bash
uv run manage seed_siri_italian_profile --actor NOME_UTENTE_ADMIN
```

Il seed comprende un solo asset `siri-2-1-schema`, tipo `xsd_bundle`, archiviato
una sola volta. Contiene i 72 XSD richiesti da `siri.xsd`, con cartelle e percorsi
relativi originali, più `manifest.json`. La provenienza è il tag ufficiale
SIRI-CEN `v2.1`, commit `87fe020ec88ec091de0f69d8c26347dd108ff6f1`.
File e checksum sono inclusi in `exchange_agreement/seed_data/siri_2_1`:
il comando non scarica dipendenze da Internet durante il seeding.

Lo stesso asset è collegato alle specifiche dei dieci servizi iniziali:
PT, ET, ST, SM, VM, CT, CM, GM, FM e SX, con ruolo `validation_schema` e
`required=True`. Le linee guida italiane sono un secondo asset condiviso,
facoltativo. Per VM, ET, SX, FM e PT viene associato anche il rispettivo XML di
esempio italiano; gli altri cinque servizi non hanno esempi nel repository.
I sette asset vengono attivati usando lo storage configurato per rpsd-storage.

Se la specifica iniziale è in bozza, vengono aggiunti i collegamenti. Se è già
pubblicata e priva dei collegamenti attesi, viene creata la corrispondente
`siri-XX_v002` in bozza. `002` è la versione di Config: lo standard resta SIRI
**2.1**. Le versioni pubblicate già complete sono riutilizzate. Profili tecnici,
revisioni e snapshot contrattuali non vengono aggiornati automaticamente;
le specifiche dimostrative non fanno parte di questo seed. Un conflitto su file,
formato, versione standard o associazioni viene segnalato senza sostituzioni.

Il bundle ufficiale si compila con libxml2 e i cinque XML italiani lo superano;
la compilazione segnala tre avvisi su import ripetuti di namespace già caricati.
Questo non verifica il runtime Prefect o tutti i requisiti del profilo italiano.
Il caricamento degli asset non attiva automaticamente regole o processi:
restano da configurare la regola XSD e i controlli sul servizio SIRI atteso.
