# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Accesso all'amministrazione richiesto
admin-guard-signed-in-as = Hai effettuato l'accesso come { $u_username }.
admin-guard-ask-an-administrator-for-access = Chiedi a un amministratore l'accesso a questa sezione.
admin-shell-dashboard = Pannello di controllo
admin-shell-collections = Raccolte
admin-shell-operations = Operazioni
admin-shell-errors-failures = Errori/Interruzioni
admin-shell-feedback = Commenti
admin-shell-users = Utenti
admin-shell-groups = Gruppi
admin-shell-settings = Impostazioni
admin-shell-llm = LLM
admin-shell-ai-status = Stato dell'AI
admin-shell-metrics = Metriche
admin-shell-administration = Amministrazione
dataset-create-panel-add-a-dataset = Aggiungi un dataset
dataset-create-panel-the-dataset-mounts-could-not = Impossibile leggere i punti di montaggio dei dataset, quindi non c'è nulla da scegliere: { $err }
dataset-create-panel-loading-the-dataset-mounts = Caricamento dei punti di montaggio dei dataset.
dataset-create-panel-no-dataset-mount-is-configured = Nessun punto di montaggio dei dataset è configurato.
dataset-create-panel-the-mount-folder-could-not = Impossibile leggere la cartella del punto di montaggio, quindi non c'è nulla da scegliere: { $err }
dataset-create-panel-no-subfolders-were-found-in = Nessuna sottocartella trovata in questo punto di montaggio.{" "}
dataset-create-panel-folder = Cartella
dataset-create-panel-select-a-folder = Seleziona una cartella
dataset-create-panel-new-folder = Nuova cartella
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } elementi), già un dataset
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } elementi)
dataset-create-panel-the-server-creates-this-folder = Il server crea questa cartella nel punto di montaggio quando crei il dataset.{" "}
dataset-create-panel-the-list-shows-the-direct = L'elenco mostra le sottocartelle dirette del punto di montaggio.
dataset-create-panel-dataset-name = Nome del dataset
dataset-create-panel-a-name-has-lowercase-letters = Un nome contiene lettere minuscole, cifre e trattini bassi. Le lettere maiuscole diventano minuscole,{" "}
dataset-create-panel-the-dataset-is-saved-as = Il dataset viene salvato come: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Questa raccolta ha già un dataset con il nome { $saved_name }.
dataset-create-panel-accept-uploads = Accetta caricamenti
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Salvato come predefiniti di questa raccolta. Nessun dataset cambia le proprie lingue.
dataset-create-panel-saving-u = Salvataggio in corso…
dataset-create-panel-save-as-collection-defaults = Salva come predefiniti della raccolta
dataset-create-panel-creating-u = Creazione in corso…
dataset-create-panel-create-and-ingest = Crea e acquisisci
dataset-create-panel-mount = Punto di montaggio
dataset-ocr-panel-last-operation = Ultima operazione: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , avviata { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Nessun avanzamento da { $current_stale_seconds_60 } minuti. Controlla il workflow di Temporal e annulla l'operazione se è bloccata.
dataset-ocr-panel-filter-languages = Filtra le lingue
dataset-ocr-panel-ocr-languages = Lingue OCR
dataset-ocr-panel-failed-to-load-the-ocr = Impossibile caricare le impostazioni OCR di questo dataset
dataset-ocr-panel-loading-u = Caricamento in corso…
dataset-ocr-panel-each-easyocr-script-group-adds = Ogni gruppo di scritture di EasyOCR aggiunge un passaggio OCR sul dataset. Tesseract legge tutte le sue lingue in un solo passaggio.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = In vigore: { $panel_tesseract_languages }, da { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = Usa { $source_label_panel_inherited_tesseract_s }: { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = Il servizio Tesseract non ha risposto, quindi le lingue installate sono sconosciute.{" "}
dataset-ocr-panel-the-image-also-has-script = L'immagine contiene anche { $script_models } modelli di scrittura, per esempio il latino. Il modulo non li offre, perché l'impostazione diventa parte di una chiave di archiviazione e accetta solo codici in minuscolo.
dataset-ocr-panel-the-first-language-is-the = La prima lingua è quella principale. Selezionate:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = EasyOCR è disattivato in questa installazione, quindi questa impostazione non ha effetto finché non viene attivato.
dataset-ocr-panel-in-force-off-from = In vigore: disattivato, da { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = In vigore: { $panel_easyocr_languages }, da { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = Usa { $source_label_panel_inherited_easyocr_sou }: disattivato
dataset-ocr-panel-use-2 = Usa { $source_label_panel_inherited_easyocr_sou }: { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Attivato
dataset-ocr-panel-the-easyocr-service-did-not = Il servizio EasyOCR non ha indicato le lingue che supporta.
dataset-ocr-panel-a-model-download-failed = Il download di un modello non è riuscito: { $failure }
dataset-ocr-panel-stored-text-variants = Varianti di testo memorizzate
dataset-ocr-panel-removing-a-language-deletes-its = Rimuovere una lingua elimina il suo testo, le sue righe di ricerca e il suo PDF ricercabile.
dataset-ocr-panel-searchable-pdfs = PDF ricercabili
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } file · { $variant_total_bytes_1024_1024 } MB
dataset-ocr-panel-searchable-pdfs-are-off-on = I PDF ricercabili sono disattivati in questa installazione.
dataset-ocr-panel-saving-u = Salvataggio in corso…
dataset-ocr-panel-apply = Applica
dataset-ocr-panel-no-changes-to-apply = Nessuna modifica da applicare.
live-chats-panel-live-llm-chats = Chat LLM in corso
live-chats-panel-agent-turns-running-right-now = Turni dell'agente in esecuzione in questo momento, prima quelli in corso da più tempo. Si aggiorna ogni 2 s. I dati provengono da Temporal, quindi qui compare anche un turno avviato prima dell'ultimo riavvio del sito.
live-chats-panel-loading-u = Caricamento in corso…
live-chats-panel-no-chats-running = Nessuna chat in esecuzione.
live-chats-panel-user = Utente
live-chats-panel-conversation = Conversazione
live-chats-panel-question = Domanda
live-chats-panel-internet = Internet
live-chats-panel-running = In esecuzione da
live-chats-panel-started = Avviata
live-chats-panel-cancels-the-workflow-the-turn = Annulla il workflow. Il turno termina con un indicatore di arresto nella trascrizione e non scompare senza lasciare traccia.
live-chats-panel-kill = Termina
processing-updates-panel-loading-u = Caricamento in corso…
processing-updates-panel-open-the-operation = Apri l'operazione
processing-updates-panel-the-pipeline-has-not-calculated = La pipeline non ha ancora calcolato questi aggiornamenti.
processing-updates-panel-calculated-at-in-ms = Calcolato alle { $view_checked_at } in { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Gli aggiornamenti automatici sono disattivati in questa installazione. Avvia gli aggiornamenti con il pulsante.
processing-updates-panel-step = Passaggio
processing-updates-panel-count = Numero
processing-updates-panel-state = Stato
processing-updates-panel-last-run = Ultima esecuzione
processing-updates-panel-runs = Esecuzioni: { $step_runs }
processing-updates-panel-a-run-again-would-select = Una nuova esecuzione selezionerebbe circa questo numero di { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } in una nuova esecuzione
processing-updates-panel-never = Mai
processing-updates-panel-update-collection = Aggiorna la raccolta
processing-updates-panel-update-processing = Aggiorna l'elaborazione
processing-updates-panel-check-again = Ricontrolla
processing-updates-panel-dataset = Dataset
processing-updates-panel-processing-updates = Aggiornamenti dell'elaborazione
admin-ai-status-admin-ai-status = Amministrazione: stato dell'AI
admin-ai-status-ai-status = Stato dell'AI
admin-ai-status-the-configured-service-and-the = Il servizio configurato e il servizio che risponde davvero. Il passaggio al servizio CPU compare solo qui.
admin-ai-status-loading-u = Caricamento in corso…
admin-ai-status-config-fingerprint = Impronta della configurazione
admin-ai-status-website-worker = Sito / worker
admin-ai-status-ai-server = Server AI
admin-ai-status-match = Corrispondenza
admin-ai-status-embeddings-probe = Verifica degli embedding
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dimensioni
admin-ai-status-llm-configured = LLM configurato
admin-ai-status-capabilities = Funzionalità
admin-ai-status-capability = Funzionalità
admin-ai-status-configured = Configurato
admin-ai-status-serving = In uso
admin-ai-status-model = Modello
admin-ai-status-reachable = Raggiungibile
admin-ai-status-detail = Dettaglio
admin-ai-status-no = NO
admin-ai-status-vector-shard-dims-vs-probe = Dimensioni degli shard vettoriali e verifica
admin-ai-status-no-collections-yet = Ancora nessuna raccolta.
admin-ai-status-collection = Raccolta
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Corrisponde alla verifica
admin-ai-status-browser-router = Router del browser
admin-ai-status-live-sessions = Sessioni attive: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Traffico LLM recente (24 h)
admin-ai-status-no-llm-call-events-yet = Ancora nessun llm_call_events.
admin-ai-status-user = Utente
admin-ai-status-calls = Chiamate
admin-ai-status-errors = Errori
admin-ai-status-service-use-24-h = Uso dei servizi % (24 h)
admin-ai-status-busy-seconds-in-the-last = Secondi di occupazione nelle ultime 24 ore, come quota della giornata.
admin-ai-status-no-samples-yet = Ancora nessun campione.
admin-ai-status-service = Servizio
admin-ai-status-busy-s = Occupato s
admin-ai-status-use = Uso %
admin-collection-detail-admin-collection = Amministrazione: raccolta { $collection_id }
admin-collection-detail-failed-to-load-collection = Impossibile caricare la raccolta
admin-collection-detail-loading = Caricamento in corso...
admin-collection-detail-datasets = Dataset
admin-collection-detail-dataset = Dataset
admin-collection-detail-documents = Documenti
admin-collection-detail-size = Dimensione
admin-collection-detail-indexed = Indicizzati
admin-collection-detail-errors = Errori
admin-collection-detail-state = Stato
admin-collection-detail-created = Creato
admin-collection-detail-settings = Impostazioni
admin-collection-detail-the-collection-database-is-not = Il database della raccolta non è ancora pronto.
admin-collection-detail-the-last-storage-provisioning-failed = L'ultima predisposizione dell'archiviazione non è riuscita: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Avanzamento dell'elaborazione e stime
admin-collection-detail-display-name = Nome visualizzato
admin-collection-detail-display-name-2 = nome visualizzato
admin-collection-detail-save = Salva
admin-collection-detail-access = Accesso
admin-collection-detail-public-every-signed-in-user = Pubblica. Ogni utente autenticato può cercare e leggere questa raccolta.
admin-collection-detail-restricted-only-members-of-the = Riservata. Solo i membri dei gruppi qui sotto possono cercare e leggere questa raccolta.
admin-collection-detail-the-collection-is-now-public = La raccolta è ora pubblica.
admin-collection-detail-the-collection-is-now-restricted = La raccolta è ora riservata.
admin-collection-detail-make-restricted = Rendi riservata
admin-collection-detail-make-public = Rendi pubblica
admin-collection-detail-group-permissions = Permessi dei gruppi
admin-collection-detail-no-group-can-read-this = Nessun gruppo può ancora leggere questa raccolta.
admin-collection-detail-revoke = Revoca
admin-collection-detail-grant-group-u = Concedi a un gruppo…
admin-collection-detail-grant = Concedi
admin-collection-detail-danger-zone = Zona pericolosa
admin-collection-detail-a-collection-can-only-be = Una raccolta può essere eliminata solo se non ha dataset.
admin-collection-detail-deleting-the-collection-also-drops = Eliminare la raccolta elimina anche il suo database{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}e tutto ciò che contiene. L'operazione non può essere annullata. Digita il nome della raccolta per confermare.
admin-collection-detail-collection-name = Nome della raccolta
admin-collection-detail-delete-collection = Elimina la raccolta
admin-collection-detail-features = Funzioni
admin-collection-detail-vectors = Vettori
admin-collection-detail-this-installation-runs-no-embedding = Questa installazione non esegue alcun servizio di embedding, quindi nessuna raccolta usa i vettori.
admin-collection-detail-vectors-find-passages-by-meaning = I vettori trovano i passaggi in base al significato. Disattivati, non vengono creati nuovi vettori e la ricerca non usa quelli memorizzati, che restano. Attivati, calcolano i vettori mancanti di ogni dataset, un dataset alla volta.
admin-collection-detail-this-collection-follows-the-installation = Questa raccolta segue l'installazione, che usa i vettori. I vettori trovano i passaggi in base al significato. Disattivati, non vengono creati nuovi vettori e la ricerca non usa quelli memorizzati, che restano.
admin-collection-processing-could-not-load-this-panel = Impossibile caricare questo pannello: { $message }
admin-collection-processing-admin-processing-of = Amministrazione: elaborazione di { $collection_id }
admin-collection-processing-u-back-to-collection = ← Torna alla raccolta
admin-collection-processing-processing-stages = Fasi di elaborazione
admin-collection-processing-loading-u = Caricamento in corso…
admin-collection-processing-the-collection-database-is-still = Il database della raccolta è ancora in fase di predisposizione.
admin-collection-processing-this-collection-has-no-datasets = Questa raccolta non ha ancora dataset.
admin-collection-processing-eta = ETA { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Ancora nessun campione per la stima. Vengono raccolti mentre il dataset è in elaborazione.
admin-collection-processing-estimated-completion = Completamento stimato:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(tra { $humanize_seconds_c_eta_seconds }, una stima approssimativa e non una promessa di pianificazione)
admin-collection-processing-no-current-estimate-the-pipeline = Nessuna stima attuale. La pipeline ha terminato oppure non compie progressi misurabili.
admin-collection-processing-where-processing-time-goes = Dove va il tempo di elaborazione
admin-collection-processing-no-task-executions-recorded-yet = Ancora nessuna esecuzione di task registrata. Ogni attività eseguita dalla pipeline scrive qui una riga, quindi una tabella vuota significa che dal rilascio della strumentazione non è stato elaborato nulla.
admin-collection-processing-summed-task-time = Tempo totale dei task
admin-collection-processing-wall-clock = Tempo reale
admin-collection-processing-achieved-parallelism = Parallelismo ottenuto
admin-collection-processing-summed-task-time-divided-by = Il tempo totale dei task diviso per il tempo reale è il parallelismo che la pipeline ha ottenuto davvero. Un valore vicino a 1 significa che il task in cima alla tabella è l'intero costo e vale la pena ottimizzarlo. Un valore vicino al numero di slot dei worker significa che gli slot sono saturi e aggiungere worker è la soluzione più economica. Il tempo reale va dalla prima all'ultima esecuzione, compreso il tempo di inattività.
admin-collection-processing-task = Task
admin-collection-processing-total = Totale
admin-collection-processing-share = Quota
admin-collection-processing-executions = Esecuzioni
admin-collection-processing-mean = Media
admin-collection-processing-max = Max
admin-collection-processing-failed = Non riuscite
admin-collection-processing-live-activity = Attività in corso
admin-collection-processing-nothing-running-no-activity-finished = Nulla in esecuzione. Nessuna attività è terminata negli ultimi { $live_window_seconds } s e nessun worker segnala lavoro in corso.
admin-collection-processing-in-flight = In corso
admin-collection-processing-average-concurrency = Concorrenza media
admin-collection-processing-task-time-in-window = Tempo dei task nella finestra
admin-collection-processing-share-of-processing-time-over = Quota del tempo di elaborazione negli ultimi { $live_window_seconds } s, aggiornata ogni 5 s. Un'esecuzione a cavallo del bordo della finestra conta solo per la parte all'interno. Una riga con esecuzioni in corso ma senza quota è una riga partita prima della finestra e non ancora terminata. Controlla la sua età.
admin-collection-processing-share-of-window = Quota della finestra
admin-collection-processing-task-time = Tempo dei task
admin-collection-processing-completed = Completate
admin-collection-processing-oldest-running = La più vecchia in corso
admin-collection-processing-temporal-workflows = Workflow di Temporal
admin-collection-processing-workflows-of-this-collection-s = Workflow dei dataset di questa raccolta, compresi i workflow figli.
admin-collection-processing-no-workflows-match-this-filter = Nessun workflow corrisponde a questo filtro.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Tipo
admin-collection-processing-status = Stato
admin-collection-processing-started = Avviato
admin-collection-processing-closed = Chiuso
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = apri ↗
admin-collection-processing-failed-tasks = Task non riusciti
admin-collection-processing-no-task-failures-recorded = Nessun errore di task registrato.
admin-collection-processing-dataset = Dataset
admin-collection-processing-errors = Errori
admin-collection-processing-documents = Documenti
admin-collection-processing-last-seen = Ultima occorrenza
admin-collection-processing-sample = Esempio
admin-collection-processing-retry = Riprova
admin-collection-processing-failures-per-document = Errori per documento
admin-collection-processing-no-document-failures-recorded = Nessun errore di documento registrato.
admin-collection-processing-document = Documento
admin-collections-list-admin-collections = Amministrazione: raccolte
admin-collections-list-collections = Raccolte
admin-collections-list-loading-collections-u = Caricamento delle raccolte…
admin-collections-list-datasets = Dataset
admin-collections-list-loading-datasets-u = Caricamento dei dataset…
admin-collections-list-add-a-collection = Aggiungi una raccolta
admin-collections-list-name-for-example-enron = Nome, per esempio enron
admin-collections-list-display-name = Nome visualizzato
admin-collections-list-add-collection = Aggiungi la raccolta
admin-collections-list-a-name-has-lowercase-letters = Un nome contiene lettere minuscole, cifre e trattini bassi. Le lettere maiuscole diventano minuscole,{" "}
admin-collections-list-the-collection-is-saved-as = La raccolta viene salvata come: { $new_name }
admin-collections-list-a-collection-with-the-name = Esiste già una raccolta con il nome { $new_name }.
admin-collections-list-collection = Raccolta
admin-collections-list-documents = Documenti
admin-collections-list-size = Dimensione
admin-collections-list-errors = Errori
admin-collections-list-state = Stato
admin-collections-list-access = Accesso
admin-collections-list-database-not-ready = Database non pronto
admin-collections-list-public = Pubblica
admin-collections-list-1-group = 1 gruppo
admin-collections-list-not-counted-yet = Non ancora conteggiato
admin-collections-list-unknown = Sconosciuto
admin-collections-list-no-collection-has-a-dataset = Nessuna raccolta ha un dataset.
admin-collections-list-dataset = Dataset
admin-collections-list-indexed = Indicizzati
admin-collections-list-created = Creato
admin-dashboard-admin-dashboard = Amministrazione: pannello di controllo
admin-dashboard-administration = Amministrazione
admin-dashboard-users = Utenti
admin-dashboard-groups = Gruppi
admin-dashboard-collections = Raccolte
admin-dashboard-datasets = Dataset
admin-dashboard-failed-to-load-counts = Impossibile caricare i conteggi: { $e }
admin-dataset-detail-admin-dataset = Amministrazione: dataset { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Impossibile caricare il dataset
admin-dataset-detail-loading = Caricamento in corso...
admin-dataset-detail-metadata = Metadati
admin-dataset-detail-display-name = Nome visualizzato
admin-dataset-detail-name = Nome
admin-dataset-detail-type = Tipo
admin-dataset-detail-path = Percorso
admin-dataset-detail-created = Creato
admin-dataset-detail-collection = Raccolta
admin-dataset-detail-save = Salva
admin-dataset-detail-statistics = Statistiche
admin-dataset-detail-state = Stato
admin-dataset-detail-documents = Documenti
admin-dataset-detail-size = Dimensione
admin-dataset-detail-indexed = Indicizzati
admin-dataset-detail-errors = Errori
admin-dataset-detail-plans-finished = Piani completati
admin-dataset-detail-disk = Disco
admin-dataset-detail-rescan-disk-reads-the-dataset = Esegui di nuovo la scansione del disco legge di nuovo la cartella del dataset, aggiunge i file nuovi e modificati e li elabora.
admin-dataset-detail-rescan-disk = Scansiona di nuovo il disco
admin-dataset-detail-danger-zone = Zona pericolosa
admin-dataset-detail-this-deletes-the-dataset-and = Questa azione elimina il dataset e tutti i dati estratti da esso. Non può essere annullata.
admin-dataset-detail-delete-dataset-and-its-data = Elimina il dataset e i suoi dati
admin-dataset-detail-accept-uploads = Accetta caricamenti
admin-dataset-detail-the-folder-of-this-dataset = La cartella di questo dataset non si trova in un punto di montaggio dei dataset scrivibile, quindi non riceve caricamenti.
admin-dataset-detail-starting-u = Avvio in corso…
admin-failure-detail-admin-failure = Amministrazione: interruzione { $op_id }
admin-failure-detail-loading-tree = Caricamento dell'albero…
admin-failure-detail-back-to-errors-and-failures = Torna a errori e interruzioni
admin-failure-detail-operations = Operazioni
admin-failure-detail-scrubbed-copy-written-to-the = Copia ripulita scritta negli appunti.
admin-failure-detail-this-tree-is-truncated-at = Questo albero è troncato. Almeno un'acquisizione ha scartato dei nodi.
admin-failure-detail-the-captured-tree-has-expired = L'albero acquisito è scaduto. La riga dell'operazione è ancora presente.
admin-failure-detail-no-captured-nodes-for-this = Nessun nodo acquisito per questa operazione.
admin-failure-detail-operation = Operazione
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } radice/i · { $tree_nodes_len } nodo/i
admin-failure-detail-open-in-temporal = Apri in Temporal
admin-failure-detail-scrubbed-copy = Copia ripulita
admin-failure-detail-the-scrubbed-copy-replaces-dataset = La copia ripulita sostituisce i percorsi del dataset con hash e i valori lunghi con la loro lunghezza.
admin-failure-detail-copy-scrubbed-record = Copia il record ripulito
admin-failure-detail-tree = Albero
admin-failure-detail-root = Radice ·{" "}
admin-failure-detail-node-parent-depth-source-stage = nodo { $node_node_index } · genitore { $node_parent_index } · profondità { $node_depth } · fonte { $node_source } · fase { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = workflow { $node_workflow_id } · esecuzione { $node_run_id } · attività { $node_activity_id } · tentativo { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } nodo/i scartato/i in questa acquisizione
admin-failures-admin-errors-and-failures = Amministrazione: errori e interruzioni
admin-failures-errors-failures = Errori/Interruzioni
admin-failures-loading-failures = Caricamento delle interruzioni…
admin-failures-operational-failures = Interruzioni operative
admin-failures-no-operational-failures-at-this = Nessuna interruzione operativa al momento.
admin-failures-collection = Raccolta
admin-failures-dataset = Dataset
admin-failures-task-name = Nome del task
admin-failures-error-class = Classe di errore
admin-failures-operation-kind = Tipo di operazione
admin-failures-from = Da
admin-failures-to = A
admin-failures-no-captured-failures-match-these = Nessuna interruzione acquisita corrisponde a questi filtri.
admin-failures-signature = Firma
admin-failures-count = Numero
admin-failures-class = Classe
admin-failures-task = Task
admin-failures-last-seen = Ultima occorrenza
admin-failures-newer = Più recenti
admin-failures-page = Pagina { $current_page_1 }
admin-failures-older = Meno recenti
admin-failures-per-page = Per pagina
admin-failures-loading-instances = Caricamento delle istanze…
admin-failures-no-instances-for-this-signature = Nessuna istanza per questa firma.
admin-failures-node = {" "}nodo { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Errori dei documenti
admin-failures-error-text = Testo dell'errore
admin-failures-loading-document-errors-u = Caricamento degli errori dei documenti…
admin-failures-no-document-errors-match-these = Nessun errore di documento corrisponde a questi filtri.
admin-failures-errors-by-dataset-and-task = Errori per dataset e task
admin-failures-documents = Documenti
admin-failures-show-only-this-dataset-and = Mostra solo questo dataset e questo task
admin-failures-total = Totale
admin-failures-errors = Errori
admin-failures-document = Documento
admin-failures-runs = Esecuzioni
admin-failures-error = Errore
admin-failures-dataset-step = Passaggio del dataset
admin-failures-previous-page = Pagina precedente
admin-failures-page-of-1-error = Pagina { $page } di { $pages }, 1 errore
admin-failures-page-of-errors = Pagina { $page } di { $pages }, { $data_total } errori
admin-failures-next-page = Pagina successiva
admin-feedback-admin-feedback = Amministrazione: commenti
admin-feedback-feedback = Commenti
admin-feedback-search-titles-descriptions-accounts-and = Cerca titoli, descrizioni, account e indirizzi
admin-feedback-search = Cerca
admin-feedback-loading-reports-u = Caricamento delle segnalazioni…
admin-feedback-1-report-matches = 1 segnalazione corrisponde.
admin-feedback-reports-match = { $data_total } segnalazioni corrispondono.
admin-feedback-received = Ricevuta
admin-feedback-type = Tipo
admin-feedback-title = Titolo
admin-feedback-from = Da
admin-feedback-captures = Acquisizioni
admin-feedback-state = Stato
admin-feedback-previous-page = Pagina precedente
admin-feedback-page-of = Pagina { $page } di { $pages }
admin-feedback-next-page = Pagina successiva
admin-feedback-image = Immagine { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Letta
admin-feedback-unread = Non letta
admin-feedback-archived = Archiviata
admin-feedback-mark-unread = Segna come non letta
admin-feedback-mark-read = Segna come letta
admin-feedback-restore = Ripristina
admin-feedback-archive = Archivia
admin-feedback-page = Pagina:{" "}
admin-feedback-the-report-has-no-description = La segnalazione non ha una descrizione.
admin-feedback-open-the-page-image = Apri l'immagine della pagina
admin-feedback-open-the-dom-copy = Apri la copia del DOM
admin-feedback-page-image-of-the-report = Immagine della pagina della segnalazione
admin-feedback-debug-context-and-browser-log = Contesto di debug e log del browser
admin-feedback-loading-u = Caricamento in corso…
admin-group-detail-admin-group = Amministrazione: gruppo { $groupname }
admin-group-detail-failed-to-load-group = Impossibile caricare il gruppo
admin-group-detail-loading = Caricamento in corso...
admin-group-detail-group = Gruppo
admin-group-detail-display-name = Nome visualizzato
admin-group-detail-display-name-2 = nome visualizzato
admin-group-detail-save = Salva
admin-group-detail-members = Membri
admin-group-detail-saving-membership = Salvataggio dell'appartenenza...
admin-group-detail-username = Nome utente
admin-group-detail-origin = Origine
admin-group-detail-group-admin = Amministratore del gruppo
admin-group-detail-uploader = Può caricare
admin-group-detail-remove = Rimuovi
admin-group-detail-username-to-add = nome utente da aggiungere
admin-group-detail-add-member = Aggiungi membro
admin-group-detail-collection-access = Accesso alle raccolte
admin-group-detail-this-group-has-no-collection = Questo gruppo non ha permessi sulle raccolte.
admin-group-detail-revoke = Revoca
admin-group-detail-grant-collection-u = Concedi una raccolta…
admin-group-detail-grant = Concedi
admin-group-detail-danger-zone = Zona pericolosa
admin-group-detail-delete-group = Elimina il gruppo
admin-groups-list-admin-groups = Amministrazione: gruppi
admin-groups-list-groups = Gruppi
admin-groups-list-add-group = Aggiungi un gruppo
admin-groups-list-display-name = nome visualizzato
admin-groups-list-use-lowercase-letters-digits-underscores = Nel nome usa lettere minuscole, cifre, trattini bassi e trattini. Il nome non può essere cambiato in seguito.
admin-groups-list-add-group-2 = Aggiungi il gruppo +
admin-groups-list-group = Gruppo
admin-groups-list-display-name-2 = Nome visualizzato
admin-groups-list-members = Membri
admin-groups-list-collections = Raccolte
admin-groups-list-loading = Caricamento in corso...
admin-llm-config-admin-llm = Amministrazione: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Caricamento in corso…
admin-llm-config-no-llm-provider-is-configured = Nessun provider LLM è configurato. Imposta LLM_BASE_URL / LLM_MODEL in hoover4.ini e ripeti il deploy.
admin-llm-config-providers = Provider
admin-llm-config-the-refresh-runs-in-the = L'aggiornamento viene eseguito in background. Nel frattempo l'elenco attuale resta visibile.
admin-llm-config-refresh-in-flight-u = {" "}Aggiornamento in corso…
admin-llm-config-provider = Provider
admin-llm-config-models = Modelli
admin-llm-config-freshest = Più recente
admin-llm-config-status = Stato
admin-llm-config-refresh-catalog = Aggiorna il catalogo
admin-llm-config-agent-turns-board-assessments-and = Turni dell'agente, valutazioni delle bacheche e conversioni dei report
admin-llm-config-titles-summaries-and-board-labels = Titoli, riepiloghi ed etichette delle bacheche
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini imposta questi modelli: quality_model del provider LLM per i turni dell'agente, le valutazioni delle bacheche e le conversioni dei report quando è impostato, e il suo model per il resto.
admin-llm-config-thinking = Ragionamento
admin-llm-config-the-model-reasons-before-each = Il modello ragiona prima di ogni chiamata di strumento e di ogni risposta.
admin-llm-config-catalog = Catalogo
admin-llm-config-filter-models-u = Filtra i modelli…
admin-llm-config-model = Modello
admin-llm-config-flags = Flag
admin-llm-config-calls-14d = Chiamate 14 g
admin-llm-config-ai-status = Stato dell'AI
admin-llm-config-shows-the-serving-health = {" "}mostra lo stato di salute del servizio.
admin-llm-reports-reports = Report
admin-llm-reports-each-report-runs-when-you = Ogni report viene eseguito quando selezioni il suo pulsante.
admin-llm-reports-running-u = In esecuzione…
admin-llm-reports-run-report = Esegui il report
admin-llm-reports-read-at = Letto alle { $read_at }
admin-llm-reports-errors = Errori
admin-llm-reports-failed-attempts-by-step-and = Tentativi non riusciti per passaggio e classe di errore, ed esecuzioni dell'agente non riuscite o terminate in anticipo, per motivo di fine.
admin-llm-reports-source = Origine
admin-llm-reports-class = Classe
admin-llm-reports-no-errors-in-30-days = Nessun errore negli ultimi 30 giorni.
admin-llm-reports-recent-errors = Errori recenti
admin-llm-reports-the-newest-100-failed-attempts = I 100 tentativi non riusciti più recenti degli ultimi 7 giorni. Apri una riga per leggerne l'errore.
admin-llm-reports-time = Ora
admin-llm-reports-user = Utente
admin-llm-reports-name = Nome
admin-llm-reports-error = Errore
admin-llm-reports-no-errors-in-7-days = Nessun errore negli ultimi 7 giorni.
admin-llm-reports-show = Mostra
admin-llm-reports-tool-calls = Chiamate di strumento
admin-llm-reports-one-row-for-each-tool = Una riga per ogni strumento, ordinata per chiamate negli ultimi 30 giorni. Un errore è una chiamata non riuscita.
admin-llm-reports-tool = Strumento
admin-llm-reports-calls-24-h = Chiamate 24 h
admin-llm-reports-error-24-h = Errori % 24 h
admin-llm-reports-avg-ms-24-h = ms medi 24 h
admin-llm-reports-calls-7-d = Chiamate 7 g
admin-llm-reports-error-7-d = Errori % 7 g
admin-llm-reports-avg-ms-7-d = ms medi 7 g
admin-llm-reports-calls-30-d = Chiamate 30 g
admin-llm-reports-error-30-d = Errori % 30 g
admin-llm-reports-avg-ms-30-d = ms medi 30 g
admin-llm-reports-no-tool-calls-in-30 = Nessuna chiamata di strumento negli ultimi 30 giorni.
admin-llm-reports-top-users = Utenti principali
admin-llm-reports-the-30-users-with-the = I 30 utenti con più tempo di modello nel periodo.
admin-llm-reports-30-days = 30 giorni
admin-llm-reports-7-days = 7 giorni
admin-llm-reports-24-hours = 24 ore
admin-llm-reports-tool-time = Tempo degli strumenti
admin-llm-reports-model-calls = Chiamate al modello
admin-llm-reports-model-time = Tempo del modello
admin-llm-reports-tokens-in = Token in ingresso
admin-llm-reports-tokens-out = Token in uscita
admin-llm-reports-no-agent-use-in-the = Nessun uso dell'agente nel periodo.
admin-llm-reports-system-one-checks = Controlli di System one
admin-llm-reports-requests-are-grouped-by-hook = Le richieste sono raggruppate per hook e regola. Le latenze sono in millisecondi. Le quote usano le richieste degli ultimi 30 giorni.
admin-llm-reports-counts = Conteggi
admin-llm-reports-recent-failures = Errori recenti
admin-llm-reports-select-run-report-to-read = Seleziona Esegui il report per leggere le statistiche.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Regola
admin-llm-reports-outcome = Esito
admin-llm-reports-questions = Domande
admin-llm-reports-median-ms = ms mediani
admin-llm-reports-95th-percentile-ms = ms al 95° percentile
admin-llm-reports-error-2 = Errori %
admin-llm-reports-positive = Positivi %
admin-llm-reports-actions = Azioni
admin-metrics-admin-metrics = Amministrazione: metriche
admin-metrics-metrics = Metriche
admin-metrics-the-last-24-hours = Le ultime 24 ore.
admin-metrics-loading-u = Caricamento in corso…
admin-metrics-manticore-load-now = Carico di Manticore (ora)
admin-metrics-ram-is-the-memory-of = La RAM è la memoria delle tabelle. Il carico dei thread si riferisce all'ultimo minuto, agli ultimi 5 e agli ultimi 15 minuti.
admin-metrics-manticore-status-could-not-be = Impossibile leggere lo stato di Manticore: { $error }
admin-metrics-thread-load-1-5-15 = Carico dei thread (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Carico dei thread primari (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Carico dei thread secondari (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Thread worker occupati / totali
admin-metrics-work-queue = Coda di lavoro
admin-metrics-ram-held-by-tables = RAM occupata dalle tabelle
admin-metrics-disk-used-by-tables = Disco usato dalle tabelle
admin-metrics-tables-merging = Tabelle in unione
admin-metrics-tables-read = Tabelle lette
admin-metrics-read-at = Letto alle
admin-metrics-largest-tables-by-ram = Tabelle più grandi per RAM
admin-metrics-table = Tabella
admin-metrics-ram = RAM
admin-metrics-disk = Disco
admin-metrics-disk-chunks = Blocchi su disco
admin-metrics-merging = In unione
admin-metrics-usage-last-24-h = Utilizzo (ultime 24 h)
admin-metrics-events-by-type = Eventi per tipo
admin-metrics-event = Evento
admin-metrics-count = Numero
admin-metrics-events-per-hour = Eventi all'ora
admin-metrics-no-events-recorded-yet = Ancora nessun evento registrato.
admin-metrics-busiest-users = Utenti più attivi
admin-metrics-user = Utente
admin-metrics-events = Eventi
admin-metrics-events-2 = { $point_bucket }: { $point_count } eventi
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = Chiamate API (ultime 24 h)
admin-metrics-no-api-calls-recorded-yet = Ancora nessuna chiamata API registrata.
admin-metrics-function = Funzione
admin-metrics-calls = Chiamate
admin-metrics-errors = Errori
admin-metrics-error-rate = Tasso di errore
admin-metrics-bytes-in = Byte in ingresso
admin-metrics-bytes-out = Byte in uscita
admin-operation-detail-admin-operation = Amministrazione: operazione { $op_id }
admin-operation-detail-loading-operation = Caricamento dell'operazione…
admin-operation-detail-back-to-operations = Torna alle operazioni
admin-operation-detail-operation = Operazione
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · in coda dalle { $row_started_at }
admin-operation-detail-not-started = non avviata
admin-operation-detail-re-run-counts-are-not = I conteggi delle riesecuzioni non sono disponibili.
admin-operation-detail-failed-document-s-task-failure = { $documents } documento/i non riuscito/i, { $row_failed_tasks_unwrap_or_0 } errore/i di task
admin-operation-detail-failures-were-not-counted = Gli errori non sono stati conteggiati.
admin-operation-detail-open-captured-failure-tree = Apri l'albero dell'interruzione acquisito
admin-operation-detail-open-in-temporal = Apri in Temporal
admin-operation-detail-plans = Piani
admin-operation-detail-plan-s-page = { $data_plans_total } piano/i, pagina { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Per questa operazione non è stato registrato alcun piano.
admin-operation-detail-dataset = Dataset
admin-operation-detail-plan-hash = Hash del piano
admin-operation-detail-source = Fonte
admin-operation-detail-finished = Terminato
admin-operation-detail-previous = Precedente
admin-operation-detail-next = Successiva
admin-operation-detail-error-events = Eventi di errore
admin-operation-detail-error-event-s-page = { $data_events_total } evento/i di errore, pagina { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Per questa operazione non è stato registrato alcun evento di errore.
admin-operation-detail-time = Ora
admin-operation-detail-hash = Hash
admin-operation-detail-task = Task
admin-operation-detail-event = Evento
admin-operation-detail-error-excerpt = Estratto dell'errore
admin-operations-admin-operations = Amministrazione: operazioni
admin-operations-operations = Operazioni
admin-operations-loading-operations = Caricamento delle operazioni…
admin-operations-filters = Filtri
admin-operations-state = Stato
admin-operations-any-state = Qualsiasi stato
admin-operations-collection = Raccolta
admin-operations-all-collections = Tutte le raccolte
admin-operations-choose-a-collection-to-see = Scegli una raccolta per vedere i suoi tassi di errore per task.
admin-operations-operations-newest-first = Operazioni, prima le più recenti
admin-operations-newer = Più recenti
admin-operations-page = Pagina { $current_page_1 }
admin-operations-older = Meno recenti
admin-operations-failure-rate-by-task-type = Tasso di errore per tipo di task ({ $collectionname })
admin-operations-one-row-per-activity-execution = Una riga per ogni esecuzione di un'attività, nuovi tentativi compresi. Un tasso superiore a{" "}
admin-operations-is-marked = {" "}viene evidenziato.
admin-operations-no-task-executions-recorded-for = Per questa raccolta non è ancora stata registrata alcuna esecuzione di task.
admin-operations-task = Task
admin-operations-error-rate = Tasso di errore
admin-operations-failed-total-executions = Esecuzioni non riuscite / totali
admin-operations-documents-affected = Documenti interessati
admin-operations-above-the-line = sopra la soglia
admin-operations-no-operations-recorded-for-this = Nessuna operazione registrata per questo filtro.
admin-operations-kind = Tipo
admin-operations-target = Destinazione
admin-operations-workflow = Workflow
admin-operations-queued-at = In coda dalle
admin-operations-started = Avviata
admin-operations-duration = Durata
admin-operations-progress = Avanzamento
admin-operations-eta = ETA
admin-operations-outcome = Esito
admin-operations-destructive = Distruttiva
admin-operations-repeated-run = Esecuzione ripetuta
admin-operations-no-estimate-yet = ancora nessuna stima
admin-operations-cancel = Annulla
admin-operations-type-to-confirm = digita { $target } per confermare
admin-operations-re-run = Esegui di nuovo
admin-operations-waiting-for-a-free-slot = in attesa di uno slot libero o di una destinazione libera
admin-operations-counting-work = conteggio del lavoro…
admin-operations-open-captured-tree = Apri l'albero acquisito
admin-operations-no-captured-tree = nessun albero acquisito
admin-operations-no-failed-documents = nessun documento non riuscito
admin-operations-document-s-failed = { $n } documento/i non riuscito/i
admin-operations-task-failure-s = { $t } errore/i di task
admin-operations-failures-not-counted = errori non conteggiati
admin-operations-the-newest-ten-operations-of = Le dieci operazioni più recenti di questa raccolta.{" "}
admin-operations-all-operations = Tutte le operazioni
admin-settings-admin-settings = Amministrazione: impostazioni
admin-settings-server-settings = Impostazioni del server
admin-settings-key = Chiave
admin-settings-value = Valore
admin-settings-description = Descrizione
admin-settings-save = Salva
admin-settings-loading = Caricamento in corso...
admin-settings-deployment-configuration-read-only = Configurazione del deploy (sola lettura)
admin-settings-not-set = (non impostato)
admin-user-detail-admin-user = Amministrazione: utente { $username }
admin-user-detail-failed-to-load-user = Impossibile caricare l'utente
admin-user-detail-loading = Caricamento in corso...
admin-user-detail-user = Utente
admin-user-detail-the-next-login-replaces-the = Al prossimo accesso, il nome completo, l'email e lo stato di superutente di un utente proveniente dal proxy di accesso vengono sostituiti.
admin-user-detail-llm-usage-u = Uso dell'LLM →
admin-user-detail-full-name = Nome completo
admin-user-detail-full-name-2 = nome completo
admin-user-detail-email = Email
admin-user-detail-superuser = Superutente
admin-user-detail-save = Salva
admin-user-detail-groups = Gruppi
admin-user-detail-saving-membership = Salvataggio dell'appartenenza...
admin-user-detail-group = Gruppo
admin-user-detail-origin = Origine
admin-user-detail-group-admin = Amministratore del gruppo
admin-user-detail-uploader = Può caricare
admin-user-detail-remove = Rimuovi
admin-user-detail-add-to-group-u = Aggiungi al gruppo…
admin-user-detail-add = Aggiungi
admin-user-detail-danger-zone = Zona pericolosa
admin-user-detail-delete-user = Elimina l'utente
admin-user-llm-admin-llm-use-by = Amministrazione: uso dell'LLM da parte di { $username }
admin-user-llm-u-back-to-user = ← Torna all'utente
admin-user-llm-loading-u = Caricamento in corso…
admin-user-llm-totals-all-time = Totali (dall'inizio)
admin-user-llm-chat-sessions = Sessioni di chat
admin-user-llm-messages = Messaggi
admin-user-llm-tool-calls = Chiamate di strumento
admin-user-llm-model-and-tool-time = Tempo del modello e degli strumenti
admin-user-llm-model-and-tool-time-of = tempo del modello e degli strumenti nei passaggi dell'agente di questo utente. Le chiamate di strumento in parallelo contano per intero
admin-user-llm-rate-limit-usage-current-windows = Uso dei limiti di frequenza (finestre attuali)
admin-user-llm-in-process-counters-of-the = Contatori interni al processo del container del sito in esecuzione. Limite della chat { $metrics_chat_per_minute }/min, limite delle API { $metrics_api_per_minute }/min, con una frequenza sostenuta decrescente nelle finestre più lunghe.
admin-user-llm-chat-messages = Messaggi della chat
admin-user-llm-api-calls = Chiamate API
admin-user-llm-window = Finestra
admin-user-llm-used = Usato
admin-user-llm-budget = Budget
admin-user-llm-no-chat-sessions = Nessuna sessione di chat.
admin-user-llm-title = Titolo
admin-user-llm-created = Creata
admin-users-list-admin-users = Amministrazione: utenti
admin-users-list-users = Utenti
admin-users-list-search-users = Cerca utenti
admin-users-list-username = Nome utente
admin-users-list-full-name = Nome completo
admin-users-list-email-address = Indirizzo email
admin-users-list-superuser = Superutente
admin-users-list-groups = Gruppi
admin-users-list-created = Creato
admin-users-list-last-login = Ultimo accesso
admin-users-list-loading = Caricamento in corso...
dataset-create-panel-put-the-documents-in-a = Metti i documenti in una cartella lì e ricarica questa pagina.
dataset-create-panel-the-name-cannot-start-with = Il nome non può iniziare con un punto né contenere una barra.
dataset-create-panel-and-a-dash-a-space = e un trattino, uno spazio o un punto diventano un trattino basso. Il nome non può essere cambiato in seguito.
dataset-create-panel-the-form-starts-with-the = Il modulo parte dai valori predefiniti della raccolta. Un dataset creato con i valori predefiniti segue le loro modifiche successive,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Applica salva le lingue, e poi l'aggiornamento OCR di questo dataset parte da solo.
dataset-ocr-panel-the-list-comes-from-the = L'elenco proviene dall'immagine in esecuzione, non dalla configurazione.
live-chats-panel-off = disattivato
processing-updates-panel-the-waiting-steps-change-each = I passaggi in attesa modificano { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), con ogni file contato una sola volta, in { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = e un trattino, uno spazio o un punto diventano un trattino basso. Il nome non può essere cambiato in seguito.
admin-llm-config-fresh = aggiornato
admin-llm-config-tools = strumenti{" "}
admin-llm-config-vision = visione{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-and-a-dataset-created-with = e un dataset creato con altri valori conserva i propri. Una modifica nella pagina del dataset esegue di nuovo l'OCR.
dataset-create-panel-read-only = { $option_name } (sola lettura)
live-chats-panel-on = attivo
processing-updates-panel-up-to-date-select-it = Aggiornato. Selezionalo per eseguirlo di nuovo.
admin-ai-status-yes = sì
admin-ai-status-no-2 = no
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } errori
admin-collection-processing-done = completati
admin-collection-processing-failed-2 = { $stage_failed_documents } non riusciti
admin-collection-processing-left = rimasti
admin-collection-processing-dataset-level = a livello di dataset
admin-collections-list-groups = { $c_group_count } gruppi
admin-failures-operation-s = { $group_operation_count } operazione/i
admin-groups-list-groupname = nome del gruppo
admin-llm-config-stale = non aggiornato
admin-llm-config-thinking-is-on = Il ragionamento è attivo
admin-llm-config-thinking-is-off = Il ragionamento è disattivato
admin-llm-config-shown = { $models_len } visualizzati
admin-llm-config-reasoning = ragionamento
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } di { $load_table_count }
admin-metrics-yes = sì
admin-metrics-no = no
admin-metrics-max = max
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = avviata alle { $run_started_at }
admin-operation-detail-yes = sì
admin-operation-detail-no = no
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = email
admin-user-llm-untitled = (senza titolo)
admin-dataset-ocr-panel-models-not-in-image = I modelli per { $languages } non sono nell'immagine. Il servizio li scarica al primo utilizzo, e questo richiede l'accesso a internet.
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } pagine
admin-processing-updates-panel-prerequisites-waiting = La raccolta richiede prima un aggiornamento: { $steps }. I passaggi che scrivono nell'indice di ricerca attendono questo aggiornamento.
admin-operations-no-task-type-failing = Nessun tipo di task supera il { $threshold }% di errori.
admin-operations-task-types-failing = { $count } tipo/i di task superano il { $threshold }% di errori.
processing-updates-panel-collection-updates = Aggiornamenti della raccolta
admin-collections-list-some-datasets-are-not-counted = Alcuni dataset non sono ancora stati conteggiati.
admin-failures-hide = Nascondi
admin-failures-show = Mostra
admin-settings-web-session-lifetime-in-seconds = Durata della sessione web in secondi (predefinito: 604800 = 1 settimana)
admin-settings-turns-every-new-chat-turn = Se è false, disattiva ogni nuovo turno di chat (predefinito: true). Un turno in corso termina. Ha effetto dal prossimo invio, senza un nuovo deploy.
admin-settings-written-by-main-py-probe = Scritto da `main.py probe-embeddings`, ed è ciò che l'endpoint serve DAVVERO. Modificarlo a mano non cambia il server.
admin-settings-the-folder-whose-subfolders-the = La cartella le cui sottocartelle sono elencate nel modulo del dataset. Per cambiarla serve un nuovo deploy.
admin-settings-from-hoover4-ini-changing-it = Da hoover4.ini. Per cambiarlo serve un nuovo deploy.
admin-feedback-bug = Bug
admin-operations-state-name = { $state ->
        [pending] in attesa
        [queued] in coda
        [running] in esecuzione
        [finished] terminata
        [errored] con errori
        [cancelled] annullata
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Albero dell'interruzione di { $op_id }
admin-failure-detail-showing-of-characters = visualizzati { $node_stack_trace_chars_count } di { $node_stack_trace_original_len } caratteri
admin-operations-operation = Operazione { $state }.
admin-operations-dispatched = Avviata { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } righe
admin-operations-plans = { $row_progress_done } / { $row_progress_total } piani
admin-group-detail-group-2 = Gruppo { $groupname }
admin-settings-the-setting-was-saved-successfully = L'impostazione “{ $k }” è stata salvata.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Il gruppo “{ $g }” è stato aggiunto.
admin-user-detail-user-2 = Utente { $username }
admin-dataset-detail-dataset = Dataset { $dataset_id }
admin-dataset-detail-collections = Raccolte › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } di { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Impossibile leggere l'impostazione dei caricamenti: { $err }
admin-dataset-detail-operation-started = Operazione avviata: { $run_id }
admin-collection-detail-collection = Raccolta { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Impossibile leggere l'impostazione dei vettori: { $err }
admin-collection-processing-processing-of = Elaborazione di { $collection_id }
admin-collection-processing-collections = Raccolte › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } esecuzioni
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = al { $at }
admin-collection-processing-over-the-last-s = negli ultimi { $live_window_seconds } s
admin-collection-processing-retry-started-run = Nuovo tentativo avviato (esecuzione { $run }).
admin-collection-processing-document-retry-started-run = Nuovo tentativo del documento avviato (esecuzione { $run }).
admin-operation-detail-operation-2 = Operazione { $op_id }
admin-user-llm-llm-usage-of = Uso dell'LLM di { $username }
admin-user-llm-users = Utenti › { $username }
processing-updates-panel-the-processing-updates-could-not = Impossibile leggere gli aggiornamenti dell'elaborazione: { $e }
processing-updates-panel-update-started = Aggiornamento avviato: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } di { $operation_progress_total } piani
dataset-ocr-panel-adding = aggiunta di { $added }
dataset-ocr-panel-removing = rimozione di { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } piano/i riaperto/i
dataset-create-panel-saved-as-this-collection-s-2 = Salvato come predefiniti di questa raccolta. Questi dataset li ereditano e i loro aggiornamenti OCR partono uno alla volta: { $changed_join }. I dataset con lingue proprie le conservano.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] cartella
       *[other] cartelle
    }
    [tables] { $count ->
        [one] tabella
       *[other] tabelle
    }
   *[files] { $count ->
        [one] file
       *[other] file
    }
}
processing-updates-step-runs = { $count ->
    [one] esecuzione del passaggio
   *[other] esecuzioni dei passaggi
}
processing-update-search_schema-title = Schema dell'indice di ricerca
processing-update-search_schema-explanation = { $files ->
    [one] { $count } tabella di ricerca della raccolta non ha una colonna che l'indice di ricerca richiede.
   *[other] { $count } tabelle di ricerca della raccolta non hanno una colonna che l'indice di ricerca richiede.
} La colonna viene aggiunta a ogni tabella. La ricerca continua a funzionare.
processing-update-search_schema-runs = Tabelle dell'indice di ricerca
processing-update-unfinished-title = Elaborazione non terminata
processing-update-unfinished-explanation = { $files ->
    [one] { $count } file non è stato elaborato fino in fondo.
   *[other] { $count } file non sono stati elaborati fino in fondo.
} Sono inclusi i file senza un piano di elaborazione, per esempio dopo un'acquisizione interrotta. La loro elaborazione viene completata.
processing-update-unfinished-runs = Tutte le fasi di elaborazione per questi file
processing-update-failed_files-title = File non riusciti
processing-update-failed_files-explanation = { $files ->
    [one] { $count } file ha un errore di elaborazione.
   *[other] { $count } file hanno un errore di elaborazione.
} Le fasi non riuscite vengono eseguite di nuovo per questi file. L'esecuzione automatica riprova un file una volta per ogni nuova versione della fase che non è riuscita.
processing-update-failed_files-runs = Le fasi non riuscite, poi estrazione delle entità, embedding e indicizzazione
processing-update-virus_scan-title = Scansione antivirus
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } file non ha un esito antivirus.
   *[other] { $count } file non hanno un esito antivirus.
} Vengono sottoposti a scansione. Un file che lo scanner trova infetto viene segnalato nella ricerca, e il download del suo originale e del suo PDF ricercabile viene rifiutato.
processing-update-virus_scan-runs = Scansione antivirus, poi l'attributo di ricerca dei file infetti
processing-update-tables-title = Tabelle
processing-update-tables-explanation = { $files ->
    [one] { $count } file ha una lettura di tabella precedente o risultati dipendenti incompleti. I risultati memorizzati vengono aggiornati.
    *[other] { $count } file hanno letture di tabelle precedenti o risultati dipendenti incompleti. I risultati memorizzati vengono aggiornati.
    }

processing-update-tables-runs = Lettura delle tabelle, entità, segnali, vettori ed entrambi gli indici
processing-update-ocr-title = OCR
processing-update-ocr-explanation = File che richiedono OCR automatico: { $count }. Le pagine rilevate selezionano i modelli installati. La sostituzione completa rimuove le varianti precedenti.
processing-update-ocr-runs = OCR e PDF ricercabili, poi estrazione delle entità, embedding e indicizzazione del nuovo testo
processing-update-ocr_detection-title = Rilevamento OCR
processing-update-ocr_detection-explanation = File senza rilevamento corrente di testo, scrittura o lingua: { $count }. Ogni immagine e pagina PDF idonea viene esaminata in lotti limitati.
processing-update-ocr_detection-runs = Rilevamento, poi gli attributi di ricerca di questi file
processing-update-pdf_text-title = Testo dei PDF ricercabili
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } file ha PDF ricercabili con un livello di testo precedente.
   *[other] { $count } file hanno PDF ricercabili con un livello di testo precedente.
} Quel livello copiava ogni lettera fuori dagli alfabeti dell’Europa occidentale come un quadrato nero. I PDF delle lingue con sole lettere dell’Europa occidentale restano invariati. Gli altri PDF vengono letti e le parti con quadrati neri vengono create di nuovo. Un PDF di immagine usa le parole OCR salvate. Una pagina PDF riceve una nuova richiesta OCR.
processing-update-pdf_text-runs = Parti dei PDF ricercabili, poi l’indicizzazione del testo OCR dei PDF ricreati
processing-update-page_text-title = Testo indicizzato delle pagine
processing-update-page_text-explanation = File con testo di ricerca incompleto: { $count }. Un carattere di controllo in una pagina ha interrotto il testo indicizzato. Viene indicizzato il testo completo.
processing-update-page_text-runs = Testo dell’indice di ricerca di queste pagine
processing-update-vectors-title = Vettori
processing-update-vectors-explanation = { $files ->
    [one] { $count } file con testo non ha vettori del modello di embedding che l'installazione serve.
   *[other] { $count } file con testo non hanno vettori del modello di embedding che l'installazione serve.
} I loro vettori vengono calcolati e indicizzati.
processing-update-vectors-runs = Embedding e indicizzazione dei vettori
processing-update-folder_counts-title = Conteggi delle cartelle
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } cartella non ha un numero di file né una dimensione, oppure ha valori di una versione precedente.
   *[other] { $count } cartelle non hanno un numero di file né una dimensione, oppure hanno valori di una versione precedente.
} I conteggi vengono calcolati di nuovo.
processing-update-folder_counts-runs = Albero delle cartelle
admin-uploads-badge = Caricamenti
admin-uploads-badge-title = Accetta caricamenti

processing-update-archive_members-title = Membri degli archivi

processing-update-archive_members-explanation = { $files ->
    [one] { $count } archivio suddiviso richiede un elenco aggiornato dei membri. I membri e i risultati di ricerca vengono aggiornati.
    *[other] { $count } archivi suddivisi richiedono elenchi aggiornati dei membri. I membri e i risultati di ricerca vengono aggiornati.
    }

processing-update-archive_members-runs = Estrazione degli archivi, riconciliazione dei membri ed elaborazione dipendente

processing-update-image_previews-title = Anteprime delle immagini

processing-update-image_previews-explanation = { $files ->
    [one] { $count } immagine in un formato poco comune non ha anteprima. L’anteprima viene ricreata.
    *[other] { $count } immagini in formati poco comuni non hanno anteprima. Le anteprime vengono ricreate.
    }

processing-update-image_previews-runs = Creazione e verifica delle anteprime delle immagini

processing-update-search_terms-title = Termini di ricerca

processing-update-search_terms-explanation = { $files ->
    [one] { $count } tabella di ricerca richiede termini di filtro aggiornati. I termini di lingua, OCR, scrittura e segnali d’allarme diventano ricercabili.
    *[other] Tabelle di ricerca che richiedono termini di filtro aggiornati: { $count }. I termini di lingua, OCR, scrittura e segnali d’allarme diventano ricercabili.
    }

processing-update-search_terms-runs = Indicizzazione e verifica dei termini di filtro

automatic-ocr-title = OCR automatico
automatic-ocr-refresh = Aggiorna stato
automatic-ocr-coverage = Copertura delle pagine
automatic-ocr-pages = Pagine
automatic-ocr-models = Modelli OCR
automatic-ocr-reason = Motivo
automatic-ocr-truncated = L’elenco diagnostico è incompleto.
automatic-ocr-presence = Contiene testo OCR pubblicato
automatic-ocr-policy = L’OCR seleziona i modelli installati dalla scrittura e dalla lingua rilevate di ogni pagina idonea. Tesseract viene usato prima, EasyOCR per le scritture non coperte.
automatic-ocr-unknown = Non è registrata alcuna pubblicazione corrente. Il rilevamento mancante e l’elaborazione non riuscita non dimostrano assenza.
automatic-ocr-retry = Usare gli aggiornamenti di elaborazione per riprovare il lavoro incompleto o fallito dopo la correzione. La copertura non supportata richiede modelli installati compatibili.
automatic-ocr-state = { $state ->
    [candidate] In attesa
    [planned] Pianificato
    [failed] Non riuscito
    [incomplete] Incompleto
    [unsupported] Non supportato
    [published] Pubblicato
    [applied] Verificato
    [ready] Testo rilevato
    [no_text] Nessun testo rilevato
    *[other] { $state }
    }

processing-update-entities-title = Entità denominate
processing-update-entities-explanation = File che richiedono estrazione di entità o risultati ricercabili aggiornati: { $count }. I precedenti risultati riusciti vengono sostituiti dopo l’inferenza.
processing-update-entities-runs = Estrazione di entità denominate, attributi di testo e termini di entità ricercabili

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Scrittura non identificata
    [tesseract_capabilities_unavailable] Copertura Tesseract non disponibile
    [detected_language] Il modello corrisponde alla lingua rilevata
    [unknown_language_script_coverage] Lingua sconosciuta. È selezionato un modello di scrittura.
    [language_script_mismatch_script_coverage] La lingua e la scrittura differiscono. È selezionato un modello di scrittura.
    [language_model_unavailable_script_coverage] Modello di lingua non disponibile. È selezionato un modello di scrittura.
    [easyocr_capabilities_unavailable] Copertura EasyOCR non disponibile
    [tesseract_script_unavailable] Tesseract non copre la scrittura. È selezionato EasyOCR.
    [script_coverage_unavailable] Nessun modello installato copre questa scrittura.
    *[other] { $reason }
    }

processing-updates-check-requested = La pipeline sta calcolando gli aggiornamenti. I conteggi cambiano al termine del calcolo.
