# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Agent radi...
chat-composer-ask-the-bot = Pitajte agenta...
chat-composer-internet-tools = Internetski alati
chat-composer-agent-language-title = Agent odgovara na jeziku: { $language }. Jezik promijenite u postavkama, u novoj kartici.
chat-composer-try-again-in-s = Pokušajte ponovno za { $secs } s
chat-composer-stop-the-answer-the-partial = Zaustavi odgovor (djelomični odgovor ne sprema se u razgovor)
chat-composer-starting-the-conversation-u = Pokretanje razgovora…
chat-composer-send = Pošalji
chat-conversation-find-search-in-conversation = Pretraži u razgovoru
chat-conversation-find-previous-match = Prethodno podudaranje
chat-conversation-find-next-match = Sljedeće podudaranje
chat-conversation-find-investigation-board = Istražna ploča
doc-ref-card-not-openable = Nije moguće otvoriti: { $reason }.
doc-ref-card-the-search-term-was = Traženi pojam bio je{" "}
doc-ref-card-open = Otvori
doc-ref-card-not-openable-2 = Nije moguće otvoriti
chat-markdown-text-show-the-cited-source = Prikaži citirani izvor
chat-markdown-text-no-citation-of-this-conversation = Nijedan citat u ovom razgovoru nije dao ovu oznaku, pa iza nje ne stoji nijedan dokument.
chat-markdown-text-citations-of-this-conversation-gave = Citati u ovom razgovoru dodijelili su ovu oznaku većem broju dokumenata, pa se ne povezuje ni s jednim od njih.
cards-browser-card-open-the-archived-page = Otvori arhiviranu stranicu
cards-browser-card-the-page-itself-was-not = Sama stranica nije arhivirana (status: { $artifact_status }). Snimka zaslona iznad je ono što je sačuvano.
cards-browser-card-click-the-screenshot-to-open = Kliknite snimku zaslona da biste otvorili arhiviranu stranicu.
cards-browser-card-show-less = Prikaži manje
cards-browser-card-show-all = Prikaži sve
cards-browser-card-archived-page = Arhivirana stranica
cards-browser-card-download = Preuzmi
cards-browser-card-archived-copy-of = Arhivirana kopija: { $artifact_url }
cards-browser-card-this-page-was-not-archived = Ova stranica nije arhivirana (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } s karticom
cards-entities-card-the-entity-list-was-cut = Popis entiteta je skraćen.
cards-entities-card-open-the-card-for-this = Otvori karticu za ovu vrijednost ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Nema kartice: ovaj razgovor nikada nije imenovao skup podataka iz kojeg te vrijednosti potječu, a preglednik se adresira skupom podataka.
cards-entities-card-more-all-of-them-in = Još: { $rest }, sve u oknu entiteta dokumenta.{" "}
cards-entities-card-names-organisations-and-places-above = Imena, organizacije i mjesta iznad rezultat su čitanja slobodnog teksta od strane modela. Nijedno pravilo ih nije potvrdilo, pa nema što objasniti i ne otvaraju ništa.
cards-entities-card-nothing-extracted-from-this-document = Iz ovog dokumenta ništa nije izdvojeno.
chat-tool-cards-hide = Sakrij
chat-tool-cards-expand = Proširi
chat-tool-cards-hide-raw-json = Sakrij neobrađeni JSON
chat-tool-cards-show-raw-json = Prikaži neobrađeni JSON
cards-result-cards-search-this = Pretraži ovo
cards-result-cards-search-every-collection = Pretraži sve zbirke
cards-result-cards-form = Varijanta { $index }: { $form }
cards-result-cards-show-full-text = Prikaži cijeli tekst
cards-result-cards-quote = Navod: { $quote }
cards-result-cards-reason = Razlog: { $why }
cards-result-cards-open-question = Otvoreno pitanje: { $question }
cards-result-cards-the-explore-gave-this-answer = Istraživanje je dalo ovaj odgovor svojoj ploči kao nalaz, vrsta: { $kind ->
        [sourced] potkrijepljen izvorom
        [inferred] zaključen
        [not_found] nije pronađen
       *[other] nepoznata vrsta
    }.
cards-result-cards-it-left-no-open-question = Nije ostavilo otvoreno pitanje.
cards-result-cards-open-questions-for-the-board = Otvorena pitanja za ploču:
cards-result-cards-arguments = Argumenti
cards-result-cards-list-after-the-call = Popis nakon poziva: { $snapshot_goal }
cards-result-cards-replaces = {" "}· zamjenjuje { $replaces_id }
cards-result-cards-the-list-at-this-version = Popis u ovoj verziji nije pohranjen.
web-search-card-these-sources-returned-nothing-so = Ovi izvori nisu vratili ništa, pa rezultati dolaze iz manjeg broja izvora od predviđenog
web-search-card-u-degraded = ⚠ Oslabljeno: { $degraded_len }
web-search-card-form = Varijanta { $index }: { $form }
web-search-card-no-results-from = Nema rezultata iz: { $degraded_text }
web-search-card-no-results-every-source-answered = Nema rezultata. Svi izvori su odgovorili i nijedan nije imao ništa za ovaj upit.
web-search-card-the-lowest-ranked-results-were = Najslabije rangirani rezultati izostavljeni su da bi ovaj poziv stao u transkript. Agent je vidio sve njih.
web-search-card-view-search-details = Prikaži detalje pretrage.
web-search-card-the-stored-result-could-not = pohranjeni rezultat nije bilo moguće ponovno pročitati kao JSON
web-search-card-nothing-was-stored-for-this = Za ovaj poziv ništa nije pohranjeno.
web-search-card-forms = Varijante: { $forms }
web-search-card-kind = Vrsta: { $row_kind }
web-search-card-published = Objavljeno: { $row_published }
web-search-card-loading-search-detail-u = Učitavanje detalja pretrage…
web-search-card-could-not-load-the-search = Nije moguće učitati detalje pretrage: { $e }
web-search-card-malformed-detail = Neispravni detalji: { $e }
web-search-card-the-tool-returned-selected-results = Alat je modelu vratio odabrane rezultate.
web-search-card-results-use-reciprocal-rank-fusion = Rezultati koriste recipročno spajanje rangova (RRF).
web-search-card-returned-nothing = nije vratilo ništa: { $degraded }
web-search-card-all-candidates-use-fusion-order = Svi kandidati koriste redoslijed spajanja.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoder rangira odabrane rezultate.
web-search-card-selected-results-use-fusion-order = Odabrani rezultati koriste redoslijed spajanja.
web-search-card-search-detail = Detalji pretrage
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Pretraži ovo
chat-tool-disclosure-search-every-collection = Pretraži sve zbirke
chat-tool-disclosure-hide = Sakrij
chat-tool-disclosure-expand = Proširi
chat-tool-disclosure-this-step-was-recorded-before = Ovaj korak zabilježen je prije nego što su se počeli pohranjivati argumenti i rezultati alata. Dostupan je samo sažetak ispod.
chat-tool-disclosure-arguments = Argumenti
chat-tool-disclosure-result = Rezultat
chat-tool-disclosure-hide-raw-json = Sakrij neobrađeni JSON
chat-tool-disclosure-show-raw-json = Prikaži neobrađeni JSON
chat-tool-disclosure-input-json = Ulazni JSON
chat-tool-disclosure-output-json = Izlazni JSON
chat-transcript-ask-a-question-about-the = Postavite pitanje o dokumentima u svojim zbirkama.
chat-transcript-suggested-next = Predloženi sljedeći koraci...
chat-transcript-earlier-answer = Raniji odgovor
chat-transcript-tokens-the-conversation-carries-the = Tokeni koje razgovor nosi, najveći pojedinačni kontekst obračunat za ovaj krug i koliko je to iskoristilo prozora modela
chat-transcript-instruction-to-the-agent = Uputa agentu
chat-transcript-the-context-stays-above-the = {" "}Kontekst ostaje iznad cilja od { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}Dijelovi sažetka koji nisu uspjeli: { $failed }. Zapis sadrži samo popise.
chat-transcript-show-the-record = Prikaži zapis
chat-transcript-hide-reasoning = Sakrij zaključivanje
chat-transcript-show-reasoning = Prikaži zaključivanje
chat-transcript-from-u-hide = { $count } { $count ->
        [one] dokument
        [few] dokumenta
       *[other] dokumenata
    } iz { $tool } — sakrij
chat-transcript-from-u-show = { $count } { $count ->
        [one] dokument
        [few] dokumenta
       *[other] dokumenata
    } iz { $tool } — prikaži
chat-transcript-u-hide = { $summary } — sakrij
chat-transcript-u-show = { $summary } — prikaži
chat-transcript-citations-of-this-conversation-give = Citati u ovom razgovoru dodjeljuju oznaku { $doc_handle } većem broju dokumenata. Odgovor je ne povezuje ni s jednim od njih.
chat-transcript-report = Izvješće { $label }
chat-transcript-open-in-the-workspace = Otvori u radnom prostoru
chat-transcript-this-version-could-not-be = Ovu verziju nije moguće pročitati. Slijedi tekst odgovora u razgovoru.
chat-transcript-files = Datoteke
chat-transcript-version = { $file_name }, verzija { $file_version }
chat-web-find-exact-text = Pronađi točan tekst
chat-web-previous-match = Prethodno podudaranje
chat-web-next-match = Sljedeće podudaranje
chat-web-close-preview = Zatvori pregled
chat-web-the-captured-page-could-not = Snimljenu stranicu nije moguće učitati.
chat-web-loading = Učitavanje…
chat-workspace-pane-workspace = Radni prostor
chat-workspace-pane-close-the-workspace = Zatvori radni prostor
chat-workspace-pane-close = Zatvori
chat-workspace-pane-loading-the-files-u = Učitavanje datoteka…
chat-workspace-pane-the-files-could-not-be = Datoteke nije moguće učitati: { $error }
chat-workspace-pane-this-conversation-has-no-files = Ovaj razgovor nema datoteka.
chat-workspace-pane-version = verzija { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Odaberite datoteku da biste je pročitali.
chat-workspace-pane-loading-the-file-u = Učitavanje datoteke…
chat-workspace-pane-the-file-could-not-be = Datoteku nije moguće učitati: { $error }
chat-workspace-pane-version-2 = { $found_name }, verzija { $found_version }
chat-board-create-collections = Zbirke
chat-board-create-loading-collections-u = Učitavanje zbirki…
chat-board-create-hoover-search-new-board = Hoover pretraga - Nova ploča
chat-board-create-ai-chat = AI razgovor
chat-board-create-new-investigation-board = Nova istražna ploča
chat-board-create-a-board-runs-its-goals = Ploča izvodi svoje ciljeve kao niz istraživanja agenta. Svako istraživanje je razgovor koji završava jednim nalazom ploče. Vi pregledavate odgovor na svaki cilj, a tijekom rada možete odbiti nalaze i dodati naputke.
chat-board-create-title = Naslov
chat-board-create-goal = Cilj
chat-board-create-remove-this-goal = Ukloni ovaj cilj
chat-board-create-remove = Ukloni
chat-board-create-add-a-goal = Dodaj cilj
chat-board-create-context-optional = Kontekst (neobavezno)
chat-board-create-hints-one-per-line-optional = Naputci, po jedan u retku (neobavezno)
chat-board-create-sources = Izvori
chat-board-create-internet-tools = Internetski alati
chat-board-create-creating-board = Stvaranje ploče...
chat-board-create-create-board = Stvori ploču
ai-chat-board-hoover-search-board = Hoover pretraga - Ploča
ai-chat-board-loading-the-board-u = Učitavanje ploče…
ai-chat-board-show-the-board-overview = Prikaži pregled ploče
ai-chat-board-zoom-out = Smanji
ai-chat-board-zoom-in = Povećaj
ai-chat-board-u-ai-chat = ← AI razgovor
ai-chat-board-settings = Postavke
ai-chat-board-board-settings = Postavke ploče
ai-chat-board-internet-tools = Internetski alati
ai-chat-board-the-next-explores-of-the = Sljedeća istraživanja ploče mogu pretraživati web i čitati web stranice. Istraživanja u tijeku zadržavaju postavku s kojom su započela.
ai-chat-board-collections = Zbirke
ai-chat-board-the-collections-are-fixed-when = Zbirke se određuju pri stvaranju ploče.
ai-chat-board-confirm-drop = Potvrdi odbacivanje
ai-chat-board-drop-the-board = Odbaci ploču
ai-chat-board-close = Zatvori
ai-chat-board-the-board-used-its-explore = Ploča je iskoristila ograničenje istraživanja
ai-chat-board-the-board-used-explores-the = Ploča je iskoristila istraživanja: { $explore_limit }, što je ograničenje jedne ploče. Ne pokreće daljnji rad. I dalje možete odlučiti o predloženim odgovorima.
ai-chat-board-create-a-new-board-to = Stvorite novu ploču da biste nastavili istragu
ai-chat-board-goal = Cilj
ai-chat-board-goals = Ciljevi
ai-chat-board-add-new-goal = Dodaj novi cilj...
ai-chat-board-a-new-goal = Novi cilj
ai-chat-board-add-goal = Dodaj cilj
ai-chat-board-a-board-has-at-most = Ploča ima najviše { $max_goals } ciljeva. Stvorite novu ploču za još jedan cilj.
ai-chat-board-background-context = Kontekst pozadine
ai-chat-board-continue-with-a-correction = Nastavi s ispravkom
ai-chat-board-correction-what-is-wrong-or = Ispravak: što je pogrešno ili nedostaje. Ploča nastavlja s njim.
ai-chat-board-the-board-waits-for-your = Ploča čeka vaš pregled
ai-chat-board-the-board-used-its-budget = Ploča je iskoristila svoj proračun od { $snap_max_explores } istraživanja.
ai-chat-board-the-assessments-gave-no-usable = Procjene nisu dale upotrebljiv smjer.
ai-chat-board-accept-or-reject-the-proposed = Prihvatite ili odbijte predloženi odgovor za svaki cilj iznad. Odbijeni odgovor omogućuje ploči da odmah nastavi.
ai-chat-board-no-proposed-answer-waits-for = Nijedan predloženi odgovor ne čeka vašu odluku.
ai-chat-board-reopen-the-board-to-continue = Ponovno otvorite ploču da biste nastavili otvorene ciljeve. Ona zadržava svoje nalaze i odgovore.
ai-chat-board-close-the-board-to-accept = Zatvorite ploču da biste prihvatili svaki predloženi odgovor i zaustavili je, ili je nastavite s ispravkom.
ai-chat-board-close-the-board = Zatvori ploču
ai-chat-board-or-reopen-the-board-to = Ili ponovno otvorite ploču da biste nastavili otvorene ciljeve bez ispravka.
ai-chat-board-the-board-is-complete = Ploča je potpuna
ai-chat-board-a-goal-has-no-accepted = Jedan cilj nema prihvaćen odgovor. Ponovno otvorite ploču da biste ga nastavili. Ploča zadržava svoje nalaze i odgovore.
ai-chat-board-add-a-hint = Dodaj naputak
ai-chat-board-the-next-assessment-reads-every = Sljedeća procjena čita svaki naputak. Naputak također odgovara na istraživanje koje je postavilo pitanje.
ai-chat-board-add-hint = Dodaj naputak
ai-chat-board-events = Događaji
ai-chat-board-newest-first = Najnovije prvo
ai-chat-board-date = Datum
ai-chat-board-actor = Izvršitelj
ai-chat-board-event = Događaj
ai-chat-board-show-details = Prikaži detalje
ai-chat-board-open = Otvori
ai-chat-board-show-the-newest-events = Prikaži najnovije događaje ({ $event_rows })
ai-chat-board-show-all-events = Prikaži sve događaje ({ $snap_events_len })
ai-chat-board-statistics = Statistika
ai-chat-board-explores = Istraživanja
ai-chat-board-model-steps-per-explore = Koraka modela po istraživanju
ai-chat-board-assessments = Procjene
ai-chat-board-intents = Namjere
ai-chat-board-findings = Nalazi
ai-chat-board-created = Stvoreno
ai-chat-board-rejected-this-finding-on-the = Odbijeno: { $rejected_by }, { $format_utc_ms_fact_rejected_ms }. Ploča više ne koristi ovaj nalaz.
ai-chat-board-rejected-this-finding-the-board = Odbijeno: { $rejected_by }. Ploča više ne koristi ovaj nalaz.
ai-chat-board-no-reason-was-given = Razlog nije naveden.
ai-chat-board-reason = Razlog: { $fact_rejected_reason }
ai-chat-board-open-questions = Otvorena pitanja
ai-chat-board-explored-in = Istraženo u{" "}
ai-chat-board-explore-this-question = Istraži ovo pitanje
ai-chat-board-your-questions = Vaša pitanja
ai-chat-board-ask-about-the-background-context = Pitaj o kontekstu pozadine
ai-chat-board-ask-about-this-finding = Pitaj o ovom nalazu
ai-chat-board-a-follow-up-question-about = Dodatno pitanje o ovom čvoru
ai-chat-board-ask = Pitaj
ai-chat-board-checks-that-changed-this-finding = Provjere koje su promijenile ovaj nalaz
ai-chat-board-reject-this-correction = Odbij ovaj ispravak
ai-chat-board-reject-this-finding = Odbij ovaj nalaz
ai-chat-board-not-answered-the-board-was = Bez odgovora. Ploča je dovršena bez odgovora na ovaj cilj. Naputak ili ponovno otvaranje ponovno ga otvara.
ai-chat-board-no-answer-yet = Još nema odgovora.
ai-chat-board-the-findings-of-this-answer = Nalazi ovog odgovora su pretrage koje ništa nisu pronašle. Prihvatite ga da biste zabilježili da zapisi ne odgovaraju na cilj ili ga odbijte da biste nastavili istragu.
ai-chat-board-open-an-assessment-to-read = {"."} Otvorite procjenu da biste pročitali zašto.
ai-chat-board-from-the-findings = Iz nalaza{" "}
ai-chat-board-accept-answer = Prihvati odgovor
ai-chat-board-why-the-answer-is-wrong = Zašto je odgovor pogrešan ili nepotpun
ai-chat-board-reject-answer = Odbij odgovor
ai-chat-board-intent = Namjera
ai-chat-board-attempts-declared = Pokušaji: { $intent_attempts }. Objavljeno { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Istraživanje je pitalo
ai-chat-board-add-a-hint-in-the = Dodajte naputak u pregledu ploče da biste odgovorili.
ai-chat-board-last-error = Zadnja pogreška
ai-chat-board-brief = Zadatak
ai-chat-board-open-the-explore-chat = Otvori razgovor istraživanja
ai-chat-board-loading-the-assessment-u = Učitavanje procjene…
ai-chat-board-assessment = Procjena { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Ishod { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Provjere koje su ga promijenile
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Ova procjena izvedena je prije nego što su se prompti pohranjivali.
ai-chat-board-response = Odgovor
ai-chat-history-hoover-search-chat-history = Hoover pretraga - Povijest razgovora
ai-chat-history-u-back = ← Natrag
ai-chat-history-conversation-history = Povijest razgovora
ai-chat-history-show-board-chats = Prikaži razgovore ploča
ai-chat-history-loading-u = Učitavanje…
ai-chat-history-could-not-load-history = Nije moguće učitati povijest: { $e }
ai-chat-history-no-conversations-yet = Još nema razgovora.
ai-chat-history-board = Ploča
ai-chat-history-new-chat = Novi razgovor
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } poruka · ažurirano { $s_updated_at }
    [few] { $s_message_count } poruke · ažurirano { $s_updated_at }
    *[other] { $s_message_count } poruka · ažurirano { $s_updated_at }
    }

ai-chat-history-delete-conversation = Izbriši razgovor
ai-chat-history-delete = Izbriši
ai-chat-homepage-hoover-search-ai-chat = Hoover pretraga - AI razgovor
ai-chat-homepage-what-are-you-researching = Što istražujete?
ai-chat-homepage-view-all-conversations = Prikaži sve razgovore
ai-chat-homepage-starting-conversation-u = Pokretanje razgovora…
ai-chat-homepage-investigation-boards = Istražne ploče
ai-chat-homepage-new-board = Nova ploča
ai-chat-homepage-loading-boards-u = Učitavanje ploča…
ai-chat-homepage-could-not-load-the-boards = Nije moguće učitati ploče: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nemate nijednu ploču. Ploča izvodi dugu istragu kao niz istraživanja agenta, a vi pregledavate njezine odgovore.
ai-chat-homepage-updated = Ažurirano { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover pretraga - AI razgovor
ai-chat-session-this-conversation-could-not-be = Ovaj razgovor nije moguće učitati.
ai-chat-session-loading-u = Učitavanje…
ai-chat-session-u-chats = ← Razgovori
ai-chat-session-history = Povijest
ai-chat-session-show-the-files-that-the = Prikaži datoteke koje je agent napisao u ovom razgovoru
ai-chat-session-workspace = Radni prostor
ai-chat-session-this-answer-was-interrupted-before = Ovaj odgovor prekinut je prije završetka jer su se stranica ili poslužitelj zaustavili usred kruga. Pitajte ponovno da biste pokušali ponovno.
ai-chat-session-dismiss = Zatvori
ai-chat-session-board-explore-chats-are-read = Razgovori istraživanja ploče samo su za čitanje.{" "}
ai-chat-session-open-the-board = Otvori ploču
chat-locked-options-on = { $label }: uključeno
chat-locked-options-off = { $label }: isključeno
chat-tool-cards-running-u = izvodi se…
cards-result-cards-quote-found = Navod pronađen
cards-result-cards-quote-not-found = Navod nije pronađen
cards-result-cards-quote-not-checked = Navod nije provjeren
web-search-card-results = Rezultata: { $results_len }
chat-tool-disclosure-running-u = izvodi se…
chat-transcript-call = poziv
chat-transcript-calls = poziva
ai-chat-board-a-board-without-collections-needs = Ploča bez zbirki treba internetske alate.
ai-chat-board-of = { $snap_explores_used } od { $snap_max_explores }
ai-chat-board-assessment-2 = procjena { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } poruka
    [few] { $s_message_count } poruke
    *[other] { $s_message_count } poruka
    }

web-search-card-reranked-in = Cross-encoder je rangirao rezultate za { $ms } ms.
web-search-card-engine-results = { $name }: { $count } za { $ms } ms
web-search-card-score-was-rank = ocjena { $score } · bio je RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Krug čeka slobodno mjesto za model.
chat-activity-the-turn-waits-for-a-2 = Krug čeka slobodno mjesto za alat.
chat-locked-options-start-a-new-chat-to = Pokrenite novi razgovor da biste promijenili ovu postavku.
chat-locked-options-internet-tools = Internetski alati
chat-session-card-new-chat = Novi razgovor
chat-tool-cards-first-frame-of-the-video = Prvi kadar videa
chat-tool-cards-screenshot-of = Snimka zaslona:
chat-tool-cards-image = Slika
cards-result-cards-the-agent-asked-a-question = Agent je postavio pitanje.
chat-transcript-hide = Sakrij
chat-transcript-show = Prikaži
chat-transcript-unverified-quote-the-quoted-span = Neprovjeren navod. Citirani dio prekratak je za provjeru.
chat-transcript-unverified-quote-the-document-text = Neprovjeren navod. Tekst dokumenta nije bilo moguće pročitati.
chat-transcript-unverified-quote-this-wording-was = Neprovjeren navod. Ova formulacija nije pronađena u dokumentu.
chat-board-create-select-a-collection-or-turn = Odaberite zbirku ili uključite internetske alate.
chat-board-create-select-at-least-one-collection = Odaberite najmanje jednu zbirku.
ai-chat-board-active = Aktivna
ai-chat-board-paused = Pauzirana
ai-chat-board-waits-for-review = Čeka pregled
ai-chat-board-completed = Završena
ai-chat-board-dropped = Odbačena
ai-chat-board-unknown = Nepoznato
ai-chat-board-pause-the-board = Pauziraj ploču
ai-chat-board-resume-the-board = Nastavi ploču
ai-chat-board-none = Nema
ai-chat-board-reopen-with-the-remaining-budget = Ponovno otvori s preostalim proračunom
ai-chat-board-finding = Nalaz
ai-chat-board-why-the-correction-is-wrong = Zašto je ispravak pogrešan
ai-chat-board-reject-correction = Odbij ispravak
ai-chat-board-why-the-finding-is-wrong = Zašto je nalaz pogrešan
ai-chat-board-reject-finding = Odbij nalaz
ai-chat-board-answer = Odgovor
ai-chat-board-proposed-answer = Predloženi odgovor
ai-chat-homepage-active = Aktivna
ai-chat-homepage-paused = Pauzirana
ai-chat-homepage-waits-for-review = Čeka pregled
ai-chat-homepage-completed = Završena
ai-chat-homepage-dropped = Odbačena
ai-chat-homepage-unknown = Nepoznato
cards-result-cards-submitted-by-board = Ploča je podnijela nalaz iz izvješća, vrsta: { $kind ->
        [sourced] potkrijepljen izvorom
        [inferred] zaključen
        [not_found] nije pronađen
       *[other] nepoznata vrsta
    }
cards-result-cards-finding-for-board = Nalaz za ploču, vrsta: { $kind ->
        [sourced] potkrijepljen izvorom
        [inferred] zaključen
        [not_found] nije pronađen
       *[other] nepoznata vrsta
    }
chat-transcript-compacting = Sažimanje konteksta: { $before } tokena do cilja od { $target }.
chat-transcript-compaction-failed = Sažetak ranijih koraka nije uspio. Model je primio ranije korake nepromijenjene, tokena: { $after }.
chat-transcript-compacted = Kontekst je sažet: sažeto koraka: { $steps }, tokena od { $before } do { $after }.
ai-chat-board-reopen-with-more = Ponovno otvori uz dodatna istraživanja: { $grant }
ai-chat-board-goal-number = Cilj { $number }
ai-chat-board-from-assessment-on = Iz procjene { $number } dana { $date }.
ai-chat-board-from-assessment = Iz procjene { $number }.
chat-board-create-goal-2 = Cilj { $index_1 }
ai-chat-session-lost-contact-with-the-chat = izgubljena veza s razgovorom: { $e }
ai-chat-session-could-not-stop-the-answer = nije moguće zaustaviti odgovor: { $e } — još je u tijeku
ai-chat-board-later-assessments-dropped-an-answer = Kasnije procjene koje su odbacile odgovor za ovaj cilj ({ $n }):
ai-chat-board-prompt-and-completion-tokens = tokena prompta: { $a_prompt_tokens }, tokena odgovora: { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = Završeno, ciljeva bez odgovora: { $n }
board-graph-intent = namjera, { $state }
chat-workspace-pane-characters = znakova: { $chars }
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } { $if_joined_live_end_1_tr_chat_transcript_ } alata u tijeku
chat-transcript-running-tool-2 = { $turn_tool_rows_len } { $if_turn_tool_rows_len_1_tr_chat_transcri } alata u tijeku
chat-transcript-answered-after-failed-attempt = Odgovoreno nakon { $retries_len } { $retries_len ->
        [one] neuspjelog pokušaja
        [few] neuspjela pokušaja
       *[other] neuspjelih pokušaja
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len } { $retries_len ->
        [one] neuspjeli pokušaj
        [few] neuspjela pokušaja
       *[other] neuspjelih pokušaja
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, verzija { $report_version }
tool-run-summary-searched = pretraženo: { $n ->
        [one] { $n } pojam
        [few] { $n } pojma
       *[other] { $n } pojmova
    }
tool-run-summary-read = pročitano: { $n ->
        [one] { $n } dokument
        [few] { $n } dokumenta
       *[other] { $n } dokumenata
    }
tool-run-summary-searched-the-web-for = pretraženo na webu: { $n ->
        [one] { $n } pojam
        [few] { $n } pojma
       *[other] { $n } pojmova
    }
tool-run-summary-read-web = pročitano: { $n ->
        [one] { $n } web stranica
        [few] { $n } web stranice
       *[other] { $n } web stranica
    }
tool-run-summary-browser = { $n ->
        [one] { $n } radnja preglednika
        [few] { $n } radnje preglednika
       *[other] { $n } radnji preglednika
    }
tool-run-summary-listed-the-entities-of = popisani entiteti za: { $n ->
        [one] { $n } dokument
        [few] { $n } dokumenta
       *[other] { $n } dokumenata
    }
tool-run-summary-cited = citirano: { $n ->
        [one] { $n } dokument
        [few] { $n } dokumenta
       *[other] { $n } dokumenata
    }
tool-run-summary-cited-web = citirano: { $n ->
        [one] { $n } web stranica
        [few] { $n } web stranice
       *[other] { $n } web stranica
    }
tool-run-summary-read-and-tool-texts = pročitano: { $n ->
        [one] { $n } vještina i tekst alata
        [few] { $n } vještine i tekstovi alata
       *[other] { $n } vještina i tekstova alata
    }
tool-run-summary-saved = spremljeno: { $n ->
        [one] { $n } bilješka
        [few] { $n } bilješke
       *[other] { $n } bilješki
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } poziv plana
        [few] { $n } poziva plana
       *[other] { $n } poziva plana
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } uputa agentu
        [few] { $n } upute agentu
       *[other] { $n } uputa agentu
    }
tool-run-summary-other = { $n ->
        [one] { $n } drugi poziv
        [few] { $n } druga poziva
       *[other] { $n } drugih poziva
    }
tool-run-summary-failed = neuspjelo: { $failures }
tool-run-summary-took = trajalo: { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } poruka
    [few] { $session_message_count } poruke
    *[other] { $session_message_count } poruka
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } stavka
        [few] { $count } stavke
       *[other] { $count } stavki
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } polje
        [few] { $count } polja
       *[other] { $count } polja
    }
chat-tool-disclosure-searched-collections = pretražene zbirke{ $filters }
chat-tool-disclosure-searched-collections-2 = pretražene zbirke · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citirani dokumenti: { $n }
chat-tool-disclosure-read-document = pročitan dokument · { $path }
chat-tool-disclosure-searched-the-web = pretražen web · { $q }
chat-tool-disclosure-opened-page = otvorena stranica · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = pozvan alat { $other }
chat-tool-disclosure-called-2 = pozvan alat { $other } · { $short }
cards-browser-card-opened = otvoreno: { $url }
cards-browser-card-could-not-open = nije moguće otvoriti: { $url }
cards-browser-card-clicked = kliknuto: { $element }
cards-browser-card-could-not-click = nije moguće kliknuti: { $element }
cards-browser-card-typed-into = upisano u: { $element }
cards-browser-card-could-not-type-into = nije moguće upisati u: { $element }
cards-browser-card-typed = upisano: „{ $text }”
cards-browser-card-could-not-type = nije moguće upisati: „{ $text }”
cards-browser-card-pressed = pritisnuto: { $key }
cards-browser-card-could-not-press = nije moguće pritisnuti: { $key }
cards-browser-card-chose-an-option-in = odabrana opcija u: { $element }
cards-browser-card-could-not-choose-an-option = nije moguće odabrati opciju u: { $element }
cards-browser-card-hovered = pokazivač preko: { $element }
cards-browser-card-could-not-hover = nije moguće postaviti pokazivač preko: { $element }
cards-browser-card-failed = { $bare } — neuspjelo
cards-entities-card-listed-entities-document = popisani entiteti · { $count } { $count ->
        [one] dokument
        [few] dokumenta
       *[other] dokumenata
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · dio { $part } od { $name } #{ $seq }
cards-result-cards-documents = {" "}· dokumenata: { $value }
cards-result-cards-forms = { $tool_name } · varijante: { $forms }
cards-result-cards-in = {" "}u { $collections }
cards-result-cards-page = {" "}· stranica { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · dokumenata: { $citations_len } · navoda nije pronađeno: { $missing }
cards-result-cards-version-unchanged = { $tool_name } · verzija { $version } · nepromijenjeno
cards-result-cards-version = { $tool_name } · verzija { $version }
web-search-card-results-in-after-deduplication = Rezultata na ulazu: { $json_u64_doc_total_before_dedupe }, nakon uklanjanja duplikata: { $json_u64_doc_total_after_dedupe }

board-status-on = Uključeno

board-status-off = Isključeno

chat-transcript-generic-tool = alat
