# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Botul lucrează...
chat-composer-ask-the-bot = Întreabă botul...
chat-composer-internet-tools = Instrumente internet
chat-composer-agent-language-title = Agentul răspunde în { $language }. Schimbă limba în setări, într-o filă nouă.
chat-composer-try-again-in-s = Încearcă din nou în { $secs } s
chat-composer-stop-the-answer-the-partial = Opri răspunsul (parțialul nu se salvează în conversație)
chat-composer-starting-the-conversation-u = Se începe conversația…
chat-composer-send = Trimite
chat-conversation-find-search-in-conversation = Caută în conversație
chat-conversation-find-previous-match = Potrivire anterioară
chat-conversation-find-next-match = Potrivire următoare
chat-conversation-find-investigation-board = Tablou de investigație
doc-ref-card-not-openable = Nu este deschibil: { $reason }.
doc-ref-card-the-search-term-was = Termenul de căutare a fost
doc-ref-card-open = Deschide
doc-ref-card-not-openable-2 = Nu este deschibil
chat-markdown-text-show-the-cited-source = Arată sursa citată
chat-markdown-text-no-citation-of-this-conversation = Nicio citație a acestei conversații nu a dat acest handle, așa că niciun document nu stă în spatele ei.
chat-markdown-text-citations-of-this-conversation-gave = Citațiile acestei conversații au dat acest handle mai multor documente, așa că nu le leagă pe niciuna.
cards-browser-card-open-the-archived-page = Deschide pagina arhivată
cards-browser-card-the-page-itself-was-not = Pagina însăși nu a fost arhivată (status: { $artifact_status }). Captura de mai sus este ceea ce s-a păstrat.
cards-browser-card-click-the-screenshot-to-open = Click pe captura de ecran pentru a deschide pagina arhivată.
cards-browser-card-show-less = Arată mai puțin
cards-browser-card-show-all = Arată tot
cards-browser-card-archived-page = Pagina arhivată
cards-browser-card-download = Descarcă
cards-browser-card-archived-copy-of = Copie arhivată a { $artifact_url }
cards-browser-card-this-page-was-not-archived = Această pagină nu a fost arhivată (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } cu o carte
cards-entities-card-the-entity-list-was-cut = Lista de entități a fost tăiată.
cards-entities-card-open-the-card-for-this = Deschide cardul pentru această valoare ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Fără card: această conversație nu a numit niciodată setul de date ca sursă a acestor valori, iar vizualizatorul este adresat în funcție de setul de date.
cards-entities-card-more-all-of-them-in = { $rest } încă, toate în panoul entităților documentului.{ " " }
cards-entities-card-names-organisations-and-places-above = Numele, organizațiile și locurile de mai sus sunt interpretarea modelului asupra textului. Niciun regulă nu le-a validat, așa că nu există nimic de explicat și nu deschid nimic.
cards-entities-card-nothing-extracted-from-this-document = Niciun extras din acest document.
chat-tool-cards-hide = Ascunde
chat-tool-cards-expand = Extinde
chat-tool-cards-hide-raw-json = Ascunde JSON brut
chat-tool-cards-show-raw-json = Arată JSON brut
cards-result-cards-search-this = Caută acest
cards-result-cards-search-every-collection = Caută în toate colecțiile
cards-result-cards-form = Formular { $index }: { $form }
cards-result-cards-show-full-text = Arată textul complet
cards-result-cards-quote = Citație: { $quote }
cards-result-cards-reason = Motiv: { $why }
cards-result-cards-open-question = Întrebare deschisă: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Explorarea a dat acest răspuns board-ului său ca { $kind ->
        [sourced] o descoperire sursată
        [inferred] o descoperire inferată
        [not_found] o descoperire negăsită
       *[other] o descoperire de tip necunoscut
    }.
cards-result-cards-it-left-no-open-question = Nu a lăsat nicio întrebare deschisă.
cards-result-cards-open-questions-for-the-board = Întrebări deschise pentru board:
cards-result-cards-arguments = Argumente
cards-result-cards-list-after-the-call = Lista după apel: { $snapshot_goal }
cards-result-cards-replaces = { " " }· înlocuiește { $replaces_id }
cards-result-cards-the-list-at-this-version = Lista la această versiune nu este stocată.
web-search-card-these-sources-returned-nothing-so = Aceste surse nu au returnat nimic, așa că rezultatele provin de la mai puține decât se intenționa
web-search-card-u-degraded = ⚠ { $degraded_len } degradat
web-search-card-form = Formular { $index }: { $form }
web-search-card-no-results-from = Fără rezultate de la: { $degraded_text }
web-search-card-no-results-every-source-answered = Fără rezultate. Fiecare sursă a răspuns și nicio una nu a avut ceva pentru această interogare.
web-search-card-the-lowest-ranked-results-were = Rezultatele clasate pe ultimele poziții au fost eliminate pentru ca acest apel să se încadreze în transcriere. Asistentul le-a văzut pe toate.
web-search-card-view-search-details = Vezi detaliile căutării.
web-search-card-the-stored-result-could-not = rezultatul stocat nu a fost citit înapoi ca JSON
web-search-card-nothing-was-stored-for-this = Nu a fost stocat nimic pentru această interogare.
web-search-card-forms = Formulare: { $forms }
web-search-card-kind = Tip: { $row_kind }
web-search-card-published = Publicat: { $row_published }
web-search-card-loading-search-detail-u = Se încarcă detaliile căutării…
web-search-card-could-not-load-the-search = Nu s-au putut încărca detaliile căutării: { $e }
web-search-card-malformed-detail = Detaliu neconform: { $e }
web-search-card-the-tool-returned-selected-results = Instrumentul a returnat rezultate selectate către model.
web-search-card-results-use-reciprocal-rank-fusion = Rezultatele folosesc fuziunea clasamentului reciproc.
web-search-card-returned-nothing = nu a returnat nimic: { $degraded }
web-search-card-all-candidates-use-fusion-order = Toți candidații folosesc ordinea de fuziune.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoder-ul clasează rezultatele selectate.
web-search-card-selected-results-use-fusion-order = Rezultatele selectate folosesc ordinea de fuziune.
web-search-card-search-detail = Detalii căutare
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Caută aici
chat-tool-disclosure-search-every-collection = Caută în toate colecțiile
chat-tool-disclosure-hide = Ascunde
chat-tool-disclosure-expand = Extinde
chat-tool-disclosure-this-step-was-recorded-before = Acest pas a fost înregistrat înainte ca argumentele și rezultatele instrumentului să fie stocate. Doar sumarului de mai jos îi este disponibil.
chat-tool-disclosure-arguments = Argumente
chat-tool-disclosure-result = Rezultat
chat-tool-disclosure-hide-raw-json = Ascunde JSON brut
chat-tool-disclosure-show-raw-json = Arată JSON brut
chat-tool-disclosure-input-json = JSON de intrare
chat-tool-disclosure-output-json = JSON de ieșire
chat-transcript-ask-a-question-about-the = Pune o întrebare despre documentele din colecțiile tale.
chat-transcript-suggested-next = Următorul sugerat...
chat-transcript-earlier-answer = Răspuns anterior
chat-transcript-tokens-the-conversation-carries-the = Tokeni pe care îi poartă conversația, cel mai mare context individual facturat în această rundă și cât din fereastra modelului a fost utilizat
chat-transcript-instruction-to-the-agent = Instrucțiuni pentru agent
chat-transcript-the-context-stays-above-the = Contextul rămâne peste ținta de { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } părți de sinteză au eșuat. Înregistrarea păstrează doar listele.
chat-transcript-show-the-record = Afișează înregistrarea
chat-transcript-hide-reasoning = Ascunde raționamentul
chat-transcript-show-reasoning = Afișează raționamentul
chat-transcript-from-u-hide = { $count } { $noun } din { $tool } — ascunde
chat-transcript-from-u-show = { $count } { $noun } din { $tool } — afișează
chat-transcript-u-hide = { $summary } — ascunde
chat-transcript-u-show = { $summary } — afișează
chat-transcript-citations-of-this-conversation-give = Citațiile acestei conversații atribuie { $doc_handle } mai multor documente. Răspunsul nu îl leagă de niciunul.
chat-transcript-report = Semnalează { $label }
chat-transcript-open-in-the-workspace = Deschide în spațiul de lucru
chat-transcript-this-version-could-not-be = Această versiune nu a putut fi citită. Textul conversației din răspuns urmează.
chat-transcript-files = Fișiere
chat-transcript-version = { $file_name }, versiunea { $file_version }
chat-web-find-exact-text = Caută textul exact
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
chat-workspace-pane-choose-a-file-to-read = Alege un fișiere pentru a-l citi.
chat-workspace-pane-loading-the-file-u = Se încarcă fișierul…
chat-workspace-pane-the-file-could-not-be = Fișierul nu a putut fi încărcat: { $error }
chat-workspace-pane-version-2 = { $found_name }, versiunea { $found_version }
chat-board-create-collections = Colecții
chat-board-create-loading-collections-u = Se încarcă colecțiile…
chat-board-create-hoover-search-new-board = Căutare Hoover - Board nou
chat-board-create-ai-chat = Conversație AI
chat-board-create-new-investigation-board = Board de investigație nou
chat-board-create-a-board-runs-its-goals = Un board își realizează obiectivele ca o succesiune de explorări ale agentului. Fiecare explorare este o conversație care se încheie cu o descoperire a board-ului. Recenzia răspunsului fiecărui obiectiv, iar poți respinge descoperirile și adăuga indicii în timp ce rulează.
chat-board-create-title = Titlu
chat-board-create-goal = Obiectiv
chat-board-create-remove-this-goal = Elimină acest obiectiv
chat-board-create-remove = Elimină
chat-board-create-add-a-goal = Adaugă un obiectiv
chat-board-create-context-optional = Context (opțional)
chat-board-create-hints-one-per-line-optional = Indicii, câte unul pe linie (opțional)
chat-board-create-sources = Surse
chat-board-create-internet-tools = Instrumente Internet
chat-board-create-creating-board = Se creează board-ul...
chat-board-create-create-board = Creează board
ai-chat-board-hoover-search-board = Căutare Hoover - Board
ai-chat-board-loading-the-board-u = Se încarcă board-ul…
ai-chat-board-show-the-board-overview = Arată prezentarea generală a board-ului
ai-chat-board-zoom-out = Micșorează
ai-chat-board-zoom-in = Mărește
ai-chat-board-u-ai-chat = ← Conversație AI
ai-chat-board-settings = Setări
ai-chat-board-board-settings = Setări board
ai-chat-board-internet-tools = Instrumente Internet
ai-chat-board-the-next-explores-of-the = Următoarele explorări ale taboului pot căuta pe web și pot citi pagini web. Explorările în curs păstrează setarea cu care au început.
ai-chat-board-collections = Colecții
ai-chat-board-the-collections-are-fixed-when = Colecțiile sunt fixate la crearea taboului.
ai-chat-board-confirm-drop = Confirmă eliminarea
ai-chat-board-drop-the-board = Elimină boardul
ai-chat-board-close = Închide
ai-chat-board-the-board-used-its-explore = Boardul și-a folosit limita de explorare
ai-chat-board-the-board-used-explores-the = Boardul și-a folosit { $explore_limit } explorări, limita unui board. Nu mai începe alte lucrări. Poți decide încă răspunsurile propuse.
ai-chat-board-create-a-new-board-to = Creează un board nou pentru a continua investigația
ai-chat-board-goal = Scop
ai-chat-board-goals = Scopuri
ai-chat-board-add-new-goal = Adaugă scop nou...
ai-chat-board-a-new-goal = Un scop nou
ai-chat-board-add-goal = Adaugă scop
ai-chat-board-a-board-has-at-most = Un board are cel mult { $max_goals } scopuri. Creează un board nou pentru un alt scop.
ai-chat-board-background-context = Context de fundal
ai-chat-board-continue-with-a-correction = Continuă cu o corecție
ai-chat-board-correction-what-is-wrong-or = Corecție: ce este greșit sau lipsă. Boardul continuă cu ea.
ai-chat-board-the-board-waits-for-your = Boardul așteaptă revizuirea ta
ai-chat-board-the-board-used-its-budget = Boardul și-a folosit bugetul de { $snap_max_explores } explorări.
ai-chat-board-the-assessments-gave-no-usable = Evaluările nu au dat nicio direcție utilizabilă.
ai-chat-board-accept-or-reject-the-proposed = Acceptă sau respinge răspunsul propus al fiecărui scop de mai sus. Un răspuns respins permite boardului să continue imediat.
ai-chat-board-no-proposed-answer-waits-for = Niciun răspuns propus nu așteaptă decizia ta.
ai-chat-board-reopen-the-board-to-continue = Redeschide taboul de investigație pentru a continua obiectivele deschise. Păstrează descoperirile și răspunsurile.
ai-chat-board-close-the-board-to-accept = Închide boardul pentru a accepta fiecare răspuns propus și a-l opri, sau continuă-l cu o corecție.
ai-chat-board-close-the-board = Închide boardul
ai-chat-board-or-reopen-the-board-to = Sau deschide din nou boardul pentru a continua scopurile deschise fără o corecție.
ai-chat-board-the-board-is-complete = Boardul este complet
ai-chat-board-a-goal-has-no-accepted = Un scop nu are un răspuns acceptat. Deschide din nou boardul pentru a-l continua. Boardul păstrează descoperirile și răspunsurile.
ai-chat-board-add-a-hint = Adaugă un indiciu
ai-chat-board-the-next-assessment-reads-every = Evaluarea următoare citește fiecare indiciu. Un indiciu răspunde și unei explorări care a pus o întrebare.
ai-chat-board-add-hint = Adaugă indiciu
ai-chat-board-events = Evenimente
ai-chat-board-newest-first = Cele mai noi prime
ai-chat-board-date = Dată
ai-chat-board-actor = Autor
ai-chat-board-event = Eveniment
ai-chat-board-show-details = Afișează detalii
ai-chat-board-open = Deschide
ai-chat-board-show-the-newest-events = Afișează cele mai noi { $event_rows } evenimente
ai-chat-board-show-all-events = Afișează toate { $snap_events_len } evenimentele
ai-chat-board-statistics = Statistici
ai-chat-board-explores = Exploări
ai-chat-board-model-steps-per-explore = Pași ai modelului per explorare
ai-chat-board-assessments = Evaluări
ai-chat-board-intents = Intenții
ai-chat-board-findings = Descoperiri
ai-chat-board-created = Creat
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } a respins această descoperire pe { $format_utc_ms_fact_rejected_ms }. Tabloul de investigație nu mai utilizează această descoperire.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } a respins această descoperire. Tabloul de investigație nu mai utilizează această descoperire.
ai-chat-board-no-reason-was-given = Nu s-a dat niciun motiv.
ai-chat-board-reason = Motiv: { $fact_rejected_reason }
ai-chat-board-open-questions = Întrebări deschise
ai-chat-board-explored-in = Explorat în
ai-chat-board-explore-this-question = Explorează această întrebare
ai-chat-board-your-questions = Întrebările tale
ai-chat-board-ask-about-the-background-context = Întreabă despre contextul de fundal
ai-chat-board-ask-about-this-finding = Întreabă despre această descoperire
ai-chat-board-a-follow-up-question-about = O întrebare de continuare despre acest nod
ai-chat-board-ask = Întreabă
ai-chat-board-checks-that-changed-this-finding = Verificări care au modificat această descoperire
ai-chat-board-reject-this-correction = Respinge această corecție
ai-chat-board-reject-this-finding = Respinge această descoperire
ai-chat-board-not-answered-the-board-was = Răspuns nul. Tabloul de investigație a fost finalizat fără un răspuns pentru acest obiectiv. Un indiciu sau o redeschidere îl redeschid.
ai-chat-board-no-answer-yet = Răspuns încă nul.
ai-chat-board-the-findings-of-this-answer = Descoperirile acestui răspuns sunt căutări care nu au găsit nimic. Acceptă-l pentru a înregistra că înregistrările nu răspund obiectivului sau respinge-l pentru a continua investigația.
ai-chat-board-open-an-assessment-to-read = { "." } Deschide o evaluare pentru a citi de ce.
ai-chat-board-from-the-findings = Din descoperiri{ " " }
ai-chat-board-accept-answer = Acceptă răspunsul
ai-chat-board-why-the-answer-is-wrong = De ce răspunsul este greșit sau incomplet
ai-chat-board-reject-answer = Respinge răspunsul
ai-chat-board-intent = Intent
ai-chat-board-attempts-declared = Încercări: { $intent_attempts }. Declarat { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Explorearea a solicitat
ai-chat-board-add-a-hint-in-the = Adaugă un indiciu în tabloul de investigație pentru a răspunde.
ai-chat-board-last-error = Ultima eroare
ai-chat-board-brief = Sinteza
ai-chat-board-open-the-explore-chat = Deschide conversația de explorare
ai-chat-board-loading-the-assessment-u = Se încarcă evaluarea…
ai-chat-board-assessment = Evaluare { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Rezultat { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Verificări care au modificat-o
ai-chat-board-prompt = Solicitare
ai-chat-board-this-assessment-ran-before-the = Această evaluare a rulat înainte ca solicitările să fie stocate.
ai-chat-board-response = Răspuns
ai-chat-history-hoover-search-chat-history = Hoover Search - Istoric conversații
ai-chat-history-u-back = ← Înapoi
ai-chat-history-conversation-history = Istoric conversații
ai-chat-history-show-board-chats = Afișează conversațiile din tablou
ai-chat-history-loading-u = Se încarcă…
ai-chat-history-could-not-load-history = Nu s-a putut încărca istoricul: { $e }
ai-chat-history-no-conversations-yet = Nu există încă conversații.
ai-chat-history-board = Tablou de investigație
ai-chat-history-new-chat = Conversație nouă
ai-chat-history-messages-updated = { $s_message_count } mesaje · actualizate { $s_updated_at }
ai-chat-history-delete-conversation = Șterge conversația
ai-chat-history-delete = Șterge
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Conversație AI
ai-chat-homepage-what-are-you-researching = Ce investighezi?
ai-chat-homepage-view-all-conversations = Vezi toate conversațiile
ai-chat-homepage-starting-conversation-u = Se începe conversația…
ai-chat-homepage-investigation-boards = Tablouri de investigație
ai-chat-homepage-new-board = Tablou nou
ai-chat-homepage-loading-boards-u = Se încarcă tablourile…
ai-chat-homepage-could-not-load-the-boards = Nu s-a putut încărcarea tablourilor: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nu ai niciun tablou. Un tablou rulează o investigație lungă sub forma unei secvențe de explorări ale agentului, iar tu evaluezi răspunsurile sale.
ai-chat-homepage-updated = Actualizat { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Conversație AI
ai-chat-session-this-conversation-could-not-be = Conversația aceasta nu s-a putut încărcă.
ai-chat-session-loading-u = Se încarcă…
ai-chat-session-u-chats = ← Conversații
ai-chat-session-history = Istoric
ai-chat-session-show-the-files-that-the = Afișează fișierele pe care asistentul le-a scris în această conversație
ai-chat-session-workspace = Spațiu de lucru
ai-chat-session-this-answer-was-interrupted-before = Răspunsul acesta a fost întrerupt înainte de a se finaliza, pentru că pagina sau serverul s-au oprit pe parcursul rundei. Solicită din nou pentru a reîncerca.
ai-chat-session-dismiss = Înlătură
ai-chat-session-board-explore-chats-are-read = Conversațiile de explorare a tabloului sunt doar citire.{ " " }
ai-chat-session-open-the-board = Deschide tablou
chat-locked-options-on = { $label }: activat
chat-locked-options-off = { $label }: dezactivat
chat-tool-cards-running-u = rulează…
cards-result-cards-quote-found = Citație găsită
cards-result-cards-quote-not-found = Citație negăsită
cards-result-cards-quote-not-checked = Citație neverificată
web-search-card-results = { $results_len } rezultate
chat-tool-disclosure-running-u = rulează…
chat-transcript-call = apel
chat-transcript-calls = apeluri
ai-chat-board-a-board-without-collections-needs = Un tablou de investigație fără colecții necesită instrumente de pe internet.
ai-chat-board-of = { $snap_explores_used } din { $snap_max_explores }
ai-chat-board-assessment-2 = evaluare { $number }
ai-chat-history-messages = { $s_message_count } mesaje
web-search-card-reranked-in = Modelul cross-encoder a reordonat rezultatele în { $ms } ms.
web-search-card-engine-results = { $name }: { $count } în { $ms } ms
web-search-card-score-was-rank = scor { $score } · era pe poziția RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Tura așteaptă un slot liber pe model.
chat-activity-the-turn-waits-for-a-2 = Tura așteaptă un slot liber pe instrument.
chat-locked-options-start-a-new-chat-to = Începe o conversație nouă pentru a schimba această setare.
chat-locked-options-internet-tools = Instrumente de pe internet
chat-session-card-new-chat = Conversație nouă
chat-tool-cards-first-frame-of-the-video = Prima cadru al videoclipului
chat-tool-cards-screenshot-of = Captură de ecran a
chat-tool-cards-image = Imagine
cards-result-cards-the-agent-asked-a-question = Agentul a pus o întrebare.
chat-transcript-hide = Ascunde
chat-transcript-show = Arată
chat-transcript-unverified-quote-the-quoted-span = Citație neverificată. Fragmentul citat este prea scurt pentru a fi verificat.
chat-transcript-unverified-quote-the-document-text = Citație neverificată. Textul documentului nu a putut fi citit.
chat-transcript-unverified-quote-this-wording-was = Citație neverificată. Această formulare nu a fost găsită în document.
chat-board-create-select-a-collection-or-turn = Selectează o colecție sau activează instrumentele de pe internet.
chat-board-create-select-at-least-one-collection = Selectați măcar o colecție.
ai-chat-board-active = Activ
ai-chat-board-paused = Suspendat
ai-chat-board-waits-for-review = În așteptare pentru revizuire
ai-chat-board-completed = Finalizat
ai-chat-board-dropped = Renunțat
ai-chat-board-unknown = Necunoscut
ai-chat-board-pause-the-board = Suspendați taboul de investigație
ai-chat-board-resume-the-board = Reiați taboul de investigație
ai-chat-board-none = Niciuna
ai-chat-board-reopen-with-the-remaining-budget = Redeschideți cu bugetul rămas
ai-chat-board-finding = Descoperire
ai-chat-board-why-the-correction-is-wrong = De ce corecția este greșită
ai-chat-board-reject-correction = Respingeți corecția
ai-chat-board-why-the-finding-is-wrong = De ce descoperirea este greșită
ai-chat-board-reject-finding = Respingeți descoperirea
ai-chat-board-answer = Răspuns
ai-chat-board-proposed-answer = Răspuns propus
ai-chat-homepage-active = Activ
ai-chat-homepage-paused = Suspendat
ai-chat-homepage-waits-for-review = În așteptare pentru revizuire
ai-chat-homepage-completed = Finalizat
ai-chat-homepage-dropped = Renunțat
ai-chat-homepage-unknown = Necunoscut
cards-result-cards-submitted-by-board =
    Încărcat de taboul de investigație: { $kind ->
        [sourced] o sursă
        [inferred] o inferență
        [not_found] o descoperire fără sursă
       *[other] un tip necunoscut
    } descoperire din raport
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] O sursă
        [inferred] O inferență
        [not_found] O descoperire fără sursă
       *[other] Un tip necunoscut
    } descoperire pentru taboul de investigație
chat-transcript-compacting = Comprimarea contextului: { $before } tokeni către o țintă de { $target } tokeni.
chat-transcript-compaction-failed = Sinteza pașilor anteriori a eșuat. Modelul a primit pașii anteriori nemodificați, { $after } tokeni.
chat-transcript-compacted = Context comprimat: { $steps } pași sintetizați, { $before } tokeni către { $after }.
ai-chat-board-reopen-with-more = Redeschideți cu { $grant } explorări în plus
ai-chat-board-goal-number = Obiectiv { $number }
ai-chat-board-from-assessment-on = Din evaluare { $number } pe { $date }.
ai-chat-board-from-assessment = Din evaluare { $number }.
chat-board-create-goal-2 = Obiectiv { $index_1 }
ai-chat-session-lost-contact-with-the-chat = a pierdut contactul cu conversația: { $e }
ai-chat-session-could-not-stop-the-answer = nu a putut opri răspunsul: { $e } — este încă în curs de execuție
ai-chat-board-later-assessments-dropped-an-answer = { $n } evaluări ulterioare au renunțat la un răspuns pentru acest obiectiv:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokeni de solicitare și { $a_completion_tokens } tokeni de completare
ai-chat-homepage-completed-goals-not-answered = Complete, { $n } obiective fără răspuns
board-graph-intent = intenție, { $state }
chat-workspace-pane-characters = { $chars } caractere
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } instrument în curs de execuție { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } instrument în curs de execuție { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Răspuns după { $retries_len } încercare eșuată{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } încercare eșuată{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, versiunea { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] căutat { $n } termen
       *[other] căutat { $n } termeni
    }
tool-run-summary-read =
    { $n ->
        [one] citit { $n } document
       *[other] citit { $n } documente
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] căutat pe web { $n } termen
       *[other] căutat pe web { $n } termeni
    }
tool-run-summary-read-web =
    { $n ->
        [one] citit { $n } pagină web
       *[other] citit { $n } pagini web
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } acțiune în navigator
       *[other] { $n } acțiuni în navigator
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listate entitățile { $n } document
       *[other] listate entitățile { $n } documente
    }
tool-run-summary-cited =
    { $n ->
        [one] citat { $n } document
       *[other] citat { $n } documente
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citat { $n } pagină web
       *[other] citat { $n } pagini web
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] citit { $n } text de competență și instrument
       *[other] citit { $n } texte de competență și instrument
    }
tool-run-summary-saved =
    { $n ->
        [one] salvat { $n } notă
       *[other] salvat { $n } note
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } apel la lista de sarcini
       *[other] { $n } apeluri la lista de sarcini
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instrucțiune către agent
       *[other] { $n } instrucțiuni către agent
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } apel altul
       *[other] { $n } apeluri altul
    }
tool-run-summary-failed = { $failures } eșuate
tool-run-summary-took = a folosit { $duration_text_ms }
chat-session-card-messages = { $session_message_count } mesaje
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } element
       *[other] { $count } elemente
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } câmp
       *[other] { $count } câmpuri
    }
chat-tool-disclosure-searched-collections = colecții căutate{ $filters }
chat-tool-disclosure-searched-collections-2 = colecții căutate · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citate { $n } documente
chat-tool-disclosure-read-document = document citit · { $path }
chat-tool-disclosure-searched-the-web = web căutat · { $q }
chat-tool-disclosure-opened-page = pagină deschisă · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = apelat { $other }
chat-tool-disclosure-called-2 = apelat { $other } · { $short }
cards-browser-card-opened = deschis { $url }
cards-browser-card-could-not-open = nu s-a putut deschide { $url }
cards-browser-card-clicked = apăsat { $element }
cards-browser-card-could-not-click = nu s-a putut apăsa { $element }
cards-browser-card-typed-into = tastat în { $element }
cards-browser-card-could-not-type-into = nu s-a putut tastat în { $element }
cards-browser-card-typed = tastat „{ $text }”
cards-browser-card-could-not-type = nu s-a putut tastat „{ $text }”
cards-browser-card-pressed = apăsare { $key }
cards-browser-card-could-not-press = nu s-a putut apăsa { $key }
cards-browser-card-chose-an-option-in = opțiune aleasă în { $element }
cards-browser-card-could-not-choose-an-option = nu s-a putut alege o opțiune în { $element }
cards-browser-card-hovered = trecere cu mouse-ul peste { $element }
cards-browser-card-could-not-hover = nu s-a putut trece cu mouse-ul peste { $element }
cards-browser-card-failed = { $bare } — eșuat
cards-entities-card-listed-entities-document = entitate listată · { $count } document{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · parte { $part } din { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } documente
cards-result-cards-forms = { $tool_name } · { $forms } formulare
cards-result-cards-in = { " " }în { $collections }
cards-result-cards-page = { " " }· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documente · { $missing } citări indisponibile
cards-result-cards-version-unchanged = { $tool_name } · versiunea { $version } · nemodificat
cards-result-cards-version = { $tool_name } · versiunea { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } rezultate, { $json_u64_doc_total_after_dedupe } după deduplicare
