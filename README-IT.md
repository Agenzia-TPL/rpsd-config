descrizione applicativo:

L’applicazione `exchange_agreement` governa la configurazione dei contratti di servizio TPL. Distingue l’agenzia (`Agency`), che crea lotti e contratti, l’azienda (`Company`) affidataria e l’autorità di governo (`Authority`), che ha visibilità istituzionale sui contratti associati senza controllarne la configurazione.

Su questo sfondo si colloca la modellazione della rete di servizio. Nel runtime Django corrente viene mantenuto il livello dei lotti (`Lot`) come contesto contrattuale, mentre linee, fermate e corse sono demandate a un database PostgreSQL esterno. Questo consente di mantenere in Django il dominio contratti/indicatori riducendo l'accoppiamento con il dettaglio della rete operativa.

Nota: i precedenti modelli runtime Django per il dettaglio della rete di servizio (`Route`, `Stop`, `Trip`, `TripStop`) sono stati rimossi dal runtime Django e sono ora previsti su un database PostgreSQL esterno.

Il catalogo tecnico separa i concetti stabili dalle loro versioni. `Dataset` identifica la famiglia logica e il valore canonico `what`; `DatasetSpecification` ne descrive una versione tecnica e gli asset di validazione. `RequirementFragment` individua, tramite locator tipizzato (per esempio XPath), una parte necessaria del formato e `FragmentValidationRule` esprime controlli dichiarativi che saranno interpretati dal validator esterno. Analogamente, `Indicator` è l’identità logica della metrica e `IndicatorVersion` ne rappresenta una definizione tecnica immutabile collegata ai frammenti richiesti.

Il cuore applicativo è `Contract`, associato direttamente a un lotto dell’agenzia, a un’azienda, a un’autorità di governo e al proprio periodo giuridico. La configurazione tecnica non è memorizzata direttamente sul contratto: ogni `ContractConfigurationRevision` seleziona un `ProcessingProfileVersion`, gli input e le versioni indicatore, con soglie, aggregazioni, penalità e parametri. Ogni revisione è uno snapshot completo, non una differenza dalla precedente.

Una revisione nasce `draft` ed è approvata dal platform admin dopo i controlli di coerenza. Le revisioni approvate o ritirate sono immutabili. Le API operative risolvono soltanto la revisione approvata corrente in base alla data del server, senza accettare una data dal chiamante. Una nuova revisione diventa corrente dalla propria `valid_from`; il termine della precedente è derivato come giorno antecedente. I riferimenti ai flow Prefect sono metadati opzionali: Config non distribuisce, pianifica o esegue i flow e non conserva i risultati degli indicatori.

## Setup devcontainer e Keycloak

- Il devcontainer ora avvia esplicitamente anche `keycloak` e `keycloak-db`.
- Variabili Django/OIDC sono lette da environment e, se presente, da file `.env.base` e `.env` nella root progetto.
- Puoi partire copiando uno dei file `.env.XXX.example` in `.env.base` e adattando solo i campi che ti servono in `.env`.

Riferimenti URL in locale:

- Browser host verso Django: `http://client.localhost:12080`
- Browser host verso Keycloak: `http://keycloak.localhost:19300`
- Django (in container) verso Keycloak: `http://keycloak.localhost:19300` (default consigliato)

Esempio `/etc/hosts`:

```txt
127.0.0.1 client.localhost
127.0.0.1 keycloak.localhost
```

Variabili OIDC consigliate in `.env`:

- `KEYCLOAK_DISCOVERY_URL`: endpoint usato da Django per discovery/token/userinfo (default consigliato: `http://keycloak.localhost:19300/...`).
- `OIDC_AUTHORIZATION_ENDPOINT_URL`: endpoint pubblico usato per la redirect del browser verso la login (es. `http://keycloak.localhost:19300/.../auth`).
- `OIDC_ISSUER_URL`: issuer pubblico atteso nella validazione dell`id_token` (es. `http://keycloak.localhost:19300/realms/rpsd`).
- `OIDC_FETCH_USERINFO`: se `false`, Django usa i claim dell`id_token` e non chiama l`endpoint `userinfo` (utile in setup locali con host OIDC misti).

Nota: se usi nomi custom in `/etc/hosts`, aggiungili in `DJANGO_ALLOWED_HOSTS` (e se serve in `DJANGO_CSRF_TRUSTED_ORIGINS`) nel `.env`.

## Troubleshooting OIDC callback (401)

Se il callback `/accounts/oidc/keycloak/login/callback/` risponde `401`, usa questi check:

1. Verifica i valori runtime letti da Django:

```bash
python src/rpsd_config/manage.py shell -c "from django.conf import settings; print(settings.SOCIALACCOUNT_PROVIDERS)"
```

2. Verifica che il token endpoint accetti `client_id` e `client_secret`:

```bash
curl -X POST "http://keycloak.localhost:19300/realms/rpsd/protocol/openid-connect/token" \
  -H "content-type: application/x-www-form-urlencoded" \
  --data "grant_type=client_credentials&client_id=django&client_secret=django-secret"
```

3. Riprova il login e leggi il log di Django: ora viene stampata la causa precisa
   (errore OAuth/state/session) tramite `RpsdSocialAccountAdapter`.


esempio:
http://client.localhost:12080/invite/6bf9bc71-45ca-4218-93bb-f4293a6f99b2/

## API (Django Ninja)

Base path API:

- `/exchange_agreement/api/`

Documentazione API:

- Swagger UI: `/exchange_agreement/api/docs`
- OpenAPI JSON: `/exchange_agreement/api/openapi.json`

Endpoint principali (v1; le letture con forma legacy sono proiezioni di
compatibilità):

- Contratti
  - `GET /exchange_agreement/api/v1/contracts`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/flow-profile`
  - `PUT /exchange_agreement/api/v1/contracts/{contract_code}/flow-profile`
- Indicatori contratto / input richiesti
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/indicators`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/indicators/{indicator_code}`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/required-inputs`
- Pubblicazioni contratto
  - `POST /exchange_agreement/api/v1/contracts/{contract_code}/publish`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/publications`
  - `GET /exchange_agreement/api/v1/contracts/{contract_code}/publications/{publication_version}`
  - `GET /exchange_agreement/api/v1/publications/{publication_id}`
- Cataloghi
  - `GET /exchange_agreement/api/v1/indicators`
  - `GET /exchange_agreement/api/v1/structures`
  - `GET /exchange_agreement/api/v1/flow-profiles`

L'assegnazione diretta tramite `PUT .../flow-profile` viene rifiutata con
`409`: la configurazione si cambia creando e approvando una revisione. I nuovi
consumer dei cataloghi usano `/v1/flow-catalog/...`,
`/v1/processing-profiles` e `/v1/indicator-catalog`.
- Helper onboarding inviti
  - `GET /exchange_agreement/api/invitations/{token}/check`
  - `POST /exchange_agreement/api/invitations/{token}/start`

Endpoint azienda M2M:

- Base path: `/exchange_agreement/api/m2m/`
- Contesto client aziendale:
  - `GET /exchange_agreement/api/m2m/v1/me`
  - `GET /exchange_agreement/api/m2m/v1/company`
  - `GET /exchange_agreement/api/m2m/v1/grants`
- Contratti autorizzati:
  - `GET /exchange_agreement/api/m2m/v1/contracts`
  - `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}`
  - `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/flow-profile`
  - `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/required-inputs`
  - `GET /exchange_agreement/api/m2m/v1/contracts/{contract_code}/ingest-authorization?data_category={what}`
  - `GET /exchange_agreement/api/m2m/v2/contracts/{contract_code}/ingest-resolution?data_category={what}`

L'invio file verso `rpsd-ingest` e' standardizzato sul flusso aziendale M2M:
il client aziendale ottiene un token Keycloak con `client_credentials`, invia
il file a ingest con `Authorization: Bearer <token>` e Config valida JWT,
contratto, grant e categoria dato. Le API Config user-based restano disponibili
per flussi utente autenticati, ma l'invio file user-based non e' il percorso
standard di ingest.

## Note Backoffice Admin

### Action publish contratti (Django admin)

In `Admin > Contracts` e' disponibile l'action massiva:

- `Publish selected contracts`

Comportamento:

- pubblica i contratti selezionati in stato `active`
- salta i contratti `draft` (scelta intenzionale)
- salta i contratti `closed`
- crea snapshot `ContractPublication` (storico append-only)

`ContractPublication` e' visibile anche in admin come vista tecnica in sola lettura per ispezionare gli snapshot.

## Comandi Django per seed e reset di sviluppo

### Reset di sviluppo del modello target

Il modello di configurazione target dispone di un seed dimostrativo
idempotente:

```bash
uv run python src/rpsd_config/manage.py seed_target_demo
```

Prima di ricreare il database di sviluppo, verificare il target esatto senza
modificare nulla:

```bash
uv run python src/rpsd_config/manage.py reset_config_database --show-target
```

Ripetere quindi come conferma il nome database mostrato dal comando (per
esempio `rpsd`):

```bash
uv run python src/rpsd_config/manage.py reset_config_database --confirm-database rpsd
```

Il comando funziona intenzionalmente soltanto con `DEBUG=True`, PostgreSQL, il
database `default` configurato e il suo schema `public`. Rifiuta i database di
manutenzione PostgreSQL, applica tutte le migrazioni Django ed esegue
`seed_target_demo`. Non si collega e non cancella Keycloak, Prefect, lo storage
ingest o altri servizi. Usare `--skip-seed` soltanto se serve un database config
vuoto ma migrato.

`seed_target_demo` crea in modo idempotente anagrafiche, cataloghi versionati,
riferimenti ai flow, un profilo pubblicato, un contratto, la revisione corrente
approvata e la relativa pubblicazione. I comandi e i modelli legacy rimossi non
sono piu necessari per predisporre l'ambiente locale.

## Confine del repository

`rpsd-config` possiede metadata di configurazione, requisiti di validazione,
revisioni contrattuali, proiezioni API e client Django. Non possiede ricezione o
storage dei file, esecuzione del validator, deployment/scheduling Prefect,
provisioning del realm/client Keycloak, librerie condivise o Compose di
piattaforma. Il cutover del modello non richiede quindi modifiche a
`rpsd-ingest`, `rpsd-commons` o `rpsd`: la compatibilità rimane negli adapter
API di Config.
