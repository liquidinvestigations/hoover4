# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Botul lucrează...
chat-composer-ask-the-bot = Întreabă botul...
chat-composer-internet-tools = Instrumente de internet
chat-composer-agent-language-title = Agentul răspunde în { $language }. Schimbă limba în setări, într-o filă nouă.
chat-composer-try-again-in-s = Încearcă din nou peste { $secs } s
chat-composer-stop-the-answer-the-partial = Oprește răspunsul (partea generată nu este salvată în conversație)
chat-composer-starting-the-conversation-u = Se pornește conversația…
chat-composer-send = Trimite
chat-conversation-find-search-in-conversation = Caută în conversație
chat-conversation-find-previous-match = Potrivirea anterioară
chat-conversation-find-next-match = Potrivirea următoare
chat-conversation-find-investigation-board = Tablou de investigație
doc-ref-card-not-openable = Nu poate fi deschis: { $reason }.
doc-ref-card-the-search-term-was = Termenul căutat a fost{" "}
doc-ref-card-open = Deschide
doc-ref-card-not-openable-2 = Nu poate fi deschis
chat-markdown-text-show-the-cited-source = Afișează sursa citată
chat-markdown-text-no-citation-of-this-conversation = Nicio citare din această conversație nu a dat această etichetă, deci niciun document nu se află în spatele ei.
chat-markdown-text-citations-of-this-conversation-gave = Citările din această conversație au dat această etichetă mai multor documente, așa că nu trimite la niciunul dintre ele.
cards-browser-card-open-the-archived-page = Deschide pagina arhivată
cards-browser-card-the-page-itself-was-not = Pagina în sine nu a fost arhivată (stare: { $artifact_status }). Captura de ecran de mai sus este ceea ce s-a păstrat.
cards-browser-card-click-the-screenshot-to-open = Fă clic pe captura de ecran pentru a deschide pagina arhivată.
cards-browser-card-show-less = Afișează mai puțin
cards-browser-card-show-all = Afișează tot
cards-browser-card-archived-page = Pagină arhivată
cards-browser-card-download = Descarcă
cards-browser-card-archived-copy-of = Copie arhivată a { $artifact_url }
cards-browser-card-this-page-was-not-archived = Această pagină nu a fost arhivată (stare: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } cu fișă
cards-entities-card-the-entity-list-was-cut = Lista de entități a fost trunchiată.
cards-entities-card-open-the-card-for-this = Deschide fișa pentru această valoare ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Fără fișă: această conversație nu a menționat niciodată setul de date din care provin aceste valori, iar vizualizatorul este adresat după setul de date.
cards-entities-card-more-all-of-them-in = Încă { $rest }, toate în panoul de entități al documentului.{" "}
cards-entities-card-names-organisations-and-places-above = Numele, organizațiile și locurile de mai sus sunt interpretarea textului de către un model. Nicio regulă nu le-a validat, deci nu există nimic de explicat și nu deschid nimic.
cards-entities-card-nothing-extracted-from-this-document = Nimic extras din acest document.
chat-tool-cards-hide = Ascunde
chat-tool-cards-expand = Extinde
chat-tool-cards-hide-raw-json = Ascunde JSON-ul brut
chat-tool-cards-show-raw-json = Afișează JSON-ul brut
cards-result-cards-search-this = Caută aceasta
cards-result-cards-search-every-collection = Caută în toate colecțiile
cards-result-cards-form = Varianta { $index }: { $form }
cards-result-cards-show-full-text = Afișează textul complet
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Motiv: { $why }
cards-result-cards-open-question = Întrebare deschisă: { $question }
cards-result-cards-the-explore-gave-this-answer = Explorarea a dat acest răspuns tabloului său ca o constatare { $kind ->
        [sourced] cu surse
        [inferred] dedusă
        [not_found] de tip „negăsit”
       *[other] de tip necunoscut
    }.
cards-result-cards-it-left-no-open-question = Nu a lăsat nicio întrebare deschisă.
cards-result-cards-open-questions-for-the-board = Întrebări deschise pentru tablou:
cards-result-cards-arguments = Argumente
cards-result-cards-list-after-the-call = Lista după apel: { $snapshot_goal }
cards-result-cards-replaces = {" "}· înlocuiește { $replaces_id }
cards-result-cards-the-list-at-this-version = Lista din această versiune nu este stocată.
web-search-card-these-sources-returned-nothing-so = Aceste surse nu au returnat nimic, deci rezultatele provin din mai puține surse decât s-a intenționat
web-search-card-u-degraded = ⚠ { $degraded_len } degradate
web-search-card-form = Varianta { $index }: { $form }
web-search-card-no-results-from = Niciun rezultat de la: { $degraded_text }
web-search-card-no-results-every-source-answered = Niciun rezultat. Toate sursele au răspuns și niciuna nu a avut ceva pentru această interogare.
web-search-card-the-lowest-ranked-results-were = Rezultatele cu cel mai mic rang au fost omise pentru ca acest apel să încapă în transcriere. Asistentul le-a văzut pe toate.
web-search-card-view-search-details = Vezi detaliile căutării.
web-search-card-the-stored-result-could-not = rezultatul stocat nu a putut fi citit înapoi ca JSON
web-search-card-nothing-was-stored-for-this = Nimic nu a fost stocat pentru acest apel.
web-search-card-forms = Variante: { $forms }
web-search-card-kind = Tip: { $row_kind }
web-search-card-published = Publicat: { $row_published }
web-search-card-loading-search-detail-u = Se încarcă detaliile căutării…
web-search-card-could-not-load-the-search = Detaliile căutării nu au putut fi încărcate: { $e }
web-search-card-malformed-detail = Detalii malformate: { $e }
web-search-card-the-tool-returned-selected-results = Instrumentul a returnat modelului rezultatele selectate.
web-search-card-results-use-reciprocal-rank-fusion = Rezultatele folosesc fuziunea rangurilor reciproce (reciprocal rank fusion).
web-search-card-returned-nothing = nu a returnat nimic: { $degraded }
web-search-card-all-candidates-use-fusion-order = Toți candidații folosesc ordinea de fuziune.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoderul ordonează rezultatele selectate.
web-search-card-selected-results-use-fusion-order = Rezultatele selectate folosesc ordinea de fuziune.
web-search-card-search-detail = Detaliile căutării
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Caută aceasta
chat-tool-disclosure-search-every-collection = Caută în toate colecțiile
chat-tool-disclosure-hide = Ascunde
chat-tool-disclosure-expand = Extinde
chat-tool-disclosure-this-step-was-recorded-before = Acest pas a fost înregistrat înainte ca argumentele și rezultatele instrumentului să fie stocate. Este disponibil doar rezumatul de mai jos.
chat-tool-disclosure-arguments = Argumente
chat-tool-disclosure-result = Rezultat
chat-tool-disclosure-hide-raw-json = Ascunde JSON-ul brut
chat-tool-disclosure-show-raw-json = Afișează JSON-ul brut
chat-tool-disclosure-input-json = JSON de intrare
chat-tool-disclosure-output-json = JSON de ieșire
chat-transcript-ask-a-question-about-the = Pune o întrebare despre documentele din colecțiile tale.
chat-transcript-suggested-next = Sugestii pentru continuare...
chat-transcript-earlier-answer = Răspuns anterior
chat-transcript-tokens-the-conversation-carries-the = Tokenii pe care îi poartă conversația, cel mai mare context facturat pentru această rundă și cât din fereastra modelului a folosit acesta
chat-transcript-instruction-to-the-agent = Instrucțiune pentru agent
chat-transcript-the-context-stays-above-the = {" "}Contextul rămâne peste ținta de { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}Părți ale rezumatului care au eșuat: { $failed }. Înregistrarea conține doar listele.
chat-transcript-show-the-record = Afișează înregistrarea
chat-transcript-hide-reasoning = Ascunde raționamentul
chat-transcript-show-reasoning = Afișează raționamentul
chat-transcript-from-u-hide = { $count } { $count ->
        [one] document
        [few] documente
       *[other] de documente
    } din { $tool } – ascunde
chat-transcript-from-u-show = { $count } { $count ->
        [one] document
        [few] documente
       *[other] de documente
    } din { $tool } – afișează
chat-transcript-u-hide = { $summary } – ascunde
chat-transcript-u-show = { $summary } – afișează
chat-transcript-citations-of-this-conversation-give = Citările din această conversație dau eticheta { $doc_handle } mai multor documente. Răspunsul nu o leagă de niciunul dintre ele.
chat-transcript-report = Raport { $label }
chat-transcript-open-in-the-workspace = Deschide în spațiul de lucru
chat-transcript-this-version-could-not-be = Această versiune nu a putut fi citită. Urmează textul răspunsului din conversație.
chat-transcript-files = Fișiere
chat-transcript-version = { $file_name }, versiunea { $file_version }
chat-web-find-exact-text = Caută text exact
chat-web-previous-match = Potrivirea anterioară
chat-web-next-match = Potrivirea următoare
chat-web-close-preview = Închide previzualizarea
chat-web-the-captured-page-could-not = Pagina capturată nu a putut fi încărcată.
chat-web-loading = Se încarcă…
chat-workspace-pane-workspace = Spațiu de lucru
chat-workspace-pane-close-the-workspace = Închide spațiul de lucru
chat-workspace-pane-close = Închide
chat-workspace-pane-loading-the-files-u = Se încarcă fișierele…
chat-workspace-pane-the-files-could-not-be = Fișierele nu au putut fi încărcate: { $error }
chat-workspace-pane-this-conversation-has-no-files = Această conversație nu are fișiere.
chat-workspace-pane-version = versiunea { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Alege un fișier pentru a-l citi.
chat-workspace-pane-loading-the-file-u = Se încarcă fișierul…
chat-workspace-pane-the-file-could-not-be = Fișierul nu a putut fi încărcat: { $error }
chat-workspace-pane-version-2 = { $found_name }, versiunea { $found_version }
chat-board-create-collections = Colecții
chat-board-create-loading-collections-u = Se încarcă colecțiile…
chat-board-create-hoover-search-new-board = Hoover Search - Tablou nou
chat-board-create-ai-chat = Conversație AI
chat-board-create-new-investigation-board = Tablou de investigație nou
chat-board-create-a-board-runs-its-goals = Un tablou își rulează obiectivele ca o succesiune de explorări ale agentului. Fiecare explorare este o conversație care se încheie cu o constatare a tabloului. Revizuiești răspunsul fiecărui obiectiv și, cât timp tabloul rulează, poți respinge constatări și adăuga sugestii.
chat-board-create-title = Titlu
chat-board-create-goal = Obiectiv
chat-board-create-remove-this-goal = Elimină acest obiectiv
chat-board-create-remove = Elimină
chat-board-create-add-a-goal = Adaugă un obiectiv
chat-board-create-context-optional = Context (opțional)
chat-board-create-hints-one-per-line-optional = Sugestii, câte una pe rând (opțional)
chat-board-create-sources = Surse
chat-board-create-internet-tools = Instrumente de internet
chat-board-create-creating-board = Se creează tabloul...
chat-board-create-create-board = Creează tabloul
ai-chat-board-hoover-search-board = Hoover Search - Tablou
ai-chat-board-loading-the-board-u = Se încarcă tabloul…
ai-chat-board-show-the-board-overview = Afișează prezentarea generală a tabloului
ai-chat-board-zoom-out = Micșorează
ai-chat-board-zoom-in = Mărește
ai-chat-board-u-ai-chat = ← Conversație AI
ai-chat-board-settings = Setări
ai-chat-board-board-settings = Setările tabloului
ai-chat-board-internet-tools = Instrumente de internet
ai-chat-board-the-next-explores-of-the = Următoarele explorări ale tabloului pot căuta pe web și pot citi pagini web. Explorările în curs păstrează setarea cu care au început.
ai-chat-board-collections = Colecții
ai-chat-board-the-collections-are-fixed-when = Colecțiile sunt fixate la crearea tabloului.
ai-chat-board-confirm-drop = Confirmă eliminarea
ai-chat-board-drop-the-board = Elimină tabloul
ai-chat-board-close = Închide
ai-chat-board-the-board-used-its-explore = Tabloul și-a folosit limita de explorări
ai-chat-board-the-board-used-explores-the = Explorări folosite de tablou: { $explore_limit }, adică limita unui tablou. Tabloul nu mai pornește altă activitate. Poți totuși decide asupra răspunsurilor propuse.
ai-chat-board-create-a-new-board-to = Creează un tablou nou pentru a continua investigația
ai-chat-board-goal = Obiectiv
ai-chat-board-goals = Obiective
ai-chat-board-add-new-goal = Adaugă un obiectiv nou...
ai-chat-board-a-new-goal = Un obiectiv nou
ai-chat-board-add-goal = Adaugă obiectivul
ai-chat-board-a-board-has-at-most = Numărul maxim de obiective ale unui tablou este { $max_goals }. Creează un tablou nou pentru alt obiectiv.
ai-chat-board-background-context = Context de fundal
ai-chat-board-continue-with-a-correction = Continuă cu o corecție
ai-chat-board-correction-what-is-wrong-or = Corecție: ce este greșit sau lipsește. Tabloul continuă cu ea.
ai-chat-board-the-board-waits-for-your = Tabloul așteaptă revizuirea ta
ai-chat-board-the-board-used-its-budget = Tabloul și-a folosit bugetul de explorări: { $snap_max_explores }.
ai-chat-board-the-assessments-gave-no-usable = Evaluările nu au dat nicio direcție utilizabilă.
ai-chat-board-accept-or-reject-the-proposed = Acceptă sau respinge răspunsul propus pentru fiecare obiectiv de mai sus. Un răspuns respins permite tabloului să continue imediat.
ai-chat-board-no-proposed-answer-waits-for = Niciun răspuns propus nu așteaptă decizia ta.
ai-chat-board-reopen-the-board-to-continue = Redeschide tabloul pentru a continua obiectivele deschise. Tabloul își păstrează constatările și răspunsurile.
ai-chat-board-close-the-board-to-accept = Închide tabloul pentru a accepta toate răspunsurile propuse și a-l opri, sau continuă-l cu o corecție.
ai-chat-board-close-the-board = Închide tabloul
ai-chat-board-or-reopen-the-board-to = Sau redeschide tabloul pentru a continua obiectivele deschise fără o corecție.
ai-chat-board-the-board-is-complete = Tabloul este complet
ai-chat-board-a-goal-has-no-accepted = Un obiectiv nu are niciun răspuns acceptat. Redeschide tabloul pentru a-l continua. Tabloul își păstrează constatările și răspunsurile.
ai-chat-board-add-a-hint = Adaugă o sugestie
ai-chat-board-the-next-assessment-reads-every = Următoarea evaluare citește fiecare sugestie. O sugestie răspunde și unei explorări care a pus o întrebare.
ai-chat-board-add-hint = Adaugă sugestia
ai-chat-board-events = Evenimente
ai-chat-board-newest-first = Cele mai noi primele
ai-chat-board-date = Dată
ai-chat-board-actor = Actor
ai-chat-board-event = Eveniment
ai-chat-board-show-details = Afișează detaliile
ai-chat-board-open = Deschide
ai-chat-board-show-the-newest-events = Afișează cele mai noi evenimente ({ $event_rows })
ai-chat-board-show-all-events = Afișează toate evenimentele ({ $snap_events_len })
ai-chat-board-statistics = Statistici
ai-chat-board-explores = Explorări
ai-chat-board-model-steps-per-explore = Pași ai modelului per explorare
ai-chat-board-assessments = Evaluări
ai-chat-board-intents = Intenții
ai-chat-board-findings = Constatări
ai-chat-board-created = Creat
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } a respins această constatare la { $format_utc_ms_fact_rejected_ms }. Tabloul nu o mai folosește.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } a respins această constatare. Tabloul nu o mai folosește.
ai-chat-board-no-reason-was-given = Nu a fost indicat niciun motiv.
ai-chat-board-reason = Motiv: { $fact_rejected_reason }
ai-chat-board-open-questions = Întrebări deschise
ai-chat-board-explored-in = Explorat în{" "}
ai-chat-board-explore-this-question = Explorează această întrebare
ai-chat-board-your-questions = Întrebările tale
ai-chat-board-ask-about-the-background-context = Întreabă despre contextul de fundal
ai-chat-board-ask-about-this-finding = Întreabă despre această constatare
ai-chat-board-a-follow-up-question-about = O întrebare suplimentară despre acest nod
ai-chat-board-ask = Întreabă
ai-chat-board-checks-that-changed-this-finding = Verificările care au modificat această constatare
ai-chat-board-reject-this-correction = Respinge această corecție
ai-chat-board-reject-this-finding = Respinge această constatare
ai-chat-board-not-answered-the-board-was = Fără răspuns. Tabloul a fost finalizat fără un răspuns pentru acest obiectiv. O sugestie sau o redeschidere îl deschide din nou.
ai-chat-board-no-answer-yet = Încă niciun răspuns.
ai-chat-board-the-findings-of-this-answer = Constatările acestui răspuns sunt căutări care nu au găsit nimic. Acceptă-l pentru a înregistra că înregistrările nu răspund obiectivului sau respinge-l pentru a continua investigația.
ai-chat-board-open-an-assessment-to-read = {"."} Deschide o evaluare pentru a citi motivul.
ai-chat-board-from-the-findings = Din constatările{" "}
ai-chat-board-accept-answer = Acceptă răspunsul
ai-chat-board-why-the-answer-is-wrong = De ce este răspunsul greșit sau incomplet
ai-chat-board-reject-answer = Respinge răspunsul
ai-chat-board-intent = Intenție
ai-chat-board-attempts-declared = Încercări: { $intent_attempts }. Declarată { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Explorarea a întrebat
ai-chat-board-add-a-hint-in-the = Adaugă o sugestie în prezentarea generală a tabloului pentru a răspunde.
ai-chat-board-last-error = Ultima eroare
ai-chat-board-brief = Instrucțiuni
ai-chat-board-open-the-explore-chat = Deschide conversația explorării
ai-chat-board-loading-the-assessment-u = Se încarcă evaluarea…
ai-chat-board-assessment = Evaluarea { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model: { $a_model }. Rezultat: { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Verificările care au modificat-o
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Această evaluare a rulat înainte ca prompturile să fie stocate.
ai-chat-board-response = Răspuns
ai-chat-history-hoover-search-chat-history = Hoover Search - Istoricul conversațiilor
ai-chat-history-u-back = ← Înapoi
ai-chat-history-conversation-history = Istoricul conversațiilor
ai-chat-history-show-board-chats = Afișează conversațiile tablourilor
ai-chat-history-loading-u = Se încarcă…
ai-chat-history-could-not-load-history = Istoricul nu a putut fi încărcat: { $e }
ai-chat-history-no-conversations-yet = Încă nicio conversație.
ai-chat-history-board = Tablou
ai-chat-history-new-chat = Conversație nouă
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } mesaj · actualizat { $s_updated_at }
    [few] { $s_message_count } mesaje · actualizat { $s_updated_at }
    *[other] { $s_message_count } de mesaje · actualizat { $s_updated_at }
    }

ai-chat-history-delete-conversation = Șterge conversația
ai-chat-history-delete = Șterge
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Conversație AI
ai-chat-homepage-what-are-you-researching = Ce cercetezi?
ai-chat-homepage-view-all-conversations = Vezi toate conversațiile
ai-chat-homepage-starting-conversation-u = Se pornește conversația…
ai-chat-homepage-investigation-boards = Tablouri de investigație
ai-chat-homepage-new-board = Tablou nou
ai-chat-homepage-loading-boards-u = Se încarcă tablourile…
ai-chat-homepage-could-not-load-the-boards = Tablourile nu au putut fi încărcate: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nu ai niciun tablou. Un tablou rulează o investigație lungă ca o succesiune de explorări ale agentului, iar tu îi revizuiești răspunsurile.
ai-chat-homepage-updated = Actualizat { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Conversație AI
ai-chat-session-this-conversation-could-not-be = Această conversație nu a putut fi încărcată.
ai-chat-session-loading-u = Se încarcă…
ai-chat-session-u-chats = ← Conversații
ai-chat-session-history = Istoric
ai-chat-session-show-the-files-that-the = Afișează fișierele pe care asistentul le-a scris în această conversație
ai-chat-session-workspace = Spațiu de lucru
ai-chat-session-this-answer-was-interrupted-before = Acest răspuns a fost întrerupt înainte de a se termina, deoarece pagina sau serverul s-a oprit în timpul rundei. Întreabă din nou pentru a reîncerca.
ai-chat-session-dismiss = Închide
ai-chat-session-board-explore-chats-are-read = Conversațiile de explorare ale tablourilor sunt doar pentru citire.{" "}
ai-chat-session-open-the-board = Deschide tabloul
chat-locked-options-on = { $label }: activat
chat-locked-options-off = { $label }: dezactivat
chat-tool-cards-running-u = rulează…
cards-result-cards-quote-found = Citat găsit
cards-result-cards-quote-not-found = Citat negăsit
cards-result-cards-quote-not-checked = Citat neverificat
web-search-card-results = Rezultate: { $results_len }
chat-tool-disclosure-running-u = rulează…
chat-transcript-call = apel
chat-transcript-calls = apeluri
ai-chat-board-a-board-without-collections-needs = Un tablou fără colecții are nevoie de instrumente de internet.
ai-chat-board-of = { $snap_explores_used } din { $snap_max_explores }
ai-chat-board-assessment-2 = evaluarea { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } mesaj
    [few] { $s_message_count } mesaje
    *[other] { $s_message_count } de mesaje
    }

web-search-card-reranked-in = Cross-encoderul a ordonat rezultatele în { $ms } ms.
web-search-card-engine-results = { $name }: { $count } în { $ms } ms
web-search-card-score-was-rank = scor { $score } · era RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Runda așteaptă un loc liber pentru model.
chat-activity-the-turn-waits-for-a-2 = Runda așteaptă un loc liber pentru instrumente.
chat-locked-options-start-a-new-chat-to = Pornește o conversație nouă pentru a schimba această setare.
chat-locked-options-internet-tools = Instrumente de internet
chat-session-card-new-chat = Conversație nouă
chat-tool-cards-first-frame-of-the-video = Primul cadru al videoclipului
chat-tool-cards-screenshot-of = Captură de ecran a
chat-tool-cards-image = Imagine
cards-result-cards-the-agent-asked-a-question = Agentul a pus o întrebare.
chat-transcript-hide = Ascunde
chat-transcript-show = Afișează
chat-transcript-unverified-quote-the-quoted-span = Citat neverificat. Fragmentul citat este prea scurt pentru a fi verificat.
chat-transcript-unverified-quote-the-document-text = Citat neverificat. Textul documentului nu a putut fi citit.
chat-transcript-unverified-quote-this-wording-was = Citat neverificat. Această formulare nu a fost găsită în document.
chat-board-create-select-a-collection-or-turn = Selectează o colecție sau activează instrumentele de internet.
chat-board-create-select-at-least-one-collection = Selectează cel puțin o colecție.
ai-chat-board-active = Activ
ai-chat-board-paused = În pauză
ai-chat-board-waits-for-review = Așteaptă revizuirea
ai-chat-board-completed = Finalizat
ai-chat-board-dropped = Eliminat
ai-chat-board-unknown = Necunoscut
ai-chat-board-pause-the-board = Pune tabloul în pauză
ai-chat-board-resume-the-board = Reia tabloul
ai-chat-board-none = Niciunul
ai-chat-board-reopen-with-the-remaining-budget = Redeschide cu bugetul rămas
ai-chat-board-finding = Constatare
ai-chat-board-why-the-correction-is-wrong = De ce este corecția greșită
ai-chat-board-reject-correction = Respinge corecția
ai-chat-board-why-the-finding-is-wrong = De ce este constatarea greșită
ai-chat-board-reject-finding = Respinge constatarea
ai-chat-board-answer = Răspuns
ai-chat-board-proposed-answer = Răspuns propus
ai-chat-homepage-active = Activ
ai-chat-homepage-paused = În pauză
ai-chat-homepage-waits-for-review = Așteaptă revizuirea
ai-chat-homepage-completed = Finalizat
ai-chat-homepage-dropped = Eliminat
ai-chat-homepage-unknown = Necunoscut
cards-result-cards-submitted-by-board = Trimisă de tablou: constatare { $kind ->
        [sourced] cu surse
        [inferred] dedusă
        [not_found] de tip „negăsit”
       *[other] de tip necunoscut
    } din raport
cards-result-cards-finding-for-board = Constatare { $kind ->
        [sourced] cu surse
        [inferred] dedusă
        [not_found] de tip „negăsit”
       *[other] de tip necunoscut
    } pentru tablou
chat-transcript-compacting = Se comprimă contextul (tokeni): de la { $before } la ținta de { $target }.
chat-transcript-compaction-failed = Rezumarea pașilor anteriori a eșuat. Modelul a primit pașii anteriori neschimbați (tokeni: { $after }).
chat-transcript-compacted = Context comprimat: pași rezumați: { $steps }, tokeni: de la { $before } la { $after }.
ai-chat-board-reopen-with-more = Redeschide cu explorări suplimentare: { $grant }
ai-chat-board-goal-number = Obiectivul { $number }
ai-chat-board-from-assessment-on = Din evaluarea { $number } din data de { $date }.
ai-chat-board-from-assessment = Din evaluarea { $number }.
chat-board-create-goal-2 = Obiectivul { $index_1 }
ai-chat-session-lost-contact-with-the-chat = contactul cu conversația s-a pierdut: { $e }
ai-chat-session-could-not-stop-the-answer = răspunsul nu a putut fi oprit: { $e } – încă rulează
ai-chat-board-later-assessments-dropped-an-answer = Evaluări ulterioare care au eliminat un răspuns pentru acest obiectiv ({ $n }):
ai-chat-board-prompt-and-completion-tokens = tokeni de prompt: { $a_prompt_tokens }, tokeni de completare: { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = Finalizat, obiective fără răspuns: { $n }
board-graph-intent = intenție, { $state }
chat-workspace-pane-characters = Caractere: { $chars }
chat-transcript-running-tool = { $if_joined_live_end_1_tr_chat_transcript_ } de instrument în curs: { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end }
chat-transcript-running-tool-2 = { $if_turn_tool_rows_len_1_tr_chat_transcri } de instrument în curs: { $turn_tool_rows_len }
chat-transcript-answered-after-failed-attempt = Răspuns după { $retries_len ->
        [one] o încercare eșuată
        [few] { $retries_len } încercări eșuate
       *[other] { $retries_len } de încercări eșuate
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len ->
        [one] O încercare eșuată
        [few] { $retries_len } încercări eșuate
       *[other] { $retries_len } de încercări eșuate
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, versiunea { $report_version }
tool-run-summary-searched = { $n ->
        [one] a căutat un termen
        [few] a căutat { $n } termeni
       *[other] a căutat { $n } de termeni
    }
tool-run-summary-read = { $n ->
        [one] a citit un document
        [few] a citit { $n } documente
       *[other] a citit { $n } de documente
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] a căutat pe web un termen
        [few] a căutat pe web { $n } termeni
       *[other] a căutat pe web { $n } de termeni
    }
tool-run-summary-read-web = { $n ->
        [one] a citit o pagină web
        [few] a citit { $n } pagini web
       *[other] a citit { $n } de pagini web
    }
tool-run-summary-browser = { $n ->
        [one] o acțiune de browser
        [few] { $n } acțiuni de browser
       *[other] { $n } de acțiuni de browser
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] a listat entitățile unui document
        [few] a listat entitățile a { $n } documente
       *[other] a listat entitățile a { $n } de documente
    }
tool-run-summary-cited = { $n ->
        [one] a citat un document
        [few] a citat { $n } documente
       *[other] a citat { $n } de documente
    }
tool-run-summary-cited-web = { $n ->
        [one] a citat o pagină web
        [few] a citat { $n } pagini web
       *[other] a citat { $n } de pagini web
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] a citit o abilitate și textele instrumentelor
        [few] a citit { $n } abilități și textele instrumentelor
       *[other] a citit { $n } de abilități și textele instrumentelor
    }
tool-run-summary-saved = { $n ->
        [one] a salvat o notă
        [few] a salvat { $n } note
       *[other] a salvat { $n } de note
    }
tool-run-summary-todo-list = { $n ->
        [one] un apel pentru lista de sarcini
        [few] { $n } apeluri pentru lista de sarcini
       *[other] { $n } de apeluri pentru lista de sarcini
    }
tool-run-summary-to-the-agent = { $n ->
        [one] o instrucțiune pentru agent
        [few] { $n } instrucțiuni pentru agent
       *[other] { $n } de instrucțiuni pentru agent
    }
tool-run-summary-other = { $n ->
        [one] un alt apel
        [few] { $n } alte apeluri
       *[other] { $n } de alte apeluri
    }
tool-run-summary-failed = eșuate: { $failures }
tool-run-summary-took = a durat { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } mesaj
    [few] { $session_message_count } mesaje
    *[other] { $session_message_count } de mesaje
    }

chat-tool-disclosure-item = { $count ->
        [one] un element
        [few] { $count } elemente
       *[other] { $count } de elemente
    }
chat-tool-disclosure-field = { $count ->
        [one] un câmp
        [few] { $count } câmpuri
       *[other] { $count } de câmpuri
    }
chat-tool-disclosure-searched-collections = a căutat în colecții{ $filters }
chat-tool-disclosure-searched-collections-2 = a căutat în colecții · { $query }{ $filters }
chat-tool-disclosure-cited-documents = a citat documente: { $n }
chat-tool-disclosure-read-document = a citit documentul · { $path }
chat-tool-disclosure-searched-the-web = a căutat pe web · { $q }
chat-tool-disclosure-opened-page = a deschis pagina · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = a apelat { $other }
chat-tool-disclosure-called-2 = a apelat { $other } · { $short }
cards-browser-card-opened = a deschis { $url }
cards-browser-card-could-not-open = nu a putut deschide { $url }
cards-browser-card-clicked = a făcut clic pe { $element }
cards-browser-card-could-not-click = nu a putut face clic pe { $element }
cards-browser-card-typed-into = a scris în { $element }
cards-browser-card-could-not-type-into = nu a putut scrie în { $element }
cards-browser-card-typed = a scris „{ $text }”
cards-browser-card-could-not-type = nu a putut scrie „{ $text }”
cards-browser-card-pressed = a apăsat { $key }
cards-browser-card-could-not-press = nu a putut apăsa { $key }
cards-browser-card-chose-an-option-in = a ales o opțiune în { $element }
cards-browser-card-could-not-choose-an-option = nu a putut alege o opțiune în { $element }
cards-browser-card-hovered = a trecut cu mouse-ul peste { $element }
cards-browser-card-could-not-hover = nu a putut trece cu mouse-ul peste { $element }
cards-browser-card-failed = { $bare } – eșuat
cards-entities-card-listed-entities-document = a listat entitățile · { $count ->
        [one] un document
        [few] { $count } documente
       *[other] { $count } de documente
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · partea { $part } din { $name } #{ $seq }
cards-result-cards-documents = {" "}· documente: { $value }
cards-result-cards-forms = { $tool_name } · variante: { $forms }
cards-result-cards-in = {" "}în { $collections }
cards-result-cards-page = {" "}· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · documente: { $citations_len } · citate negăsite: { $missing }
cards-result-cards-version-unchanged = { $tool_name } · versiunea { $version } · neschimbată
cards-result-cards-version = { $tool_name } · versiunea { $version }
web-search-card-results-in-after-deduplication = Rezultate primite: { $json_u64_doc_total_before_dedupe }, după deduplicare: { $json_u64_doc_total_after_dedupe }

board-status-on = Activat

board-status-off = Dezactivat

chat-transcript-generic-tool = instrumentul
