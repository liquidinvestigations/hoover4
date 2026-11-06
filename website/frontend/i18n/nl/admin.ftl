# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Toegang tot het beheer is vereist
admin-guard-signed-in-as = Aangemeld als { $u_username }.
admin-guard-ask-an-administrator-for-access = Vraag een beheerder om toegang tot dit onderdeel.
admin-shell-dashboard = Dashboard
admin-shell-collections = Collecties
admin-shell-operations = Bewerkingen
admin-shell-errors-failures = Fouten/mislukkingen
admin-shell-feedback = Feedback
admin-shell-users = Gebruikers
admin-shell-groups = Groepen
admin-shell-settings = Instellingen
admin-shell-llm = LLM
admin-shell-ai-status = AI-status
admin-shell-metrics = Metrieken
admin-shell-administration = Beheer
dataset-create-panel-add-a-dataset = Een dataset toevoegen
dataset-create-panel-the-dataset-mounts-could-not = De datasetmounts konden niet worden gelezen, dus er valt niets te kiezen: { $err }
dataset-create-panel-loading-the-dataset-mounts = De datasetmounts laden.
dataset-create-panel-no-dataset-mount-is-configured = Er is geen datasetmount ingesteld.
dataset-create-panel-the-mount-folder-could-not = De mountmap kon niet worden gelezen, dus er valt niets te kiezen: { $err }
dataset-create-panel-no-subfolders-were-found-in = In deze mount zijn geen submappen gevonden.{" "}
dataset-create-panel-folder = Map
dataset-create-panel-select-a-folder = Kies een map
dataset-create-panel-new-folder = Nieuwe map
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } items), al een dataset
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } items)
dataset-create-panel-the-server-creates-this-folder = De server maakt deze map in de mount aan wanneer je de dataset aanmaakt.{" "}
dataset-create-panel-the-list-shows-the-direct = De lijst toont de directe submappen van de mount.
dataset-create-panel-dataset-name = Naam van de dataset
dataset-create-panel-a-name-has-lowercase-letters = Een naam bevat kleine letters, cijfers en underscores. Hoofdletters worden kleine letters,{" "}
dataset-create-panel-the-dataset-is-saved-as = De dataset wordt opgeslagen als: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Deze collectie heeft al een dataset met de naam { $saved_name }.
dataset-create-panel-accept-uploads = Uploads accepteren
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Opgeslagen als standaardwaarden van deze collectie. Geen enkele dataset wijzigt zijn talen.
dataset-create-panel-saving-u = Opslaan…
dataset-create-panel-save-as-collection-defaults = Opslaan als standaardwaarden van de collectie
dataset-create-panel-creating-u = Aanmaken…
dataset-create-panel-create-and-ingest = Aanmaken en inlezen
dataset-create-panel-mount = Mount
dataset-ocr-panel-last-operation = Laatste bewerking: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , gestart { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Al { $current_stale_seconds_60 } minuten geen voortgang. Controleer de Temporal-workflow en annuleer de bewerking als die vastzit.
dataset-ocr-panel-filter-languages = Talen filteren
dataset-ocr-panel-ocr-languages = OCR-talen
dataset-ocr-panel-failed-to-load-the-ocr = De OCR-instellingen van deze dataset konden niet worden geladen
dataset-ocr-panel-loading-u = Laden…
dataset-ocr-panel-each-easyocr-script-group-adds = Elke EasyOCR-schriftgroep voegt één OCR-ronde over de dataset toe. Tesseract leest al zijn talen in één ronde.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = Van kracht: { $panel_tesseract_languages }, afkomstig van { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = { $source_label_panel_inherited_tesseract_s } gebruiken: { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = De Tesseract-service antwoordde niet, dus de geïnstalleerde talen zijn onbekend.{" "}
dataset-ocr-panel-the-image-also-has-script = De image heeft ook { $script_models } schriftmodellen, bijvoorbeeld Latijn. Het formulier biedt ze niet aan, omdat de instelling deel wordt van een opslagsleutel en alleen codes in kleine letters accepteert.
dataset-ocr-panel-the-first-language-is-the = De eerste taal is de primaire taal. Gekozen:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = EasyOCR staat uit in deze installatie, dus deze instelling heeft geen effect totdat het aan staat.
dataset-ocr-panel-in-force-off-from = Van kracht: uit, afkomstig van { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = Van kracht: { $panel_easyocr_languages }, afkomstig van { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = { $source_label_panel_inherited_easyocr_sou } gebruiken: uit
dataset-ocr-panel-use-2 = { $source_label_panel_inherited_easyocr_sou } gebruiken: { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Ingeschakeld
dataset-ocr-panel-the-easyocr-service-did-not = De EasyOCR-service gaf niet door welke talen hij ondersteunt.
dataset-ocr-panel-a-model-download-failed = Het downloaden van een model is mislukt: { $failure }
dataset-ocr-panel-stored-text-variants = Opgeslagen tekstvarianten
dataset-ocr-panel-removing-a-language-deletes-its = Als je een taal verwijdert, worden de tekst, de zoekrijen en de doorzoekbare PDF van die taal verwijderd.
dataset-ocr-panel-searchable-pdfs = Doorzoekbare PDF's
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } bestanden · { $variant_total_bytes_1024_1024 } MB
dataset-ocr-panel-searchable-pdfs-are-off-on = Doorzoekbare PDF's staan uit in deze installatie.
dataset-ocr-panel-saving-u = Opslaan…
dataset-ocr-panel-apply = Toepassen
dataset-ocr-panel-no-changes-to-apply = Geen wijzigingen om toe te passen.
live-chats-panel-live-llm-chats = Live LLM-chats
live-chats-panel-agent-turns-running-right-now = Beurten van agents die nu lopen, de langstlopende eerst. Wordt elke 2 s vernieuwd. Gelezen uit Temporal, dus een beurt die voor de laatste herstart van de website begon, staat hier ook.
live-chats-panel-loading-u = Laden…
live-chats-panel-no-chats-running = Er lopen geen chats.
live-chats-panel-user = Gebruiker
live-chats-panel-conversation = Gesprek
live-chats-panel-question = Vraag
live-chats-panel-internet = Internet
live-chats-panel-running = Loopt
live-chats-panel-started = Gestart
live-chats-panel-cancels-the-workflow-the-turn = Annuleert de workflow. De beurt eindigt met een stopmarkering in het transcript en verdwijnt niet.
live-chats-panel-kill = Beëindigen
processing-updates-panel-loading-u = Laden…
processing-updates-panel-open-the-operation = De bewerking openen
processing-updates-panel-the-pipeline-has-not-calculated = De pipeline heeft deze updates nog niet berekend.
processing-updates-panel-calculated-at-in-ms = Berekend op { $view_checked_at } in { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatische updates staan uit in deze installatie. Start de updates met de knop.
processing-updates-panel-step = Stap
processing-updates-panel-count = Aantal
processing-updates-panel-state = Status
processing-updates-panel-last-run = Laatste uitvoering
processing-updates-panel-runs = Uitvoeringen: { $step_runs }
processing-updates-panel-a-run-again-would-select = Een nieuwe uitvoering zou ongeveer dit aantal { $step_unit } selecteren.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } bij een nieuwe uitvoering
processing-updates-panel-never = Nooit
processing-updates-panel-update-collection = Collectie bijwerken
processing-updates-panel-update-processing = Verwerking bijwerken
processing-updates-panel-check-again = Opnieuw controleren
processing-updates-panel-dataset = Dataset
processing-updates-panel-processing-updates = Verwerkingsupdates
admin-ai-status-admin-ai-status = Beheer: AI-status
admin-ai-status-ai-status = AI-status
admin-ai-status-the-configured-service-and-the = De ingestelde service en de service die daadwerkelijk antwoordt. Een terugval op de CPU-service is alleen hier te zien.
admin-ai-status-loading-u = Laden…
admin-ai-status-config-fingerprint = Configuratievingerafdruk
admin-ai-status-website-worker = Website / worker
admin-ai-status-ai-server = AI-server
admin-ai-status-match = Overeenkomst
admin-ai-status-embeddings-probe = Embeddingstest
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dimensies
admin-ai-status-llm-configured = LLM ingesteld
admin-ai-status-capabilities = Mogelijkheden
admin-ai-status-capability = Mogelijkheid
admin-ai-status-configured = Ingesteld
admin-ai-status-serving = Actief
admin-ai-status-model = Model
admin-ai-status-reachable = Bereikbaar
admin-ai-status-detail = Detail
admin-ai-status-no = NEE
admin-ai-status-vector-shard-dims-vs-probe = Dimensies van vectorshards tegenover de test
admin-ai-status-no-collections-yet = Nog geen collecties.
admin-ai-status-collection = Collectie
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Komt overeen met de test
admin-ai-status-browser-router = Browserrouter
admin-ai-status-live-sessions = Live sessies: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Recent LLM-verkeer (24 u)
admin-ai-status-no-llm-call-events-yet = Nog geen llm_call_events.
admin-ai-status-user = Gebruiker
admin-ai-status-calls = Aanroepen
admin-ai-status-errors = Fouten
admin-ai-status-service-use-24-h = Servicegebruik % (24 u)
admin-ai-status-busy-seconds-in-the-last = Bezette seconden in de laatste 24 uur, als aandeel van de dag.
admin-ai-status-no-samples-yet = Nog geen metingen.
admin-ai-status-service = Service
admin-ai-status-busy-s = Bezet s
admin-ai-status-use = Gebruik %
admin-collection-detail-admin-collection = Beheer: collectie { $collection_id }
admin-collection-detail-failed-to-load-collection = De collectie kon niet worden geladen
admin-collection-detail-loading = Laden...
admin-collection-detail-datasets = Datasets
admin-collection-detail-dataset = Dataset
admin-collection-detail-documents = Documenten
admin-collection-detail-size = Grootte
admin-collection-detail-indexed = Geïndexeerd
admin-collection-detail-errors = Fouten
admin-collection-detail-state = Status
admin-collection-detail-created = Aangemaakt
admin-collection-detail-settings = Instellingen
admin-collection-detail-the-collection-database-is-not = De database van de collectie is nog niet gereed.
admin-collection-detail-the-last-storage-provisioning-failed = De laatste inrichting van de opslag is mislukt: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Verwerkingsvoortgang en schattingen
admin-collection-detail-display-name = Weergavenaam
admin-collection-detail-display-name-2 = weergavenaam
admin-collection-detail-save = Opslaan
admin-collection-detail-access = Toegang
admin-collection-detail-public-every-signed-in-user = Openbaar. Elke aangemelde gebruiker kan deze collectie doorzoeken en lezen.
admin-collection-detail-restricted-only-members-of-the = Beperkt. Alleen leden van de groepen hieronder kunnen deze collectie doorzoeken en lezen.
admin-collection-detail-the-collection-is-now-public = De collectie is nu openbaar.
admin-collection-detail-the-collection-is-now-restricted = De collectie is nu beperkt.
admin-collection-detail-make-restricted = Beperkt maken
admin-collection-detail-make-public = Openbaar maken
admin-collection-detail-group-permissions = Groepsrechten
admin-collection-detail-no-group-can-read-this = Nog geen groep kan deze collectie lezen.
admin-collection-detail-revoke = Intrekken
admin-collection-detail-grant-group-u = Groep toekennen…
admin-collection-detail-grant = Toekennen
admin-collection-detail-danger-zone = Gevarenzone
admin-collection-detail-a-collection-can-only-be = Een collectie kan alleen worden verwijderd zolang ze geen datasets heeft.
admin-collection-detail-deleting-the-collection-also-drops = Als je de collectie verwijdert, verwijder je ook haar database{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}en alles erin. Dit kan niet ongedaan worden gemaakt. Typ de naam van de collectie ter bevestiging.
admin-collection-detail-collection-name = Naam van de collectie
admin-collection-detail-delete-collection = Collectie verwijderen
admin-collection-detail-features = Functies
admin-collection-detail-vectors = Vectoren
admin-collection-detail-this-installation-runs-no-embedding = Deze installatie draait geen embeddingservice, dus geen enkele collectie gebruikt vectoren.
admin-collection-detail-vectors-find-passages-by-meaning = Vectoren vinden passages op betekenis. Uit stopt nieuwe vectoren en laat het zoeken de opgeslagen vectoren niet meer gebruiken, die blijven bewaard. Aan berekent de ontbrekende vectoren van elke dataset, één dataset tegelijk.
admin-collection-detail-this-collection-follows-the-installation = Deze collectie volgt de installatie, die vectoren gebruikt. Vectoren vinden passages op betekenis. Uit stopt nieuwe vectoren en laat het zoeken de opgeslagen vectoren niet meer gebruiken, die blijven bewaard.
admin-collection-processing-could-not-load-this-panel = Dit paneel kon niet worden geladen: { $message }
admin-collection-processing-admin-processing-of = Beheer: verwerking van { $collection_id }
admin-collection-processing-u-back-to-collection = ← Terug naar de collectie
admin-collection-processing-processing-stages = Verwerkingsfasen
admin-collection-processing-loading-u = Laden…
admin-collection-processing-the-collection-database-is-still = De database van de collectie wordt nog ingericht.
admin-collection-processing-this-collection-has-no-datasets = Deze collectie heeft nog geen datasets.
admin-collection-processing-eta = Verwacht klaar over { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Nog geen metingen voor de schatting. Ze worden verzameld terwijl de dataset wordt verwerkt.
admin-collection-processing-estimated-completion = Geschatte voltooiing:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(over { $humanize_seconds_c_eta_seconds }, een schatting naar beste vermogen en geen planning)
admin-collection-processing-no-current-estimate-the-pipeline = Geen actuele schatting. De pipeline is klaar of boekt geen meetbare voortgang.
admin-collection-processing-where-processing-time-goes = Waar de verwerkingstijd blijft
admin-collection-processing-no-task-executions-recorded-yet = Nog geen taakuitvoeringen vastgelegd. Elke activiteit die de pipeline uitvoert schrijft hier één rij, dus een lege tabel betekent dat er niets is verwerkt sinds de instrumentatie is uitgerold.
admin-collection-processing-summed-task-time = Opgetelde taaktijd
admin-collection-processing-wall-clock = Kloktijd
admin-collection-processing-achieved-parallelism = Bereikte parallelliteit
admin-collection-processing-summed-task-time-divided-by = Opgetelde taaktijd gedeeld door kloktijd is wat de pipeline feitelijk parallel heeft bereikt. Dicht bij 1 betekent dat de bovenste taak hieronder alle kosten vormt en het waard is om te optimaliseren. Dicht bij het aantal workerslots betekent dat de slots verzadigd zijn en dat meer workers de goedkopere oplossing is. De kloktijd loopt van de eerste tot de laatste uitvoering, inclusief wachttijd.
admin-collection-processing-task = Taak
admin-collection-processing-total = Totaal
admin-collection-processing-share = Aandeel
admin-collection-processing-executions = Uitvoeringen
admin-collection-processing-mean = Gemiddelde
admin-collection-processing-max = Max
admin-collection-processing-failed = Mislukt
admin-collection-processing-live-activity = Live activiteit
admin-collection-processing-nothing-running-no-activity-finished = Er loopt niets. In de laatste { $live_window_seconds } s is geen activiteit voltooid en geen worker meldt iets dat bezig is.
admin-collection-processing-in-flight = Bezig
admin-collection-processing-average-concurrency = Gemiddelde gelijktijdigheid
admin-collection-processing-task-time-in-window = Taaktijd in het venster
admin-collection-processing-share-of-processing-time-over = Aandeel van de verwerkingstijd over de laatste { $live_window_seconds } s, elke 5 s vernieuwd. Een uitvoering die over de rand van het venster loopt, telt alleen mee voor het deel binnen het venster. Een rij met uitvoeringen die bezig zijn maar zonder aandeel, begon voor het venster en is nog niet klaar. Controleer de leeftijd ervan.
admin-collection-processing-share-of-window = Aandeel van het venster
admin-collection-processing-task-time = Taaktijd
admin-collection-processing-completed = Voltooid
admin-collection-processing-oldest-running = Oudste lopende
admin-collection-processing-temporal-workflows = Temporal-workflows
admin-collection-processing-workflows-of-this-collection-s = Workflows van de datasets van deze collectie, inclusief onderliggende workflows.
admin-collection-processing-no-workflows-match-this-filter = Geen workflows komen overeen met dit filter.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Type
admin-collection-processing-status = Status
admin-collection-processing-started = Gestart
admin-collection-processing-closed = Afgesloten
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = openen ↗
admin-collection-processing-failed-tasks = Mislukte taken
admin-collection-processing-no-task-failures-recorded = Geen taakmislukkingen vastgelegd.
admin-collection-processing-dataset = Dataset
admin-collection-processing-errors = Fouten
admin-collection-processing-documents = Documenten
admin-collection-processing-last-seen = Laatst gezien
admin-collection-processing-sample = Voorbeeld
admin-collection-processing-retry = Opnieuw proberen
admin-collection-processing-failures-per-document = Mislukkingen per document
admin-collection-processing-no-document-failures-recorded = Geen documentmislukkingen vastgelegd.
admin-collection-processing-document = Document
admin-collections-list-admin-collections = Beheer: collecties
admin-collections-list-collections = Collecties
admin-collections-list-loading-collections-u = Collecties laden…
admin-collections-list-datasets = Datasets
admin-collections-list-loading-datasets-u = Datasets laden…
admin-collections-list-add-a-collection = Een collectie toevoegen
admin-collections-list-name-for-example-enron = Naam, bijvoorbeeld enron
admin-collections-list-display-name = Weergavenaam
admin-collections-list-add-collection = Collectie toevoegen
admin-collections-list-a-name-has-lowercase-letters = Een naam bevat kleine letters, cijfers en underscores. Hoofdletters worden kleine letters,{" "}
admin-collections-list-the-collection-is-saved-as = De collectie wordt opgeslagen als: { $new_name }
admin-collections-list-a-collection-with-the-name = Er bestaat al een collectie met de naam { $new_name }.
admin-collections-list-collection = Collectie
admin-collections-list-documents = Documenten
admin-collections-list-size = Grootte
admin-collections-list-errors = Fouten
admin-collections-list-state = Status
admin-collections-list-access = Toegang
admin-collections-list-database-not-ready = Database niet gereed
admin-collections-list-public = Openbaar
admin-collections-list-1-group = 1 groep
admin-collections-list-not-counted-yet = Nog niet geteld
admin-collections-list-unknown = Onbekend
admin-collections-list-no-collection-has-a-dataset = Geen enkele collectie heeft een dataset.
admin-collections-list-dataset = Dataset
admin-collections-list-indexed = Geïndexeerd
admin-collections-list-created = Aangemaakt
admin-dashboard-admin-dashboard = Beheer: dashboard
admin-dashboard-administration = Beheer
admin-dashboard-users = Gebruikers
admin-dashboard-groups = Groepen
admin-dashboard-collections = Collecties
admin-dashboard-datasets = Datasets
admin-dashboard-failed-to-load-counts = De aantallen konden niet worden geladen: { $e }
admin-dataset-detail-admin-dataset = Beheer: dataset { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = De dataset kon niet worden geladen
admin-dataset-detail-loading = Laden...
admin-dataset-detail-metadata = Metadata
admin-dataset-detail-display-name = Weergavenaam
admin-dataset-detail-name = Naam
admin-dataset-detail-type = Type
admin-dataset-detail-path = Pad
admin-dataset-detail-created = Aangemaakt
admin-dataset-detail-collection = Collectie
admin-dataset-detail-save = Opslaan
admin-dataset-detail-statistics = Statistieken
admin-dataset-detail-state = Status
admin-dataset-detail-documents = Documenten
admin-dataset-detail-size = Grootte
admin-dataset-detail-indexed = Geïndexeerd
admin-dataset-detail-errors = Fouten
admin-dataset-detail-plans-finished = Afgeronde plannen
admin-dataset-detail-disk = Schijf
admin-dataset-detail-rescan-disk-reads-the-dataset = Schijf opnieuw scannen leest de map van de dataset opnieuw, voegt nieuwe en gewijzigde bestanden toe en verwerkt ze.
admin-dataset-detail-rescan-disk = Schijf opnieuw scannen
admin-dataset-detail-danger-zone = Gevarenzone
admin-dataset-detail-this-deletes-the-dataset-and = Dit verwijdert de dataset en alle gegevens die eruit zijn gehaald. Je kunt het niet ongedaan maken.
admin-dataset-detail-delete-dataset-and-its-data = Dataset en bijbehorende gegevens verwijderen
admin-dataset-detail-accept-uploads = Uploads accepteren
admin-dataset-detail-the-folder-of-this-dataset = De map van deze dataset staat niet in een beschrijfbare datasetmount, dus er komen geen uploads binnen.
admin-dataset-detail-starting-u = Starten…
admin-failure-detail-admin-failure = Beheer: mislukking { $op_id }
admin-failure-detail-loading-tree = Boom laden…
admin-failure-detail-back-to-errors-and-failures = Terug naar fouten en mislukkingen
admin-failure-detail-operations = Bewerkingen
admin-failure-detail-scrubbed-copy-written-to-the = Geschoonde kopie naar het klembord geschreven.
admin-failure-detail-this-tree-is-truncated-at = Deze boom is afgekapt. Minstens één vastlegging heeft knooppunten weggelaten.
admin-failure-detail-the-captured-tree-has-expired = De vastgelegde boom is verlopen. De rij van de bewerking is nog aanwezig.
admin-failure-detail-no-captured-nodes-for-this = Geen vastgelegde knooppunten voor deze bewerking.
admin-failure-detail-operation = Bewerking
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } wortel(s) · { $tree_nodes_len } knooppunt(en)
admin-failure-detail-open-in-temporal = Openen in Temporal
admin-failure-detail-scrubbed-copy = Geschoonde kopie
admin-failure-detail-the-scrubbed-copy-replaces-dataset = De geschoonde kopie vervangt datasetpaden door hashes en lange waarden door hun lengte.
admin-failure-detail-copy-scrubbed-record = Geschoonde record kopiëren
admin-failure-detail-tree = Boom
admin-failure-detail-root = Wortel ·{" "}
admin-failure-detail-node-parent-depth-source-stage = knooppunt { $node_node_index } · bovenliggend { $node_parent_index } · diepte { $node_depth } · bron { $node_source } · fase { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = workflow { $node_workflow_id } · run { $node_run_id } · activiteit { $node_activity_id } · poging { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } knooppunt(en) weggelaten bij deze vastlegging
admin-failures-admin-errors-and-failures = Beheer: fouten en mislukkingen
admin-failures-errors-failures = Fouten/mislukkingen
admin-failures-loading-failures = Mislukkingen laden…
admin-failures-operational-failures = Operationele mislukkingen
admin-failures-no-operational-failures-at-this = Er zijn nu geen operationele mislukkingen.
admin-failures-collection = Collectie
admin-failures-dataset = Dataset
admin-failures-task-name = Taaknaam
admin-failures-error-class = Foutklasse
admin-failures-operation-kind = Soort bewerking
admin-failures-from = Van
admin-failures-to = Tot
admin-failures-no-captured-failures-match-these = Geen vastgelegde mislukkingen komen overeen met deze filters.
admin-failures-signature = Signatuur
admin-failures-count = Aantal
admin-failures-class = Klasse
admin-failures-task = Taak
admin-failures-last-seen = Laatst gezien
admin-failures-newer = Nieuwer
admin-failures-page = Pagina { $current_page_1 }
admin-failures-older = Ouder
admin-failures-per-page = Per pagina
admin-failures-loading-instances = Exemplaren laden…
admin-failures-no-instances-for-this-signature = Geen exemplaren voor deze signatuur.
admin-failures-node = {" "}knooppunt { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Documentfouten
admin-failures-error-text = Foutmelding
admin-failures-loading-document-errors-u = Documentfouten laden…
admin-failures-no-document-errors-match-these = Geen documentfouten komen overeen met deze filters.
admin-failures-errors-by-dataset-and-task = Fouten per dataset en taak
admin-failures-documents = Documenten
admin-failures-show-only-this-dataset-and = Alleen deze dataset en taak tonen
admin-failures-total = Totaal
admin-failures-errors = Fouten
admin-failures-document = Document
admin-failures-runs = Uitvoeringen
admin-failures-error = Fout
admin-failures-dataset-step = Datasetstap
admin-failures-previous-page = Vorige pagina
admin-failures-page-of-1-error = Pagina { $page } van { $pages }, 1 fout
admin-failures-page-of-errors = Pagina { $page } van { $pages }, { $data_total } fouten
admin-failures-next-page = Volgende pagina
admin-feedback-admin-feedback = Beheer: feedback
admin-feedback-feedback = Feedback
admin-feedback-search-titles-descriptions-accounts-and = Zoek in titels, beschrijvingen, accounts en adressen
admin-feedback-search = Zoeken
admin-feedback-loading-reports-u = Meldingen laden…
admin-feedback-1-report-matches = 1 melding komt overeen.
admin-feedback-reports-match = { $data_total } meldingen komen overeen.
admin-feedback-received = Ontvangen
admin-feedback-type = Type
admin-feedback-title = Titel
admin-feedback-from = Van
admin-feedback-captures = Vastleggingen
admin-feedback-state = Status
admin-feedback-previous-page = Vorige pagina
admin-feedback-page-of = Pagina { $page } van { $pages }
admin-feedback-next-page = Volgende pagina
admin-feedback-image = Afbeelding { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Gelezen
admin-feedback-unread = Ongelezen
admin-feedback-archived = Gearchiveerd
admin-feedback-mark-unread = Markeren als ongelezen
admin-feedback-mark-read = Markeren als gelezen
admin-feedback-restore = Herstellen
admin-feedback-archive = Archiveren
admin-feedback-page = Pagina:{" "}
admin-feedback-the-report-has-no-description = De melding heeft geen beschrijving.
admin-feedback-open-the-page-image = De pagina-afbeelding openen
admin-feedback-open-the-dom-copy = De DOM-kopie openen
admin-feedback-page-image-of-the-report = Pagina-afbeelding van de melding
admin-feedback-debug-context-and-browser-log = Debugcontext en browserlogboek
admin-feedback-loading-u = Laden…
admin-group-detail-admin-group = Beheer: groep { $groupname }
admin-group-detail-failed-to-load-group = De groep kon niet worden geladen
admin-group-detail-loading = Laden...
admin-group-detail-group = Groep
admin-group-detail-display-name = Weergavenaam
admin-group-detail-display-name-2 = weergavenaam
admin-group-detail-save = Opslaan
admin-group-detail-members = Leden
admin-group-detail-saving-membership = Lidmaatschap opslaan...
admin-group-detail-username = Gebruikersnaam
admin-group-detail-origin = Herkomst
admin-group-detail-group-admin = Groepsbeheerder
admin-group-detail-uploader = Uploader
admin-group-detail-remove = Verwijderen
admin-group-detail-username-to-add = gebruikersnaam om toe te voegen
admin-group-detail-add-member = Lid toevoegen
admin-group-detail-collection-access = Toegang tot collecties
admin-group-detail-this-group-has-no-collection = Deze groep heeft geen collectierechten.
admin-group-detail-revoke = Intrekken
admin-group-detail-grant-collection-u = Collectie toekennen…
admin-group-detail-grant = Toekennen
admin-group-detail-danger-zone = Gevarenzone
admin-group-detail-delete-group = Groep verwijderen
admin-groups-list-admin-groups = Beheer: groepen
admin-groups-list-groups = Groepen
admin-groups-list-add-group = Groep toevoegen
admin-groups-list-display-name = weergavenaam
admin-groups-list-use-lowercase-letters-digits-underscores = Gebruik in de naam kleine letters, cijfers, underscores en streepjes. De naam kan later niet worden gewijzigd.
admin-groups-list-add-group-2 = Groep toevoegen +
admin-groups-list-group = Groep
admin-groups-list-display-name-2 = Weergavenaam
admin-groups-list-members = Leden
admin-groups-list-collections = Collecties
admin-groups-list-loading = Laden...
admin-llm-config-admin-llm = Beheer: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Laden…
admin-llm-config-no-llm-provider-is-configured = Er is geen LLM-provider ingesteld. Stel LLM_BASE_URL / LLM_MODEL in hoover4.ini in en implementeer opnieuw.
admin-llm-config-providers = Providers
admin-llm-config-the-refresh-runs-in-the = De vernieuwing draait op de achtergrond. De huidige lijst blijft intussen zichtbaar.
admin-llm-config-refresh-in-flight-u = {" "}Vernieuwing bezig…
admin-llm-config-provider = Provider
admin-llm-config-models = Modellen
admin-llm-config-freshest = Meest recent
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Catalogus vernieuwen
admin-llm-config-agent-turns-board-assessments-and = Beurten van agents, evaluaties van borden en rapportconversies
admin-llm-config-titles-summaries-and-board-labels = Titels, samenvattingen en labels van borden
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini stelt deze modellen in: het quality_model van de LLM-provider voor beurten van agents, evaluaties van borden en rapportconversies wanneer dat is ingesteld, en het model van de provider voor de rest.
admin-llm-config-thinking = Thinking
admin-llm-config-the-model-reasons-before-each = Het model redeneert voor elke toolaanroep en elk antwoord.
admin-llm-config-catalog = Catalogus
admin-llm-config-filter-models-u = Modellen filteren…
admin-llm-config-model = Model
admin-llm-config-flags = Vlaggen
admin-llm-config-calls-14d = Aanroepen 14d
admin-llm-config-ai-status = AI-status
admin-llm-config-shows-the-serving-health = {" "}toont de gezondheid van de service.
admin-llm-reports-reports = Rapporten
admin-llm-reports-each-report-runs-when-you = Elk rapport draait wanneer je op de knop ervan klikt.
admin-llm-reports-running-u = Bezig…
admin-llm-reports-run-report = Rapport uitvoeren
admin-llm-reports-read-at = Gelezen op { $read_at }
admin-llm-reports-errors = Fouten
admin-llm-reports-failed-attempts-by-step-and = Mislukte pogingen per stap en foutklasse, en agent-runs die mislukten of eerder eindigden, per reden van beëindiging.
admin-llm-reports-source = Bron
admin-llm-reports-class = Klasse
admin-llm-reports-no-errors-in-30-days = Geen fouten in 30 dagen.
admin-llm-reports-recent-errors = Recente fouten
admin-llm-reports-the-newest-100-failed-attempts = De nieuwste 100 mislukte pogingen van 7 dagen. Open een rij om de fout te lezen.
admin-llm-reports-time = Tijd
admin-llm-reports-user = Gebruiker
admin-llm-reports-name = Naam
admin-llm-reports-error = Fout
admin-llm-reports-no-errors-in-7-days = Geen fouten in 7 dagen.
admin-llm-reports-show = Tonen
admin-llm-reports-tool-calls = Toolaanroepen
admin-llm-reports-one-row-for-each-tool = Eén rij per tool, op aantal aanroepen in 30 dagen. Een fout is een mislukte aanroep.
admin-llm-reports-tool = Tool
admin-llm-reports-calls-24-h = Aanroepen 24 u
admin-llm-reports-error-24-h = Fout % 24 u
admin-llm-reports-avg-ms-24-h = Gem. ms 24 u
admin-llm-reports-calls-7-d = Aanroepen 7 d
admin-llm-reports-error-7-d = Fout % 7 d
admin-llm-reports-avg-ms-7-d = Gem. ms 7 d
admin-llm-reports-calls-30-d = Aanroepen 30 d
admin-llm-reports-error-30-d = Fout % 30 d
admin-llm-reports-avg-ms-30-d = Gem. ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Geen toolaanroepen in 30 dagen.
admin-llm-reports-top-users = Topgebruikers
admin-llm-reports-the-30-users-with-the = De 30 gebruikers met de meeste modeltijd in het venster.
admin-llm-reports-30-days = 30 dagen
admin-llm-reports-7-days = 7 dagen
admin-llm-reports-24-hours = 24 uur
admin-llm-reports-tool-time = Tooltijd
admin-llm-reports-model-calls = Modelaanroepen
admin-llm-reports-model-time = Modeltijd
admin-llm-reports-tokens-in = Tokens in
admin-llm-reports-tokens-out = Tokens uit
admin-llm-reports-no-agent-use-in-the = Geen agentgebruik in het venster.
admin-llm-reports-system-one-checks = Controles van System one
admin-llm-reports-requests-are-grouped-by-hook = Aanvragen zijn gegroepeerd per hook en regel. Latenties zijn in milliseconden. Aandelen gebruiken de aanvragen van de laatste 30 dagen.
admin-llm-reports-counts = Aantallen
admin-llm-reports-recent-failures = Recente mislukkingen
admin-llm-reports-select-run-report-to-read = Kies Rapport uitvoeren om de statistieken te lezen.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Regel
admin-llm-reports-outcome = Uitkomst
admin-llm-reports-questions = Vragen
admin-llm-reports-median-ms = Mediaan ms
admin-llm-reports-95th-percentile-ms = 95e percentiel ms
admin-llm-reports-error-2 = Fout %
admin-llm-reports-positive = Positief %
admin-llm-reports-actions = Acties
admin-metrics-admin-metrics = Beheer: metrieken
admin-metrics-metrics = Metrieken
admin-metrics-the-last-24-hours = De laatste 24 uur.
admin-metrics-loading-u = Laden…
admin-metrics-manticore-load-now = Manticore-belasting (nu)
admin-metrics-ram-is-the-memory-of = RAM is het geheugen van de tabellen. De threadbelasting geldt voor de laatste 1, 5 en 15 minuten.
admin-metrics-manticore-status-could-not-be = De Manticore-status kon niet worden gelezen: { $error }
admin-metrics-thread-load-1-5-15 = Threadbelasting (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Primaire threadbelasting (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Secundaire threadbelasting (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Workerthreads bezet / totaal
admin-metrics-work-queue = Werkwachtrij
admin-metrics-ram-held-by-tables = RAM in gebruik door tabellen
admin-metrics-disk-used-by-tables = Schijfruimte in gebruik door tabellen
admin-metrics-tables-merging = Tabellen die samenvoegen
admin-metrics-tables-read = Gelezen tabellen
admin-metrics-read-at = Gelezen op
admin-metrics-largest-tables-by-ram = Grootste tabellen naar RAM
admin-metrics-table = Tabel
admin-metrics-ram = RAM
admin-metrics-disk = Schijf
admin-metrics-disk-chunks = Schijfchunks
admin-metrics-merging = Samenvoegen
admin-metrics-usage-last-24-h = Gebruik (laatste 24 u)
admin-metrics-events-by-type = Gebeurtenissen per type
admin-metrics-event = Gebeurtenis
admin-metrics-count = Aantal
admin-metrics-events-per-hour = Gebeurtenissen per uur
admin-metrics-no-events-recorded-yet = Nog geen gebeurtenissen vastgelegd.
admin-metrics-busiest-users = Drukste gebruikers
admin-metrics-user = Gebruiker
admin-metrics-events = Gebeurtenissen
admin-metrics-events-2 = { $point_bucket }: { $point_count } gebeurtenissen
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API-aanroepen (laatste 24 u)
admin-metrics-no-api-calls-recorded-yet = Nog geen API-aanroepen vastgelegd.
admin-metrics-function = Functie
admin-metrics-calls = Aanroepen
admin-metrics-errors = Fouten
admin-metrics-error-rate = Foutpercentage
admin-metrics-bytes-in = Bytes in
admin-metrics-bytes-out = Bytes uit
admin-operation-detail-admin-operation = Beheer: bewerking { $op_id }
admin-operation-detail-loading-operation = Bewerking laden…
admin-operation-detail-back-to-operations = Terug naar bewerkingen
admin-operation-detail-operation = Bewerking
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · in de wachtrij gezet op { $row_started_at }
admin-operation-detail-not-started = niet gestart
admin-operation-detail-re-run-counts-are-not = De aantallen voor een nieuwe uitvoering zijn niet beschikbaar.
admin-operation-detail-failed-document-s-task-failure = { $documents } mislukte document(en), { $row_failed_tasks_unwrap_or_0 } taakmislukking(en)
admin-operation-detail-failures-were-not-counted = Mislukkingen zijn niet geteld.
admin-operation-detail-open-captured-failure-tree = De vastgelegde mislukkingsboom openen
admin-operation-detail-open-in-temporal = Openen in Temporal
admin-operation-detail-plans = Plannen
admin-operation-detail-plan-s-page = { $data_plans_total } plan(nen), pagina { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Voor deze bewerking zijn geen plannen vastgelegd.
admin-operation-detail-dataset = Dataset
admin-operation-detail-plan-hash = Planhash
admin-operation-detail-source = Bron
admin-operation-detail-finished = Afgerond
admin-operation-detail-previous = Vorige
admin-operation-detail-next = Volgende
admin-operation-detail-error-events = Foutgebeurtenissen
admin-operation-detail-error-event-s-page = { $data_events_total } foutgebeurtenis(sen), pagina { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Voor deze bewerking zijn geen foutgebeurtenissen vastgelegd.
admin-operation-detail-time = Tijd
admin-operation-detail-hash = Hash
admin-operation-detail-task = Taak
admin-operation-detail-event = Gebeurtenis
admin-operation-detail-error-excerpt = Fragment van de fout
admin-operations-admin-operations = Beheer: bewerkingen
admin-operations-operations = Bewerkingen
admin-operations-loading-operations = Bewerkingen laden…
admin-operations-filters = Filters
admin-operations-state = Status
admin-operations-any-state = Elke status
admin-operations-collection = Collectie
admin-operations-all-collections = Alle collecties
admin-operations-choose-a-collection-to-see = Kies een collectie om de foutpercentages per taak te zien.
admin-operations-operations-newest-first = Bewerkingen, nieuwste eerst
admin-operations-newer = Nieuwer
admin-operations-page = Pagina { $current_page_1 }
admin-operations-older = Ouder
admin-operations-failure-rate-by-task-type = Mislukkingspercentage per tasktype ({ $collectionname })
admin-operations-one-row-per-activity-execution = Eén rij per uitvoering van een activiteit, nieuwe pogingen inbegrepen. Een percentage boven{" "}
admin-operations-is-marked = {" "}wordt gemarkeerd.
admin-operations-no-task-executions-recorded-for = Voor deze collectie zijn nog geen taakuitvoeringen vastgelegd.
admin-operations-task = Taak
admin-operations-error-rate = Foutpercentage
admin-operations-failed-total-executions = Mislukte / totale uitvoeringen
admin-operations-documents-affected = Getroffen documenten
admin-operations-above-the-line = boven de grens
admin-operations-no-operations-recorded-for-this = Voor dit filter zijn geen bewerkingen vastgelegd.
admin-operations-kind = Soort
admin-operations-target = Doel
admin-operations-workflow = Workflow
admin-operations-queued-at = In de wachtrij gezet op
admin-operations-started = Gestart
admin-operations-duration = Duur
admin-operations-progress = Voortgang
admin-operations-eta = Verwacht klaar
admin-operations-outcome = Uitkomst
admin-operations-destructive = Destructief
admin-operations-repeated-run = Herhaalde uitvoering
admin-operations-no-estimate-yet = nog geen schatting
admin-operations-cancel = Annuleren
admin-operations-type-to-confirm = typ { $target } ter bevestiging
admin-operations-re-run = Opnieuw uitvoeren
admin-operations-waiting-for-a-free-slot = wacht op een vrij slot of een vrij doel
admin-operations-counting-work = werk tellen…
admin-operations-open-captured-tree = Vastgelegde boom openen
admin-operations-no-captured-tree = geen vastgelegde boom
admin-operations-no-failed-documents = geen mislukte documenten
admin-operations-document-s-failed = { $n } document(en) mislukt
admin-operations-task-failure-s = { $t } taakmislukking(en)
admin-operations-failures-not-counted = mislukkingen niet geteld
admin-operations-the-newest-ten-operations-of = De nieuwste tien bewerkingen van deze collectie.{" "}
admin-operations-all-operations = Alle bewerkingen
admin-settings-admin-settings = Beheer: instellingen
admin-settings-server-settings = Serverinstellingen
admin-settings-key = Sleutel
admin-settings-value = Waarde
admin-settings-description = Beschrijving
admin-settings-save = Opslaan
admin-settings-loading = Laden...
admin-settings-deployment-configuration-read-only = Configuratie van de installatie (alleen-lezen)
admin-settings-not-set = (niet ingesteld)
admin-user-detail-admin-user = Beheer: gebruiker { $username }
admin-user-detail-failed-to-load-user = De gebruiker kon niet worden geladen
admin-user-detail-loading = Laden...
admin-user-detail-user = Gebruiker
admin-user-detail-the-next-login-replaces-the = Bij de volgende aanmelding vervangt de loginproxy de volledige naam, het e-mailadres en de superuserstatus van een gebruiker.
admin-user-detail-llm-usage-u = LLM-gebruik →
admin-user-detail-full-name = Volledige naam
admin-user-detail-full-name-2 = volledige naam
admin-user-detail-email = E-mail
admin-user-detail-superuser = Superuser
admin-user-detail-save = Opslaan
admin-user-detail-groups = Groepen
admin-user-detail-saving-membership = Lidmaatschap opslaan...
admin-user-detail-group = Groep
admin-user-detail-origin = Herkomst
admin-user-detail-group-admin = Groepsbeheerder
admin-user-detail-uploader = Uploader
admin-user-detail-remove = Verwijderen
admin-user-detail-add-to-group-u = Aan groep toevoegen…
admin-user-detail-add = Toevoegen
admin-user-detail-danger-zone = Gevarenzone
admin-user-detail-delete-user = Gebruiker verwijderen
admin-user-llm-admin-llm-use-by = Beheer: LLM-gebruik van { $username }
admin-user-llm-u-back-to-user = ← Terug naar de gebruiker
admin-user-llm-loading-u = Laden…
admin-user-llm-totals-all-time = Totalen (alle tijd)
admin-user-llm-chat-sessions = Chatsessies
admin-user-llm-messages = Berichten
admin-user-llm-tool-calls = Toolaanroepen
admin-user-llm-model-and-tool-time = Model- en tooltijd
admin-user-llm-model-and-tool-time-of = model- en tooltijd van de agentstappen van deze gebruiker. Parallelle toolaanroepen tellen volledig mee
admin-user-llm-rate-limit-usage-current-windows = Gebruik van de snelheidslimiet (huidige vensters)
admin-user-llm-in-process-counters-of-the = Tellers in het proces van de draaiende websitecontainer. Chatlimiet { $metrics_chat_per_minute }/min, API-limiet { $metrics_api_per_minute }/min, met een afnemend aanhoudend tempo over de langere vensters.
admin-user-llm-chat-messages = Chatberichten
admin-user-llm-api-calls = API-aanroepen
admin-user-llm-window = Venster
admin-user-llm-used = Gebruikt
admin-user-llm-budget = Budget
admin-user-llm-no-chat-sessions = Geen chatsessies.
admin-user-llm-title = Titel
admin-user-llm-created = Aangemaakt
admin-users-list-admin-users = Beheer: gebruikers
admin-users-list-users = Gebruikers
admin-users-list-search-users = Gebruikers zoeken
admin-users-list-username = Gebruikersnaam
admin-users-list-full-name = Volledige naam
admin-users-list-email-address = E-mailadres
admin-users-list-superuser = Superuser
admin-users-list-groups = Groepen
admin-users-list-created = Aangemaakt
admin-users-list-last-login = Laatste aanmelding
admin-users-list-loading = Laden...
dataset-create-panel-put-the-documents-in-a = Zet de documenten daar in een map en laad deze pagina opnieuw.
dataset-create-panel-the-name-cannot-start-with = De naam mag niet beginnen met een punt en geen schuine streep bevatten.
dataset-create-panel-and-a-dash-a-space = en een streepje, een spatie of een punt wordt een underscore. De naam kan later niet worden gewijzigd.
dataset-create-panel-the-form-starts-with-the = Het formulier begint met de standaardwaarden van de collectie. Een dataset die met de standaardwaarden is aangemaakt, volgt latere wijzigingen daarvan,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Toepassen slaat de talen op, waarna de OCR-update van deze dataset vanzelf start.
dataset-ocr-panel-the-list-comes-from-the = De lijst komt van de draaiende image, niet uit de configuratie.
live-chats-panel-off = uit
processing-updates-panel-the-waiting-steps-change-each = De wachtende stappen wijzigen { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), elk bestand eenmaal geteld, in { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = en een streepje, een spatie of een punt wordt een underscore. De naam kan later niet worden gewijzigd.
admin-llm-config-fresh = actueel
admin-llm-config-tools = tools{" "}
admin-llm-config-vision = vision{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-and-a-dataset-created-with = en een dataset die met andere waarden is aangemaakt, houdt zijn eigen waarden. Een wijziging op de datasetpagina voert OCR opnieuw uit.
dataset-create-panel-read-only = { $option_name } (alleen-lezen)
live-chats-panel-on = aan
processing-updates-panel-up-to-date-select-it = Actueel. Selecteer het om het opnieuw uit te voeren.
admin-ai-status-yes = ja
admin-ai-status-no-2 = nee
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } fouten
admin-collection-processing-done = klaar
admin-collection-processing-failed-2 = { $stage_failed_documents } mislukt
admin-collection-processing-left = over
admin-collection-processing-dataset-level = datasetniveau
admin-collections-list-groups = { $c_group_count } groepen
admin-failures-operation-s = { $group_operation_count } bewerking(en)
admin-groups-list-groupname = groepsnaam
admin-llm-config-stale = verouderd
admin-llm-config-thinking-is-on = Thinking staat aan
admin-llm-config-thinking-is-off = Thinking staat uit
admin-llm-config-shown = { $models_len } getoond
admin-llm-config-reasoning = reasoning
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } van { $load_table_count }
admin-metrics-yes = ja
admin-metrics-no = nee
admin-metrics-max = max
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = gestart { $run_started_at }
admin-operation-detail-yes = ja
admin-operation-detail-no = nee
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = e-mail
admin-user-llm-untitled = (zonder titel)
admin-dataset-ocr-panel-models-not-in-image = De modellen van { $languages } zitten niet in de image. De service downloadt ze bij het eerste gebruik, wat internettoegang vereist.
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } pagina's
admin-processing-updates-panel-prerequisites-waiting = De collectie heeft eerst een update nodig: { $steps }. Stappen die naar de zoekindex schrijven, wachten hierop.
admin-operations-no-task-type-failing = Geen tasktype mislukt boven { $threshold }%.
admin-operations-task-types-failing = { $count } tasktype(n) mislukken boven { $threshold }%.
processing-updates-panel-collection-updates = Collectie-updates
admin-collections-list-some-datasets-are-not-counted = Sommige datasets zijn nog niet geteld.
admin-failures-hide = Verbergen
admin-failures-show = Tonen
admin-settings-web-session-lifetime-in-seconds = Levensduur van de websessie in seconden (standaard: 604800 = 1 week)
admin-settings-turns-every-new-chat-turn = Schakelt elke nieuwe chatbeurt uit bij false (standaard: true). Een beurt die bezig is, wordt afgemaakt. Werkt vanaf het volgende verzenden, zonder nieuwe implementatie.
admin-settings-written-by-main-py-probe = Geschreven door `main.py probe-embeddings`, en het is wat het endpoint DAADWERKELIJK aanbiedt. Als je dit met de hand wijzigt, verandert de server niet.
admin-settings-the-folder-whose-subfolders-the = De map waarvan de submappen in het datasetformulier staan. Een wijziging vereist een nieuwe implementatie.
admin-settings-from-hoover4-ini-changing-it = Uit hoover4.ini. Een wijziging vereist een nieuwe implementatie.
admin-feedback-bug = Bug
admin-operations-state-name = { $state ->
        [pending] wachtend
        [queued] in de wachtrij
        [running] actief
        [finished] voltooid
        [errored] met fouten
        [cancelled] geannuleerd
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Mislukkingsboom van { $op_id }
admin-failure-detail-showing-of-characters = { $node_stack_trace_chars_count } van { $node_stack_trace_original_len } tekens getoond
admin-operations-operation = Bewerking { $state }.
admin-operations-dispatched = { $new_id } verzonden.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } rijen
admin-operations-plans = { $row_progress_done } / { $row_progress_total } plannen
admin-group-detail-group-2 = Groep { $groupname }
admin-settings-the-setting-was-saved-successfully = De instelling “{ $k }” is opgeslagen.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = De groep “{ $g }” is toegevoegd.
admin-user-detail-user-2 = Gebruiker { $username }
admin-dataset-detail-dataset = Dataset { $dataset_id }
admin-dataset-detail-collections = Collecties › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } van { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = De uploadinstelling kon niet worden gelezen: { $err }
admin-dataset-detail-operation-started = Bewerking gestart: { $run_id }
admin-collection-detail-collection = Collectie { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = De vectorinstelling kon niet worden gelezen: { $err }
admin-collection-processing-processing-of = Verwerking van { $collection_id }
admin-collection-processing-collections = Collecties › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } uitvoeringen
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = per { $at }
admin-collection-processing-over-the-last-s = over de laatste { $live_window_seconds } s
admin-collection-processing-retry-started-run = Opnieuw proberen gestart (run { $run }).
admin-collection-processing-document-retry-started-run = Opnieuw proberen van het document gestart (run { $run }).
admin-operation-detail-operation-2 = Bewerking { $op_id }
admin-user-llm-llm-usage-of = LLM-gebruik van { $username }
admin-user-llm-users = Gebruikers › { $username }
processing-updates-panel-the-processing-updates-could-not = De verwerkingsupdates konden niet worden gelezen: { $e }
processing-updates-panel-update-started = Update gestart: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } van { $operation_progress_total } plannen
dataset-ocr-panel-adding = toevoegen: { $added }
dataset-ocr-panel-removing = verwijderen: { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } plan(nen) heropend
dataset-create-panel-saved-as-this-collection-s-2 = Opgeslagen als standaardwaarden van deze collectie. Deze datasets nemen ze over en hun OCR-updates starten een voor een: { $changed_join }. Datasets met eigen talen houden die.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] map
       *[other] mappen
    }
    [tables] { $count ->
        [one] tabel
       *[other] tabellen
    }
   *[files] { $count ->
        [one] bestand
       *[other] bestanden
    }
}
processing-updates-step-runs = { $count ->
    [one] stapuitvoering
   *[other] stapuitvoeringen
}
processing-update-search_schema-title = Schema van de zoekindex
processing-update-search_schema-explanation = { $files ->
    [one] { $count } zoektabel van de collectie mist een kolom die de zoekindex nodig heeft.
   *[other] { $count } zoektabellen van de collectie missen een kolom die de zoekindex nodig heeft.
} De kolom wordt aan elke tabel toegevoegd. Zoeken blijft werken.
processing-update-search_schema-runs = Tabellen van de zoekindex
processing-update-unfinished-title = Onvoltooide verwerking
processing-update-unfinished-explanation = { $files ->
    [one] { $count } bestand is niet tot het einde verwerkt.
   *[other] { $count } bestanden zijn niet tot het einde verwerkt.
} Dit omvat bestanden zonder verwerkingsplan, bijvoorbeeld na een onderbroken inleesproces. Hun verwerking wordt voltooid.
processing-update-unfinished-runs = Alle verwerkingsfasen voor deze bestanden
processing-update-failed_files-title = Mislukte bestanden
processing-update-failed_files-explanation = { $files ->
    [one] { $count } bestand heeft een verwerkingsfout.
   *[other] { $count } bestanden hebben een verwerkingsfout.
} De mislukte fasen worden er opnieuw voor uitgevoerd. De automatische uitvoering probeert een bestand eenmaal opnieuw voor elke nieuwe versie van de fase die mislukte.
processing-update-failed_files-runs = De mislukte fasen, daarna entiteitsextractie, embedding en indexering
processing-update-virus_scan-title = Virusscan
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } bestand heeft geen antivirusoordeel.
   *[other] { $count } bestanden hebben geen antivirusoordeel.
} Ze worden gescand. Een bestand dat de scanner als geïnfecteerd aanmerkt, wordt in het zoeken gemarkeerd en de download van het origineel en van de doorzoekbare PDF wordt geweigerd.
processing-update-virus_scan-runs = Antivirusscan, daarna het zoekkenmerk van geïnfecteerde bestanden
processing-update-tables-title = Tabellen
processing-update-tables-explanation = { $files ->
    [one] { $count } bestand heeft een eerdere tabellezing of onvolledige afhankelijke uitvoer. De opgeslagen resultaten worden bijgewerkt.
    *[other] { $count } bestanden hebben eerdere tabellezingen of onvolledige afhankelijke uitvoer. Hun opgeslagen resultaten worden bijgewerkt.
    }

processing-update-tables-runs = Tabellen lezen, entiteiten, signalen, inbeddingen en beide indexen
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Bestanden die automatische OCR nodig hebben: { $count }. Gedetecteerde pagina’s bepalen de geïnstalleerde modellen. Volledige vervangende uitvoer verwijdert oude varianten.
processing-update-ocr-runs = OCR en doorzoekbare PDF's, daarna entiteitsextractie, embedding en indexering van de nieuwe tekst
processing-update-ocr_detection-title = OCR-detectie
processing-update-ocr_detection-explanation = Bestanden zonder huidige tekst-, schrift- of taaldetectie: { $count }. Elke geschikte afbeelding en PDF-pagina wordt in begrensde batches onderzocht.
processing-update-ocr_detection-runs = Detectie, daarna de zoekkenmerken van deze bestanden
processing-update-pdf_text-title = Tekst van doorzoekbare pdf's
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } bestand heeft doorzoekbare pdf's met een eerdere tekstlaag.
   *[other] { $count } bestanden hebben doorzoekbare pdf's met een eerdere tekstlaag.
} Die laag kopieerde elke letter buiten de West-Europese alfabetten als een zwart vierkant. Pdf's van talen met alleen West-Europese letters blijven ongewijzigd. De andere pdf's worden gelezen, en de delen met zwarte vierkanten worden opnieuw gemaakt. Een afbeeldings-pdf gebruikt de opgeslagen OCR-woorden. Een pdf-pagina krijgt een nieuw OCR-verzoek.
processing-update-pdf_text-runs = Delen van doorzoekbare pdf's, daarna de indexering van de OCR-tekst van de opnieuw gemaakte pdf's
processing-update-vectors-title = Vectoren
processing-update-vectors-explanation = { $files ->
    [one] { $count } bestand met tekst heeft geen vectoren van het embeddingmodel dat de installatie aanbiedt.
   *[other] { $count } bestanden met tekst hebben geen vectoren van het embeddingmodel dat de installatie aanbiedt.
} Hun vectoren worden berekend en geïndexeerd.
processing-update-vectors-runs = Embedding en vectorindexering
processing-update-folder_counts-title = Maptellingen
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } map heeft geen aantal bestanden of grootte, of heeft waarden van een eerdere versie.
   *[other] { $count } mappen hebben geen aantal bestanden of grootte, of hebben waarden van een eerdere versie.
} De aantallen worden opnieuw berekend.
processing-update-folder_counts-runs = Mappenboom
admin-uploads-badge = Uploads
admin-uploads-badge-title = Accepteert uploads

processing-update-archive_members-title = Archiefonderdelen

processing-update-archive_members-explanation = { $files ->
    [one] { $count } gesplitst archief vereist een actuele onderdelenlijst. De onderdelen en zoekresultaten worden bijgewerkt.
    *[other] { $count } gesplitste archieven vereisen actuele onderdelenlijsten. Hun onderdelen en zoekresultaten worden bijgewerkt.
    }

processing-update-archive_members-runs = Archieven uitpakken, onderdelen afstemmen en afhankelijke verwerking

processing-update-image_previews-title = Afbeeldingsvoorbeelden

processing-update-image_previews-explanation = { $files ->
    [one] { $count } ongebruikelijke afbeelding heeft geen voorbeeld. Het voorbeeld wordt opnieuw gemaakt.
    *[other] { $count } ongebruikelijke afbeeldingen hebben geen voorbeeld. Hun voorbeelden worden opnieuw gemaakt.
    }

processing-update-image_previews-runs = Afbeeldingsvoorbeelden maken en verifiëren

processing-update-search_terms-title = Zoektermen

processing-update-search_terms-explanation = { $files ->
    [one] { $count } zoektabel heeft actuele filtertermen nodig. Termen voor taal, OCR, schrift en rode vlaggen worden doorzoekbaar.
    *[other] Zoektabellen die actuele filtertermen nodig hebben: { $count }. Termen voor taal, OCR, schrift en rode vlaggen worden doorzoekbaar.
    }

processing-update-search_terms-runs = Filtertermen indexeren en verifiëren

automatic-ocr-title = Automatische OCR
automatic-ocr-refresh = Status vernieuwen
automatic-ocr-coverage = Paginadekking
automatic-ocr-pages = Pagina’s
automatic-ocr-models = OCR-modellen
automatic-ocr-reason = Reden
automatic-ocr-truncated = De diagnoselijst is onvolledig.
automatic-ocr-presence = Heeft gepubliceerde OCR-tekst
automatic-ocr-policy = OCR kiest geïnstalleerde modellen op basis van het gedetecteerde schrift en de taal van elke geschikte pagina. Tesseract komt eerst, EasyOCR dekt overige ondersteunde schriften.
automatic-ocr-unknown = Er is geen huidige publicatie vastgelegd. Ontbrekende detectie en mislukte verwerking bewijzen geen afwezigheid.
automatic-ocr-retry = Gebruik verwerkingsupdates om onvolledig of mislukt werk opnieuw uit te voeren nadat de oorzaak is verholpen. Niet-ondersteunde dekking vereist geschikte geïnstalleerde modellen.
automatic-ocr-state = { $state ->
    [candidate] In afwachting
    [planned] Gepland
    [failed] Mislukt
    [incomplete] Onvolledig
    [unsupported] Niet ondersteund
    [published] Gepubliceerd
    [applied] Geverifieerd
    [ready] Tekst gedetecteerd
    [no_text] Geen tekst gedetecteerd
    *[other] { $state }
    }

processing-update-entities-title = Benoemde entiteiten
processing-update-entities-explanation = Bestanden die huidige entiteitsextractie of doorzoekbare uitvoer nodig hebben: { $count }. Eerdere geslaagde resultaten worden na de inferentie vervangen.
processing-update-entities-runs = Extractie van benoemde entiteiten, tekstattributen en doorzoekbare entiteitstermen

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Schrift niet geïdentificeerd
    [tesseract_capabilities_unavailable] Tesseract-dekking niet beschikbaar
    [detected_language] Model past bij gedetecteerde taal
    [unknown_language_script_coverage] Onbekende taal. Een schriftmodel is geselecteerd.
    [language_script_mismatch_script_coverage] Taal en schrift verschillen. Een schriftmodel is geselecteerd.
    [language_model_unavailable_script_coverage] Taalmodel niet beschikbaar. Een schriftmodel is geselecteerd.
    [easyocr_capabilities_unavailable] EasyOCR-dekking niet beschikbaar
    [tesseract_script_unavailable] Tesseract dekt het schrift niet. EasyOCR is geselecteerd.
    [script_coverage_unavailable] Geen geïnstalleerd model dekt dit schrift.
    *[other] { $reason }
    }

processing-updates-check-requested = De pijplijn berekent de updates. De aantallen veranderen wanneer de berekening klaar is.
