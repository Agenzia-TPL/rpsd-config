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
non compila né esegue l'espressione XPath. Le vecchie regole `exists` restano
nel catalogo legacy e non vengono convertite implicitamente.

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
interprete supporta il formato dichiarato dalla specifica (`metadata.format`).
Per NeTEx e SIRI VM/ET il formato XML è riconosciuto anche senza tale metadato.

Ogni associazione dataset/regola ha una politica:

| Politica | Controlli da includere | Conseguenza prevista di una violazione |
|---|---|---|
| `reject_import` | Sempre per quel dataset | Il futuro validator deve rifiutare il trasferimento. |
| `warn` | Sempre per quel dataset | Il trasferimento può essere accettato con un warning. |
| `indicator_only` | Se richiesta dagli indicatori effettivi | Il giudizio riguarda gli indicatori che consumano la regola. |

Il collegamento a una versione di indicatore specifica la conseguenza distinta:
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

Le regole base si modificano solo mentre la specifica è in bozza. Su una
specifica pubblicata si possono aggiungere nuove applicazioni `indicator_only`
con regole pubblicate; le righe già pubblicate restano congelate. Questa
aggiunta non altera gli snapshot dei contratti già approvati. I collegamenti,
gli impatti e le dimensioni di un indicatore si modificano solo in bozza.
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
separatamente i riferimenti di provenienza delle versioni e i file YAML legacy.
Non elimina file o riferimenti: la dismissione operativa resta nella 026.


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
