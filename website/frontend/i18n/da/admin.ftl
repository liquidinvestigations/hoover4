# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Adgang til administration kræves
admin-guard-signed-in-as = Logget ind som { $u_username }.
admin-guard-ask-an-administrator-for-access = Bed en administrator om adgang til dette afsnit.
admin-shell-dashboard = Dashboard
admin-shell-collections = Samlinger
admin-shell-operations = Operationer
admin-shell-errors-failures = Fejl/Svigt
admin-shell-feedback = Feedback
admin-shell-users = Brugere
admin-shell-groups = Grupper
admin-shell-settings = Indstillinger
admin-shell-llm = LLM
admin-shell-ai-status = AI-status
admin-shell-metrics = Målinger
admin-shell-administration = Administration
dataset-create-panel-add-a-dataset = Tilføj et datasæt
dataset-create-panel-the-dataset-mounts-could-not = Datasætmountene kunne ikke læses, så der er intet at vælge imellem: { $err }
dataset-create-panel-loading-the-dataset-mounts = Indlæser datasætmountene.
dataset-create-panel-no-dataset-mount-is-configured = Intet datasætmount er konfigureret.
dataset-create-panel-the-mount-folder-could-not = Mountens mappe kunne ikke læses, så der er intet at vælge imellem: { $err }
dataset-create-panel-no-subfolders-were-found-in = Der blev ikke fundet undermapper i dette mount.{" "}
dataset-create-panel-folder = Mappe
dataset-create-panel-select-a-folder = Vælg en mappe
dataset-create-panel-new-folder = Ny mappe
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } poster), allerede et datasæt
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } poster)
dataset-create-panel-the-server-creates-this-folder = Serveren opretter denne mappe i mountet, når du opretter datasættet.{" "}
dataset-create-panel-the-list-shows-the-direct = Listen viser mountets direkte undermapper.
dataset-create-panel-dataset-name = Datasættets navn
dataset-create-panel-a-name-has-lowercase-letters = Et navn har små bogstaver, cifre og understregninger. Store bogstaver bliver til små,{" "}
dataset-create-panel-the-dataset-is-saved-as = Datasættet gemmes som: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Denne samling har et datasæt med navnet { $saved_name }.
dataset-create-panel-accept-uploads = Accepter uploads
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Gemt som denne samlings standarder. Intet datasæt ændrer sine sprog.
dataset-create-panel-saving-u = Gemmer…
dataset-create-panel-save-as-collection-defaults = Gem som samlingens standarder
dataset-create-panel-creating-u = Opretter…
dataset-create-panel-create-and-ingest = Opret og indlæs
dataset-create-panel-mount = Mount
dataset-ocr-panel-last-operation = Seneste operation: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , startet { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Ingen fremgang i { $current_stale_seconds_60 } minutter. Kontrollér Temporal-workflowet, og annullér operationen, hvis den sidder fast.
dataset-ocr-panel-filter-languages = Filtrér sprog
dataset-ocr-panel-ocr-languages = OCR-sprog
dataset-ocr-panel-failed-to-load-the-ocr = OCR-indstillingerne for dette datasæt kunne ikke indlæses
dataset-ocr-panel-loading-u = Indlæser…
dataset-ocr-panel-each-easyocr-script-group-adds = Hver EasyOCR-skriftgruppe tilføjer ét OCR-gennemløb over datasættet. Tesseract læser alle sine sprog i ét gennemløb.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = Gældende: { $panel_tesseract_languages }, fra { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = Brug { $source_label_panel_inherited_tesseract_s }: { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = Tesseract-tjenesten svarede ikke, så de installerede sprog er ukendte.{" "}
dataset-ocr-panel-the-image-also-has-script = Imaget har også { $script_models } skriftmodeller, for eksempel latin. Formularen tilbyder dem ikke, fordi indstillingen bliver en del af en lagernøgle og kun accepterer koder med små bogstaver.
dataset-ocr-panel-the-first-language-is-the = Det første sprog er det primære. Valgt:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = EasyOCR er slået fra på denne installation, så denne indstilling har ingen virkning, før det er slået til.
dataset-ocr-panel-in-force-off-from = Gældende: fra, fra { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = Gældende: { $panel_easyocr_languages }, fra { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = Brug { $source_label_panel_inherited_easyocr_sou }: fra
dataset-ocr-panel-use-2 = Brug { $source_label_panel_inherited_easyocr_sou }: { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Aktiveret
dataset-ocr-panel-the-easyocr-service-did-not = EasyOCR-tjenesten rapporterede ikke, hvilke sprog den understøtter.
dataset-ocr-panel-a-model-download-failed = Download af en model mislykkedes: { $failure }
dataset-ocr-panel-stored-text-variants = Gemte tekstvarianter
dataset-ocr-panel-removing-a-language-deletes-its = Når du fjerner et sprog, slettes dets tekst, dets søgerækker og dets søgbare PDF.
dataset-ocr-panel-searchable-pdfs = Søgbare PDF'er
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } filer · { $variant_total_bytes_1024_1024 } MB
dataset-ocr-panel-searchable-pdfs-are-off-on = Søgbare PDF'er er slået fra på denne installation.
dataset-ocr-panel-saving-u = Gemmer…
dataset-ocr-panel-apply = Anvend
dataset-ocr-panel-no-changes-to-apply = Ingen ændringer at anvende.
live-chats-panel-live-llm-chats = Aktive LLM-chats
live-chats-panel-agent-turns-running-right-now = Agentrunder, der kører lige nu, de længst kørende først. Opdateres hvert 2. sekund. Læst fra Temporal, så en runde, der startede før websitets seneste genstart, er også med.
live-chats-panel-loading-u = Indlæser…
live-chats-panel-no-chats-running = Ingen chats kører.
live-chats-panel-user = Bruger
live-chats-panel-conversation = Samtale
live-chats-panel-question = Spørgsmål
live-chats-panel-internet = Internet
live-chats-panel-running = Kører
live-chats-panel-started = Startet
live-chats-panel-cancels-the-workflow-the-turn = Annullerer workflowet. Runden ender med en stopmarkering i udskriften og forsvinder ikke bare.
live-chats-panel-kill = Afbryd
processing-updates-panel-loading-u = Indlæser…
processing-updates-panel-open-the-operation = Åbn operationen
processing-updates-panel-the-pipeline-has-not-calculated = Pipelinen har endnu ikke beregnet disse opdateringer.
processing-updates-panel-calculated-at-in-ms = Beregnet { $view_checked_at } på { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatiske opdateringer er slået fra på denne installation. Start opdateringerne med knappen.
processing-updates-panel-step = Trin
processing-updates-panel-count = Antal
processing-updates-panel-state = Tilstand
processing-updates-panel-last-run = Seneste kørsel
processing-updates-panel-runs = Kørsler: { $step_runs }
processing-updates-panel-a-run-again-would-select = En ny kørsel ville vælge omtrent dette antal { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } ved en ny kørsel
processing-updates-panel-never = Aldrig
processing-updates-panel-update-collection = Opdatér samling
processing-updates-panel-update-processing = Opdatér behandling
processing-updates-panel-check-again = Kontrollér igen
processing-updates-panel-dataset = Datasæt
processing-updates-panel-processing-updates = Behandlingsopdateringer
admin-ai-status-admin-ai-status = Admin: AI-status
admin-ai-status-ai-status = AI-status
admin-ai-status-the-configured-service-and-the = Den konfigurerede tjeneste og den tjeneste, der faktisk svarer. En overgang til CPU-tjenesten vises kun her.
admin-ai-status-loading-u = Indlæser…
admin-ai-status-config-fingerprint = Konfigurationsfingeraftryk
admin-ai-status-website-worker = Website / worker
admin-ai-status-ai-server = AI-server
admin-ai-status-match = Stemmer overens
admin-ai-status-embeddings-probe = Embeddings-prøve
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dimensioner
admin-ai-status-llm-configured = LLM konfigureret
admin-ai-status-capabilities = Funktioner
admin-ai-status-capability = Funktion
admin-ai-status-configured = Konfigureret
admin-ai-status-serving = Leverer
admin-ai-status-model = Model
admin-ai-status-reachable = Kan nås
admin-ai-status-detail = Detalje
admin-ai-status-no = NEJ
admin-ai-status-vector-shard-dims-vs-probe = Vektorshardens dimensioner mod prøven
admin-ai-status-no-collections-yet = Ingen samlinger endnu.
admin-ai-status-collection = Samling
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Stemmer overens med prøven
admin-ai-status-browser-router = Browserrouter
admin-ai-status-live-sessions = Aktive sessioner: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Seneste LLM-trafik (24 t)
admin-ai-status-no-llm-call-events-yet = Ingen llm_call_events endnu.
admin-ai-status-user = Bruger
admin-ai-status-calls = Kald
admin-ai-status-errors = Fejl
admin-ai-status-service-use-24-h = Tjenestebrug % (24 t)
admin-ai-status-busy-seconds-in-the-last = Optagne sekunder i de seneste 24 timer, som andel af døgnet.
admin-ai-status-no-samples-yet = Ingen prøver endnu.
admin-ai-status-service = Tjeneste
admin-ai-status-busy-s = Optaget s
admin-ai-status-use = Brug %
admin-collection-detail-admin-collection = Admin: samling { $collection_id }
admin-collection-detail-failed-to-load-collection = Samlingen kunne ikke indlæses
admin-collection-detail-loading = Indlæser...
admin-collection-detail-datasets = Datasæt
admin-collection-detail-dataset = Datasæt
admin-collection-detail-documents = Dokumenter
admin-collection-detail-size = Størrelse
admin-collection-detail-indexed = Indekseret
admin-collection-detail-errors = Fejl
admin-collection-detail-state = Tilstand
admin-collection-detail-created = Oprettet
admin-collection-detail-settings = Indstillinger
admin-collection-detail-the-collection-database-is-not = Samlingens database er endnu ikke klar.
admin-collection-detail-the-last-storage-provisioning-failed = Den seneste klargøring af lager mislykkedes: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Behandlingens fremgang og skøn
admin-collection-detail-display-name = Visningsnavn
admin-collection-detail-display-name-2 = visningsnavn
admin-collection-detail-save = Gem
admin-collection-detail-access = Adgang
admin-collection-detail-public-every-signed-in-user = Offentlig. Alle loggede brugere kan søge i og læse denne samling.
admin-collection-detail-restricted-only-members-of-the = Begrænset. Kun medlemmer af grupperne nedenfor kan søge i og læse denne samling.
admin-collection-detail-the-collection-is-now-public = Samlingen er nu offentlig.
admin-collection-detail-the-collection-is-now-restricted = Samlingen er nu begrænset.
admin-collection-detail-make-restricted = Gør begrænset
admin-collection-detail-make-public = Gør offentlig
admin-collection-detail-group-permissions = Gruppetilladelser
admin-collection-detail-no-group-can-read-this = Ingen gruppe kan endnu læse denne samling.
admin-collection-detail-revoke = Tilbagekald
admin-collection-detail-grant-group-u = Tildel gruppe…
admin-collection-detail-grant = Tildel
admin-collection-detail-danger-zone = Farezone
admin-collection-detail-a-collection-can-only-be = En samling kan kun slettes, mens den ikke har datasæt.
admin-collection-detail-deleting-the-collection-also-drops = Når du sletter samlingen, slettes også dens database{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}og alt i den. Dette kan ikke fortrydes. Skriv samlingens navn for at bekræfte.
admin-collection-detail-collection-name = Samlingens navn
admin-collection-detail-delete-collection = Slet samling
admin-collection-detail-features = Funktioner
admin-collection-detail-vectors = Vektorer
admin-collection-detail-this-installation-runs-no-embedding = Denne installation kører ingen embedding-tjeneste, så ingen samling bruger vektorer.
admin-collection-detail-vectors-find-passages-by-meaning = Vektorer finder passager efter betydning. Fra stopper nye vektorer og forhindrer, at søgningen bruger de gemte, som bliver liggende. Til beregner de manglende vektorer for hvert datasæt, ét datasæt ad gangen.
admin-collection-detail-this-collection-follows-the-installation = Denne samling følger installationen, som bruger vektorer. Vektorer finder passager efter betydning. Fra stopper nye vektorer og forhindrer, at søgningen bruger de gemte, som bliver liggende.
admin-collection-processing-could-not-load-this-panel = Dette panel kunne ikke indlæses: { $message }
admin-collection-processing-admin-processing-of = Admin: behandling af { $collection_id }
admin-collection-processing-u-back-to-collection = ← Tilbage til samlingen
admin-collection-processing-processing-stages = Behandlingsfaser
admin-collection-processing-loading-u = Indlæser…
admin-collection-processing-the-collection-database-is-still = Samlingens database bliver stadig klargjort.
admin-collection-processing-this-collection-has-no-datasets = Denne samling har endnu ingen datasæt.
admin-collection-processing-eta = Forventet færdig om { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Ingen skønsprøver endnu. De indsamles, mens datasættet behandles.
admin-collection-processing-estimated-completion = Forventet afslutning:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(om { $humanize_seconds_c_eta_seconds }, et skøn efter bedste evne og ikke et løfte om planlægning)
admin-collection-processing-no-current-estimate-the-pipeline = Intet aktuelt skøn. Pipelinen er færdig eller gør ikke målbar fremgang.
admin-collection-processing-where-processing-time-goes = Hvor behandlingstiden går hen
admin-collection-processing-no-task-executions-recorded-yet = Ingen opgavekørsler registreret endnu. Hver aktivitet, pipelinen kører, skriver én række her, så en tom tabel betyder, at intet er blevet behandlet, siden instrumenteringen blev udrullet.
admin-collection-processing-summed-task-time = Samlet opgavetid
admin-collection-processing-wall-clock = Vægtid
admin-collection-processing-achieved-parallelism = Opnået parallelitet
admin-collection-processing-summed-task-time-divided-by = Samlet opgavetid divideret med vægtid er det, pipelinen faktisk opnåede parallelt. Tæt på 1 betyder, at den øverste opgave nedenfor er hele omkostningen og er værd at optimere. Tæt på antallet af workerpladser betyder, at pladserne er mættede, og at flere workere er den billigste løsning. Vægtiden går fra den første kørsel til den sidste, inklusive tomgangstid.
admin-collection-processing-task = Opgave
admin-collection-processing-total = I alt
admin-collection-processing-share = Andel
admin-collection-processing-executions = Kørsler
admin-collection-processing-mean = Gennemsnit
admin-collection-processing-max = Maks.
admin-collection-processing-failed = Mislykkedes
admin-collection-processing-live-activity = Aktuel aktivitet
admin-collection-processing-nothing-running-no-activity-finished = Intet kører. Ingen aktivitet blev færdig de seneste { $live_window_seconds } s, og ingen worker rapporterer noget under udførelse.
admin-collection-processing-in-flight = Under udførelse
admin-collection-processing-average-concurrency = Gennemsnitlig samtidighed
admin-collection-processing-task-time-in-window = Opgavetid i vinduet
admin-collection-processing-share-of-processing-time-over = Andel af behandlingstiden i de seneste { $live_window_seconds } s, opdateret hvert 5. sekund. En kørsel, der krydser vinduets kant, tæller kun for den del, der ligger inden for det. En række med kørsler under udførelse, men uden andel, er startet før vinduet og er ikke færdig. Kontrollér dens alder.
admin-collection-processing-share-of-window = Andel af vinduet
admin-collection-processing-task-time = Opgavetid
admin-collection-processing-completed = Gennemført
admin-collection-processing-oldest-running = Ældste kørende
admin-collection-processing-temporal-workflows = Temporal-workflows
admin-collection-processing-workflows-of-this-collection-s = Workflows for denne samlings datasæt, inklusive underworkflows.
admin-collection-processing-no-workflows-match-this-filter = Ingen workflows matcher dette filter.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Type
admin-collection-processing-status = Status
admin-collection-processing-started = Startet
admin-collection-processing-closed = Lukket
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = åbn ↗
admin-collection-processing-failed-tasks = Mislykkede opgaver
admin-collection-processing-no-task-failures-recorded = Ingen opgavesvigt registreret.
admin-collection-processing-dataset = Datasæt
admin-collection-processing-errors = Fejl
admin-collection-processing-documents = Dokumenter
admin-collection-processing-last-seen = Sidst set
admin-collection-processing-sample = Eksempel
admin-collection-processing-retry = Prøv igen
admin-collection-processing-failures-per-document = Svigt pr. dokument
admin-collection-processing-no-document-failures-recorded = Ingen dokumentsvigt registreret.
admin-collection-processing-document = Dokument
admin-collections-list-admin-collections = Admin: samlinger
admin-collections-list-collections = Samlinger
admin-collections-list-loading-collections-u = Indlæser samlinger…
admin-collections-list-datasets = Datasæt
admin-collections-list-loading-datasets-u = Indlæser datasæt…
admin-collections-list-add-a-collection = Tilføj en samling
admin-collections-list-name-for-example-enron = Navn, for eksempel enron
admin-collections-list-display-name = Visningsnavn
admin-collections-list-add-collection = Tilføj samling
admin-collections-list-a-name-has-lowercase-letters = Et navn har små bogstaver, cifre og understregninger. Store bogstaver bliver til små,{" "}
admin-collections-list-the-collection-is-saved-as = Samlingen gemmes som: { $new_name }
admin-collections-list-a-collection-with-the-name = Der findes allerede en samling med navnet { $new_name }.
admin-collections-list-collection = Samling
admin-collections-list-documents = Dokumenter
admin-collections-list-size = Størrelse
admin-collections-list-errors = Fejl
admin-collections-list-state = Tilstand
admin-collections-list-access = Adgang
admin-collections-list-database-not-ready = Databasen er ikke klar
admin-collections-list-public = Offentlig
admin-collections-list-1-group = 1 gruppe
admin-collections-list-not-counted-yet = Endnu ikke talt
admin-collections-list-unknown = Ukendt
admin-collections-list-no-collection-has-a-dataset = Ingen samling har et datasæt.
admin-collections-list-dataset = Datasæt
admin-collections-list-indexed = Indekseret
admin-collections-list-created = Oprettet
admin-dashboard-admin-dashboard = Admin: dashboard
admin-dashboard-administration = Administration
admin-dashboard-users = Brugere
admin-dashboard-groups = Grupper
admin-dashboard-collections = Samlinger
admin-dashboard-datasets = Datasæt
admin-dashboard-failed-to-load-counts = Tallene kunne ikke indlæses: { $e }
admin-dataset-detail-admin-dataset = Admin: datasæt { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Datasættet kunne ikke indlæses
admin-dataset-detail-loading = Indlæser...
admin-dataset-detail-metadata = Metadata
admin-dataset-detail-display-name = Visningsnavn
admin-dataset-detail-name = Navn
admin-dataset-detail-type = Type
admin-dataset-detail-path = Sti
admin-dataset-detail-created = Oprettet
admin-dataset-detail-collection = Samling
admin-dataset-detail-save = Gem
admin-dataset-detail-statistics = Statistik
admin-dataset-detail-state = Tilstand
admin-dataset-detail-documents = Dokumenter
admin-dataset-detail-size = Størrelse
admin-dataset-detail-indexed = Indekseret
admin-dataset-detail-errors = Fejl
admin-dataset-detail-plans-finished = Færdige planer
admin-dataset-detail-disk = Disk
admin-dataset-detail-rescan-disk-reads-the-dataset = Scan disk igen læser datasættets mappe på ny, tilføjer nye og ændrede filer og behandler dem.
admin-dataset-detail-rescan-disk = Scan disk igen
admin-dataset-detail-danger-zone = Farezone
admin-dataset-detail-this-deletes-the-dataset-and = Dette sletter datasættet og alle data, der er udtrukket fra det. Det kan ikke fortrydes.
admin-dataset-detail-delete-dataset-and-its-data = Slet datasættet og dets data
admin-dataset-detail-accept-uploads = Accepter uploads
admin-dataset-detail-the-folder-of-this-dataset = Dette datasæts mappe ligger ikke i et skrivbart datasætmount, så det modtager ingen uploads.
admin-dataset-detail-starting-u = Starter…
admin-failure-detail-admin-failure = Admin: svigt { $op_id }
admin-failure-detail-loading-tree = Indlæser træ…
admin-failure-detail-back-to-errors-and-failures = Tilbage til fejl og svigt
admin-failure-detail-operations = Operationer
admin-failure-detail-scrubbed-copy-written-to-the = Renset kopi skrevet til udklipsholderen.
admin-failure-detail-this-tree-is-truncated-at = Dette træ er afkortet. Mindst én registrering har tabt noder.
admin-failure-detail-the-captured-tree-has-expired = Det registrerede træ er udløbet. Operationsrækken findes stadig.
admin-failure-detail-no-captured-nodes-for-this = Ingen registrerede noder for denne operation.
admin-failure-detail-operation = Operation
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } rod(rødder) · { $tree_nodes_len } node(r)
admin-failure-detail-open-in-temporal = Åbn i Temporal
admin-failure-detail-scrubbed-copy = Renset kopi
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Den rensede kopi erstatter datasætstier med hashværdier og lange værdier med deres længder.
admin-failure-detail-copy-scrubbed-record = Kopiér renset post
admin-failure-detail-tree = Træ
admin-failure-detail-root = Rod ·{" "}
admin-failure-detail-node-parent-depth-source-stage = node { $node_node_index } · forælder { $node_parent_index } · dybde { $node_depth } · kilde { $node_source } · fase { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = workflow { $node_workflow_id } · kørsel { $node_run_id } · aktivitet { $node_activity_id } · forsøg { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } node(r) tabt ved denne registrering
admin-failures-admin-errors-and-failures = Admin: fejl og svigt
admin-failures-errors-failures = Fejl/Svigt
admin-failures-loading-failures = Indlæser svigt…
admin-failures-operational-failures = Driftssvigt
admin-failures-no-operational-failures-at-this = Ingen driftssvigt i øjeblikket.
admin-failures-collection = Samling
admin-failures-dataset = Datasæt
admin-failures-task-name = Opgavenavn
admin-failures-error-class = Fejlklasse
admin-failures-operation-kind = Operationstype
admin-failures-from = Fra
admin-failures-to = Til
admin-failures-no-captured-failures-match-these = Ingen registrerede svigt matcher disse filtre.
admin-failures-signature = Signatur
admin-failures-count = Antal
admin-failures-class = Klasse
admin-failures-task = Opgave
admin-failures-last-seen = Sidst set
admin-failures-newer = Nyere
admin-failures-page = Side { $current_page_1 }
admin-failures-older = Ældre
admin-failures-per-page = Pr. side
admin-failures-loading-instances = Indlæser forekomster…
admin-failures-no-instances-for-this-signature = Ingen forekomster for denne signatur.
admin-failures-node = {" "}node { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Dokumentfejl
admin-failures-error-text = Fejltekst
admin-failures-loading-document-errors-u = Indlæser dokumentfejl…
admin-failures-no-document-errors-match-these = Ingen dokumentfejl matcher disse filtre.
admin-failures-errors-by-dataset-and-task = Fejl pr. datasæt og opgave
admin-failures-documents = Dokumenter
admin-failures-show-only-this-dataset-and = Vis kun dette datasæt og denne opgave
admin-failures-total = I alt
admin-failures-errors = Fejl
admin-failures-document = Dokument
admin-failures-runs = Kørsler
admin-failures-error = Fejl
admin-failures-dataset-step = Datasættrin
admin-failures-previous-page = Forrige side
admin-failures-page-of-1-error = Side { $page } af { $pages }, 1 fejl
admin-failures-page-of-errors = Side { $page } af { $pages }, { $data_total } fejl
admin-failures-next-page = Næste side
admin-feedback-admin-feedback = Admin: feedback
admin-feedback-feedback = Feedback
admin-feedback-search-titles-descriptions-accounts-and = Søg i titler, beskrivelser, konti og adresser
admin-feedback-search = Søg
admin-feedback-loading-reports-u = Indlæser rapporter…
admin-feedback-1-report-matches = 1 rapport matcher.
admin-feedback-reports-match = { $data_total } rapporter matcher.
admin-feedback-received = Modtaget
admin-feedback-type = Type
admin-feedback-title = Titel
admin-feedback-from = Fra
admin-feedback-captures = Registreringer
admin-feedback-state = Tilstand
admin-feedback-previous-page = Forrige side
admin-feedback-page-of = Side { $page } af { $pages }
admin-feedback-next-page = Næste side
admin-feedback-image = Billede { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Læst
admin-feedback-unread = Ulæst
admin-feedback-archived = Arkiveret
admin-feedback-mark-unread = Markér som ulæst
admin-feedback-mark-read = Markér som læst
admin-feedback-restore = Gendan
admin-feedback-archive = Arkivér
admin-feedback-page = Side:{" "}
admin-feedback-the-report-has-no-description = Rapporten har ingen beskrivelse.
admin-feedback-open-the-page-image = Åbn sidebilledet
admin-feedback-open-the-dom-copy = Åbn DOM-kopien
admin-feedback-page-image-of-the-report = Rapportens sidebillede
admin-feedback-debug-context-and-browser-log = Fejlsøgningskontekst og browserlog
admin-feedback-loading-u = Indlæser…
admin-group-detail-admin-group = Admin: gruppe { $groupname }
admin-group-detail-failed-to-load-group = Gruppen kunne ikke indlæses
admin-group-detail-loading = Indlæser...
admin-group-detail-group = Gruppe
admin-group-detail-display-name = Visningsnavn
admin-group-detail-display-name-2 = visningsnavn
admin-group-detail-save = Gem
admin-group-detail-members = Medlemmer
admin-group-detail-saving-membership = Gemmer medlemskab...
admin-group-detail-username = Brugernavn
admin-group-detail-origin = Oprindelse
admin-group-detail-group-admin = Gruppeadministrator
admin-group-detail-uploader = Uploader
admin-group-detail-remove = Fjern
admin-group-detail-username-to-add = brugernavn, der skal tilføjes
admin-group-detail-add-member = Tilføj medlem
admin-group-detail-collection-access = Adgang til samlinger
admin-group-detail-this-group-has-no-collection = Denne gruppe har ingen tilladelser til samlinger.
admin-group-detail-revoke = Tilbagekald
admin-group-detail-grant-collection-u = Tildel samling…
admin-group-detail-grant = Tildel
admin-group-detail-danger-zone = Farezone
admin-group-detail-delete-group = Slet gruppe
admin-groups-list-admin-groups = Admin: grupper
admin-groups-list-groups = Grupper
admin-groups-list-add-group = Tilføj gruppe
admin-groups-list-display-name = visningsnavn
admin-groups-list-use-lowercase-letters-digits-underscores = Brug små bogstaver, cifre, understregninger og bindestreger i navnet. Navnet kan ikke ændres senere.
admin-groups-list-add-group-2 = Tilføj gruppe +
admin-groups-list-group = Gruppe
admin-groups-list-display-name-2 = Visningsnavn
admin-groups-list-members = Medlemmer
admin-groups-list-collections = Samlinger
admin-groups-list-loading = Indlæser...
admin-llm-config-admin-llm = Admin: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Indlæser…
admin-llm-config-no-llm-provider-is-configured = Ingen LLM-udbyder er konfigureret. Angiv LLM_BASE_URL / LLM_MODEL i hoover4.ini, og udrul igen.
admin-llm-config-providers = Udbydere
admin-llm-config-the-refresh-runs-in-the = Opdateringen kører i baggrunden. Den nuværende liste forbliver synlig imens.
admin-llm-config-refresh-in-flight-u = {" "}Opdatering i gang…
admin-llm-config-provider = Udbyder
admin-llm-config-models = Modeller
admin-llm-config-freshest = Nyeste
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Opdatér katalog
admin-llm-config-agent-turns-board-assessments-and = Agentrunder, tavlevurderinger og rapportkonverteringer
admin-llm-config-titles-summaries-and-board-labels = Titler, resuméer og tavlemærkater
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini angiver disse modeller: LLM-udbyderens quality_model til agentrunder, tavlevurderinger og rapportkonverteringer, når den er angivet, og dens model til resten.
admin-llm-config-thinking = Thinking
admin-llm-config-the-model-reasons-before-each = Modellen ræsonnerer før hvert værktøjskald og hvert svar.
admin-llm-config-catalog = Katalog
admin-llm-config-filter-models-u = Filtrér modeller…
admin-llm-config-model = Model
admin-llm-config-flags = Markeringer
admin-llm-config-calls-14d = Kald 14 d
admin-llm-config-ai-status = AI-status
admin-llm-config-shows-the-serving-health = {" "}viser tjenestens helbred.
admin-llm-reports-reports = Rapporter
admin-llm-reports-each-report-runs-when-you = Hver rapport kører, når du vælger dens knap.
admin-llm-reports-running-u = Kører…
admin-llm-reports-run-report = Kør rapport
admin-llm-reports-read-at = Læst { $read_at }
admin-llm-reports-errors = Fejl
admin-llm-reports-failed-attempts-by-step-and = Mislykkede forsøg efter trin og fejlklasse samt agentkørsler, der mislykkedes eller sluttede tidligt, efter slutårsag.
admin-llm-reports-source = Kilde
admin-llm-reports-class = Klasse
admin-llm-reports-no-errors-in-30-days = Ingen fejl i 30 dage.
admin-llm-reports-recent-errors = Seneste fejl
admin-llm-reports-the-newest-100-failed-attempts = De 100 nyeste mislykkede forsøg fra 7 dage. Åbn en række for at læse dens fejl.
admin-llm-reports-time = Tid
admin-llm-reports-user = Bruger
admin-llm-reports-name = Navn
admin-llm-reports-error = Fejl
admin-llm-reports-no-errors-in-7-days = Ingen fejl i 7 dage.
admin-llm-reports-show = Vis
admin-llm-reports-tool-calls = Værktøjskald
admin-llm-reports-one-row-for-each-tool = Én række pr. værktøj, efter kald i 30 dage. En fejl er et mislykket kald.
admin-llm-reports-tool = Værktøj
admin-llm-reports-calls-24-h = Kald 24 t
admin-llm-reports-error-24-h = Fejl % 24 t
admin-llm-reports-avg-ms-24-h = Gns. ms 24 t
admin-llm-reports-calls-7-d = Kald 7 d
admin-llm-reports-error-7-d = Fejl % 7 d
admin-llm-reports-avg-ms-7-d = Gns. ms 7 d
admin-llm-reports-calls-30-d = Kald 30 d
admin-llm-reports-error-30-d = Fejl % 30 d
admin-llm-reports-avg-ms-30-d = Gns. ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Ingen værktøjskald i 30 dage.
admin-llm-reports-top-users = Mest aktive brugere
admin-llm-reports-the-30-users-with-the = De 30 brugere med mest modeltid i perioden.
admin-llm-reports-30-days = 30 dage
admin-llm-reports-7-days = 7 dage
admin-llm-reports-24-hours = 24 timer
admin-llm-reports-tool-time = Værktøjstid
admin-llm-reports-model-calls = Modelkald
admin-llm-reports-model-time = Modeltid
admin-llm-reports-tokens-in = Tokens ind
admin-llm-reports-tokens-out = Tokens ud
admin-llm-reports-no-agent-use-in-the = Ingen agentbrug i perioden.
admin-llm-reports-system-one-checks = System one-kontroller
admin-llm-reports-requests-are-grouped-by-hook = Forespørgsler grupperes efter hook og regel. Latenser er i millisekunder. Andele bruger forespørgsler fra de seneste 30 dage.
admin-llm-reports-counts = Antal
admin-llm-reports-recent-failures = Seneste svigt
admin-llm-reports-select-run-report-to-read = Vælg Kør rapport for at læse statistikken.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Regel
admin-llm-reports-outcome = Udfald
admin-llm-reports-questions = Spørgsmål
admin-llm-reports-median-ms = Median ms
admin-llm-reports-95th-percentile-ms = 95. percentil ms
admin-llm-reports-error-2 = Fejl %
admin-llm-reports-positive = Positive %
admin-llm-reports-actions = Handlinger
admin-metrics-admin-metrics = Admin: målinger
admin-metrics-metrics = Målinger
admin-metrics-the-last-24-hours = De seneste 24 timer.
admin-metrics-loading-u = Indlæser…
admin-metrics-manticore-load-now = Manticore-belastning (nu)
admin-metrics-ram-is-the-memory-of = RAM er tabellernes hukommelse. Trådbelastningen gælder de seneste 1, 5 og 15 minutter.
admin-metrics-manticore-status-could-not-be = Manticores status kunne ikke læses: { $error }
admin-metrics-thread-load-1-5-15 = Trådbelastning (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Primær trådbelastning (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Sekundær trådbelastning (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Workertråde optagede / i alt
admin-metrics-work-queue = Arbejdskø
admin-metrics-ram-held-by-tables = RAM brugt af tabeller
admin-metrics-disk-used-by-tables = Disk brugt af tabeller
admin-metrics-tables-merging = Tabeller under sammenlægning
admin-metrics-tables-read = Tabeller læst
admin-metrics-read-at = Læst
admin-metrics-largest-tables-by-ram = Største tabeller efter RAM
admin-metrics-table = Tabel
admin-metrics-ram = RAM
admin-metrics-disk = Disk
admin-metrics-disk-chunks = Diskbidder
admin-metrics-merging = Sammenlægges
admin-metrics-usage-last-24-h = Brug (seneste 24 t)
admin-metrics-events-by-type = Hændelser efter type
admin-metrics-event = Hændelse
admin-metrics-count = Antal
admin-metrics-events-per-hour = Hændelser pr. time
admin-metrics-no-events-recorded-yet = Ingen hændelser registreret endnu.
admin-metrics-busiest-users = Mest aktive brugere
admin-metrics-user = Bruger
admin-metrics-events = Hændelser
admin-metrics-events-2 = { $point_bucket }: { $point_count } hændelser
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API-kald (seneste 24 t)
admin-metrics-no-api-calls-recorded-yet = Ingen API-kald registreret endnu.
admin-metrics-function = Funktion
admin-metrics-calls = Kald
admin-metrics-errors = Fejl
admin-metrics-error-rate = Fejlrate
admin-metrics-bytes-in = Bytes ind
admin-metrics-bytes-out = Bytes ud
admin-operation-detail-admin-operation = Admin: operation { $op_id }
admin-operation-detail-loading-operation = Indlæser operation…
admin-operation-detail-back-to-operations = Tilbage til operationer
admin-operation-detail-operation = Operation
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · sat i kø { $row_started_at }
admin-operation-detail-not-started = ikke startet
admin-operation-detail-re-run-counts-are-not = Tal for ny kørsel er ikke tilgængelige.
admin-operation-detail-failed-document-s-task-failure = { $documents } mislykkede dokument(er), { $row_failed_tasks_unwrap_or_0 } opgavesvigt
admin-operation-detail-failures-were-not-counted = Svigt blev ikke talt.
admin-operation-detail-open-captured-failure-tree = Åbn det registrerede svigttræ
admin-operation-detail-open-in-temporal = Åbn i Temporal
admin-operation-detail-plans = Planer
admin-operation-detail-plan-s-page = { $data_plans_total } plan(er), side { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Der blev ikke registreret nogen planer for denne operation.
admin-operation-detail-dataset = Datasæt
admin-operation-detail-plan-hash = Planens hashværdi
admin-operation-detail-source = Kilde
admin-operation-detail-finished = Afsluttet
admin-operation-detail-previous = Forrige
admin-operation-detail-next = Næste
admin-operation-detail-error-events = Fejlhændelser
admin-operation-detail-error-event-s-page = { $data_events_total } fejlhændelse(r), side { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Der blev ikke registreret nogen fejlhændelser for denne operation.
admin-operation-detail-time = Tid
admin-operation-detail-hash = Hashværdi
admin-operation-detail-task = Opgave
admin-operation-detail-event = Hændelse
admin-operation-detail-error-excerpt = Fejluddrag
admin-operations-admin-operations = Admin: operationer
admin-operations-operations = Operationer
admin-operations-loading-operations = Indlæser operationer…
admin-operations-filters = Filtre
admin-operations-state = Tilstand
admin-operations-any-state = Enhver tilstand
admin-operations-collection = Samling
admin-operations-all-collections = Alle samlinger
admin-operations-choose-a-collection-to-see = Vælg en samling for at se fejlraterne pr. opgave.
admin-operations-operations-newest-first = Operationer, nyeste først
admin-operations-newer = Nyere
admin-operations-page = Side { $current_page_1 }
admin-operations-older = Ældre
admin-operations-failure-rate-by-task-type = Svigtrate pr. opgavetype ({ $collectionname })
admin-operations-one-row-per-activity-execution = Én række pr. aktivitetskørsel, forsøg medregnet. En rate over{" "}
admin-operations-is-marked = {" "}er markeret.
admin-operations-no-task-executions-recorded-for = Ingen opgavekørsler registreret for denne samling endnu.
admin-operations-task = Opgave
admin-operations-error-rate = Fejlrate
admin-operations-failed-total-executions = Mislykkede / samlede kørsler
admin-operations-documents-affected = Berørte dokumenter
admin-operations-above-the-line = over grænsen
admin-operations-no-operations-recorded-for-this = Ingen operationer registreret for dette filter.
admin-operations-kind = Type
admin-operations-target = Mål
admin-operations-workflow = Workflow
admin-operations-queued-at = Sat i kø
admin-operations-started = Startet
admin-operations-duration = Varighed
admin-operations-progress = Fremgang
admin-operations-eta = Forventet færdig
admin-operations-outcome = Udfald
admin-operations-destructive = Destruktiv
admin-operations-repeated-run = Gentaget kørsel
admin-operations-no-estimate-yet = intet skøn endnu
admin-operations-cancel = Annullér
admin-operations-type-to-confirm = skriv { $target } for at bekræfte
admin-operations-re-run = Kør igen
admin-operations-waiting-for-a-free-slot = venter på en ledig plads eller et ledigt mål
admin-operations-counting-work = tæller arbejde…
admin-operations-open-captured-tree = Åbn det registrerede træ
admin-operations-no-captured-tree = intet registreret træ
admin-operations-no-failed-documents = ingen mislykkede dokumenter
admin-operations-document-s-failed = { $n } dokument(er) mislykkedes
admin-operations-task-failure-s = { $t } opgavesvigt
admin-operations-failures-not-counted = svigt ikke talt
admin-operations-the-newest-ten-operations-of = De ti nyeste operationer for denne samling.{" "}
admin-operations-all-operations = Alle operationer
admin-settings-admin-settings = Admin: indstillinger
admin-settings-server-settings = Serverindstillinger
admin-settings-key = Nøgle
admin-settings-value = Værdi
admin-settings-description = Beskrivelse
admin-settings-save = Gem
admin-settings-loading = Indlæser...
admin-settings-deployment-configuration-read-only = Installationens konfiguration (skrivebeskyttet)
admin-settings-not-set = (ikke angivet)
admin-user-detail-admin-user = Admin: bruger { $username }
admin-user-detail-failed-to-load-user = Brugeren kunne ikke indlæses
admin-user-detail-loading = Indlæser...
admin-user-detail-user = Bruger
admin-user-detail-the-next-login-replaces-the = Det næste login erstatter det fulde navn, e-mailadressen og superbruger-status for en bruger fra login-proxyen.
admin-user-detail-llm-usage-u = LLM-brug →
admin-user-detail-full-name = Fulde navn
admin-user-detail-full-name-2 = fulde navn
admin-user-detail-email = E-mail
admin-user-detail-superuser = Superbruger
admin-user-detail-save = Gem
admin-user-detail-groups = Grupper
admin-user-detail-saving-membership = Gemmer medlemskab...
admin-user-detail-group = Gruppe
admin-user-detail-origin = Oprindelse
admin-user-detail-group-admin = Gruppeadministrator
admin-user-detail-uploader = Uploader
admin-user-detail-remove = Fjern
admin-user-detail-add-to-group-u = Tilføj til gruppe…
admin-user-detail-add = Tilføj
admin-user-detail-danger-zone = Farezone
admin-user-detail-delete-user = Slet bruger
admin-user-llm-admin-llm-use-by = Admin: LLM-brug af { $username }
admin-user-llm-u-back-to-user = ← Tilbage til brugeren
admin-user-llm-loading-u = Indlæser…
admin-user-llm-totals-all-time = Totaler (hele perioden)
admin-user-llm-chat-sessions = Chatsessioner
admin-user-llm-messages = Beskeder
admin-user-llm-tool-calls = Værktøjskald
admin-user-llm-model-and-tool-time = Model- og værktøjstid
admin-user-llm-model-and-tool-time-of = model- og værktøjstid for denne brugers agenttrin. Parallelle værktøjskald tæller fuldt ud
admin-user-llm-rate-limit-usage-current-windows = Forbrug mod hastighedsgrænser (aktuelle vinduer)
admin-user-llm-in-process-counters-of-the = Tællere i processen for den kørende website-container. Chatgrænse { $metrics_chat_per_minute }/min, API-grænse { $metrics_api_per_minute }/min, med en aftagende vedvarende rate over de længere vinduer.
admin-user-llm-chat-messages = Chatbeskeder
admin-user-llm-api-calls = API-kald
admin-user-llm-window = Vindue
admin-user-llm-used = Brugt
admin-user-llm-budget = Budget
admin-user-llm-no-chat-sessions = Ingen chatsessioner.
admin-user-llm-title = Titel
admin-user-llm-created = Oprettet
admin-users-list-admin-users = Admin: brugere
admin-users-list-users = Brugere
admin-users-list-search-users = Søg i brugere
admin-users-list-username = Brugernavn
admin-users-list-full-name = Fulde navn
admin-users-list-email-address = E-mailadresse
admin-users-list-superuser = Superbruger
admin-users-list-groups = Grupper
admin-users-list-created = Oprettet
admin-users-list-last-login = Seneste login
admin-users-list-loading = Indlæser...
dataset-create-panel-put-the-documents-in-a = Læg dokumenterne i en mappe der, og genindlæs denne side.
dataset-create-panel-the-name-cannot-start-with = Navnet kan ikke begynde med et punktum eller indeholde en skråstreg.
dataset-create-panel-and-a-dash-a-space = og en bindestreg, et mellemrum eller et punktum bliver til en understregning. Navnet kan ikke ændres senere.
dataset-create-panel-the-form-starts-with-the = Formularen starter med samlingens standarder. Et datasæt, der oprettes med standarderne, følger senere ændringer af dem,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Anvend gemmer sprogene, og derefter starter dette datasæts OCR-opdatering af sig selv.
dataset-ocr-panel-the-list-comes-from-the = Listen kommer fra det kørende image og ikke fra konfigurationen.
live-chats-panel-off = fra
processing-updates-panel-the-waiting-steps-change-each = De ventende trin ændrer { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), hver fil talt én gang, i { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = og en bindestreg, et mellemrum eller et punktum bliver til en understregning. Navnet kan ikke ændres senere.
admin-llm-config-fresh = frisk
admin-llm-config-tools = værktøjer{" "}
admin-llm-config-vision = syn{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-and-a-dataset-created-with = og et datasæt, der oprettes med andre værdier, beholder sine egne. En ændring på datasættets side kører OCR igen.
dataset-create-panel-read-only = { $option_name } (skrivebeskyttet)
live-chats-panel-on = til
processing-updates-panel-up-to-date-select-it = Opdateret. Vælg den for at køre den igen.
admin-ai-status-yes = ja
admin-ai-status-no-2 = nej
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } fejl
admin-collection-processing-done = færdig
admin-collection-processing-failed-2 = { $stage_failed_documents } mislykkedes
admin-collection-processing-left = tilbage
admin-collection-processing-dataset-level = på datasætniveau
admin-collections-list-groups = { $c_group_count } grupper
admin-failures-operation-s = { $group_operation_count } operation(er)
admin-groups-list-groupname = gruppenavn
admin-llm-config-stale = forældet
admin-llm-config-thinking-is-on = Thinking er slået til
admin-llm-config-thinking-is-off = Thinking er slået fra
admin-llm-config-shown = { $models_len } vist
admin-llm-config-reasoning = ræsonnement
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } af { $load_table_count }
admin-metrics-yes = ja
admin-metrics-no = nej
admin-metrics-max = maks.
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = startet { $run_started_at }
admin-operation-detail-yes = ja
admin-operation-detail-no = nej
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = e-mail
admin-user-llm-untitled = (uden titel)
admin-dataset-ocr-panel-models-not-in-image = Modellerne for { $languages } findes ikke i imaget. Tjenesten downloader dem ved første brug, hvilket kræver internetadgang.
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } sider
admin-processing-updates-panel-prerequisites-waiting = Samlingen skal opdateres først: { $steps }. Trin, der skriver til søgeindekset, venter på det.
admin-operations-no-task-type-failing = Ingen opgavetype fejler over { $threshold }%.
admin-operations-task-types-failing = { $count } opgavetype(r) fejler over { $threshold }%.
processing-updates-panel-collection-updates = Samlingsopdateringer
admin-collections-list-some-datasets-are-not-counted = Nogle datasæt er endnu ikke talt.
admin-failures-hide = Skjul
admin-failures-show = Vis
admin-settings-web-session-lifetime-in-seconds = Websessionens levetid i sekunder (standard: 604800 = 1 uge)
admin-settings-turns-every-new-chat-turn = Slår hver ny chatrunde fra, når værdien er false (standard: true). En runde, der er i gang, bliver færdig. Træder i kraft ved næste afsendelse, uden ny udrulning.
admin-settings-written-by-main-py-probe = Skrives af `main.py probe-embeddings` og er det, som endpointet FAKTISK leverer. Hvis du redigerer dette i hånden, ændrer det ikke serveren.
admin-settings-the-folder-whose-subfolders-the = Mappen, hvis undermapper datasætformularen viser. Hvis du ændrer den, kræves en ny udrulning.
admin-settings-from-hoover4-ini-changing-it = Fra hoover4.ini. Hvis du ændrer den, kræves en ny udrulning.
admin-feedback-bug = Fejl
admin-operations-state-name = { $state ->
        [pending] afventer
        [queued] i kø
        [running] kører
        [finished] afsluttet
        [errored] fejlet
        [cancelled] annulleret
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Svigttræ for { $op_id }
admin-failure-detail-showing-of-characters = viser { $node_stack_trace_chars_count } af { $node_stack_trace_original_len } tegn
admin-operations-operation = Operation { $state }.
admin-operations-dispatched = Afsendt { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } rækker
admin-operations-plans = { $row_progress_done } / { $row_progress_total } planer
admin-group-detail-group-2 = Gruppe { $groupname }
admin-settings-the-setting-was-saved-successfully = Indstillingen “{ $k }” blev gemt.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Gruppen “{ $g }” blev tilføjet.
admin-user-detail-user-2 = Bruger { $username }
admin-dataset-detail-dataset = Datasæt { $dataset_id }
admin-dataset-detail-collections = Samlinger › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } af { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Uploadindstillingen kunne ikke læses: { $err }
admin-dataset-detail-operation-started = Operation startet: { $run_id }
admin-collection-detail-collection = Samling { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Vektorindstillingen kunne ikke læses: { $err }
admin-collection-processing-processing-of = Behandling af { $collection_id }
admin-collection-processing-collections = Samlinger › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } kørsler
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = pr. { $at }
admin-collection-processing-over-the-last-s = over de seneste { $live_window_seconds } s
admin-collection-processing-retry-started-run = Nyt forsøg startet (kørsel { $run }).
admin-collection-processing-document-retry-started-run = Nyt forsøg for dokument startet (kørsel { $run }).
admin-operation-detail-operation-2 = Operation { $op_id }
admin-user-llm-llm-usage-of = LLM-brug af { $username }
admin-user-llm-users = Brugere › { $username }
processing-updates-panel-the-processing-updates-could-not = Behandlingsopdateringerne kunne ikke læses: { $e }
processing-updates-panel-update-started = Opdatering startet: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } af { $operation_progress_total } planer
dataset-ocr-panel-adding = tilføjer { $added }
dataset-ocr-panel-removing = fjerner { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } plan(er) genåbnet
dataset-create-panel-saved-as-this-collection-s-2 = Gemt som denne samlings standarder. Disse datasæt arver dem, og deres OCR-opdateringer starter én ad gangen: { $changed_join }. Datasæt med egne sprog beholder dem.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] mappe
       *[other] mapper
    }
    [tables] { $count ->
        [one] tabel
       *[other] tabeller
    }
   *[files] { $count ->
        [one] fil
       *[other] filer
    }
}
processing-updates-step-runs = { $count ->
    [one] trinkørsel
   *[other] trinkørsler
}
processing-update-search_schema-title = Søgeindeksets skema
processing-update-search_schema-explanation = { $files ->
    [one] { $count } søgetabel i samlingen mangler en kolonne, som søgeindekset kræver.
   *[other] { $count } søgetabeller i samlingen mangler en kolonne, som søgeindekset kræver.
} Kolonnen tilføjes til hver tabel. Søgningen fortsætter med at virke.
processing-update-search_schema-runs = Søgeindeksets tabeller
processing-update-unfinished-title = Ufærdig behandling
processing-update-unfinished-explanation = { $files ->
    [one] { $count } fil er ikke behandlet til ende.
   *[other] { $count } filer er ikke behandlet til ende.
} Det omfatter filer uden en behandlingsplan, for eksempel efter en afbrudt indlæsning. Deres behandling gennemføres.
processing-update-unfinished-runs = Alle behandlingsfaser for disse filer
processing-update-failed_files-title = Mislykkede filer
processing-update-failed_files-explanation = { $files ->
    [one] { $count } fil har en behandlingsfejl.
   *[other] { $count } filer har en behandlingsfejl.
} De mislykkede faser kører igen for dem. Den automatiske kørsel prøver en fil én gang for hver ny version af den fase, der mislykkedes.
processing-update-failed_files-runs = De mislykkede faser, derefter entitetsudtrækning, embedding og indeksering
processing-update-virus_scan-title = Virusscanning
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } fil har ingen antivirusafgørelse.
   *[other] { $count } filer har ingen antivirusafgørelse.
} De scannes. En fil, som scanneren finder inficeret, markeres i søgningen, og download af dens original og søgbare PDF afvises.
processing-update-virus_scan-runs = Antivirusscanning, derefter søgeattributten for inficerede filer
processing-update-tables-title = Tabeller
processing-update-tables-explanation = { $files ->
    [one] { $count } fil har en tidligere tabellæsning eller ufuldstændige afhængige resultater. Dens gemte resultater opdateres.
    *[other] { $count } filer har tidligere tabellæsninger eller ufuldstændige afhængige resultater. Deres gemte resultater opdateres.
    }

processing-update-tables-runs = Tabellæsning, entiteter, signaler, indlejringer og begge indeks
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Filer med behov for automatisk OCR: { $count }. Registrerede sider vælger installerede modeller. Fuldstændigt erstatningsoutput fjerner tidligere varianter.
processing-update-ocr-runs = OCR og søgbare PDF'er, derefter entitetsudtrækning, embedding og indeksering af den nye tekst
processing-update-ocr_detection-title = OCR-registrering
processing-update-ocr_detection-explanation = Filer uden aktuel registrering af tekst, skriftsystem eller sprog: { $count }. Hvert egnet billede og hver PDF-side undersøges i begrænsede batches.
processing-update-ocr_detection-runs = Registrering, derefter søgeattributterne for disse filer
processing-update-pdf_text-title = Tekst i søgbare PDF'er
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } fil har søgbare PDF'er med et tidligere tekstlag.
   *[other] { $count } filer har søgbare PDF'er med et tidligere tekstlag.
} Det lag kopierede hvert bogstav uden for de vesteuropæiske alfabeter som en sort firkant. PDF'er på sprog med kun vesteuropæiske bogstaver bevares. De andre PDF'er læses, og delene med sorte firkanter oprettes igen. En billed-PDF bruger de gemte OCR-ord. En PDF-side får en ny OCR-anmodning.
processing-update-pdf_text-runs = Dele af søgbare PDF'er, derefter indeksering af OCR-teksten i de genoprettede PDF'er
processing-update-page_text-title = Indekseret sidetekst
processing-update-page_text-explanation = Filer med ufuldstændig søgetekst: { $count }. Et kontroltegn på en side afsluttede dens indekserede tekst. Den fulde tekst indekseres.
processing-update-page_text-runs = Søgeindeksets tekst for disse sider
processing-update-text_rows-title = Tekstopdeling
processing-update-text_rows-explanation = Filer med tekst fra en tidligere opdeling: { $count }. PDF-tekst flyttes til én række for hver PDF-del, og lang tekst deles med et kort overlap. Der køres ingen ny OCR eller parsing.
processing-update-text_rows-runs = Tekstopdeling, derefter entitetsudtrækning, embedding og indeksering af den nye tekst
processing-update-vectors-title = Vektorer
processing-update-vectors-explanation = { $files ->
    [one] { $count } fil med tekst har ingen vektorer fra den embedding-model, som installationen leverer.
   *[other] { $count } filer med tekst har ingen vektorer fra den embedding-model, som installationen leverer.
} Deres vektorer beregnes og indekseres.
processing-update-vectors-runs = Embedding og vektorindeksering
processing-update-folder_counts-title = Mappetal
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } mappe har ikke noget filantal eller nogen størrelse, eller har værdier fra en tidligere version.
   *[other] { $count } mapper har ikke noget filantal eller nogen størrelse, eller har værdier fra en tidligere version.
} Tallene beregnes igen.
processing-update-folder_counts-runs = Mappetræ
admin-uploads-badge = Uploads
admin-uploads-badge-title = Accepterer uploads

processing-update-archive_members-title = Arkivmedlemmer

processing-update-archive_members-explanation = { $files ->
    [one] { $count } opdelt arkiv kræver en aktuel medlemsliste. Dets medlemmer og søgeresultater opdateres.
    *[other] { $count } opdelte arkiver kræver aktuelle medlemslister. Deres medlemmer og søgeresultater opdateres.
    }

processing-update-archive_members-runs = Arkivudtrækning, medlemsafstemning og afhængig behandling

processing-update-image_previews-title = Billedforhåndsvisninger

processing-update-image_previews-explanation = { $files ->
    [one] { $count } usædvanligt billede har ingen forhåndsvisning. Dets forhåndsvisning oprettes igen.
    *[other] { $count } usædvanlige billeder har ingen forhåndsvisning. Deres forhåndsvisninger oprettes igen.
    }

processing-update-image_previews-runs = Oprettelse og kontrol af billedforhåndsvisninger

processing-update-search_terms-title = Søgeord

processing-update-search_terms-explanation = { $files ->
    [one] { $count } søgetabel kræver aktuelle filtertermer. Termer for sprog, OCR, skrift og røde flag bliver søgbare.
    *[other] Søgetabeller, som kræver aktuelle filtertermer: { $count }. Termer for sprog, OCR, skrift og røde flag bliver søgbare.
    }

processing-update-search_terms-runs = Indeksering og kontrol af filtertermer

automatic-ocr-title = Automatisk OCR
automatic-ocr-refresh = Opdater status
automatic-ocr-coverage = Sidedækning
automatic-ocr-pages = Sider
automatic-ocr-models = OCR-modeller
automatic-ocr-reason = Årsag
automatic-ocr-truncated = Diagnoselisten er ufuldstændig.
automatic-ocr-presence = Har publiceret OCR-tekst
automatic-ocr-policy = OCR vælger installerede modeller ud fra det registrerede skriftsystem og sprog på hver egnet side. Tesseract bruges først, EasyOCR dækker øvrige understøttede skriftsystemer.
automatic-ocr-unknown = Ingen aktuel publicering er registreret. Manglende registrering og mislykket behandling beviser ikke fravær.
automatic-ocr-retry = Brug behandlingsopdateringer til at gentage ufuldstændigt eller mislykket arbejde efter rettelse. Ikke-understøttet dækning kræver kompatible installerede modeller.
automatic-ocr-state = { $state ->
    [candidate] Afventer
    [planned] Planlagt
    [failed] Mislykket
    [incomplete] Ufuldstændig
    [unsupported] Ikke understøttet
    [published] Publiceret
    [applied] Verificeret
    [ready] Tekst registreret
    [no_text] Ingen tekst registreret
    *[other] { $state }
    }

processing-update-entities-title = Navngivne entiteter
processing-update-entities-explanation = Filer med behov for aktuel entitetsudtrækning eller søgbart output: { $count }. Tidligere vellykkede resultater erstattes efter inferens.
processing-update-entities-runs = Udtrækning af navngivne entiteter, tekstattributter og søgbare entitetstermer

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Skriftsystem ikke identificeret
    [tesseract_capabilities_unavailable] Tesseract-dækning ikke tilgængelig
    [detected_language] Modellen svarer til det registrerede sprog
    [unknown_language_script_coverage] Ukendt sprog. En skriftsystemmodel er valgt.
    [language_script_mismatch_script_coverage] Sprog og skriftsystem er forskellige. En skriftsystemmodel er valgt.
    [language_model_unavailable_script_coverage] Sprogmodel ikke tilgængelig. En skriftsystemmodel er valgt.
    [easyocr_capabilities_unavailable] EasyOCR-dækning ikke tilgængelig
    [tesseract_script_unavailable] Tesseract dækker ikke skriftsystemet. EasyOCR er valgt.
    [script_coverage_unavailable] Ingen installeret model dækker dette skriftsystem.
    *[other] { $reason }
    }

processing-updates-check-requested = Pipelinen beregner opdateringerne. Antallene ændres, når beregningen er færdig.
