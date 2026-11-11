# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Il bot sta lavorando...
chat-composer-ask-the-bot = Chiedi al bot...
chat-composer-internet-tools = Strumenti internet
chat-composer-agent-language-title = L'agente risponde in { $language }. Cambia la lingua nelle impostazioni, in una nuova scheda del browser.
chat-composer-try-again-in-s = Riprova tra { $secs } s
chat-composer-stop-the-answer-the-partial = Interrompi la risposta (la parte parziale non viene salvata nella conversazione)
chat-composer-starting-the-conversation-u = Avvio della conversazione…
chat-composer-send = Invia
chat-conversation-find-search-in-conversation = Cerca nella conversazione
chat-conversation-find-previous-match = Corrispondenza precedente
chat-conversation-find-next-match = Corrispondenza successiva
chat-conversation-find-investigation-board = Bacheca investigativa
doc-ref-card-not-openable = Non apribile: { $reason }.
doc-ref-card-the-search-term-was = Il termine cercato era{" "}
doc-ref-card-open = Apri
doc-ref-card-not-openable-2 = Non apribile
chat-markdown-text-show-the-cited-source = Mostra la fonte citata
chat-markdown-text-no-citation-of-this-conversation = Nessuna citazione di questa conversazione ha assegnato questa etichetta, quindi nessun documento le corrisponde.
chat-markdown-text-citations-of-this-conversation-gave = Le citazioni di questa conversazione hanno assegnato questa etichetta a più di un documento, quindi non rimanda a nessuno di essi.
cards-browser-card-open-the-archived-page = Apri la pagina archiviata
cards-browser-card-the-page-itself-was-not = La pagina in sé non è stata archiviata (stato: { $artifact_status }). Lo screenshot qui sopra è ciò che è stato conservato.
cards-browser-card-click-the-screenshot-to-open = Fai clic sullo screenshot per aprire la pagina archiviata.
cards-browser-card-show-less = Mostra meno
cards-browser-card-show-all = Mostra tutto
cards-browser-card-archived-page = Pagina archiviata
cards-browser-card-download = Scarica
cards-browser-card-archived-copy-of = Copia archiviata di { $artifact_url }
cards-browser-card-this-page-was-not-archived = Questa pagina non è stata archiviata (stato: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } con una scheda
cards-entities-card-the-entity-list-was-cut = L'elenco delle entità è stato troncato.
cards-entities-card-open-the-card-for-this = Apri la scheda di questo valore ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Nessuna scheda: questa conversazione non ha mai indicato il dataset da cui provengono questi valori, e il visualizzatore si indirizza per dataset.
cards-entities-card-more-all-of-them-in = Altri { $rest }, tutti nel pannello delle entità del documento.{" "}
cards-entities-card-names-organisations-and-places-above = I nomi, le organizzazioni e i luoghi qui sopra sono l'interpretazione del testo fatta da un modello. Nessuna regola li ha convalidati, quindi non c'è nulla da spiegare e non aprono nulla.
cards-entities-card-nothing-extracted-from-this-document = Nulla è stato estratto da questo documento.
chat-tool-cards-hide = Nascondi
chat-tool-cards-expand = Espandi
chat-tool-cards-hide-raw-json = Nascondi il JSON grezzo
chat-tool-cards-show-raw-json = Mostra il JSON grezzo
cards-result-cards-search-this = Cerca questo
cards-result-cards-search-every-collection = Cerca in tutte le raccolte
cards-result-cards-form = Forma { $index }: { $form }
cards-result-cards-show-full-text = Mostra il testo completo
cards-result-cards-quote = Citazione testuale: { $quote }
cards-result-cards-reason = Motivo: { $why }
cards-result-cards-open-question = Domanda aperta: { $question }
cards-result-cards-the-explore-gave-this-answer = L'esplorazione ha dato questa risposta alla sua bacheca come riscontro { $kind ->
        [sourced] con fonti
        [inferred] dedotto
        [not_found] negativo
       *[other] di tipo sconosciuto
    }.
cards-result-cards-it-left-no-open-question = Non ha lasciato alcuna domanda aperta.
cards-result-cards-open-questions-for-the-board = Domande aperte per la bacheca:
cards-result-cards-arguments = Parametri
cards-result-cards-list-after-the-call = Elenco dopo la chiamata: { $snapshot_goal }
cards-result-cards-replaces = {" "}· sostituisce { $replaces_id }
cards-result-cards-the-list-at-this-version = L'elenco in questa versione non è memorizzato.
web-search-card-these-sources-returned-nothing-so = Queste fonti non hanno restituito nulla, quindi i risultati provengono da meno fonti del previsto
web-search-card-u-degraded = ⚠ { $degraded_len } con funzionamento ridotto
web-search-card-form = Forma { $index }: { $form }
web-search-card-no-results-from = Nessun risultato da: { $degraded_text }
web-search-card-no-results-every-source-answered = Nessun risultato. Ogni fonte ha risposto e nessuna aveva qualcosa per questa query.
web-search-card-the-lowest-ranked-results-were = I risultati con la posizione più bassa sono stati scartati perché questa chiamata stesse nella trascrizione. L'assistente li ha visti tutti.
web-search-card-view-search-details = Mostra i dettagli della ricerca.
web-search-card-the-stored-result-could-not = non è stato possibile rileggere il risultato memorizzato come JSON
web-search-card-nothing-was-stored-for-this = Per questa chiamata non è stato memorizzato nulla.
web-search-card-forms = Forme: { $forms }
web-search-card-kind = Tipo: { $row_kind }
web-search-card-published = Pubblicato: { $row_published }
web-search-card-loading-search-detail-u = Caricamento dei dettagli della ricerca…
web-search-card-could-not-load-the-search = Impossibile caricare i dettagli della ricerca: { $e }
web-search-card-malformed-detail = Dettagli malformati: { $e }
web-search-card-the-tool-returned-selected-results = Lo strumento ha restituito al modello i risultati selezionati.
web-search-card-results-use-reciprocal-rank-fusion = I risultati usano la fusione dei ranghi reciproci (reciprocal rank fusion).
web-search-card-returned-nothing = non ha restituito nulla: { $degraded }
web-search-card-all-candidates-use-fusion-order = Tutti i candidati seguono l'ordine della fusione.
web-search-card-the-cross-encoder-ranks-selected = Il cross-encoder classifica i risultati selezionati.
web-search-card-selected-results-use-fusion-order = I risultati selezionati seguono l'ordine della fusione.
web-search-card-search-detail = Dettagli della ricerca
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Cerca questo
chat-tool-disclosure-search-every-collection = Cerca in tutte le raccolte
chat-tool-disclosure-hide = Nascondi
chat-tool-disclosure-expand = Espandi
chat-tool-disclosure-this-step-was-recorded-before = Questo passaggio è stato registrato prima che i parametri e i risultati degli strumenti venissero memorizzati. È disponibile solo il riepilogo qui sotto.
chat-tool-disclosure-arguments = Parametri
chat-tool-disclosure-result = Risultato
chat-tool-disclosure-hide-raw-json = Nascondi il JSON grezzo
chat-tool-disclosure-show-raw-json = Mostra il JSON grezzo
chat-tool-disclosure-input-json = JSON di input
chat-tool-disclosure-output-json = JSON di output
chat-transcript-ask-a-question-about-the = Fai una domanda sui documenti delle tue raccolte.
chat-transcript-suggested-next = Suggerimenti successivi...
chat-transcript-earlier-answer = Risposta precedente
chat-transcript-tokens-the-conversation-carries-the = Token contenuti nella conversazione, il contesto singolo più grande fatturato in questo turno e quanta parte della finestra del modello hanno usato
chat-transcript-instruction-to-the-agent = Istruzione all'agente
chat-transcript-the-context-stays-above-the = {" "}Il contesto resta sopra l'obiettivo di { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } parti del riepilogo non sono riuscite. Il registro contiene solo gli elenchi.
chat-transcript-show-the-record = Mostra il registro
chat-transcript-hide-reasoning = Nascondi il ragionamento
chat-transcript-show-reasoning = Mostra il ragionamento
chat-transcript-from-u-hide = { $count } { $count ->
        [one] documento
       *[other] documenti
    } da { $tool }: nascondi
chat-transcript-from-u-show = { $count } { $count ->
        [one] documento
       *[other] documenti
    } da { $tool }: mostra
chat-transcript-u-hide = { $summary }: nascondi
chat-transcript-u-show = { $summary }: mostra
chat-transcript-citations-of-this-conversation-give = Le citazioni di questa conversazione assegnano { $doc_handle } a più di un documento. La risposta non lo collega a nessuno di essi.
chat-transcript-report = Report { $label }
chat-transcript-open-in-the-workspace = Apri nello spazio di lavoro
chat-transcript-this-version-could-not-be = Impossibile leggere questa versione. Segue il testo della risposta nella chat.
chat-transcript-files = File
chat-transcript-version = { $file_name }, versione { $file_version }
chat-web-find-exact-text = Trova il testo esatto
chat-web-previous-match = Corrispondenza precedente
chat-web-next-match = Corrispondenza successiva
chat-web-close-preview = Chiudi l'anteprima
chat-web-the-captured-page-could-not = Impossibile caricare la pagina acquisita.
chat-web-loading = Caricamento in corso…
chat-workspace-pane-workspace = Spazio di lavoro
chat-workspace-pane-close-the-workspace = Chiudi lo spazio di lavoro
chat-workspace-pane-close = Chiudi
chat-workspace-pane-loading-the-files-u = Caricamento dei file…
chat-workspace-pane-the-files-could-not-be = Impossibile caricare i file: { $error }
chat-workspace-pane-this-conversation-has-no-files = Questa conversazione non ha file.
chat-workspace-pane-version = versione { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Scegli un file per leggerlo.
chat-workspace-pane-loading-the-file-u = Caricamento del file…
chat-workspace-pane-the-file-could-not-be = Impossibile caricare il file: { $error }
chat-workspace-pane-version-2 = { $found_name }, versione { $found_version }
chat-board-create-collections = Raccolte
chat-board-create-loading-collections-u = Caricamento delle raccolte…
chat-board-create-hoover-search-new-board = Hoover Search - Nuova bacheca
chat-board-create-ai-chat = Chat AI
chat-board-create-new-investigation-board = Nuova bacheca investigativa
chat-board-create-a-board-runs-its-goals = Una bacheca esegue i suoi obiettivi come una sequenza di esplorazioni dell'agente. Ogni esplorazione è una chat che termina con un riscontro della bacheca. Tu esamini la risposta a ogni obiettivo e, mentre la bacheca lavora, puoi rifiutare i riscontri e aggiungere suggerimenti.
chat-board-create-title = Titolo
chat-board-create-goal = Obiettivo
chat-board-create-remove-this-goal = Rimuovi questo obiettivo
chat-board-create-remove = Rimuovi
chat-board-create-add-a-goal = Aggiungi un obiettivo
chat-board-create-context-optional = Contesto (facoltativo)
chat-board-create-hints-one-per-line-optional = Suggerimenti, uno per riga (facoltativo)
chat-board-create-sources = Fonti
chat-board-create-internet-tools = Strumenti internet
chat-board-create-creating-board = Creazione della bacheca...
chat-board-create-create-board = Crea la bacheca
chat-board-create-board-language = Lingua della bacheca
ai-chat-board-hoover-search-board = Hoover Search - Bacheca
ai-chat-board-loading-the-board-u = Caricamento della bacheca…
ai-chat-board-show-the-board-overview = Mostra la panoramica della bacheca
ai-chat-board-zoom-out = Riduci
ai-chat-board-zoom-in = Ingrandisci
ai-chat-board-u-ai-chat = ← Chat AI
ai-chat-board-settings = Impostazioni
ai-chat-board-board-settings = Impostazioni della bacheca
ai-chat-board-internet-tools = Strumenti internet
ai-chat-board-the-next-explores-of-the = Le prossime esplorazioni della bacheca possono cercare sul web e leggere pagine web. Le esplorazioni in corso mantengono l'impostazione con cui sono partite.
ai-chat-board-collections = Raccolte
ai-chat-board-the-collections-are-fixed-when = Le raccolte vengono fissate quando la bacheca viene creata.
ai-chat-board-language = Lingua
ai-chat-board-the-language-is-fixed-when = La lingua viene fissata quando la bacheca viene creata.
ai-chat-board-the-agent-language-of-the-owner = La lingua dell'agente del proprietario
ai-chat-board-confirm-drop = Conferma lo scarto
ai-chat-board-drop-the-board = Scarta la bacheca
ai-chat-board-close = Chiudi
ai-chat-board-the-board-used-its-explore = La bacheca ha raggiunto il limite di esplorazioni
ai-chat-board-the-board-used-explores-the = La bacheca ha usato { $explore_limit } esplorazioni, il limite di una bacheca. Non avvia altro lavoro. Puoi comunque decidere sulle risposte proposte.
ai-chat-board-create-a-new-board-to = Crea una nuova bacheca per continuare l'indagine
ai-chat-board-goal = Obiettivo
ai-chat-board-goals = Obiettivi
ai-chat-board-add-new-goal = Aggiungi un nuovo obiettivo...
ai-chat-board-a-new-goal = Un nuovo obiettivo
ai-chat-board-add-goal = Aggiungi l'obiettivo
ai-chat-board-a-board-has-at-most = Una bacheca ha al massimo { $max_goals } obiettivi. Crea una nuova bacheca per un altro obiettivo.
ai-chat-board-background-context = Contesto di partenza
ai-chat-board-continue-with-a-correction = Continua con una correzione
ai-chat-board-correction-what-is-wrong-or = Correzione: che cosa è sbagliato o manca. La bacheca prosegue con questa correzione.
ai-chat-board-the-board-waits-for-your = La bacheca attende la tua revisione
ai-chat-board-the-board-used-its-budget = La bacheca ha usato il suo budget di { $snap_max_explores } esplorazioni.
ai-chat-board-the-assessments-gave-no-usable = Le valutazioni non hanno dato alcuna indicazione utilizzabile.
ai-chat-board-accept-or-reject-the-proposed = Accetta o rifiuta la risposta proposta per ogni obiettivo qui sopra. Se rifiuti una risposta, la bacheca prosegue subito.
ai-chat-board-no-proposed-answer-waits-for = Nessuna risposta proposta attende la tua decisione.
ai-chat-board-reopen-the-board-to-continue = Riapri la bacheca per proseguire con gli obiettivi aperti. Conserva i suoi riscontri e le sue risposte.
ai-chat-board-close-the-board-to-accept = Chiudi la bacheca per accettare tutte le risposte proposte e fermarla, oppure proseguila con una correzione.
ai-chat-board-close-the-board = Chiudi la bacheca
ai-chat-board-or-reopen-the-board-to = Oppure riapri la bacheca per proseguire con gli obiettivi aperti senza una correzione.
ai-chat-board-the-board-is-complete = La bacheca è completa
ai-chat-board-a-goal-has-no-accepted = Un obiettivo non ha una risposta accettata. Riapri la bacheca per proseguire. La bacheca conserva i suoi riscontri e le sue risposte.
ai-chat-board-add-a-hint = Aggiungi un suggerimento
ai-chat-board-the-next-assessment-reads-every = La prossima valutazione legge tutti i suggerimenti. Un suggerimento risponde anche a un'esplorazione che ha posto una domanda.
ai-chat-board-add-hint = Aggiungi il suggerimento
ai-chat-board-events = Eventi
ai-chat-board-newest-first = Prima i più recenti
ai-chat-board-date = Data
ai-chat-board-actor = Autore
ai-chat-board-event = Evento
ai-chat-board-show-details = Mostra i dettagli
ai-chat-board-open = Apri
ai-chat-board-show-the-newest-events = Mostra i { $event_rows } eventi più recenti
ai-chat-board-show-all-events = Mostra tutti i { $snap_events_len } eventi
ai-chat-board-statistics = Statistiche
ai-chat-board-explores = Esplorazioni
ai-chat-board-model-steps-per-explore = Passaggi del modello per esplorazione
ai-chat-board-assessments = Valutazioni
ai-chat-board-intents = Intenti
ai-chat-board-findings = Riscontri
ai-chat-board-created = Creata
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } ha rifiutato questo riscontro il { $format_utc_ms_fact_rejected_ms }. La bacheca non lo usa più.
ai-chat-board-this-finding-was-replaced-by = Questo riscontro è stato sostituito da { $new } il { $date }. La bacheca non lo usa più.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } ha rifiutato questo riscontro. La bacheca non lo usa più.
ai-chat-board-no-reason-was-given = Non è stato indicato alcun motivo.
ai-chat-board-reason = Motivo: { $fact_rejected_reason }
ai-chat-board-open-questions = Domande aperte
ai-chat-board-explored-in = Esplorata in{" "}
ai-chat-board-explore-this-question = Esplora questa domanda
ai-chat-board-your-questions = Le tue domande
ai-chat-board-ask-about-the-background-context = Fai una domanda sul contesto di partenza
ai-chat-board-ask-about-this-finding = Fai una domanda su questo riscontro
ai-chat-board-a-follow-up-question-about = Una domanda di approfondimento su questo nodo
ai-chat-board-ask = Chiedi
ai-chat-board-checks-that-changed-this-finding = Verifiche che hanno modificato questo riscontro
ai-chat-board-reject-this-correction = Rifiuta questa correzione
ai-chat-board-reject-this-finding = Rifiuta questo riscontro
ai-chat-board-not-answered-the-board-was = Senza risposta. La bacheca è stata conclusa senza una risposta per questo obiettivo. Un suggerimento o una riapertura lo riapre.
ai-chat-board-no-answer-yet = Ancora nessuna risposta.
ai-chat-board-the-findings-of-this-answer = I riscontri di questa risposta sono ricerche che non hanno trovato nulla. Accettala per registrare che i record non rispondono all'obiettivo, oppure rifiutala per proseguire l'indagine.
ai-chat-board-open-an-assessment-to-read = {"."} Apri una valutazione per leggerne il motivo.
ai-chat-board-from-the-findings = Dai riscontri{" "}
ai-chat-board-accept-answer = Accetta la risposta
ai-chat-board-why-the-answer-is-wrong = Perché la risposta è sbagliata o incompleta
ai-chat-board-reject-answer = Rifiuta la risposta
ai-chat-board-intent = Intento
ai-chat-board-attempts-declared = Tentativi: { $intent_attempts }. Dichiarato { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = L'esplorazione ha chiesto
ai-chat-board-add-a-hint-in-the = Aggiungi un suggerimento nella panoramica della bacheca per rispondere.
ai-chat-board-last-error = Ultimo errore
ai-chat-board-brief = Brief
ai-chat-board-open-the-explore-chat = Apri la chat dell'esplorazione
ai-chat-board-loading-the-assessment-u = Caricamento della valutazione…
ai-chat-board-assessment = Valutazione { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modello { $a_model }. Esito { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Verifiche che l'hanno modificato
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Questa valutazione è stata eseguita prima che i prompt venissero memorizzati.
ai-chat-board-response = Risposta
ai-chat-history-hoover-search-chat-history = Hoover Search - Cronologia delle chat
ai-chat-history-u-back = ← Indietro
ai-chat-history-conversation-history = Cronologia delle conversazioni
ai-chat-history-show-board-chats = Mostra le chat delle bacheche
ai-chat-history-loading-u = Caricamento in corso…
ai-chat-history-could-not-load-history = Impossibile caricare la cronologia: { $e }
ai-chat-history-no-conversations-yet = Ancora nessuna conversazione.
ai-chat-history-board = Bacheca
ai-chat-history-new-chat = Nuova chat
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } messaggio · aggiornata { $s_updated_at }
    *[other] { $s_message_count } messaggi · aggiornata { $s_updated_at }
    }

ai-chat-history-delete-conversation = Elimina la conversazione
ai-chat-history-delete = Elimina
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Chat AI
ai-chat-homepage-what-are-you-researching = Che cosa stai cercando di scoprire?
ai-chat-homepage-view-all-conversations = Mostra tutte le conversazioni
ai-chat-homepage-starting-conversation-u = Avvio della conversazione…
ai-chat-homepage-investigation-boards = Bacheche investigative
ai-chat-homepage-new-board = Nuova bacheca
ai-chat-homepage-loading-boards-u = Caricamento delle bacheche…
ai-chat-homepage-could-not-load-the-boards = Impossibile caricare le bacheche: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Non hai nessuna bacheca. Una bacheca svolge un'indagine lunga come sequenza di esplorazioni dell'agente, e tu ne esamini le risposte.
ai-chat-homepage-updated = Aggiornata { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Chat AI
ai-chat-session-this-conversation-could-not-be = Impossibile caricare questa conversazione.
ai-chat-session-loading-u = Caricamento in corso…
ai-chat-session-u-chats = ← Chat
ai-chat-session-history = Cronologia
ai-chat-session-show-the-files-that-the = Mostra i file che l'assistente ha scritto in questa conversazione
ai-chat-session-workspace = Spazio di lavoro
ai-chat-session-this-answer-was-interrupted-before = Questa risposta è stata interrotta prima di terminare, perché la pagina o il server si sono fermati durante il turno. Chiedi di nuovo per riprovare.
ai-chat-session-dismiss = Chiudi
ai-chat-session-board-explore-chats-are-read = Le chat di esplorazione delle bacheche sono di sola lettura.{" "}
ai-chat-session-open-the-board = Apri la bacheca
chat-locked-options-on = { $label }: attivo
chat-locked-options-off = { $label }: disattivato
chat-tool-cards-running-u = in esecuzione…
cards-result-cards-quote-found = Citazione testuale trovata
cards-result-cards-quote-not-found = Citazione testuale non trovata
cards-result-cards-quote-not-checked = Citazione testuale non verificata
web-search-card-results = { $results_len } risultati
chat-tool-disclosure-running-u = in esecuzione…
chat-transcript-call = chiamata
chat-transcript-calls = chiamate
ai-chat-board-a-board-without-collections-needs = Una bacheca senza raccolte richiede gli strumenti internet.
ai-chat-board-of = { $snap_explores_used } di { $snap_max_explores }
ai-chat-board-assessment-2 = valutazione { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } messaggio
    *[other] { $s_message_count } messaggi
    }

web-search-card-reranked-in = Il cross-encoder ha riordinato i risultati in { $ms } ms.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = punteggio { $score } · era RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Il turno attende uno slot libero del modello.
chat-activity-the-turn-waits-for-a-2 = Il turno attende uno slot libero per gli strumenti.
chat-locked-options-start-a-new-chat-to = Avvia una nuova chat per cambiare questa impostazione.
chat-locked-options-internet-tools = Strumenti internet
chat-session-card-new-chat = Nuova chat
chat-tool-cards-first-frame-of-the-video = Primo fotogramma del video
chat-tool-cards-screenshot-of = Screenshot di
chat-tool-cards-image = Immagine
cards-result-cards-the-agent-asked-a-question = L'agente ha posto una domanda.
chat-transcript-hide = Nascondi
chat-transcript-show = Mostra
chat-transcript-unverified-quote-the-quoted-span = Citazione testuale non verificata. Il tratto citato è troppo breve per essere controllato.
chat-transcript-unverified-quote-the-document-text = Citazione testuale non verificata. Impossibile leggere il testo del documento.
chat-transcript-unverified-quote-this-wording-was = Citazione testuale non verificata. Questa formulazione non è stata trovata nel documento.
chat-board-create-select-a-collection-or-turn = Seleziona una raccolta o attiva gli strumenti internet.
chat-board-create-select-at-least-one-collection = Seleziona almeno una raccolta.
ai-chat-board-active = Attiva
ai-chat-board-paused = In pausa
ai-chat-board-waits-for-review = In attesa di revisione
ai-chat-board-completed = Completata
ai-chat-board-dropped = Scartata
ai-chat-board-unknown = Sconosciuta
ai-chat-board-pause-the-board = Metti in pausa la bacheca
ai-chat-board-resume-the-board = Riprendi la bacheca
ai-chat-board-none = Nessuno
ai-chat-board-reopen-with-the-remaining-budget = Riapri con il budget rimanente
ai-chat-board-finding = Riscontro
ai-chat-board-why-the-correction-is-wrong = Perché la correzione è sbagliata
ai-chat-board-reject-correction = Rifiuta la correzione
ai-chat-board-why-the-finding-is-wrong = Perché il riscontro è sbagliato
ai-chat-board-reject-finding = Rifiuta il riscontro
ai-chat-board-answer = Risposta
ai-chat-board-proposed-answer = Risposta proposta
ai-chat-homepage-active = Attiva
ai-chat-homepage-paused = In pausa
ai-chat-homepage-waits-for-review = In attesa di revisione
ai-chat-homepage-completed = Completata
ai-chat-homepage-dropped = Scartata
ai-chat-homepage-unknown = Sconosciuta
cards-result-cards-submitted-by-board = Inviato dalla bacheca: riscontro { $kind ->
        [sourced] con fonti
        [inferred] dedotto
        [not_found] negativo
       *[other] di tipo sconosciuto
    } dal report
cards-result-cards-finding-for-board = Riscontro { $kind ->
        [sourced] con fonti
        [inferred] dedotto
        [not_found] negativo
       *[other] di tipo sconosciuto
    } per la bacheca
chat-transcript-compacting = Compattazione del contesto: da { $before } token a un obiettivo di { $target }.
chat-transcript-compaction-failed = Il riepilogo dei passaggi precedenti non è riuscito. Il modello ha ricevuto i passaggi precedenti invariati, { $after } token.
chat-transcript-compacted = Contesto compattato: { $steps } passaggi riassunti, da { $before } a { $after } token.
ai-chat-board-reopen-with-more = Riapri con altre { $grant } esplorazioni
ai-chat-board-goal-number = Obiettivo { $number }
ai-chat-board-from-assessment-on = Dalla valutazione { $number } del { $date }.
ai-chat-board-from-assessment = Dalla valutazione { $number }.
chat-board-create-goal-2 = Obiettivo { $index_1 }
ai-chat-session-lost-contact-with-the-chat = contatto con la chat perso: { $e }
ai-chat-session-could-not-stop-the-answer = impossibile interrompere la risposta: { $e } (è ancora in esecuzione)
ai-chat-board-later-assessments-dropped-an-answer = { $n } valutazioni successive hanno scartato una risposta per questo obiettivo:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } token di prompt e { $a_completion_tokens } token di completamento
ai-chat-homepage-completed-goals-not-answered = Completata, { $n } obiettivi senza risposta
board-graph-intent = intento, { $state }
chat-workspace-pane-characters = { $chars } caratteri
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } { $if_joined_live_end_1_tr_chat_transcript_ } di strumento in corso
chat-transcript-running-tool-2 = { $turn_tool_rows_len } { $if_turn_tool_rows_len_1_tr_chat_transcri } di strumento in corso
chat-transcript-answered-after-failed-attempt = { $retries_len ->
        [one] Risposta dopo { $retries_len } tentativo non riuscito
       *[other] Risposta dopo { $retries_len } tentativi non riusciti
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len ->
        [one] { $retries_len } tentativo non riuscito
       *[other] { $retries_len } tentativi non riusciti
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, versione { $report_version }
tool-run-summary-searched = { $n ->
        [one] cercato { $n } termine
       *[other] cercati { $n } termini
    }
tool-run-summary-read = { $n ->
        [one] letto { $n } documento
       *[other] letti { $n } documenti
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] cercato sul web { $n } termine
       *[other] cercati sul web { $n } termini
    }
tool-run-summary-read-web = { $n ->
        [one] letta { $n } pagina web
       *[other] lette { $n } pagine web
    }
tool-run-summary-browser = { $n ->
        [one] { $n } azione del browser
       *[other] { $n } azioni del browser
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] elencate le entità di { $n } documento
       *[other] elencate le entità di { $n } documenti
    }
tool-run-summary-cited = { $n ->
        [one] citato { $n } documento
       *[other] citati { $n } documenti
    }
tool-run-summary-cited-web = { $n ->
        [one] citata { $n } pagina web
       *[other] citate { $n } pagine web
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] letto { $n } skill e i testi degli strumenti
       *[other] letti { $n } skill e i testi degli strumenti
    }
tool-run-summary-saved = { $n ->
        [one] salvata { $n } nota
       *[other] salvate { $n } note
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } chiamata all'elenco delle attività
       *[other] { $n } chiamate all'elenco delle attività
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } istruzione all'agente
       *[other] { $n } istruzioni all'agente
    }
tool-run-summary-other = { $n ->
        [one] { $n } altra chiamata
       *[other] { $n } altre chiamate
    }
tool-run-summary-failed = { $failures } non riuscite
tool-run-summary-took = durata { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } messaggio
    *[other] { $session_message_count } messaggi
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } elemento
       *[other] { $count } elementi
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } campo
       *[other] { $count } campi
    }
chat-tool-disclosure-searched-collections = ricerca nelle raccolte{ $filters }
chat-tool-disclosure-searched-collections-2 = ricerca nelle raccolte · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citati { $n } documenti
chat-tool-disclosure-read-document = lettura del documento · { $path }
chat-tool-disclosure-searched-the-web = ricerca sul web · { $q }
chat-tool-disclosure-opened-page = pagina aperta · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = chiamato { $other }
chat-tool-disclosure-called-2 = chiamato { $other } · { $short }
cards-browser-card-opened = aperto { $url }
cards-browser-card-could-not-open = impossibile aprire { $url }
cards-browser-card-clicked = clic su { $element }
cards-browser-card-could-not-click = impossibile fare clic su { $element }
cards-browser-card-typed-into = testo digitato in { $element }
cards-browser-card-could-not-type-into = impossibile digitare in { $element }
cards-browser-card-typed = digitato “{ $text }”
cards-browser-card-could-not-type = impossibile digitare “{ $text }”
cards-browser-card-pressed = premuto { $key }
cards-browser-card-could-not-press = impossibile premere { $key }
cards-browser-card-chose-an-option-in = opzione scelta in { $element }
cards-browser-card-could-not-choose-an-option = impossibile scegliere un'opzione in { $element }
cards-browser-card-hovered = puntatore su { $element }
cards-browser-card-could-not-hover = impossibile puntare { $element }
cards-browser-card-failed = { $bare }: non riuscito
cards-entities-card-listed-entities-document = entità elencate · { $count ->
        [one] { $count } documento
       *[other] { $count } documenti
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · parte { $part } di { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } documenti
cards-result-cards-forms = { $tool_name } · { $forms } forme
cards-result-cards-in = {" "}in { $collections }
cards-result-cards-page = {" "}· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documenti · { $missing } citazioni testuali non trovate
cards-result-cards-version-unchanged = { $tool_name } · versione { $version } · invariata
cards-result-cards-version = { $tool_name } · versione { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } risultati in ingresso, { $json_u64_doc_total_after_dedupe } dopo la deduplicazione

board-status-on = Attivo

board-status-off = Disattivo

chat-transcript-generic-tool = lo strumento
