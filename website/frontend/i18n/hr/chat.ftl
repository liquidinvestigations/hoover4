# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Bot radi...
chat-composer-ask-the-bot = Postavi pitanje botu...
chat-composer-internet-tools = Alati interneta
chat-composer-agent-language-title = Agent odgovara na jeziku { $language }. Promijeni jezik u postavama, u novoj kartici.
chat-composer-try-again-in-s = Pokušaj ponovo za { $secs } s
chat-composer-stop-the-answer-the-partial = Zaustavi odgovor (djelomični odgovor nije spremljen u razgovor)
chat-composer-starting-the-conversation-u = Pokretanje razgovora…
chat-composer-send = Pošlji
chat-conversation-find-search-in-conversation = Pretraži u razgovoru
chat-conversation-find-previous-match = Prethodno poklapanje
chat-conversation-find-next-match = Sljedeće poklapanje
chat-conversation-find-investigation-board = Tabla istrage
doc-ref-card-not-openable = Nije otvarivo: { $reason }.
doc-ref-card-the-search-term-was = Izraz za pretragu je{ " " }
doc-ref-card-open = Otvori
doc-ref-card-not-openable-2 = Nije otvarivo
chat-markdown-text-show-the-cited-source = Prikaži citirani izvor
chat-markdown-text-no-citation-of-this-conversation = Nijedan citat ovog razgovora nije dao ovaj naziv, pa se iza njega ne nalazi nijedni dokument.
chat-markdown-text-citations-of-this-conversation-gave = Citati ovog razgovora dali su ovaj naziv više od jednog dokumenta, pa se ne povezuje s nijednim od njih.
cards-browser-card-open-the-archived-page = Otvori arhiviranu stranicu
cards-browser-card-the-page-itself-was-not = Sama stranica nije arhivirana (status: { $artifact_status }). Slika iznad ono je što je sačuvano.
cards-browser-card-click-the-screenshot-to-open = Klikni na sliku za otvaranje arhivirane stranice.
cards-browser-card-show-less = Prikaži manje
cards-browser-card-show-all = Prikaži sve
cards-browser-card-archived-page = Arhivirana stranica
cards-browser-card-download = Preuzmi
cards-browser-card-archived-copy-of = Arhivirana kopija stranice { $artifact_url }
cards-browser-card-this-page-was-not-archived = Ova stranica nije arhivirana (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } s karticom
cards-entities-card-the-entity-list-was-cut = Popis entiteta je odsječen.
cards-entities-card-open-the-card-for-this = Otvorite karticu za ovu vrijednost ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Nema kartice: ovaj razgovor nikad nije naveo iz kojeg je podatka ova vrijednost, a prikazivatelj je adresiran po podatku.
cards-entities-card-more-all-of-them-in = { $rest } više, sve u panelu entiteta dokumenta.{ " " }
cards-entities-card-names-organisations-and-places-above = Imena, organizacije i mjesta iznad model je pročitao iz teksta. Nijedno pravilo ih nije validiralo, pa nema što objašnjavati i ništa ne otvaraju.
cards-entities-card-nothing-extracted-from-this-document = Iz ovog dokumenta nije izvađeno ništa.
chat-tool-cards-hide = Sakrij
chat-tool-cards-expand = Proširi
chat-tool-cards-hide-raw-json = Sakrij sirovi JSON
chat-tool-cards-show-raw-json = Prikaži sirovi JSON
cards-result-cards-search-this = Pretraži ovo
cards-result-cards-search-every-collection = Pretraži svaku kolekciju
cards-result-cards-form = Oblik { $index }: { $form }
cards-result-cards-show-full-text = Prikaži cijeli tekst
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Razlog: { $why }
cards-result-cards-open-question = Otvoreno pitanje: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Istraživanje je dalo ovaj odgovor svojoj tabli kao { $kind ->
        [sourced] izvorom utvrđen
        [inferred] zaključen
        [not_found] pronađen
       *[other] nepoznat
    } nalaz.
cards-result-cards-it-left-no-open-question = Nije ostavilo otvoreno pitanje.
cards-result-cards-open-questions-for-the-board = Otvorena pitanja za tablu:
cards-result-cards-arguments = Argumenti
cards-result-cards-list-after-the-call = Popis nakon poziva: { $snapshot_goal }
cards-result-cards-replaces = { " " }· zamjenjuje { $replaces_id }
cards-result-cards-the-list-at-this-version = Popis se ovoj verziji ne pohranjuje.
web-search-card-these-sources-returned-nothing-so = Ovi izvori nisu ništa vratili, pa su rezultati manji od zamišljenih
web-search-card-u-degraded = ⚠ { $degraded_len } degradirano
web-search-card-form = Oblik { $index }: { $form }
web-search-card-no-results-from = Rezultata nema od: { $degraded_text }
web-search-card-no-results-every-source-answered = Rezultata nema. Svaki je izvor odgovorio, ali nijedan nije imao ništa za ovaj upit.
web-search-card-the-lowest-ranked-results-were = Rezultati najnižeg ranga odbaceni su kako bi ovaj poziv stao u transkript. Pomoćnik ih je sve vidio.
web-search-card-view-search-details = Prikazi detalje pretrace.
web-search-card-the-stored-result-could-not = Spremljeni rezultat nije bilo moguće pročitati kao JSON
web-search-card-nothing-was-stored-for-this = Za ovaj poziv nije ništa spremljeno.
web-search-card-forms = Obrazi: { $forms }
web-search-card-kind = Vrsta: { $row_kind }
web-search-card-published = Objavljeno: { $row_published }
web-search-card-loading-search-detail-u = Učitavanje detalja pretrace…
web-search-card-could-not-load-the-search = Detalja pretrace nije bilo moguće učitati: { $e }
web-search-card-malformed-detail = Neispravan detalj: { $e }
web-search-card-the-tool-returned-selected-results = Alat je modelu vratio odabrane rezultate.
web-search-card-results-use-reciprocal-rank-fusion = Rezultati koriste fuziju po reciprovnem rangiranju.
web-search-card-returned-nothing = nije vratio ništa: { $degraded }
web-search-card-all-candidates-use-fusion-order = Svi kandidati koriste redoslijed fuzije.
web-search-card-the-cross-encoder-ranks-selected = Kros-enkoder rangira odabrane rezultate.
web-search-card-selected-results-use-fusion-order = Odabrani rezultati koriste redoslijed fuzije.
web-search-card-search-detail = Detalj pretrace
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Pretraži ovo
chat-tool-disclosure-search-every-collection = Pretraži sve kolekcije
chat-tool-disclosure-hide = Sakrij
chat-tool-disclosure-expand = Proširi
chat-tool-disclosure-this-step-was-recorded-before = Ovaj korak je zabilježen prije nego što su spremljeni argumenti alata i rezultati. Dostupan je samo sažetak ispod.
chat-tool-disclosure-arguments = Argumenti
chat-tool-disclosure-result = Rezultat
chat-tool-disclosure-hide-raw-json = Sakrij sirovi JSON
chat-tool-disclosure-show-raw-json = Prikaži sirovi JSON
chat-tool-disclosure-input-json = Ulazni JSON
chat-tool-disclosure-output-json = Izlazni JSON
chat-transcript-ask-a-question-about-the = Postavite pitanje o dokumentima u svojim kolekcijama.
chat-transcript-suggested-next = Predloženi sljedeći...
chat-transcript-earlier-answer = Raniji odgovor
chat-transcript-tokens-the-conversation-carries-the = Tokeni koje razgovor nosi, najveći pojedinačni kontekst naplaćen u ovom potezu i koliko je modelov prozor bio iskorišten
chat-transcript-instruction-to-the-agent = Uputa za agenta
chat-transcript-the-context-stays-above-the = Okvir ostaje iznad cilja od { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } dijelova sažetka nije uspjelo. Zapis sadrži samo popise.
chat-transcript-show-the-record = Prikaži zapis
chat-transcript-hide-reasoning = Sakrij razlog
chat-transcript-show-reasoning = Prikaži razlog
chat-transcript-from-u-hide = { $count } { $noun } iz alata { $tool } — sakrij
chat-transcript-from-u-show = { $count } { $noun } iz alata { $tool } — prikaži
chat-transcript-u-hide = { $summary } — sakrij
chat-transcript-u-show = { $summary } — prikaži
chat-transcript-citations-of-this-conversation-give = Citati ovog razgovora dodjeljuju { $doc_handle } više od jednog dokumenta. Odgovor ga ne povezuje ni s jednim.
chat-transcript-report = Prijavi { $label }
chat-transcript-open-in-the-workspace = Otvori u radnom prostoru
chat-transcript-this-version-could-not-be = Ovaj se izvor nije mogao pročitati. Slijedi chat tekst odgovora.
chat-transcript-files = Datoteke
chat-transcript-version = { $file_name }, izvor { $file_version }
chat-web-find-exact-text = Pronađi točan tekst
chat-web-previous-match = Prethodno poklapanje
chat-web-next-match = Sljedeće poklapanje
chat-web-close-preview = Zatvori pregled
chat-web-the-captured-page-could-not = Zahvaćena stranica se nije mogla učitati.
chat-web-loading = Učitavanje…
chat-workspace-pane-workspace = Radni prostor
chat-workspace-pane-close-the-workspace = Zatvori radni prostor
chat-workspace-pane-close = Zatvori
chat-workspace-pane-loading-the-files-u = Učitavanje datoteka…
chat-workspace-pane-the-files-could-not-be = Datoteke se nisu mogle učitati: { $error }
chat-workspace-pane-this-conversation-has-no-files = Ovaz razgovor nema datoteke.
chat-workspace-pane-version = izvor { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Odaberite datoteku za čitanje.
chat-workspace-pane-loading-the-file-u = Učitavanje datoteke…
chat-workspace-pane-the-file-could-not-be = Datoteku nije bilo moguće učitati: { $error }
chat-workspace-pane-version-2 = { $found_name }, verzija { $found_version }
chat-board-create-collections = Kolekcije
chat-board-create-loading-collections-u = Učitavanje kolekcija…
chat-board-create-hoover-search-new-board = Hoover Pretraga - Nova tabla
chat-board-create-ai-chat = AI Razgovor
chat-board-create-new-investigation-board = Nova istražna tabla
chat-board-create-a-board-runs-its-goals = Tabla ostvaruje svoje ciljeve kao niz agent istraživanja. Svako istraživanje je razgovor koji se završava jednim nalazom table. Pregledavate odgovor svakog cilja, a možete odbiti nalaze i dodati naznake dok se izvršava.
chat-board-create-title = Naslov
chat-board-create-goal = Cilj
chat-board-create-remove-this-goal = Ukloni ovaj cilj
chat-board-create-remove = Ukloni
chat-board-create-add-a-goal = Dodaj cilj
chat-board-create-context-optional = Kontekst (opcionalno)
chat-board-create-hints-one-per-line-optional = Naznake, jedna po redu (opcionalno)
chat-board-create-sources = Izvori
chat-board-create-internet-tools = Alati za internet
chat-board-create-creating-board = Izrada table...
chat-board-create-create-board = Izradi tablu
ai-chat-board-hoover-search-board = Hoover Pretraga - Tabla
ai-chat-board-loading-the-board-u = Učitavanje table…
ai-chat-board-show-the-board-overview = Prikaži pregled table
ai-chat-board-zoom-out = Smanji
ai-chat-board-zoom-in = Uvećaj
ai-chat-board-u-ai-chat = ← AI Razgovor
ai-chat-board-settings = Postavke
ai-chat-board-board-settings = Postavke table
ai-chat-board-internet-tools = Alati za internet
ai-chat-board-the-next-explores-of-the = Sljedeća istraživanja na tabli mogu pretraživati web i čitati web stranice. Istraživanja u tijeku zadržavaju postavku s kojom su započela.
ai-chat-board-collections = Kolekcije
ai-chat-board-the-collections-are-fixed-when = Kolekcije su fiksne od stvaranja table.
ai-chat-board-confirm-drop = Potvrdi odustajanje
ai-chat-board-drop-the-board = Odustaj od table
ai-chat-board-close = Zatvori
ai-chat-board-the-board-used-its-explore = Tabela je iskoristila svoj limit istraživanja
ai-chat-board-the-board-used-explores-the = Tabela je iskoristila { $explore_limit } istraživanja, limit jedne table. Ne započinje više posla. Još uvijek možete odlučivati o predloženim odgovorima.
ai-chat-board-create-a-new-board-to = Stvorite novu tablu za nastavak istrage
ai-chat-board-goal = Cilj
ai-chat-board-goals = Ciljevi
ai-chat-board-add-new-goal = Dodaj novi cilj...
ai-chat-board-a-new-goal = Novi cilj
ai-chat-board-add-goal = Dodaj cilj
ai-chat-board-a-board-has-at-most = Tabela ima najviše { $max_goals } ciljeva. Stvorite novu tablu za drugi cilj.
ai-chat-board-background-context = Pozadinski kontekst
ai-chat-board-continue-with-a-correction = Nastavi s ispravkom
ai-chat-board-correction-what-is-wrong-or = Ispravak: što je pogrešno ili nedostaje. Tabela nastavlja s tim.
ai-chat-board-the-board-waits-for-your = Tabela čeka vaš pregled
ai-chat-board-the-board-used-its-budget = Tabela je iskoristila svoj budžet od { $snap_max_explores } istraživanja.
ai-chat-board-the-assessments-gave-no-usable = Procjene nisu dale upotrebljivu smjernicu.
ai-chat-board-accept-or-reject-the-proposed = Prihvatite ili odbijte predloženi odgovor svakog cilja iznad. Odbijen odgovor omogućuje tabeli da nastupi odmah.
ai-chat-board-no-proposed-answer-waits-for = Nema predloženog odgovora koji čeka vašu odluku.
ai-chat-board-reopen-the-board-to-continue = Ponovo otvorite tablu za nastavak otvorenih ciljeva. Zadržava svoje nalaze i odgovore.
ai-chat-board-close-the-board-to-accept = Zatvorite tablu za prihvaćanje svakog predloženog odgovora i zaustavljanje, ili je nastavite s ispravkom.
ai-chat-board-close-the-board = Zatvori tablu
ai-chat-board-or-reopen-the-board-to = Ili ponovo otvorite tablu za nastavak otvorenih ciljeva bez ispravka.
ai-chat-board-the-board-is-complete = Tabela je završena
ai-chat-board-a-goal-has-no-accepted = Cilj nema prihvaćenog odgovora. Ponovo otvorite tablu za nastavak. Tabela zadržava svoje nalaze i odgovore.
ai-chat-board-add-a-hint = Dodaj naznaku
ai-chat-board-the-next-assessment-reads-every = Sljedeća procjena čita svaki trag. Trag također odgovara na istraživanje koje je postavilo pitanje.
ai-chat-board-add-hint = Dodaj trag
ai-chat-board-events = Događaji
ai-chat-board-newest-first = Najnovije prvo
ai-chat-board-date = Datum
ai-chat-board-actor = Djelatnik
ai-chat-board-event = Događaj
ai-chat-board-show-details = Prikaži detalje
ai-chat-board-open = Otvoreno
ai-chat-board-show-the-newest-events = Prikaži najnovije { $event_rows } događaja
ai-chat-board-show-all-events = Prikaži svih { $snap_events_len } događaja
ai-chat-board-statistics = Statistika
ai-chat-board-explores = Istraživanja
ai-chat-board-model-steps-per-explore = Koraci modela po istraživanju
ai-chat-board-assessments = Procjene
ai-chat-board-intents = Namjere
ai-chat-board-findings = Nalazi
ai-chat-board-created = Stvoreno
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } odbio/odbila ovaj nalaz na { $format_utc_ms_fact_rejected_ms }. Tabla ga više ne koristi.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } odbio/odbila ovaj nalaz. Tabla ga više ne koristi.
ai-chat-board-no-reason-was-given = Razlog nije naveden.
ai-chat-board-reason = Razlog: { $fact_rejected_reason }
ai-chat-board-open-questions = Otvorena pitanja
ai-chat-board-explored-in = Istraženo u{ " " }
ai-chat-board-explore-this-question = Istraži ovo pitanje
ai-chat-board-your-questions = Tvoja pitanja
ai-chat-board-ask-about-the-background-context = Pitaži o kontekstu pozadine
ai-chat-board-ask-about-this-finding = Pitaži o ovom nalazu
ai-chat-board-a-follow-up-question-about = Pitanje koje slijedi o ovom čvoru
ai-chat-board-ask = Pitaži
ai-chat-board-checks-that-changed-this-finding = Provjere koje su promijenile ovaj nalaz
ai-chat-board-reject-this-correction = Odbij ovu ispravku
ai-chat-board-reject-this-finding = Odbij ovaj nalaz
ai-chat-board-not-answered-the-board-was = Nije odgovoreno. Tabla je završena bez odgovora na ovaj cilj. Savjet ili ponovno otvaranje ponovo ga otvara.
ai-chat-board-no-answer-yet = Još nema odgovora.
ai-chat-board-the-findings-of-this-answer = Nalazi ovog odgovora su pretrace koje ništa nisu pronašle. Prihvatite ga za bilježnje da zapisi ne odgovaraju cilju ili odbijte ga za nastavak istraživanja.
ai-chat-board-open-an-assessment-to-read = { "." } Otvorite procjenu za čitanje zašto.
ai-chat-board-from-the-findings = Iz nalaza{ " " }
ai-chat-board-accept-answer = Prihvati odgovor
ai-chat-board-why-the-answer-is-wrong = Zašto je odgovor pogrešan ili nepotpun
ai-chat-board-reject-answer = Odbij odgovor
ai-chat-board-intent = Namjera
ai-chat-board-attempts-declared = Pokušaji: { $intent_attempts }. Objavljeno { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Istraživanje je pitalo
ai-chat-board-add-a-hint-in-the = Dod savjet u pregled tablice za odgovor na njega.
ai-chat-board-last-error = Zadnja greška
ai-chat-board-brief = Sažetak
ai-chat-board-open-the-explore-chat = Otvorite razgovor istraživanja
ai-chat-board-loading-the-assessment-u = Učitavanje procjene…
ai-chat-board-assessment = Procjena { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Ishod { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Provjere koje su ga promijenile
ai-chat-board-prompt = Upit
ai-chat-board-this-assessment-ran-before-the = Ova procjena pokrenuta je prije spremanja upita.
ai-chat-board-response = Odgovor
ai-chat-history-hoover-search-chat-history = Hoover Search - Povijest razgovora
ai-chat-history-u-back = ← Nazad
ai-chat-history-conversation-history = Povijest razgovora
ai-chat-history-show-board-chats = Prikaži razgovore na tablicama
ai-chat-history-loading-u = Učitavanje…
ai-chat-history-could-not-load-history = Nije moguće učitati povijest: { $e }
ai-chat-history-no-conversations-yet = Trenutno nema razgovora.
ai-chat-history-board = Tabla
ai-chat-history-new-chat = Novi razgovor
ai-chat-history-messages-updated = { $s_message_count } poruka · ažurirano { $s_updated_at }
ai-chat-history-delete-conversation = Izbriši razgovor
ai-chat-history-delete = Izbriši
ai-chat-homepage-hoover-search-ai-chat = Hoover Search – AI chat
ai-chat-homepage-what-are-you-researching = Što istražujete?
ai-chat-homepage-view-all-conversations = Prikaži sve razgovore
ai-chat-homepage-starting-conversation-u = Poklanjanje razgovora…
ai-chat-homepage-investigation-boards = Table istraživanja
ai-chat-homepage-new-board = Nova tabla
ai-chat-homepage-loading-boards-u = Učitavanje tabli…
ai-chat-homepage-could-not-load-the-boards = Nije moguće učitati table: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nemate nijednu tablu. Tabla pokreće dugo istraživanje kao niz agentovih istraživanja, a vi pregledavate njezine odgovore.
ai-chat-homepage-updated = Ažurirano { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search – AI chat
ai-chat-session-this-conversation-could-not-be = Ovaj se razgovor nije mogao učitati.
ai-chat-session-loading-u = Učitavanje…
ai-chat-session-u-chats = ← Razgovori
ai-chat-session-history = Povijest
ai-chat-session-show-the-files-that-the = Prikaži datoteke koje je asistent zapisao u ovom razgovoru
ai-chat-session-workspace = Radni prostor
ai-chat-session-this-answer-was-interrupted-before = Ovaj je odgovor prekinut prije nego što je završen jer se stranica ili poslužitor zaustavio usred poteza. Pokušajte ponovo.
ai-chat-session-dismiss = Odbaci
ai-chat-session-board-explore-chats-are-read = Razgovori istraživanja na tabli su samo za čitanje.{ " " }
ai-chat-session-open-the-board = Otvori tablu
chat-locked-options-on = { $label }: uključeno
chat-locked-options-off = { $label }: isključeno
chat-tool-cards-running-u = pokreće se…
cards-result-cards-quote-found = Citat pronađen
cards-result-cards-quote-not-found = Citat nije pronađen
cards-result-cards-quote-not-checked = Citat nije provjeren
web-search-card-results = { $results_len } rezultata
chat-tool-disclosure-running-u = pokreće se…
chat-transcript-call = poziv
chat-transcript-calls = pozivi
ai-chat-board-a-board-without-collections-needs = Tabla bez kolekcija treba internet alate.
ai-chat-board-of = { $snap_explores_used } od { $snap_max_explores }
ai-chat-board-assessment-2 = procjena { $number }
ai-chat-history-messages = { $s_message_count } poruka
web-search-card-reranked-in = Kroz-encoder rangirao je rezultate za { $ms } ms.
web-search-card-engine-results = { $name }: { $count } u { $ms } ms
web-search-card-score-was-rank = ocjena { $score } · bio je RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Tretman čeka slobodan slot modela.
chat-activity-the-turn-waits-for-a-2 = Tretman čeka slobodan slot alata.
chat-locked-options-start-a-new-chat-to = Pokrenite novi razgovor za promjenu ove postavke.
chat-locked-options-internet-tools = Internet alati
chat-session-card-new-chat = Novi razgovor
chat-tool-cards-first-frame-of-the-video = Prvi kadar videa
chat-tool-cards-screenshot-of = Slika zaslona
chat-tool-cards-image = Slika
cards-result-cards-the-agent-asked-a-question = Agent je postavio pitanje.
chat-transcript-hide = Sakrij
chat-transcript-show = Prikaži
chat-transcript-unverified-quote-the-quoted-span = Neprovjeren citat. Navedeni fragment je prekratak za provjeru.
chat-transcript-unverified-quote-the-document-text = Neprovjeren citat. Tekst dokumenta nije bilo moguće pročitati.
chat-transcript-unverified-quote-this-wording-was = Neprovjeren citat. Ovaj je formulacija pronađena u dokumentu.
chat-board-create-select-a-collection-or-turn = Odaberite kolekciju ili uključite internet alate.
chat-board-create-select-at-least-one-collection = Odaberite barem jednu kolekciju.
ai-chat-board-active = Aktivno
ai-chat-board-paused = Pauzirano
ai-chat-board-waits-for-review = Čeka pregled
ai-chat-board-completed = Završeno
ai-chat-board-dropped = Odbijeno
ai-chat-board-unknown = Nepoznato
ai-chat-board-pause-the-board = Pauziraj tablu
ai-chat-board-resume-the-board = Nastavi s tablom
ai-chat-board-none = Ništa
ai-chat-board-reopen-with-the-remaining-budget = Ponovo otvori s preostalog budžeta
ai-chat-board-finding = Nalaz
ai-chat-board-why-the-correction-is-wrong = Zašto je ispravak pogrešan
ai-chat-board-reject-correction = Odbij ispravak
ai-chat-board-why-the-finding-is-wrong = Zašto je nalaz pogrešan
ai-chat-board-reject-finding = Odbij nalaz
ai-chat-board-answer = Odgovor
ai-chat-board-proposed-answer = Predloženi odgovor
ai-chat-homepage-active = Aktivno
ai-chat-homepage-paused = Pauzirano
ai-chat-homepage-waits-for-review = Čeka pregled
ai-chat-homepage-completed = Završeno
ai-chat-homepage-dropped = Odbijeno
ai-chat-homepage-unknown = Nepostojeće
cards-result-cards-submitted-by-board =
    Podnijela tablica: { $kind ->
        [sourced] izvorom utvrđen
        [inferred] zaključak
        [not_found] nije pronađen
       *[other] nepoznatog tipa
    } nalaz iz izvješća
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Izvorom utvrđen
        [inferred] Zaključak
        [not_found] Nije pronađen
       *[other] Nepoznatog tipa
    } nalaz za tablicu
chat-transcript-compacting = Sažimanje konteksta: { $before } tokena na ciljnih { $target }.
chat-transcript-compaction-failed = Sažetak ranijih koraka nije uspio. Model je primio ranije korake nepromijenjene, { $after } tokena.
chat-transcript-compacted = Kontekt sažiman: { $steps } koraka sažeto, { $before } tokena na { $after }.
ai-chat-board-reopen-with-more = Ponovo otvori s još { $grant } istraživanja
ai-chat-board-goal-number = Cilj { $number }
ai-chat-board-from-assessment-on = Iz procjene { $number } na { $date }.
ai-chat-board-from-assessment = Iz procjene { $number }.
chat-board-create-goal-2 = Cilj { $index_1 }
ai-chat-session-lost-contact-with-the-chat = izgubio vezu s razgovorom: { $e }
ai-chat-session-could-not-stop-the-answer = nije mogao zaustaviti odgovor: { $e } — još se izvodi
ai-chat-board-later-assessments-dropped-an-answer = { $n } kasnijih procjena izbacilo je odgovor za ovaj cilj:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokena upita i { $a_completion_tokens } tokena završetka
ai-chat-homepage-completed-goals-not-answered = Završeno, { $n } ciljeva bez odgovora
board-graph-intent = namjera, { $state }
chat-workspace-pane-characters = { $chars } znakova
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } izvodi alat { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } izvodnji alata { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Odgovoreno nakon { $retries_len } neuspješnog pokušaja { $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } neuspješni pokušaji { $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, verzija { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] pretražen { $n } izraz
        [few] pretražena { $n } izraza
       *[other] pretraženo { $n } izraza
    }
tool-run-summary-read =
    { $n ->
        [one] pročitani { $n } dokument
        [few] pročitana { $n } dokumenata
       *[other] pročitano { $n } dokumenata
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] pretražio web zbog { $n } izraza
        [few] pretražio web zbog { $n } izraza
       *[other] pretražio web zbog { $n } izraza
    }
tool-run-summary-read-web =
    { $n ->
        [one] pročitana { $n } web stranica
        [few] pročitane { $n } web stranica
       *[other] pročitano { $n } web stranica
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } radnja u pregledniku
        [few] { $n } radnje u pregledniku
       *[other] { $n } radnji u pregledniku
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] popisani entiteti { $n } dokumenta
        [few] popisani entiteti { $n } dokumenata
       *[other] popisani entiteti { $n } dokumenata
    }
tool-run-summary-cited =
    { $n ->
        [one] citirani { $n } dokument
        [few] citirana { $n } dokumenata
       *[other] citirano { $n } dokumenata
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citirana { $n } web stranica
        [few] citirane { $n } web stranica
       *[other] citirano { $n } web stranica
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] pročitani { $n } tekst vještine i alata
        [few] pročitana { $n } teksta vještine i alata
       *[other] pročitano { $n } teksta vještine i alata
    }
tool-run-summary-saved =
    { $n ->
        [one] spremljen { $n } bilješka
        [few] spremljene { $n } bilješke
       *[other] spremljeno { $n } bilješki
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } poziv popisa zadaća
        [few] { $n } poziva popisa zadaća
       *[other] { $n } poziva popisa zadaća
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } uputa agentu
        [few] { $n } upute agentu
       *[other] { $n } uputa agentu
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } drugi poziv
        [few] { $n } druga poziva
       *[other] { $n } drugih poziva
    }
tool-run-summary-failed = { $failures } neuspješno
tool-run-summary-took = izvršeno u { $duration_text_ms }
chat-session-card-messages = { $session_message_count } poruka
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } stavka
       *[other] { $count } stavke
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } polje
       *[other] { $count } polja
    }
chat-tool-disclosure-searched-collections = pretražene kolekcije{ $filters }
chat-tool-disclosure-searched-collections-2 = pretražene kolekcije · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citirano { $n } dokumenata
chat-tool-disclosure-read-document = pročitani dokument · { $path }
chat-tool-disclosure-searched-the-web = pretraženi web · { $q }
chat-tool-disclosure-opened-page = otvorena stranica · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = pozvano { $other }
chat-tool-disclosure-called-2 = pozvano { $other } · { $short }
cards-browser-card-opened = otvoreno { $url }
cards-browser-card-could-not-open = nije bilo moguće otvoriti { $url }
cards-browser-card-clicked = kliknuto na { $element }
cards-browser-card-could-not-click = nije bilo moguće kliknuti na { $element }
cards-browser-card-typed-into = upisano u { $element }
cards-browser-card-could-not-type-into = nije bilo moguće upisati u { $element }
cards-browser-card-typed = upisano „{ $text }”
cards-browser-card-could-not-type = nije bilo moguće upisati „{ $text }”
cards-browser-card-pressed = pritisnuto { $key }
cards-browser-card-could-not-press = nije bilo moguće pritisnuti { $key }
cards-browser-card-chose-an-option-in = odabran je izbor u { $element }
cards-browser-card-could-not-choose-an-option = nije bilo moguće odabrati izbor u { $element }
cards-browser-card-hovered = pokazano na { $element }
cards-browser-card-could-not-hover = nije bilo moguće pokazati na { $element }
cards-browser-card-failed = { $bare } — neuspjeh
cards-entities-card-listed-entities-document = navedeni entiteti · { $count } dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · dio { $part } od { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } dokumenata
cards-result-cards-forms = { $tool_name } · { $forms } obrazaca
cards-result-cards-in = { " " }u { $collections }
cards-result-cards-page = { " " }· stranica { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenata · { $missing } navoda pronađeno
cards-result-cards-version-unchanged = { $tool_name } · verzija { $version } · nepromijenjeno
cards-result-cards-version = { $tool_name } · verzija { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } rezultata, { $json_u64_doc_total_after_dedupe } nakon uklanjanja duplicata
