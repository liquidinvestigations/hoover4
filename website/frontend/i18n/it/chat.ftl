# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Il bot sta lavorando...
chat-composer-ask-the-bot = Chiedi al bot...
chat-composer-internet-tools = Strumenti Internet
chat-composer-agent-language-title = L'agente risponde in { $language }. Modifica la lingua nelle impostazioni, in una nuova scheda.
chat-composer-try-again-in-s = Riprova tra { $secs } s
chat-composer-stop-the-answer-the-partial = Interrompi la risposta (la risposta parziale non viene salvata nella conversazione)
chat-composer-starting-the-conversation-u = Avvio della conversazione…
chat-composer-send = Invia
chat-conversation-find-search-in-conversation = Cerca nella conversazione
chat-conversation-find-previous-match = Corrispondenza precedente
chat-conversation-find-next-match = Corrispondenza successiva
chat-conversation-find-investigation-board = Scheda d'investigazione
doc-ref-card-not-openable = Non aperto: { $reason }.
doc-ref-card-the-search-term-was = Il termine di ricerca era{ " " }
doc-ref-card-open = Apri
doc-ref-card-not-openable-2 = Non aperto
chat-markdown-text-show-the-cited-source = Mostra la fonte citata
chat-markdown-text-no-citation-of-this-conversation = Nessuna citazione di questa conversazione attribuisce questo handle, quindi nessun documento le è associato.
chat-markdown-text-citations-of-this-conversation-gave = Le citazioni di questa conversazione attribuiscono questo handle a più di un documento, quindi non è associato a nessuno di essi.
cards-browser-card-open-the-archived-page = Apri la pagina archiviata
cards-browser-card-the-page-itself-was-not = La pagina stessa non è stata archiviata (stato: { $artifact_status }). L'istantanea sopra è ciò che è stato conservato.
cards-browser-card-click-the-screenshot-to-open = Clicca sull'istantanea per aprire la pagina archiviata.
cards-browser-card-show-less = Mostra meno
cards-browser-card-show-all = Mostra tutto
cards-browser-card-archived-page = Pagina archiviata
cards-browser-card-download = Scarica
cards-browser-card-archived-copy-of = Copia archiviata di { $artifact_url }
cards-browser-card-this-page-was-not-archived = Questa pagina non è stata archiviata (stato: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } con una scheda
cards-entities-card-the-entity-list-was-cut = L'elenco delle entità è stato troncato.
cards-entities-card-open-the-card-for-this = Apri la scheda per questo valore ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Nessuna scheda: questa conversazione non ha mai indicato da quale insieme di dati provengono questi valori, e lo spettatore è indirizzato dall'insieme di dati.
cards-entities-card-more-all-of-them-in = { $rest } altri, tutti nel pannello delle entità del documento.{ " " }
cards-entities-card-names-organisations-and-places-above = Nomi, organizzazioni e luoghi sopra sono l'interpretazione del testo da parte di un modello. Nessuna regola li ha validati, quindi non c'è nulla da spiegare e non aprono nulla.
cards-entities-card-nothing-extracted-from-this-document = Nessun estratto da questo documento.
chat-tool-cards-hide = Nascondi
chat-tool-cards-expand = Espandi
chat-tool-cards-hide-raw-json = Nascondi JSON grezzo
chat-tool-cards-show-raw-json = Mostra JSON grezzo
cards-result-cards-search-this = Cerca questo
cards-result-cards-search-every-collection = Cerca in ogni collezione
cards-result-cards-form = Modulo { $index }: { $form }
cards-result-cards-show-full-text = Mostra testo completo
cards-result-cards-quote = Citazione: { $quote }
cards-result-cards-reason = Motivo: { $why }
cards-result-cards-open-question = Domanda aperta: { $question }
cards-result-cards-the-explore-gave-this-answer =
    L'esplorazione ha dato questa risposta alla sua scheda come { $kind ->
        [sourced] risultato
        [inferred] risultato
        [not_found] risultato
       *[other] risultato di tipo sconosciuto
    }.
cards-result-cards-it-left-no-open-question = Non ha lasciato domande aperte.
cards-result-cards-open-questions-for-the-board = Domande aperte per la scheda:
cards-result-cards-arguments = Argomenti
cards-result-cards-list-after-the-call = Elenco dopo la chiamata: { $snapshot_goal }
cards-result-cards-replaces = { " " }· sostituisce { $replaces_id }
cards-result-cards-the-list-at-this-version = L'elenco a questa versione non è memorizzato.
web-search-card-these-sources-returned-nothing-so = Queste fonti non hanno restituito nulla, quindi i risultati provengono da meno fonti del previsto
web-search-card-u-degraded = ⚠ { $degraded_len } degradato
web-search-card-form = Modulo { $index }: { $form }
web-search-card-no-results-from = Nessun risultato da: { $degraded_text }
web-search-card-no-results-every-source-answered = Nessun risultato. Ogni fonte ha risposto e nessuna aveva qualcosa per questa query.
web-search-card-the-lowest-ranked-results-were = I risultati con rango più basso sono stati scartati così questa chiamata entra nel transcript. L'assistente li ha visti tutti.
web-search-card-view-search-details = Vedi dettagli ricerca.
web-search-card-the-stored-result-could-not = il risultato memorizzato non è stato letto come JSON
web-search-card-nothing-was-stored-for-this = Non è stato nulla memorizzato per questa chiamata.
web-search-card-forms = Moduli: { $forms }
web-search-card-kind = Tipo: { $row_kind }
web-search-card-published = Pubblicazione: { $row_published }
web-search-card-loading-search-detail-u = Caricamento del dettaglio della ricerca…
web-search-card-could-not-load-the-search = Impossibile caricare i dettagli della ricerca: { $e }
web-search-card-malformed-detail = Dettaglio non valido: { $e }
web-search-card-the-tool-returned-selected-results = Lo strumento ha restituito i risultati selezionati al modello.
web-search-card-results-use-reciprocal-rank-fusion = I risultati utilizzano la fusione del rango reciproco.
web-search-card-returned-nothing = non ha restituito nulla: { $degraded }
web-search-card-all-candidates-use-fusion-order = Tutti i candidati utilizzano l'ordine di fusione.
web-search-card-the-cross-encoder-ranks-selected = Il cross-encoder classifica i risultati selezionati.
web-search-card-selected-results-use-fusion-order = I risultati selezionati utilizzano l'ordine di fusione.
web-search-card-search-detail = Dettagli della ricerca
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Cerca qui
chat-tool-disclosure-search-every-collection = Cerca in tutte le collezioni
chat-tool-disclosure-hide = Nascondi
chat-tool-disclosure-expand = Espandi
chat-tool-disclosure-this-step-was-recorded-before = Questo passo è stato registrato prima che gli argomenti e i risultati dello strumento fossero memorizzati. È disponibile solo il riassunto seguente.
chat-tool-disclosure-arguments = Argomenti
chat-tool-disclosure-result = Risultato
chat-tool-disclosure-hide-raw-json = Nascondi JSON grezzo
chat-tool-disclosure-show-raw-json = Mostra JSON grezzo
chat-tool-disclosure-input-json = JSON in ingresso
chat-tool-disclosure-output-json = JSON in uscita
chat-transcript-ask-a-question-about-the = Fai una domanda sui documenti presenti nelle tue collezioni.
chat-transcript-suggested-next = Prossimo suggerito…
chat-transcript-earlier-answer = Risposta precedente
chat-transcript-tokens-the-conversation-carries-the = Token che la conversazione trasporta, il singolo contesto più ampio per questo turno per cui è stato addebitato e quanto dello spazio del modello è stato utilizzato
chat-transcript-instruction-to-the-agent = Istruzione per l'agente
chat-transcript-the-context-stays-above-the = Il contesto rimane sopra l'obiettivo di { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } parti del riassunto non sono riuscite. Il record contiene solo le liste.
chat-transcript-show-the-record = Mostra il record
chat-transcript-hide-reasoning = Nascondi il ragionamento
chat-transcript-show-reasoning = Mostra il ragionamento
chat-transcript-from-u-hide = { $count } { $noun } da { $tool } — nascondi
chat-transcript-from-u-show = { $count } { $noun } da { $tool } — mostra
chat-transcript-u-hide = { $summary } — nascondi
chat-transcript-u-show = { $summary } — mostra
chat-transcript-citations-of-this-conversation-give = Le citazioni di questa conversazione attribuiscono { $doc_handle } a più di un documento. La risposta non lo collega a nessuno di essi.
chat-transcript-report = Segnala { $label }
chat-transcript-open-in-the-workspace = Apri nello spazio di lavoro
chat-transcript-this-version-could-not-be = Questa versione non è stata letta. Di seguito il testo della risposta.
chat-transcript-files = File
chat-transcript-version = { $file_name }, versione { $file_version }
chat-web-find-exact-text = Trova testo esatto
chat-web-previous-match = Corrispondenza precedente
chat-web-next-match = Corrispondenza successiva
chat-web-close-preview = Chiudi anteprima
chat-web-the-captured-page-could-not = La pagina catturata non è stata caricata.
chat-web-loading = Caricamento…
chat-workspace-pane-workspace = Spazio di lavoro
chat-workspace-pane-close-the-workspace = Chiudi lo spazio di lavoro
chat-workspace-pane-close = Chiudi
chat-workspace-pane-loading-the-files-u = Caricamento dei file…
chat-workspace-pane-the-files-could-not-be = I file non sono stati caricati: { $error }
chat-workspace-pane-this-conversation-has-no-files = Questa conversazione non ha file.
chat-workspace-pane-version = versione { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Scegli un file per leggerlo.
chat-workspace-pane-loading-the-file-u = Caricamento del file…
chat-workspace-pane-the-file-could-not-be = Impossibile caricare il file: { $error }
chat-workspace-pane-version-2 = { $found_name }, versione { $found_version }
chat-board-create-collections = Collezione
chat-board-create-loading-collections-u = Caricamento delle collezioni…
chat-board-create-hoover-search-new-board = Hoover Search - Nuova scheda
chat-board-create-ai-chat = Chat AI
chat-board-create-new-investigation-board = Nuova scheda di indagine
chat-board-create-a-board-runs-its-goals = Una scheda esegue i propri obiettivi come sequenza di esplorazioni dell'agente. Ogni esplorazione è una chat che termina con un singolo risultato della scheda. Rivedi la risposta di ogni obiettivo e puoi rifiutare i risultati e aggiungere indizi durante l'esecuzione.
chat-board-create-title = Titolo
chat-board-create-goal = Obiettivo
chat-board-create-remove-this-goal = Rimovi questo obiettivo
chat-board-create-remove = Rimovi
chat-board-create-add-a-goal = Aggiungi un obiettivo
chat-board-create-context-optional = Contesto (opzionale)
chat-board-create-hints-one-per-line-optional = Indizi, uno per riga (opzionale)
chat-board-create-sources = Fonti
chat-board-create-internet-tools = Strumenti Internet
chat-board-create-creating-board = Creazione della scheda...
chat-board-create-create-board = Crea scheda
ai-chat-board-hoover-search-board = Hoover Search - Scheda
ai-chat-board-loading-the-board-u = Caricamento della scheda…
ai-chat-board-show-the-board-overview = Mostra la panoramica della scheda
ai-chat-board-zoom-out = Riduci ingrandimento
ai-chat-board-zoom-in = Aumenta ingrandimento
ai-chat-board-u-ai-chat = ← Chat AI
ai-chat-board-settings = Impostazioni
ai-chat-board-board-settings = Impostazioni della scheda
ai-chat-board-internet-tools = Strumenti Internet
ai-chat-board-the-next-explores-of-the = Le prossime esplorazioni della scheda possono cercare nel web e leggere pagine web. Le esplorazioni in corso mantengono l'impostazione con cui sono state avviate.
ai-chat-board-collections = Collezioni
ai-chat-board-the-collections-are-fixed-when = Le collezioni sono fisse quando la scheda viene creata.
ai-chat-board-confirm-drop = Conferma eliminazione
ai-chat-board-drop-the-board = Elimina la scheda
ai-chat-board-close = Chiudi
ai-chat-board-the-board-used-its-explore = La scheda ha usato il limite di esplorazione
ai-chat-board-the-board-used-explores-the = La scheda ha usato { $explore_limit } esplorazioni, il limite di una scheda. Non avvia più lavori. Puoi comunque decidere le risposte proposte.
ai-chat-board-create-a-new-board-to = Crea una nuova scheda per continuare l'indagine
ai-chat-board-goal = Obiettivo
ai-chat-board-goals = Obiettivi
ai-chat-board-add-new-goal = Aggiungi un nuovo obiettivo...
ai-chat-board-a-new-goal = Un nuovo obiettivo
ai-chat-board-add-goal = Aggiungi obiettivo
ai-chat-board-a-board-has-at-most = Una scheda ha al massimo { $max_goals } obiettivi. Crea una nuova scheda per un altro obiettivo.
ai-chat-board-background-context = Contesto di background
ai-chat-board-continue-with-a-correction = Continua con una correzione
ai-chat-board-correction-what-is-wrong-or = Correzione: cosa è sbagliata o mancante. La scheda continua con essa.
ai-chat-board-the-board-waits-for-your = La scheda attende la tua revisione
ai-chat-board-the-board-used-its-budget = La scheda ha usato il suo budget di { $snap_max_explores } esplorazioni.
ai-chat-board-the-assessments-gave-no-usable = Le valutazioni non hanno dato alcuna direzione utilizzabile.
ai-chat-board-accept-or-reject-the-proposed = Accetta o rifiuta la risposta proposta di ogni obiettivo sopra. Una risposta rifiutada lascia che la scheda continui subito.
ai-chat-board-no-proposed-answer-waits-for = Nessuna risposta proposta attende la tua decisione.
ai-chat-board-reopen-the-board-to-continue = Riapri la scheda per continuare gli obiettivi aperti. Mantiene i suoi risultati e le sue risposte.
ai-chat-board-close-the-board-to-accept = Chiudi la scheda per accettare ogni risposta proposta e arrestarla, o per le continue con una correzione.
ai-chat-board-close-the-board = Chiudi la scheda
ai-chat-board-or-reopen-the-board-to = Oppure riapri la scheda per continuare gli obiettivi aperti senza una correzione.
ai-chat-board-the-board-is-complete = La scheda è completa
ai-chat-board-a-goal-has-no-accepted = Un obiettivo non ha una risposta accettata. Riapri la scheda per continuarla. La scheda mantiene i suoi risultati e le sue risposte.
ai-chat-board-add-a-hint = Aggiungi un suggerimento
ai-chat-board-the-next-assessment-reads-every = La prossima valutazione legge ogni suggerimento. Un suggerimento risponde anche a un'esplorazione che ha posto una domanda.
ai-chat-board-add-hint = Aggiungi suggerimento
ai-chat-board-events = Eventi
ai-chat-board-newest-first = Più recenti per primi
ai-chat-board-date = Data
ai-chat-board-actor = Autore
ai-chat-board-event = Evento
ai-chat-board-show-details = Mostra dettagli
ai-chat-board-open = Apri
ai-chat-board-show-the-newest-events = Mostra gli eventi più recenti { $event_rows }
ai-chat-board-show-all-events = Mostra tutti gli eventi { $snap_events_len }
ai-chat-board-statistics = Statistiche
ai-chat-board-explores = Esplorazioni
ai-chat-board-model-steps-per-explore = Passi del modello per esplorazione
ai-chat-board-assessments = Valutazioni
ai-chat-board-intents = Intenzioni
ai-chat-board-findings = Risultati
ai-chat-board-created = Creato
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } ha scartato questo risultato il { $format_utc_ms_fact_rejected_ms }. La scheda non lo utilizza più.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } ha scartato questo risultato. La scheda non lo utilizza più.
ai-chat-board-no-reason-was-given = Nessun motivo fornito.
ai-chat-board-reason = Motivo: { $fact_rejected_reason }
ai-chat-board-open-questions = Domande aperte
ai-chat-board-explored-in = Esplorato in{ " " }
ai-chat-board-explore-this-question = Esplora questa domanda
ai-chat-board-your-questions = Le tue domande
ai-chat-board-ask-about-the-background-context = Chiedi sul contesto di sfondo
ai-chat-board-ask-about-this-finding = Chiedi su questo risultato
ai-chat-board-a-follow-up-question-about = Una domanda di approfondimento su questo nodo
ai-chat-board-ask = Chiedi
ai-chat-board-checks-that-changed-this-finding = Controlli che hanno modificato questo risultato
ai-chat-board-reject-this-correction = Rifiuta questa correzione
ai-chat-board-reject-this-finding = Rifiuta questo risultato
ai-chat-board-not-answered-the-board-was = Non risposto. La scheda è stata conclusa senza risposta per questo obiettivo. Un suggerimento o una riapertura la riaprono.
ai-chat-board-no-answer-yet = Ancora senza risposta.
ai-chat-board-the-findings-of-this-answer = I risultati di questa risposta sono ricerche che non hanno trovato nulla. Accettalo per registrare che i documenti non rispondono alla domanda, o rifiutalo per continuare l'indagine.
ai-chat-board-open-an-assessment-to-read = { "." } Apri una valutazione per leggere il motivo.
ai-chat-board-from-the-findings = Dai risultati{ " " }
ai-chat-board-accept-answer = Accetta la risposta
ai-chat-board-why-the-answer-is-wrong = Perché la risposta è sbagliata o incompleta
ai-chat-board-reject-answer = Rifiuta la risposta
ai-chat-board-intent = Intento
ai-chat-board-attempts-declared = Tentativi: { $intent_attempts }. Dichiarato { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = L'esplorazione ha chiesto
ai-chat-board-add-a-hint-in-the = Aggiungi un suggerimento nella panoramica della scheda per rispondervi.
ai-chat-board-last-error = Ultimo errore
ai-chat-board-brief = Sintesi
ai-chat-board-open-the-explore-chat = Apri la chat di esplorazione
ai-chat-board-loading-the-assessment-u = Caricamento della valutazione…
ai-chat-board-assessment = Valutazione { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modello { $a_model }. Esito { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Controlli che l' hanno modificato
ai-chat-board-prompt = Richiesta
ai-chat-board-this-assessment-ran-before-the = Questa valutazione è stata eseguita prima che le richieste fossero memorizzate.
ai-chat-board-response = Risposta
ai-chat-history-hoover-search-chat-history = Hoover Search - Cronologia chat
ai-chat-history-u-back = ← Indietro
ai-chat-history-conversation-history = Cronologia conversazione
ai-chat-history-show-board-chats = Mostra le chat della scheda
ai-chat-history-loading-u = Caricamento…
ai-chat-history-could-not-load-history = Impossibile caricare la cronologia: { $e }
ai-chat-history-no-conversations-yet = Nessuna conversazione ancora.
ai-chat-history-board = Scheda
ai-chat-history-new-chat = Nuova chat
ai-chat-history-messages-updated = { $s_message_count } messaggi · aggiornati alle { $s_updated_at }
ai-chat-history-delete-conversation = Elimina conversazione
ai-chat-history-delete = Elimina
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Chat AI
ai-chat-homepage-what-are-you-researching = Cosa stai studiando?
ai-chat-homepage-view-all-conversations = Visualizza tutte le conversazioni
ai-chat-homepage-starting-conversation-u = Avvio della conversazione…
ai-chat-homepage-investigation-boards = Schede di indagine
ai-chat-homepage-new-board = Nuova scheda
ai-chat-homepage-loading-boards-u = Caricamento delle schede…
ai-chat-homepage-could-not-load-the-boards = Impossibile caricare le schede: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Non hai nessuna scheda. Una scheda esegue un'indagine lunga come sequenza di esplorazioni dell'agente, e tu riesamini le sue risposte.
ai-chat-homepage-updated = Aggiornata alle { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Chat AI
ai-chat-session-this-conversation-could-not-be = Questa conversazione non può essere caricata.
ai-chat-session-loading-u = Caricamento…
ai-chat-session-u-chats = ← Chat
ai-chat-session-history = Cronologia
ai-chat-session-show-the-files-that-the = Mostra i file scritti dall'assistente in questa conversazione
ai-chat-session-workspace = Area di lavoro
ai-chat-session-this-answer-was-interrupted-before = Questa risposta è stata interrotta prima di essere completata, perché la pagina o il server si sono arrestati a turno. Chiedi di nuovo per riprovare.
ai-chat-session-dismiss = Ignora
ai-chat-session-board-explore-chats-are-read = Le chat di esplorazione della scheda sono di sola lettura.{ " " }
ai-chat-session-open-the-board = Apri la scheda
chat-locked-options-on = { $label }: attivo
chat-locked-options-off = { $label }: disattivo
chat-tool-cards-running-u = in corso…
cards-result-cards-quote-found = Quote trovate
cards-result-cards-quote-not-found = Quote non trovate
cards-result-cards-quote-not-checked = Quote non verificate
web-search-card-results = { $results_len } risultati
chat-tool-disclosure-running-u = elaborazione in corso…
chat-transcript-call = chiamata
chat-transcript-calls = chiamate
ai-chat-board-a-board-without-collections-needs = Una scheda senza collezioni richiede gli strumenti di ricerca online.
ai-chat-board-of = { $snap_explores_used } di { $snap_max_explores }
ai-chat-board-assessment-2 = valutazione { $number }
ai-chat-history-messages = { $s_message_count } messaggi
web-search-card-reranked-in = Il cross-encoder ha riorinato i risultati in { $ms } ms.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = punteggio { $score } · era al rango RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Il turno attende uno slot modello disponibile.
chat-activity-the-turn-waits-for-a-2 = Il turno attende uno slot strumenti disponibile.
chat-locked-options-start-a-new-chat-to = Avvia una nuova chat per modificare questa impostazione.
chat-locked-options-internet-tools = Strumenti di ricerca online
chat-session-card-new-chat = Nuova chat
chat-tool-cards-first-frame-of-the-video = Primo fotogramma del video
chat-tool-cards-screenshot-of = Cattura dello schermo di
chat-tool-cards-image = Immagine
cards-result-cards-the-agent-asked-a-question = L'agente ha posto una domanda.
chat-transcript-hide = Nascondi
chat-transcript-show = Mostra
chat-transcript-unverified-quote-the-quoted-span = Quote non verificata. Il brano citato è troppo breve per essere verificato.
chat-transcript-unverified-quote-the-document-text = Quote non verificata. Il testo del documento non è stato letto.
chat-transcript-unverified-quote-this-wording-was = Quote non verificata. Questa formulazione non è stata trovata nel documento.
chat-board-create-select-a-collection-or-turn = Seleziona una collezione o attiva gli strumenti di ricerca online.
chat-board-create-select-at-least-one-collection = Seleziona almeno una collezione.
ai-chat-board-active = Attivo
ai-chat-board-paused = In pausa
ai-chat-board-waits-for-review = In attesa di revisione
ai-chat-board-completed = Completato
ai-chat-board-dropped = Abbandonato
ai-chat-board-unknown = Sconosciuto
ai-chat-board-pause-the-board = Sospendi la scheda
ai-chat-board-resume-the-board = Riprendi la scheda
ai-chat-board-none = Nessuno
ai-chat-board-reopen-with-the-remaining-budget = Riapri con il budget rimanente
ai-chat-board-finding = Risultato
ai-chat-board-why-the-correction-is-wrong = Perché la correzione è sbagliata
ai-chat-board-reject-correction = Rifiuta la correzione
ai-chat-board-why-the-finding-is-wrong = Perché il risultato è sbagliato
ai-chat-board-reject-finding = Rifiuta il risultato
ai-chat-board-answer = Risposta
ai-chat-board-proposed-answer = Risposta proposta
ai-chat-homepage-active = Attivo
ai-chat-homepage-paused = In pausa
ai-chat-homepage-waits-for-review = In attesa di revisione
ai-chat-homepage-completed = Completato
ai-chat-homepage-dropped = Abbandonato
ai-chat-homepage-unknown = Sconosciuto
cards-result-cards-submitted-by-board =
    Presentato dalla scheda: { $kind ->
        [sourced] una fonte
        [inferred] una deduzione
        [not_found] non trovato
       *[other] un genere sconosciuto
    } risultato dal report
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Una fonte
        [inferred] Una deduzione
        [not_found] Non trovato
       *[other] Un genere sconosciuto
    } risultato per la scheda
chat-transcript-compacting = Compattazione del contesto: { $before } token verso un obiettivo di { $target }.
chat-transcript-compaction-failed = Il riassunto dei passaggi precedenti non è riuscito. Il modello ha ricevuto i passaggi precedenti invariati, { $after } token.
chat-transcript-compacted = Contexto compactato: { $steps } passaggi riassunti, { $before } token diventi { $after }.
ai-chat-board-reopen-with-more = Riapri con { $grant } esplorazioni in più
ai-chat-board-goal-number = Obiettivo { $number }
ai-chat-board-from-assessment-on = Dalla valutazione { $number } del { $date }.
ai-chat-board-from-assessment = Dalla valutazione { $number }.
chat-board-create-goal-2 = Obiettivo { $index_1 }
ai-chat-session-lost-contact-with-the-chat = perso il contatto con la chat: { $e }
ai-chat-session-could-not-stop-the-answer = impossibile arrestare la risposta: { $e } — è ancora in corso
ai-chat-board-later-assessments-dropped-an-answer = { $n } valutazioni successive hanno scartato una risposta per questo obiettivo:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } token di richiesta e { $a_completion_tokens } token di completamento
ai-chat-homepage-completed-goals-not-answered = Completati, { $n } obiettivi senza risposta
board-graph-intent = intento, { $state }
chat-workspace-pane-characters = { $chars } caratteri
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } esecuzione dello strumento { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } esecuzione dello strumento { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Risposta dopo { $retries_len } tentativo{ $if_retries_len_1_else_s } non riuscito
chat-transcript-failed-attempt = { $retries_len } tentativo{ $if_retries_len_1_else_s } non riuscito
chat-transcript-version-2 = { $report_name }, versione { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] cercato il termine { $n }
       *[other] cercati i termini { $n }
    }
tool-run-summary-read =
    { $n ->
        [one] letto il documento { $n }
       *[other] letti i documenti { $n }
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] cercato sul web il termine { $n }
       *[other] cercato sul web i termini { $n }
    }
tool-run-summary-read-web =
    { $n ->
        [one] letta la pagina web { $n }
       *[other] lette le pagine web { $n }
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } azione sul browser
       *[other] { $n } azioni sul browser
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] elencate le entità del documento { $n }
       *[other] elencate le entità dei documenti { $n }
    }
tool-run-summary-cited =
    { $n ->
        [one] citato il documento { $n }
       *[other] citati i documenti { $n }
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citata la pagina web { $n }
       *[other] citate le pagine web { $n }
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] letto il testo della funzione e degli strumenti { $n }
       *[other] letti i testi delle funzioni e degli strumenti { $n }
    }
tool-run-summary-saved =
    { $n ->
        [one] salvata la nota { $n }
       *[other] salvate le note { $n }
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } chiamata alla lista di attività
       *[other] { $n } chiamate alla lista di attività
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } istruzione all'agente
       *[other] { $n } istruzioni all'agente
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } altra chiamata
       *[other] { $n } altre chiamate
    }
tool-run-summary-failed = { $failures } falliti
tool-run-summary-took = richiesto { $duration_text_ms }
chat-session-card-messages = { $session_message_count } messaggi
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } elemento
       *[other] { $count } elementi
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } campo
       *[other] { $count } campi
    }
chat-tool-disclosure-searched-collections = collezioni cercate{ $filters }
chat-tool-disclosure-searched-collections-2 = collezioni cercate · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citati { $n } documenti
chat-tool-disclosure-read-document = documento letto · { $path }
chat-tool-disclosure-searched-the-web = web cercato · { $q }
chat-tool-disclosure-opened-page = pagina aperta · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = chiamato { $other }
chat-tool-disclosure-called-2 = chiamato { $other } · { $short }
cards-browser-card-opened = aperta { $url }
cards-browser-card-could-not-open = non è possibile aprire { $url }
cards-browser-card-clicked = cliccato { $element }
cards-browser-card-could-not-click = non è possibile cliccare { $element }
cards-browser-card-typed-into = digitato in { $element }
cards-browser-card-could-not-type-into = non è possibile digitare in { $element }
cards-browser-card-typed = digitato “{ $text }”
cards-browser-card-could-not-type = non è possibile digitare “{ $text }”
cards-browser-card-pressed = premuto { $key }
cards-browser-card-could-not-press = non è possibile premere { $key }
cards-browser-card-chose-an-option-in = scelta un'opzione in { $element }
cards-browser-card-could-not-choose-an-option = non è possibile scegliere un'opzione in { $element }
cards-browser-card-hovered = posizionato su { $element }
cards-browser-card-could-not-hover = non è possibile posizionare su { $element }
cards-browser-card-failed = { $bare } — fallito
cards-entities-card-listed-entities-document = entità elencate · { $count } documento{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · parte { $part } di { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } documenti
cards-result-cards-forms = { $tool_name } · { $forms } moduli
cards-result-cards-in = { " " }in { $collections }
cards-result-cards-page = { " " }· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documenti · { $missing } citazioni non trovate
cards-result-cards-version-unchanged = { $tool_name } · versione { $version } · invariata
cards-result-cards-version = { $tool_name } · versione { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } risultati, { $json_u64_doc_total_after_dedupe } dopo deduplicazione
