descrizione applicativo:

Nota (stato corrente): la rete di servizio (`Route`, `Stop`, `Trip`, `TripStop`) e'
stata rimossa dal runtime Django e verra' gestita in un database PostgreSQL
esterno. Il dominio Django mantiene `Lot` e la parte contratti/indicatori/strutture.

L’applicazione exchange_agreement modella l’ecosistema dei contratti di servizio nel trasporto pubblico locale, mettendo in relazione i soggetti coinvolti, la rete di servizio, i dataset di riferimento e gli indicatori con cui viene monitorato l’andamento del contratto. Il punto di partenza è la distinzione tra i diversi stakeholder: le agenzie (Agency), che tipicamente rappresentano gli enti concedenti o clienti; le aziende (Company), che svolgono il ruolo di gestori o contraenti; e le autorità territoriali (Authority), che rappresentano il contesto amministrativo (Regioni, Comuni, altri enti) e ne descrivono anche l’estensione geografica tramite geometrie GIS. In questo modo il sistema riesce a contestualizzare ogni elemento del contratto sia dal punto di vista istituzionale che territoriale.

Su questo sfondo si colloca la modellazione della rete di servizio. Nel runtime Django corrente viene mantenuto il livello dei lotti (`Lot`) come contesto contrattuale, mentre linee, fermate e corse sono demandate a un database PostgreSQL esterno. Questo consente di mantenere in Django il dominio contratti/indicatori riducendo l'accoppiamento con il dettaglio della rete operativa.

Parallelamente alla rete, il sistema gestisce i dataset e le loro strutture logiche. Il modello Dataset identifica le diverse famiglie di dati utilizzate (ad esempio NetEx, SIRI PT, SIRI VM), mentre Structure descrive le singole sezioni o segmenti di ciascun dataset, associando a ognuno un eventuale schema di validazione (XSD, XML, JSON, YAML). A partire da queste strutture vengono definite le metriche di monitoraggio tramite IndicatorDef, che descrive gli indicatori utilizzati per la valutazione del servizio (indicatori di qualità, quantità, puntualità, ecc.). Ogni indicatore è collegato a una struttura di dataset, rendendo esplicite le dipendenze informative necessarie per il suo calcolo.

Il cuore applicativo si trova nei modelli di contratto. Contract rappresenta un contratto di servizio tra un’agenzia cliente e un’azienda contraente, collegato a un lotto di servizio e caratterizzato da un codice univoco, da un intervallo di validità temporale e da un tipo (avvio, rinnovo) con versione progressiva. All’interno del contratto è possibile associare il programma di esercizio contrattuale tramite un file NetEx (contract_program_file), che viene archiviato in una struttura di directory organizzata per codice di contratto. A complemento di questo, ContractDocument consente di archiviare la documentazione di supporto (atti, allegati, verbali), anch’essa organizzata per contratto.

Infine, il modello ContractIndicator mette in relazione contratti e indicatori, permettendo di specificare per ogni combinazione contratto–indicatore una configurazione dedicata (parametri, soglie, pesi) rappresentata in un campo JSON. Questo consente di adattare il significato operativo degli indicatori al singolo contratto, senza duplicare le definizioni di base. L’insieme di questi modelli costruisce un quadro coerente in cui gli accordi contrattuali, la rete di servizio, i dati disponibili e gli strumenti di monitoraggio sono descritti in modo strutturato, tracciabile e interoperabile con altri sistemi.

## Setup devcontainer e Keycloak

- Il devcontainer ora avvia esplicitamente anche `keycloak` e `keycloak-db`.
- Variabili Django/OIDC sono lette da environment e, se presente, da file `.env` nella root progetto.
- Puoi partire copiando `.env.example` in `.env` e adattando solo i campi che ti servono.

Riferimenti URL in locale:

- Browser host verso Django: `http://client.localhost:12080`
- Browser host verso Keycloak: `http://keycloak.localhost:18080`
- Django (in container) verso Keycloak: `http://keycloak.localhost:18080` (default consigliato)

Esempio `/etc/hosts`:

```txt
127.0.0.1 client.localhost
127.0.0.1 keycloak.localhost
```

Variabili OIDC consigliate in `.env`:

- `KEYCLOAK_DISCOVERY_URL`: endpoint usato da Django per discovery/token/userinfo (default consigliato: `http://keycloak.localhost:18080/...`).
- `OIDC_AUTHORIZATION_ENDPOINT_URL`: endpoint pubblico usato per la redirect del browser verso la login (es. `http://keycloak.localhost:18080/.../auth`).
- `OIDC_ISSUER_URL`: issuer pubblico atteso nella validazione dell`id_token` (es. `http://keycloak.localhost:18080/realms/rapsodia`).
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
curl -X POST "http://keycloak.localhost:18080/realms/rapsodia/protocol/openid-connect/token" \
  -H "content-type: application/x-www-form-urlencoded" \
  --data "grant_type=client_credentials&client_id=django&client_secret=django-secret"
```

3. Riprova il login e leggi il log di Django: ora viene stampata la causa precisa
   (errore OAuth/state/session) tramite `RpsdSocialAccountAdapter`.


esempio:
http://client.localhost:12080/invite/6bf9bc71-45ca-4218-93bb-f4293a6f99b2/

2do:
onboarding di un admin agenzia quando non ci sono contratti.
va fatta sull'istanza di agenzia ?
oppure si lascia preparare da admin un account specifico e lo si assegna ad un utente ?







## Comandi Django per seed dummy completo.

File creati:
- `src/rpsd_config/exchange_agreement/management/__init__.py`
- `src/rpsd_config/exchange_agreement/management/commands/__init__.py`
- `src/rpsd_config/exchange_agreement/management/commands/seed_dummy_data.py`

Cosa popola:
- anagrafiche: `Agency`, `Company`, `Authority`, `Lot`
- catalogo dati: `Dataset`, `Structure`
- indicatori: `IndicatorDef` + relazione `structures`
- contratti: `Contract` + file programma + `ContractDocument`
- mapping: `ContractIndicator`
- accessi: `ContractMembership`
- onboarding: `ContractInvitation`

Uso:
```bash
uv run python src/rpsd_config/manage.py seed_dummy_data
```

Con reset totale prima del seed:
```bash
uv run python src/rpsd_config/manage.py seed_dummy_data --reset
```

Parametri utili:
```bash
uv run python src/rpsd_config/manage.py seed_dummy_data --lots 5 --indicators 10 --seed 123
```


# 2do
salvare gtfs in area condivisa bisogna importare libreria e aggiungere una azione customa l modello del contratto. 
In modo che una volta salvato deve salvare o fare una copia i file nello spazio condiviso. 
-------------------------------------
Cambiare nome nel db da "dataset" a "tipi di dataset" o datasetType
---------------------------------------------- 
-----------------------------------------------------------------------------
serve da rivalutare come si fa l'invito iniziale ad un admin agenzia che possa creare nuovi cotratti. 
---------------------------------------------------------------------------------------
Gli indicatori devono essere immutabili. Una volta salvato puoi solo cancellarli o crearne di nuovi o duplicarne uno (magari aggiungendo una versoine da mostrare anche nel nome)
-----------------------------------------------------------------------------------------
Un contratto è vincolato dal fatto che solo lui puo avere quel codice univoco.

non ci possono essere contratti con codice diverso, ma associati allo stesso lotto, stessa azienda e stessa agenzia e stessa versione. 
Se ne vuoi creare uno uguale deve incrementare la versione. 
Inoltre non esiste il vincolo di sovrapposizione temporale sullo stesso lotto
----------------------------------------------------------------------------------------------

Aggiungere una funzione di pubblicaizone che genera una tabella con dentro 
Un contratto pubblicato una seconda volta crea una versione 2. 
Quando viene avviata una pubblicaizone si genera un record di una tabella contratti pubblicati con versione.
Va aggiunto un range di pubblicazione in modo da sapere quando è stata pubblicata. 
-------------------------------------------------------------------------------------
si può anche rimuovere lo stato in modo da non dover mantenere questa informazione
-------------------------------------------------------------------------------------- 