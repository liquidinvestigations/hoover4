# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Tilgang til administrasjon kreves
admin-guard-signed-in-as = Logget inn som { $u_username }.
admin-guard-ask-an-administrator-for-access = Be en administrator om tilgang til denne delen.
admin-shell-dashboard = Dashbord
admin-shell-collections = Samlinger
admin-shell-operations = Operasjoner
admin-shell-errors-failures = Feil/svikt
admin-shell-feedback = Tilbakemelding
admin-shell-users = Brukere
admin-shell-groups = Grupper
admin-shell-settings = Innstillinger
admin-shell-llm = LLM
admin-shell-ai-status = AI-status
admin-shell-metrics = Målinger
admin-shell-administration = Administrasjon
dataset-create-panel-add-a-dataset = Legg til et datasett
dataset-create-panel-the-dataset-mounts-could-not = Datasettmonteringene kunne ikke leses, så det er ingenting å velge mellom: { $err }
dataset-create-panel-loading-the-dataset-mounts = Laster datasettmonteringene.
dataset-create-panel-no-dataset-mount-is-configured = Ingen datasettmontering er konfigurert.
dataset-create-panel-the-mount-folder-could-not = Monteringsmappen kunne ikke leses, så det er ingenting å velge mellom: { $err }
dataset-create-panel-no-subfolders-were-found-in = Fant ingen undermapper i denne monteringen.{" "}
dataset-create-panel-folder = Mappe
dataset-create-panel-select-a-folder = Velg en mappe
dataset-create-panel-new-folder = Ny mappe
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } oppføringer), allerede et datasett
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } oppføringer)
dataset-create-panel-the-server-creates-this-folder = Tjeneren oppretter denne mappen i monteringen når du oppretter datasettet.{" "}
dataset-create-panel-the-list-shows-the-direct = Listen viser de direkte undermappene i monteringen.
dataset-create-panel-dataset-name = Datasettnavn
dataset-create-panel-a-name-has-lowercase-letters = Et navn har små bokstaver, sifre og understreker. Store bokstaver blir til små,{" "}
dataset-create-panel-the-dataset-is-saved-as = Datasettet lagres som: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Denne samlingen har allerede et datasett med navnet { $saved_name }.
dataset-create-panel-accept-uploads = Ta imot opplastinger
dataset-create-panel-creating-u = Oppretter …
dataset-create-panel-create-and-ingest = Opprett og ta inn
dataset-create-panel-mount = Montering
dataset-ocr-panel-last-operation = Siste operasjon: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , startet { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Ingen fremdrift på { $current_stale_seconds_60 } minutter. Kontroller Temporal-arbeidsflyten, og avbryt operasjonen hvis den har satt seg fast.
dataset-ocr-panel-loading-u = Laster …
dataset-ocr-panel-stored-text-variants = Lagrede tekstvarianter
dataset-ocr-panel-searchable-pdfs = Søkbare PDF-er
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } filer · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = Pågående LLM-samtaler
live-chats-panel-agent-turns-running-right-now = Agentomganger som kjører akkurat nå, de lengst kjørende først. Oppdateres hvert 2. sekund. Leses fra Temporal, så en omgang som startet før siste omstart av nettstedet, vises også her.
live-chats-panel-loading-u = Laster …
live-chats-panel-no-chats-running = Ingen samtaler kjører.
live-chats-panel-user = Bruker
live-chats-panel-conversation = Samtale
live-chats-panel-question = Spørsmål
live-chats-panel-internet = Internett
live-chats-panel-running = Kjører
live-chats-panel-started = Startet
live-chats-panel-cancels-the-workflow-the-turn = Avbryter arbeidsflyten. Omgangen avsluttes med en stoppmarkør i transkripsjonen i stedet for å forsvinne.
live-chats-panel-kill = Tving stopp
processing-updates-panel-loading-u = Laster …
processing-updates-panel-open-the-operation = Åpne operasjonen
processing-updates-panel-the-pipeline-has-not-calculated = Pipelinen har ikke beregnet disse oppdateringene ennå.
processing-updates-panel-calculated-at-in-ms = Beregnet { $view_checked_at } på { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatiske oppdateringer er slått av i denne installasjonen. Start oppdateringene med knappen.
processing-updates-panel-step = Trinn
processing-updates-panel-count = Antall
processing-updates-panel-state = Tilstand
processing-updates-panel-last-run = Siste kjøring
processing-updates-panel-runs = Kjører: { $step_runs }
processing-updates-panel-a-run-again-would-select = En ny kjøring ville valgt omtrent så mange { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } ved ny kjøring
processing-updates-panel-never = Aldri
processing-updates-panel-update-collection = Oppdater samlingen
processing-updates-panel-update-processing = Oppdater behandlingen
processing-updates-panel-check-again = Kontroller på nytt
processing-updates-panel-dataset = Datasett
processing-updates-panel-processing-updates = Behandlingsoppdateringer
admin-ai-status-admin-ai-status = Administrasjon: AI-status
admin-ai-status-ai-status = AI-status
admin-ai-status-the-configured-service-and-the = Den konfigurerte tjenesten og tjenesten som faktisk svarer. En overgang til CPU-tjenesten som reserve vises bare her.
admin-ai-status-loading-u = Laster …
admin-ai-status-config-fingerprint = Konfigurasjonsfingeravtrykk
admin-ai-status-website-worker = Nettsted / arbeider
admin-ai-status-ai-server = AI-tjener
admin-ai-status-match = Samsvar
admin-ai-status-embeddings-probe = Test av embeddinger
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dimensjoner
admin-ai-status-llm-configured = LLM konfigurert
admin-ai-status-capabilities = Funksjoner
admin-ai-status-capability = Funksjon
admin-ai-status-configured = Konfigurert
admin-ai-status-serving = Leverer
admin-ai-status-model = Modell
admin-ai-status-reachable = Tilgjengelig
admin-ai-status-detail = Detaljer
admin-ai-status-no = NEI
admin-ai-status-vector-shard-dims-vs-probe = Dimensjoner i vektorshard mot test
admin-ai-status-no-collections-yet = Ingen samlinger ennå.
admin-ai-status-collection = Samling
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Samsvarer med testen
admin-ai-status-browser-router = Nettleserruter
admin-ai-status-live-sessions = Aktive økter: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Nylig LLM-trafikk (24 t)
admin-ai-status-no-llm-call-events-yet = Ingen llm_call_events ennå.
admin-ai-status-user = Bruker
admin-ai-status-calls = Kall
admin-ai-status-errors = Feil
admin-ai-status-service-use-24-h = Tjenestebruk i % (24 t)
admin-ai-status-busy-seconds-in-the-last = Opptatte sekunder de siste 24 timene, som andel av døgnet.
admin-ai-status-no-samples-yet = Ingen målinger ennå.
admin-ai-status-service = Tjeneste
admin-ai-status-busy-s = Opptatt s
admin-ai-status-use = Bruk %
admin-collection-detail-admin-collection = Administrasjon: samling { $collection_id }
admin-collection-detail-failed-to-load-collection = Kunne ikke laste samlingen
admin-collection-detail-loading = Laster …
admin-collection-detail-datasets = Datasett
admin-collection-detail-dataset = Datasett
admin-collection-detail-documents = Dokumenter
admin-collection-detail-size = Størrelse
admin-collection-detail-indexed = Indeksert
admin-collection-detail-errors = Feil
admin-collection-detail-state = Tilstand
admin-collection-detail-created = Opprettet
admin-collection-detail-settings = Innstillinger
admin-collection-detail-the-collection-database-is-not = Samlingsdatabasen er ikke klar ennå.
admin-collection-detail-the-last-storage-provisioning-failed = Den siste klargjøringen av lagring mislyktes: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Behandlingsfremdrift og estimater
admin-collection-detail-display-name = Visningsnavn
admin-collection-detail-display-name-2 = visningsnavn
admin-collection-detail-save = Lagre
admin-collection-detail-access = Tilgang
admin-collection-detail-public-every-signed-in-user = Offentlig. Alle innloggede brukere kan søke i og lese denne samlingen.
admin-collection-detail-restricted-only-members-of-the = Begrenset. Bare medlemmer av gruppene under kan søke i og lese denne samlingen.
admin-collection-detail-the-collection-is-now-public = Samlingen er nå offentlig.
admin-collection-detail-the-collection-is-now-restricted = Samlingen er nå begrenset.
admin-collection-detail-make-restricted = Gjør begrenset
admin-collection-detail-make-public = Gjør offentlig
admin-collection-detail-group-permissions = Gruppetillatelser
admin-collection-detail-no-group-can-read-this = Ingen gruppe kan lese denne samlingen ennå.
admin-collection-detail-revoke = Trekk tilbake
admin-collection-detail-grant-group-u = Gi gruppe tilgang …
admin-collection-detail-grant = Gi tilgang
admin-collection-detail-danger-zone = Faresone
admin-collection-detail-a-collection-can-only-be = En samling kan bare slettes når den ikke har datasett.
admin-collection-detail-deleting-the-collection-also-drops = Sletting av samlingen fjerner også databasen{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}og alt i den. Dette kan ikke angres. Skriv inn samlingsnavnet for å bekrefte.
admin-collection-detail-collection-name = Samlingsnavn
admin-collection-detail-delete-collection = Slett samlingen
admin-collection-detail-features = Funksjoner
admin-collection-detail-vectors = Vektorer
admin-collection-detail-this-installation-runs-no-embedding = Denne installasjonen kjører ingen embedding-tjeneste, så ingen samling bruker vektorer.
admin-collection-detail-vectors-find-passages-by-meaning = Vektorer finner tekstutdrag etter betydning. Av stopper nye vektorer og hindrer søket i å bruke de lagrede, som blir værende. På beregner de manglende vektorene for hvert datasett, ett datasett om gangen.
admin-collection-detail-this-collection-follows-the-installation = Denne samlingen følger installasjonen, som bruker vektorer. Vektorer finner tekstutdrag etter betydning. Av stopper nye vektorer og hindrer søket i å bruke de lagrede, som blir værende.
admin-collection-processing-could-not-load-this-panel = Kunne ikke laste dette panelet: { $message }
admin-collection-processing-admin-processing-of = Administrasjon: behandling av { $collection_id }
admin-collection-processing-u-back-to-collection = ← Tilbake til samlingen
admin-collection-processing-processing-stages = Behandlingstrinn
admin-collection-processing-loading-u = Laster …
admin-collection-processing-the-collection-database-is-still = Samlingsdatabasen klargjøres fortsatt.
admin-collection-processing-this-collection-has-no-datasets = Denne samlingen har ingen datasett ennå.
admin-collection-processing-eta = ETA { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Ingen estimatmålinger ennå. De samles inn mens datasettet behandles.
admin-collection-processing-estimated-completion = Beregnet ferdigstilt:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(om { $humanize_seconds_c_eta_seconds }, et estimat etter beste evne og ikke et planleggingsløfte)
admin-collection-processing-no-current-estimate-the-pipeline = Ingen gjeldende estimat. Pipelinen er ferdig eller gjør ingen målbar fremdrift.
admin-collection-processing-where-processing-time-goes = Hvor behandlingstiden går
admin-collection-processing-no-task-executions-recorded-yet = Ingen oppgavekjøringer er registrert ennå. Hver aktivitet pipelinen kjører, skriver én rad her, så en tom tabell betyr at ingenting er behandlet siden instrumenteringen ble tatt i bruk.
admin-collection-processing-summed-task-time = Samlet oppgavetid
admin-collection-processing-wall-clock = Reell tid
admin-collection-processing-achieved-parallelism = Oppnådd parallellitet
admin-collection-processing-summed-task-time-divided-by = Samlet oppgavetid delt på reell tid er det pipelinen faktisk oppnådde i parallell. Nær 1 betyr at den øverste oppgaven under utgjør hele kostnaden og er verdt å optimalisere. Nær antallet arbeiderplasser betyr at plassene er mettet, og at flere arbeidere er den billigste løsningen. Reell tid går fra første til siste kjøring, inkludert ledig tid.
admin-collection-processing-task = Oppgave
admin-collection-processing-total = Totalt
admin-collection-processing-share = Andel
admin-collection-processing-executions = Kjøringer
admin-collection-processing-mean = Gjennomsnitt
admin-collection-processing-max = Maks
admin-collection-processing-failed = Mislyktes
admin-collection-processing-live-activity = Sanntidsaktivitet
admin-collection-processing-nothing-running-no-activity-finished = Ingenting kjører. Ingen aktivitet ble ferdig de siste { $live_window_seconds } s, og ingen arbeider melder om noe som pågår.
admin-collection-processing-in-flight = Pågående
admin-collection-processing-average-concurrency = Gjennomsnittlig samtidighet
admin-collection-processing-task-time-in-window = Oppgavetid i vinduet
admin-collection-processing-share-of-processing-time-over = Andel av behandlingstiden de siste { $live_window_seconds } s, oppdatert hvert 5. sekund. En kjøring som krysser vindukanten, teller bare for delen innenfor. En rad med pågående kjøringer, men uten andel, startet før vinduet og er ikke ferdig. Kontroller alderen.
admin-collection-processing-share-of-window = Andel av vinduet
admin-collection-processing-task-time = Oppgavetid
admin-collection-processing-completed = Fullført
admin-collection-processing-oldest-running = Eldste pågående
admin-collection-processing-temporal-workflows = Temporal-arbeidsflyter
admin-collection-processing-workflows-of-this-collection-s = Arbeidsflyter for datasettene i denne samlingen, inkludert underarbeidsflyter.
admin-collection-processing-no-workflows-match-this-filter = Ingen arbeidsflyter samsvarer med dette filteret.
admin-collection-processing-workflow = Arbeidsflyt
admin-collection-processing-type = Type
admin-collection-processing-status = Status
admin-collection-processing-started = Startet
admin-collection-processing-closed = Lukket
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = åpne ↗
admin-collection-processing-failed-tasks = Mislykkede oppgaver
admin-collection-processing-no-task-failures-recorded = Ingen oppgavefeil registrert.
admin-collection-processing-dataset = Datasett
admin-collection-processing-errors = Feil
admin-collection-processing-documents = Dokumenter
admin-collection-processing-last-seen = Sist sett
admin-collection-processing-sample = Eksempel
admin-collection-processing-retry = Prøv igjen
admin-collection-processing-failures-per-document = Feil per dokument
admin-collection-processing-no-document-failures-recorded = Ingen dokumentfeil registrert.
admin-collection-processing-document = Dokument
admin-collections-list-admin-collections = Administrasjon: samlinger
admin-collections-list-collections = Samlinger
admin-collections-list-loading-collections-u = Laster samlinger …
admin-collections-list-datasets = Datasett
admin-collections-list-loading-datasets-u = Laster datasett …
admin-collections-list-add-a-collection = Legg til en samling
admin-collections-list-name-for-example-enron = Navn, for eksempel enron
admin-collections-list-display-name = Visningsnavn
admin-collections-list-add-collection = Legg til samling
admin-collections-list-a-name-has-lowercase-letters = Et navn har små bokstaver, sifre og understreker. Store bokstaver blir til små,{" "}
admin-collections-list-the-collection-is-saved-as = Samlingen lagres som: { $new_name }
admin-collections-list-a-collection-with-the-name = Det finnes allerede en samling med navnet { $new_name }.
admin-collections-list-collection = Samling
admin-collections-list-documents = Dokumenter
admin-collections-list-size = Størrelse
admin-collections-list-errors = Feil
admin-collections-list-state = Tilstand
admin-collections-list-access = Tilgang
admin-collections-list-database-not-ready = Databasen er ikke klar
admin-collections-list-public = Offentlig
admin-collections-list-1-group = 1 gruppe
admin-collections-list-not-counted-yet = Ikke talt ennå
admin-collections-list-unknown = Ukjent
admin-collections-list-no-collection-has-a-dataset = Ingen samling har et datasett.
admin-collections-list-dataset = Datasett
admin-collections-list-indexed = Indeksert
admin-collections-list-created = Opprettet
admin-dashboard-admin-dashboard = Administrasjon: dashbord
admin-dashboard-administration = Administrasjon
admin-dashboard-users = Brukere
admin-dashboard-groups = Grupper
admin-dashboard-collections = Samlinger
admin-dashboard-datasets = Datasett
admin-dashboard-failed-to-load-counts = Kunne ikke laste tallene: { $e }
admin-dataset-detail-admin-dataset = Administrasjon: datasett { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Kunne ikke laste datasettet
admin-dataset-detail-loading = Laster …
admin-dataset-detail-metadata = Metadata
admin-dataset-detail-display-name = Visningsnavn
admin-dataset-detail-name = Navn
admin-dataset-detail-type = Type
admin-dataset-detail-path = Sti
admin-dataset-detail-created = Opprettet
admin-dataset-detail-collection = Samling
admin-dataset-detail-save = Lagre
admin-dataset-detail-statistics = Statistikk
admin-dataset-detail-state = Tilstand
admin-dataset-detail-documents = Dokumenter
admin-dataset-detail-size = Størrelse
admin-dataset-detail-indexed = Indeksert
admin-dataset-detail-errors = Feil
admin-dataset-detail-plans-finished = Ferdige planer
admin-dataset-detail-disk = Disk
admin-dataset-detail-rescan-disk-reads-the-dataset = Skann disken på nytt leser datasettmappen igjen, legger til nye og endrede filer og behandler dem.
admin-dataset-detail-rescan-disk = Skann disken på nytt
admin-dataset-detail-danger-zone = Faresone
admin-dataset-detail-this-deletes-the-dataset-and = Dette sletter datasettet og alle data som er hentet ut fra det. Det kan ikke angres.
admin-dataset-detail-delete-dataset-and-its-data = Slett datasettet og dataene
admin-dataset-detail-accept-uploads = Ta imot opplastinger
admin-dataset-detail-the-folder-of-this-dataset = Mappen til dette datasettet ligger ikke i en skrivbar datasettmontering, så det mottar ingen opplastinger.
admin-dataset-detail-starting-u = Starter …
admin-failure-detail-admin-failure = Administrasjon: svikt { $op_id }
admin-failure-detail-loading-tree = Laster treet …
admin-failure-detail-back-to-errors-and-failures = Tilbake til feil og svikt
admin-failure-detail-operations = Operasjoner
admin-failure-detail-scrubbed-copy-written-to-the = Renset kopi er skrevet til utklippstavlen.
admin-failure-detail-this-tree-is-truncated-at = Dette treet er avkortet. Minst én fangst droppet noder.
admin-failure-detail-the-captured-tree-has-expired = Det fangede treet er utløpt. Operasjonsraden finnes fortsatt.
admin-failure-detail-no-captured-nodes-for-this = Ingen fangede noder for denne operasjonen.
admin-failure-detail-operation = Operasjon
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } rot(er) · { $tree_nodes_len } node(r)
admin-failure-detail-open-in-temporal = Åpne i Temporal
admin-failure-detail-scrubbed-copy = Renset kopi
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Den rensede kopien erstatter datasettstier med hasher og lange verdier med lengdene deres.
admin-failure-detail-copy-scrubbed-record = Kopier renset post
admin-failure-detail-tree = Tre
admin-failure-detail-root = Rot ·{" "}
admin-failure-detail-node-parent-depth-source-stage = node { $node_node_index } · overordnet { $node_parent_index } · dybde { $node_depth } · kilde { $node_source } · trinn { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = arbeidsflyt { $node_workflow_id } · kjøring { $node_run_id } · aktivitet { $node_activity_id } · forsøk { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } node(r) droppet ved denne fangsten
admin-failures-admin-errors-and-failures = Administrasjon: feil og svikt
admin-failures-errors-failures = Feil/svikt
admin-failures-loading-failures = Laster svikt …
admin-failures-operational-failures = Driftssvikt
admin-failures-no-operational-failures-at-this = Ingen driftssvikt for øyeblikket.
admin-failures-collection = Samling
admin-failures-dataset = Datasett
admin-failures-task-name = Oppgavenavn
admin-failures-error-class = Feilklasse
admin-failures-operation-kind = Operasjonstype
admin-failures-from = Fra
admin-failures-to = Til
admin-failures-no-captured-failures-match-these = Ingen fangede svikt samsvarer med disse filtrene.
admin-failures-signature = Signatur
admin-failures-count = Antall
admin-failures-class = Klasse
admin-failures-task = Oppgave
admin-failures-last-seen = Sist sett
admin-failures-newer = Nyere
admin-failures-page = Side { $current_page_1 }
admin-failures-older = Eldre
admin-failures-per-page = Per side
admin-failures-loading-instances = Laster forekomster …
admin-failures-no-instances-for-this-signature = Ingen forekomster for denne signaturen.
admin-failures-node = {" "}node { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Dokumentfeil
admin-failures-error-text = Feiltekst
admin-failures-loading-document-errors-u = Laster dokumentfeil …
admin-failures-no-document-errors-match-these = Ingen dokumentfeil samsvarer med disse filtrene.
admin-failures-errors-by-dataset-and-task = Feil etter datasett og oppgave
admin-failures-documents = Dokumenter
admin-failures-show-only-this-dataset-and = Vis bare dette datasettet og denne oppgaven
admin-failures-total = Totalt
admin-failures-errors = Feil
admin-failures-document = Dokument
admin-failures-runs = Kjøringer
admin-failures-error = Feil
admin-failures-dataset-step = Trinn i datasettet
admin-failures-previous-page = Forrige side
admin-failures-page-of-1-error = Side { $page } av { $pages }, 1 feil
admin-failures-page-of-errors = Side { $page } av { $pages }, { $data_total } feil
admin-failures-next-page = Neste side
admin-feedback-admin-feedback = Administrasjon: tilbakemelding
admin-feedback-feedback = Tilbakemelding
admin-feedback-search-titles-descriptions-accounts-and = Søk i titler, beskrivelser, kontoer og adresser
admin-feedback-search = Søk
admin-feedback-loading-reports-u = Laster rapporter …
admin-feedback-1-report-matches = 1 rapport samsvarer.
admin-feedback-reports-match = { $data_total } rapporter samsvarer.
admin-feedback-received = Mottatt
admin-feedback-type = Type
admin-feedback-title = Tittel
admin-feedback-from = Fra
admin-feedback-captures = Opptak
admin-feedback-state = Tilstand
admin-feedback-previous-page = Forrige side
admin-feedback-page-of = Side { $page } av { $pages }
admin-feedback-next-page = Neste side
admin-feedback-image = Bilde { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Lest
admin-feedback-unread = Ulest
admin-feedback-archived = Arkivert
admin-feedback-mark-unread = Merk som ulest
admin-feedback-mark-read = Merk som lest
admin-feedback-restore = Gjenopprett
admin-feedback-archive = Arkiver
admin-feedback-page = Side:{" "}
admin-feedback-the-report-has-no-description = Rapporten har ingen beskrivelse.
admin-feedback-open-the-page-image = Åpne sidebildet
admin-feedback-open-the-dom-copy = Åpne DOM-kopien
admin-feedback-page-image-of-the-report = Sidebilde fra rapporten
admin-feedback-debug-context-and-browser-log = Feilsøkingsinformasjon og nettleserlogg
admin-feedback-loading-u = Laster …
admin-group-detail-admin-group = Administrasjon: gruppe { $groupname }
admin-group-detail-failed-to-load-group = Kunne ikke laste gruppen
admin-group-detail-loading = Laster …
admin-group-detail-group = Gruppe
admin-group-detail-display-name = Visningsnavn
admin-group-detail-display-name-2 = visningsnavn
admin-group-detail-save = Lagre
admin-group-detail-members = Medlemmer
admin-group-detail-saving-membership = Lagrer medlemskap …
admin-group-detail-username = Brukernavn
admin-group-detail-origin = Opprinnelse
admin-group-detail-group-admin = Gruppeadministrator
admin-group-detail-uploader = Opplaster
admin-group-detail-remove = Fjern
admin-group-detail-username-to-add = brukernavn å legge til
admin-group-detail-add-member = Legg til medlem
admin-group-detail-collection-access = Tilgang til samlinger
admin-group-detail-this-group-has-no-collection = Denne gruppen har ingen samlingstillatelser.
admin-group-detail-revoke = Trekk tilbake
admin-group-detail-grant-collection-u = Gi tilgang til samling …
admin-group-detail-grant = Gi tilgang
admin-group-detail-danger-zone = Faresone
admin-group-detail-delete-group = Slett gruppen
admin-groups-list-admin-groups = Administrasjon: grupper
admin-groups-list-groups = Grupper
admin-groups-list-add-group = Legg til gruppe
admin-groups-list-display-name = visningsnavn
admin-groups-list-use-lowercase-letters-digits-underscores = Bruk små bokstaver, sifre, understreker og bindestreker i navnet. Navnet kan ikke endres senere.
admin-groups-list-add-group-2 = Legg til gruppe +
admin-groups-list-group = Gruppe
admin-groups-list-display-name-2 = Visningsnavn
admin-groups-list-members = Medlemmer
admin-groups-list-collections = Samlinger
admin-groups-list-loading = Laster …
admin-llm-config-admin-llm = Administrasjon: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Laster …
admin-llm-config-no-llm-provider-is-configured = Ingen LLM-leverandør er konfigurert. Sett LLM_BASE_URL / LLM_MODEL i hoover4.ini og distribuer på nytt.
admin-llm-config-providers = Leverandører
admin-llm-config-the-refresh-runs-in-the = Innlastingen kjører i bakgrunnen. Den gjeldende listen forblir synlig i mellomtiden.
admin-llm-config-refresh-in-flight-u = {" "}Laster på nytt …
admin-llm-config-provider = Leverandør
admin-llm-config-models = Modeller
admin-llm-config-freshest = Nyeste
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Last katalogen på nytt
admin-llm-config-agent-turns-board-assessments-and = Agentomganger, tavlevurderinger og rapportkonverteringer
admin-llm-config-titles-summaries-and-board-labels = Titler, sammendrag og tavleetiketter
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini angir disse modellene: quality_model hos LLM-leverandøren for agentomganger, tavlevurderinger og rapportkonverteringer når den er satt, og leverandørens modell for resten.
admin-llm-config-thinking = Tenkning
admin-llm-config-the-model-reasons-before-each = Modellen resonnerer før hvert verktøykall og hvert svar.
admin-llm-config-catalog = Katalog
admin-llm-config-filter-models-u = Filtrer modeller …
admin-llm-config-model = Modell
admin-llm-config-flags = Flagg
admin-llm-config-calls-14d = Kall 14 d
admin-llm-config-ai-status = AI-status
admin-llm-config-shows-the-serving-health = {" "}viser driftsstatusen til tjenestene.
admin-llm-reports-reports = Rapporter
admin-llm-reports-each-report-runs-when-you = Hver rapport kjøres når du velger knappen.
admin-llm-reports-running-u = Kjører …
admin-llm-reports-run-report = Kjør rapport
admin-llm-reports-read-at = Lest { $read_at }
admin-llm-reports-errors = Feil
admin-llm-reports-failed-attempts-by-step-and = Mislykkede forsøk etter trinn og feilklasse, og agentkjøringer som mislyktes eller endte tidlig, etter sluttårsak.
admin-llm-reports-source = Kilde
admin-llm-reports-class = Klasse
admin-llm-reports-no-errors-in-30-days = Ingen feil de siste 30 dagene.
admin-llm-reports-recent-errors = Nylige feil
admin-llm-reports-the-newest-100-failed-attempts = De 100 nyeste mislykkede forsøkene de siste 7 dagene. Åpne en rad for å lese feilen.
admin-llm-reports-time = Tid
admin-llm-reports-user = Bruker
admin-llm-reports-name = Navn
admin-llm-reports-error = Feil
admin-llm-reports-no-errors-in-7-days = Ingen feil de siste 7 dagene.
admin-llm-reports-show = Vis
admin-llm-reports-tool-calls = Verktøykall
admin-llm-reports-one-row-for-each-tool = Én rad per verktøy, etter antall kall de siste 30 dagene. En feil er et mislykket kall.
admin-llm-reports-tool = Verktøy
admin-llm-reports-calls-24-h = Kall 24 t
admin-llm-reports-error-24-h = Feil % 24 t
admin-llm-reports-avg-ms-24-h = Gj.snitt ms 24 t
admin-llm-reports-calls-7-d = Kall 7 d
admin-llm-reports-error-7-d = Feil % 7 d
admin-llm-reports-avg-ms-7-d = Gj.snitt ms 7 d
admin-llm-reports-calls-30-d = Kall 30 d
admin-llm-reports-error-30-d = Feil % 30 d
admin-llm-reports-avg-ms-30-d = Gj.snitt ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Ingen verktøykall de siste 30 dagene.
admin-llm-reports-top-users = Mest aktive brukere
admin-llm-reports-the-30-users-with-the = De 30 brukerne med mest modelltid i vinduet.
admin-llm-reports-30-days = 30 dager
admin-llm-reports-7-days = 7 dager
admin-llm-reports-24-hours = 24 timer
admin-llm-reports-tool-time = Verktøytid
admin-llm-reports-model-calls = Modellkall
admin-llm-reports-model-time = Modelltid
admin-llm-reports-tokens-in = Tokens inn
admin-llm-reports-tokens-out = Tokens ut
admin-llm-reports-no-agent-use-in-the = Ingen agentbruk i vinduet.
admin-llm-reports-system-one-checks = System one-kontroller
admin-llm-reports-requests-are-grouped-by-hook = Forespørsler grupperes etter hook og regel. Ventetider er i millisekunder. Andeler bruker forespørsler fra de siste 30 dagene.
admin-llm-reports-counts = Antall
admin-llm-reports-recent-failures = Nylige feil
admin-llm-reports-select-run-report-to-read = Velg Kjør rapport for å lese statistikken.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Regel
admin-llm-reports-outcome = Utfall
admin-llm-reports-questions = Spørsmål
admin-llm-reports-median-ms = Median ms
admin-llm-reports-95th-percentile-ms = 95. persentil ms
admin-llm-reports-error-2 = Feil %
admin-llm-reports-positive = Positive %
admin-llm-reports-actions = Handlinger
admin-metrics-admin-metrics = Administrasjon: målinger
admin-metrics-metrics = Målinger
admin-metrics-the-last-24-hours = De siste 24 timene.
admin-metrics-loading-u = Laster …
admin-metrics-manticore-load-now = Manticore-belastning (nå)
admin-metrics-ram-is-the-memory-of = RAM er minnet til tabellene. Trådbelastningen gjelder de siste 1, 5 og 15 minuttene.
admin-metrics-manticore-status-could-not-be = Manticore-statusen kunne ikke leses: { $error }
admin-metrics-thread-load-1-5-15 = Trådbelastning (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Primær trådbelastning (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Sekundær trådbelastning (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Arbeidstråder opptatt / totalt
admin-metrics-work-queue = Arbeidskø
admin-metrics-ram-held-by-tables = RAM brukt av tabeller
admin-metrics-disk-used-by-tables = Disk brukt av tabeller
admin-metrics-tables-merging = Tabeller som slås sammen
admin-metrics-tables-read = Tabeller lest
admin-metrics-read-at = Lest
admin-metrics-largest-tables-by-ram = Største tabeller etter RAM
admin-metrics-table = Tabell
admin-metrics-ram = RAM
admin-metrics-disk = Disk
admin-metrics-disk-chunks = Diskdeler
admin-metrics-merging = Sammenslåing
admin-metrics-usage-last-24-h = Bruk (siste 24 t)
admin-metrics-events-by-type = Hendelser etter type
admin-metrics-event = Hendelse
admin-metrics-count = Antall
admin-metrics-events-per-hour = Hendelser per time
admin-metrics-no-events-recorded-yet = Ingen hendelser registrert ennå.
admin-metrics-busiest-users = Mest aktive brukere
admin-metrics-user = Bruker
admin-metrics-events = Hendelser
admin-metrics-events-2 = { $point_bucket }: { $point_count } hendelser
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API-kall (siste 24 t)
admin-metrics-no-api-calls-recorded-yet = Ingen API-kall registrert ennå.
admin-metrics-function = Funksjon
admin-metrics-calls = Kall
admin-metrics-errors = Feil
admin-metrics-error-rate = Feilrate
admin-metrics-bytes-in = Byte inn
admin-metrics-bytes-out = Byte ut
admin-operation-detail-admin-operation = Administrasjon: operasjon { $op_id }
admin-operation-detail-loading-operation = Laster operasjonen …
admin-operation-detail-back-to-operations = Tilbake til operasjoner
admin-operation-detail-operation = Operasjon
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · satt i kø { $row_started_at }
admin-operation-detail-not-started = ikke startet
admin-operation-detail-re-run-counts-are-not = Antall nye kjøringer er ikke tilgjengelig.
admin-operation-detail-failed-document-s-task-failure = { $documents } mislykkede dokument(er), { $row_failed_tasks_unwrap_or_0 } oppgavefeil
admin-operation-detail-failures-were-not-counted = Svikt ble ikke talt.
admin-operation-detail-open-captured-failure-tree = Åpne fanget sviktetre
admin-operation-detail-open-in-temporal = Åpne i Temporal
admin-operation-detail-plans = Planer
admin-operation-detail-plan-s-page = { $data_plans_total } plan(er), side { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Ingen planer ble registrert for denne operasjonen.
admin-operation-detail-dataset = Datasett
admin-operation-detail-plan-hash = Plan-hash
admin-operation-detail-source = Kilde
admin-operation-detail-finished = Ferdig
admin-operation-detail-previous = Forrige
admin-operation-detail-next = Neste
admin-operation-detail-error-events = Feilhendelser
admin-operation-detail-error-event-s-page = { $data_events_total } feilhendelse(r), side { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Ingen feilhendelser ble registrert for denne operasjonen.
admin-operation-detail-time = Tid
admin-operation-detail-hash = Hash
admin-operation-detail-task = Oppgave
admin-operation-detail-event = Hendelse
admin-operation-detail-error-excerpt = Utdrag av feilen
admin-operations-admin-operations = Administrasjon: operasjoner
admin-operations-operations = Operasjoner
admin-operations-loading-operations = Laster operasjoner …
admin-operations-filters = Filtre
admin-operations-state = Tilstand
admin-operations-any-state = Alle tilstander
admin-operations-collection = Samling
admin-operations-all-collections = Alle samlinger
admin-operations-choose-a-collection-to-see = Velg en samling for å se feilratene per oppgave.
admin-operations-operations-newest-first = Operasjoner, nyeste først
admin-operations-newer = Nyere
admin-operations-page = Side { $current_page_1 }
admin-operations-older = Eldre
admin-operations-failure-rate-by-task-type = Sviktrate etter oppgavetype ({ $collectionname })
admin-operations-one-row-per-activity-execution = Én rad per aktivitetskjøring, nye forsøk medregnet. En rate over{" "}
admin-operations-is-marked = {" "}er markert.
admin-operations-no-task-executions-recorded-for = Ingen oppgavekjøringer er registrert for denne samlingen ennå.
admin-operations-task = Oppgave
admin-operations-error-rate = Feilrate
admin-operations-failed-total-executions = Mislykkede / totale kjøringer
admin-operations-documents-affected = Berørte dokumenter
admin-operations-above-the-line = over streken
admin-operations-no-operations-recorded-for-this = Ingen operasjoner er registrert for dette filteret.
admin-operations-kind = Type
admin-operations-target = Mål
admin-operations-workflow = Arbeidsflyt
admin-operations-queued-at = Satt i kø
admin-operations-started = Startet
admin-operations-duration = Varighet
admin-operations-progress = Fremdrift
admin-operations-eta = ETA
admin-operations-outcome = Utfall
admin-operations-destructive = Destruktiv
admin-operations-repeated-run = Gjentatt kjøring
admin-operations-no-estimate-yet = ingen estimat ennå
admin-operations-cancel = Avbryt
admin-operations-type-to-confirm = skriv { $target } for å bekrefte
admin-operations-re-run = Kjør på nytt
admin-operations-waiting-for-a-free-slot = venter på en ledig plass eller et ledig mål
admin-operations-counting-work = teller arbeid …
admin-operations-open-captured-tree = Åpne fanget tre
admin-operations-no-captured-tree = intet fanget tre
admin-operations-no-failed-documents = ingen mislykkede dokumenter
admin-operations-document-s-failed = { $n } dokument(er) mislyktes
admin-operations-task-failure-s = { $t } oppgavefeil
admin-operations-failures-not-counted = svikt ikke talt
admin-operations-the-newest-ten-operations-of = De ti nyeste operasjonene for denne samlingen.{" "}
admin-operations-all-operations = Alle operasjoner
admin-settings-admin-settings = Administrasjon: innstillinger
admin-settings-server-settings = Tjenerinnstillinger
admin-settings-key = Nøkkel
admin-settings-value = Verdi
admin-settings-description = Beskrivelse
admin-settings-save = Lagre
admin-settings-loading = Laster …
admin-settings-deployment-configuration-read-only = Konfigurasjon av installasjonen (skrivebeskyttet)
admin-settings-not-set = (ikke satt)
admin-user-detail-admin-user = Administrasjon: bruker { $username }
admin-user-detail-failed-to-load-user = Kunne ikke laste brukeren
admin-user-detail-loading = Laster …
admin-user-detail-user = Bruker
admin-user-detail-the-next-login-replaces-the = Neste innlogging erstatter fullt navn, e-post og superbrukerstatus for en bruker som kommer fra innloggingsproxyen.
admin-user-detail-llm-usage-u = LLM-bruk →
admin-user-detail-full-name = Fullt navn
admin-user-detail-full-name-2 = fullt navn
admin-user-detail-email = E-post
admin-user-detail-superuser = Superbruker
admin-user-detail-save = Lagre
admin-user-detail-groups = Grupper
admin-user-detail-saving-membership = Lagrer medlemskap …
admin-user-detail-group = Gruppe
admin-user-detail-origin = Opprinnelse
admin-user-detail-group-admin = Gruppeadministrator
admin-user-detail-uploader = Opplaster
admin-user-detail-remove = Fjern
admin-user-detail-add-to-group-u = Legg til i gruppe …
admin-user-detail-add = Legg til
admin-user-detail-danger-zone = Faresone
admin-user-detail-delete-user = Slett brukeren
admin-user-llm-admin-llm-use-by = Administrasjon: LLM-bruk av { $username }
admin-user-llm-u-back-to-user = ← Tilbake til brukeren
admin-user-llm-loading-u = Laster …
admin-user-llm-totals-all-time = Totaler (hele tiden)
admin-user-llm-chat-sessions = Chat-økter
admin-user-llm-messages = Meldinger
admin-user-llm-tool-calls = Verktøykall
admin-user-llm-model-and-tool-time = Modell- og verktøytid
admin-user-llm-model-and-tool-time-of = modell- og verktøytid for agenttrinnene til denne brukeren. Parallelle verktøykall telles fullt ut
admin-user-llm-rate-limit-usage-current-windows = Bruk av hastighetsgrenser (gjeldende vinduer)
admin-user-llm-in-process-counters-of-the = Tellere i prosessen til den kjørende nettstedscontaineren. Chat-grense { $metrics_chat_per_minute }/min, API-grense { $metrics_api_per_minute }/min, med en avtagende vedvarende rate over de lengre vinduene.
admin-user-llm-chat-messages = Chat-meldinger
admin-user-llm-api-calls = API-kall
admin-user-llm-window = Vindu
admin-user-llm-used = Brukt
admin-user-llm-budget = Kvote
admin-user-llm-no-chat-sessions = Ingen chat-økter.
admin-user-llm-title = Tittel
admin-user-llm-created = Opprettet
admin-users-list-admin-users = Administrasjon: brukere
admin-users-list-users = Brukere
admin-users-list-search-users = Søk i brukere
admin-users-list-username = Brukernavn
admin-users-list-full-name = Fullt navn
admin-users-list-email-address = E-postadresse
admin-users-list-superuser = Superbruker
admin-users-list-groups = Grupper
admin-users-list-created = Opprettet
admin-users-list-last-login = Siste innlogging
admin-users-list-loading = Laster …
dataset-create-panel-put-the-documents-in-a = Legg dokumentene i en mappe der og last denne siden på nytt.
dataset-create-panel-the-name-cannot-start-with = Navnet kan ikke begynne med punktum eller inneholde skråstrek.
dataset-create-panel-and-a-dash-a-space = og en bindestrek, et mellomrom eller et punktum blir til en understrek. Navnet kan ikke endres senere.
live-chats-panel-off = av
processing-updates-panel-the-waiting-steps-change-each = De ventende trinnene endrer { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), der hver fil telles én gang, i { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = og en bindestrek, et mellomrom eller et punktum blir til en understrek. Navnet kan ikke endres senere.
admin-llm-config-fresh = fersk
admin-llm-config-tools = verktøy{" "}
admin-llm-config-vision = bilde{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (skrivebeskyttet)
live-chats-panel-on = på
processing-updates-panel-up-to-date-select-it = Oppdatert. Velg den for å kjøre den på nytt.
admin-ai-status-yes = ja
admin-ai-status-no-2 = nei
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } feil
admin-collection-processing-done = ferdig
admin-collection-processing-failed-2 = { $stage_failed_documents } mislyktes
admin-collection-processing-left = igjen
admin-collection-processing-dataset-level = på datasettnivå
admin-collections-list-groups = { $c_group_count } grupper
admin-failures-operation-s = { $group_operation_count } operasjon(er)
admin-groups-list-groupname = gruppenavn
admin-llm-config-stale = utdatert
admin-llm-config-thinking-is-on = Tenkning er på
admin-llm-config-thinking-is-off = Tenkning er av
admin-llm-config-shown = { $models_len } vist
admin-llm-config-reasoning = resonnering
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } av { $load_table_count }
admin-metrics-yes = ja
admin-metrics-no = nei
admin-metrics-max = maks
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = startet { $run_started_at }
admin-operation-detail-yes = ja
admin-operation-detail-no = nei
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = e-post
admin-user-llm-untitled = (uten tittel)
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } sider
admin-processing-updates-panel-prerequisites-waiting = Samlingen må oppdateres først: { $steps }. Trinn som skriver til søkeindeksen, venter på det.
admin-operations-no-task-type-failing = Ingen oppgavetype svikter over { $threshold } %.
admin-operations-task-types-failing = { $count } oppgavetype(r) svikter over { $threshold } %.
processing-updates-panel-collection-updates = Samlingsoppdateringer
admin-collections-list-some-datasets-are-not-counted = Noen datasett er ikke talt ennå.
admin-failures-hide = Skjul
admin-failures-show = Vis
admin-settings-web-session-lifetime-in-seconds = Levetid for nettøkter i sekunder (standard: 604800 = 1 uke)
admin-settings-turns-every-new-chat-turn = Slår av alle nye chat-omganger når verdien er false (standard: true). En omgang som pågår, fullføres. Gjelder fra neste sending, uten ny distribusjon.
admin-settings-written-by-main-py-probe = Skrives av `main.py probe-embeddings`, og er det endepunktet FAKTISK leverer. Å redigere dette for hånd endrer ikke tjeneren.
admin-settings-the-folder-whose-subfolders-the = Mappen hvis undermapper datasettskjemaet viser for denne monteringen. En endring i hoover4.ini krever ny distribusjon.
admin-settings-from-hoover4-ini-changing-it = Fra hoover4.ini. En endring krever ny distribusjon.
admin-feedback-bug = Feil
admin-operations-state-name = { $state ->
        [pending] ventende
        [queued] i kø
        [running] kjører
        [finished] ferdig
        [errored] feilet
        [cancelled] avbrutt
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Sviktetre for { $op_id }
admin-failure-detail-showing-of-characters = viser { $node_stack_trace_chars_count } av { $node_stack_trace_original_len } tegn
admin-operations-operation = Operasjon { $state }.
admin-operations-dispatched = Sendt ut { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } rader
admin-operations-plans = { $row_progress_done } / { $row_progress_total } planer
admin-group-detail-group-2 = Gruppe { $groupname }
admin-settings-the-setting-was-saved-successfully = Innstillingen «{ $k }» ble lagret.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Gruppen «{ $g }» ble lagt til.
admin-user-detail-user-2 = Bruker { $username }
admin-dataset-detail-dataset = Datasett { $dataset_id }
admin-dataset-detail-collections = Samlinger › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } av { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Opplastingsinnstillingen kunne ikke leses: { $err }
admin-dataset-detail-operation-started = Operasjon startet: { $run_id }
admin-collection-detail-collection = Samling { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Vektorinnstillingen kunne ikke leses: { $err }
admin-collection-processing-processing-of = Behandling av { $collection_id }
admin-collection-processing-collections = Samlinger › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } kjøringer
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = per { $at }
admin-collection-processing-over-the-last-s = de siste { $live_window_seconds } s
admin-collection-processing-retry-started-run = Nytt forsøk startet (kjøring { $run }).
admin-collection-processing-document-retry-started-run = Nytt forsøk for dokumentet startet (kjøring { $run }).
admin-operation-detail-operation-2 = Operasjon { $op_id }
admin-user-llm-llm-usage-of = LLM-bruk av { $username }
admin-user-llm-users = Brukere › { $username }
processing-updates-panel-the-processing-updates-could-not = Behandlingsoppdateringene kunne ikke leses: { $e }
processing-updates-panel-update-started = Oppdatering startet: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } av { $operation_progress_total } planer
dataset-ocr-panel-adding = legger til { $added }
dataset-ocr-panel-removing = fjerner { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } plan(er) gjenåpnet
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] mappe
       *[other] mapper
    }
    [tables] { $count ->
        [one] tabell
       *[other] tabeller
    }
   *[files] { $count ->
        [one] fil
       *[other] filer
    }
}
processing-updates-step-runs = { $count ->
    [one] trinnkjøring
   *[other] trinnkjøringer
}
processing-update-search_schema-title = Skjema for søkeindeksen
processing-update-search_schema-explanation = { $files ->
    [one] { $count } søketabell i samlingen mangler en kolonne som søkeindeksen trenger.
   *[other] { $count } søketabeller i samlingen mangler en kolonne som søkeindeksen trenger.
} Kolonnen legges til i hver tabell. Søket fungerer hele tiden.
processing-update-search_schema-runs = Tabeller i søkeindeksen
processing-update-unfinished-title = Uferdig behandling
processing-update-unfinished-explanation = { $files ->
    [one] { $count } fil er ikke behandlet ferdig.
   *[other] { $count } filer er ikke behandlet ferdig.
} Dette omfatter filer uten behandlingsplan, for eksempel etter en avbrutt innhenting. Behandlingen deres fullføres.
processing-update-unfinished-runs = Alle behandlingstrinn for disse filene
processing-update-failed_files-title = Mislykkede filer
processing-update-failed_files-explanation = { $files ->
    [one] { $count } fil har en behandlingsfeil.
   *[other] { $count } filer har en behandlingsfeil.
} De mislykkede trinnene kjøres på nytt for dem. Den automatiske kjøringen prøver en fil én gang for hver nye versjon av trinnet som mislyktes.
processing-update-failed_files-runs = De mislykkede trinnene, deretter uthenting av entiteter, embedding og indeksering
processing-update-virus_scan-title = Virusskanning
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } fil har ingen antivirusvurdering.
   *[other] { $count } filer har ingen antivirusvurdering.
} De skannes. En fil som skanneren finner infisert, merkes i søket, og nedlasting av originalen og den søkbare PDF-en avvises.
processing-update-virus_scan-runs = Antivirusskanning, deretter søkeattributtet for infiserte filer
processing-update-tables-title = Tabeller
processing-update-tables-explanation = { $files ->
    [one] { $count } fil har en eldre tabellavlesning eller ufullstendige avhengige resultater. De lagrede resultatene oppdateres.
    *[other] { $count } filer har eldre tabellavlesninger eller ufullstendige avhengige resultater. De lagrede resultatene oppdateres.
    }

processing-update-tables-runs = Tabellavlesning, entiteter, signaler, innbygginger og begge indekser
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Filer som trenger automatisk OCR: { $count }. Tidligere OCR-tekst på det oppdagede språket beholdes uten ny OCR. De andre sidene får OCR med den installerte modellen for det oppdagede språket. Tidligere varianter fjernes når erstatningen er fullstendig.
processing-update-ocr-runs = OCR og søkbare PDF-er, deretter uthenting av entiteter, embedding og indeksering av den nye teksten
processing-update-ocr_detection-title = OCR-gjenkjenning
processing-update-ocr_detection-explanation = Filer uten gjeldende deteksjon av tekst, skriftsystem eller språk: { $count }. Hvert egnet bilde og hver PDF-side undersøkes i avgrensede grupper.
processing-update-ocr_detection-runs = Gjenkjenning, deretter søkeattributtene for disse filene
processing-update-pdf_text-title = Tekst i søkbare PDF-er
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } fil har søkbare PDF-er med et tidligere tekstlag.
   *[other] { $count } filer har søkbare PDF-er med et tidligere tekstlag.
} Det laget kopierte hver bokstav utenfor de vesteuropeiske alfabetene som en svart firkant. PDF-er på språk med bare vesteuropeiske bokstaver beholdes. De andre PDF-ene leses, og delene med svarte firkanter lages på nytt. En bilde-PDF bruker de lagrede OCR-ordene. En PDF-side får en ny OCR-forespørsel.
processing-update-pdf_text-runs = Deler av søkbare PDF-er, deretter indeksering av OCR-teksten i de gjenskapte PDF-ene
processing-update-page_text-title = Indeksert sidetekst
processing-update-page_text-explanation = Filer med ufullstendig søketekst: { $count }. Et kontrolltegn på en side avsluttet den indekserte teksten. Hele teksten blir indeksert.
processing-update-page_text-runs = Søkeindekstekst for disse sidene
processing-update-text_rows-title = Tekstdeling
processing-update-text_rows-explanation = Filer med tekst fra en tidligere deling: { $count }. PDF-tekst flyttes til én rad for hver PDF-del, og lang tekst deles med en kort overlapping. Ingen ny OCR eller parsing kjøres.
processing-update-text_rows-runs = Tekstdeling, deretter uthenting av entiteter, embedding og indeksering av den nye teksten
processing-update-vectors-title = Vektorer
processing-update-vectors-explanation = { $files ->
    [one] { $count } fil med tekst mangler vektorer fra embedding-modellen som installasjonen bruker.
   *[other] { $count } filer med tekst mangler vektorer fra embedding-modellen som installasjonen bruker.
} Vektorene deres beregnes og indekseres.
processing-update-vectors-runs = Embedding og vektorindeksering
processing-update-folder_counts-title = Mappetall
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } mappe mangler antall filer og størrelse, eller har verdier fra en tidligere versjon.
   *[other] { $count } mapper mangler antall filer og størrelse, eller har verdier fra en tidligere versjon.
} Tallene beregnes på nytt.
processing-update-folder_counts-runs = Mappetre
admin-uploads-badge = Opplastinger
admin-uploads-badge-title = Tar imot opplastinger

processing-update-archive_members-title = Arkivmedlemmer

processing-update-archive_members-explanation = { $files ->
    [one] { $count } delt arkiv trenger en gjeldende medlemsliste. Medlemmene og søkeresultatene oppdateres.
    *[other] { $count } delte arkiver trenger gjeldende medlemslister. Medlemmene og søkeresultatene oppdateres.
    }

processing-update-archive_members-runs = Arkivuttrekking, medlemsavstemming og avhengig behandling

processing-update-image_previews-title = Bildeforhåndsvisninger

processing-update-image_previews-explanation = { $files ->
    [one] { $count } uvanlig bilde mangler forhåndsvisning. Forhåndsvisningen opprettes på nytt.
    *[other] { $count } uvanlige bilder mangler forhåndsvisning. Forhåndsvisningene opprettes på nytt.
    }

processing-update-image_previews-runs = Oppretting og kontroll av bildeforhåndsvisninger

processing-update-search_terms-title = Søkeord

processing-update-search_terms-explanation = { $files ->
    [one] { $count } søketabell trenger gjeldende filtertermer. Termer for språk, OCR, skriftsystem og røde flagg blir søkbare.
    *[other] Søketabeller som trenger gjeldende filtertermer: { $count }. Termer for språk, OCR, skriftsystem og røde flagg blir søkbare.
    }

processing-update-search_terms-runs = Indeksering og kontroll av filtertermer

automatic-ocr-title = Automatisk OCR
automatic-ocr-refresh = Oppdater status
automatic-ocr-coverage = Sidedekning
automatic-ocr-pages = Sider
automatic-ocr-models = OCR-modeller
automatic-ocr-reason = Årsak
automatic-ocr-truncated = Diagnoselisten er ufullstendig.
automatic-ocr-presence = Har publisert OCR-tekst
automatic-ocr-policy = OCR velger installerte modeller ut fra oppdaget skriftsystem og språk på hver egnet side. Tesseract brukes først, EasyOCR dekker andre støttede skriftsystemer.
automatic-ocr-unknown = Ingen gjeldende publisering er registrert. Manglende deteksjon og mislykket behandling beviser ikke fravær.
automatic-ocr-retry = Bruk behandlingsoppdateringer for å gjenta ufullstendig eller mislykket arbeid etter retting. Ikke-støttet dekning krever kompatible installerte modeller.
automatic-ocr-state = { $state ->
    [candidate] Venter
    [planned] Planlagt
    [failed] Mislyktes
    [incomplete] Ufullstendig
    [unsupported] Ikke støttet
    [published] Publisert
    [applied] Verifisert
    [ready] Tekst oppdaget
    [no_text] Ingen tekst oppdaget
    *[other] { $state }
    }

processing-update-entities-title = Navngitte entiteter
processing-update-entities-explanation = Filer som trenger gjeldende entitetsuttrekk eller søkbare resultater: { $count }. Tidligere vellykkede resultater erstattes etter inferensen.
processing-update-entities-runs = Uttrekk av navngitte entiteter, tekstattributter og søkbare entitetsuttrykk

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Skriftsystem ikke identifisert
    [tesseract_capabilities_unavailable] Tesseract-dekning utilgjengelig
    [detected_language] Modellen samsvarer med oppdaget språk
    [unknown_language_script_coverage] Ukjent språk. En skriftsystemmodell er valgt.
    [language_script_mismatch_script_coverage] Språk og skriftsystem er forskjellige. En skriftsystemmodell er valgt.
    [language_model_unavailable_script_coverage] Språkmodell utilgjengelig. En skriftsystemmodell er valgt.
    [easyocr_capabilities_unavailable] EasyOCR-dekning utilgjengelig
    [tesseract_script_unavailable] Tesseract dekker ikke skriftsystemet. EasyOCR er valgt.
    [script_coverage_unavailable] Ingen installert modell dekker dette skriftsystemet.
    *[other] { $reason }
    }

processing-updates-check-requested = Pipelinen beregner oppdateringene. Antallene endres når beregningen er ferdig.
