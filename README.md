descrizione applicativo:

L’applicazione exchange_agreement modella l’ecosistema dei contratti di servizio nel trasporto pubblico locale, mettendo in relazione i soggetti coinvolti, la rete di servizio, i dataset di riferimento e gli indicatori con cui viene monitorato l’andamento del contratto. Il punto di partenza è la distinzione tra i diversi stakeholder: le agenzie (Agency), che tipicamente rappresentano gli enti concedenti o clienti; le aziende (Company), che svolgono il ruolo di gestori o contraenti; e le autorità territoriali (Authority), che rappresentano il contesto amministrativo (Regioni, Comuni, altri enti) e ne descrivono anche l’estensione geografica tramite geometrie GIS. In questo modo il sistema riesce a contestualizzare ogni elemento del contratto sia dal punto di vista istituzionale che territoriale.

Su questo sfondo si colloca la modellazione della rete di servizio. I lotti (Lot) rappresentano le unità contrattuali o territoriali su cui è organizzato il servizio. All’interno di ogni lotto vengono definite le linee (Line), ciascuna associata a una specifica autorità e identificata in maniera univoca da un codice. Le fermate (Stop) descrivono i punti fisici della rete, geolocalizzati in coordinate WGS84, mentre le corse (Trip) rappresentano i singoli viaggi previsti su una linea. La relazione tra corse e fermate è resa esplicita e ordinata attraverso il modello intermedio TripStop, che consente di ricostruire in modo preciso la sequenza delle fermate attraversate da ogni corsa. Questo insieme di modelli permette di rappresentare la rete non solo come elenco di entità, ma come grafo georeferenziato e navigabile.

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
- rete: `Stop`, `Route`, `Trip`, `TripStop`
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
uv run python src/rpsd_config/manage.py seed_dummy_data --lots 5 --routes-per-lot 4 --trips-per-route 3 --stops 30 --indicators 10 --seed 123
```

