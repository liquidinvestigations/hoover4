# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Bot pracuje...
chat-composer-ask-the-bot = Zapytaj bota...
chat-composer-internet-tools = Narzędzia internetowe
chat-composer-agent-language-title = Agent odpowiada po: { $language }. Zmień język w ustawieniach, w nowej karcie.
chat-composer-try-again-in-s = Spróbuj ponownie za { $secs } s
chat-composer-stop-the-answer-the-partial = Zatrzymaj odpowiedź (część już wygenerowana nie zostanie zapisana w rozmowie)
chat-composer-starting-the-conversation-u = Rozpoczynanie rozmowy…
chat-composer-send = Wyślij
chat-conversation-find-search-in-conversation = Szukaj w rozmowie
chat-conversation-find-previous-match = Poprzednie dopasowanie
chat-conversation-find-next-match = Następne dopasowanie
chat-conversation-find-investigation-board = Tablica śledcza
doc-ref-card-not-openable = Nie można otworzyć: { $reason }.
doc-ref-card-the-search-term-was = Szukane wyrażenie:{" "}
doc-ref-card-open = Otwórz
doc-ref-card-not-openable-2 = Nie można otworzyć
chat-markdown-text-show-the-cited-source = Pokaż cytowane źródło
chat-markdown-text-no-citation-of-this-conversation = Żadne cytowanie w tej rozmowie nie nadało tej sygnatury, więc nie stoi za nią żaden dokument.
chat-markdown-text-citations-of-this-conversation-gave = Cytowania w tej rozmowie nadały tę sygnaturę więcej niż jednemu dokumentowi, więc nie prowadzi ona do żadnego z nich.
cards-browser-card-open-the-archived-page = Otwórz zarchiwizowaną stronę
cards-browser-card-the-page-itself-was-not = Samej strony nie zarchiwizowano (status: { $artifact_status }). Zachowano tylko powyższy zrzut ekranu.
cards-browser-card-click-the-screenshot-to-open = Kliknij zrzut ekranu, aby otworzyć zarchiwizowaną stronę.
cards-browser-card-show-less = Pokaż mniej
cards-browser-card-show-all = Pokaż wszystko
cards-browser-card-archived-page = Zarchiwizowana strona
cards-browser-card-download = Pobierz
cards-browser-card-archived-copy-of = Zarchiwizowana kopia: { $artifact_url }
cards-browser-card-this-page-was-not-archived = Tej strony nie zarchiwizowano (status: { $artifact_status }).
cards-entities-card-with-a-card = Z kartą: { $openable }
cards-entities-card-the-entity-list-was-cut = Lista encji została skrócona.
cards-entities-card-open-the-card-for-this = Otwórz kartę tej wartości ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Brak karty: ta rozmowa nigdy nie podała zbioru danych, z którego pochodzą te wartości, a przeglądarka dokumentów jest adresowana według zbioru danych.
cards-entities-card-more-all-of-them-in = Jeszcze { $rest }, wszystkie w panelu encji dokumentu.{" "}
cards-entities-card-names-organisations-and-places-above = Nazwiska, organizacje i miejsca powyżej to odczyt tekstu wykonany przez model. Żadna reguła ich nie zweryfikowała, więc nie ma czego wyjaśniać i niczego nie otwierają.
cards-entities-card-nothing-extracted-from-this-document = Z tego dokumentu nic nie wyodrębniono.
chat-tool-cards-hide = Ukryj
chat-tool-cards-expand = Rozwiń
chat-tool-cards-hide-raw-json = Ukryj surowy JSON
chat-tool-cards-show-raw-json = Pokaż surowy JSON
cards-result-cards-search-this = Szukaj tego
cards-result-cards-search-every-collection = Przeszukaj każdą kolekcję
cards-result-cards-form = Forma { $index }: { $form }
cards-result-cards-show-full-text = Pokaż pełny tekst
cards-result-cards-quote = Cytat: { $quote }
cards-result-cards-reason = Powód: { $why }
cards-result-cards-open-question = Otwarte pytanie: { $question }
cards-result-cards-the-explore-gave-this-answer = Eksploracja przekazała tablicy tę odpowiedź jako { $kind ->
        [sourced] ustalenie ze źródłem
        [inferred] ustalenie wywnioskowane
        [not_found] ustalenie „nie znaleziono”
       *[other] ustalenie nieznanego rodzaju
    }.
cards-result-cards-it-left-no-open-question = Nie zostawiła otwartego pytania.
cards-result-cards-open-questions-for-the-board = Otwarte pytania dla tablicy:
cards-result-cards-arguments = Argumenty
cards-result-cards-list-after-the-call = Lista po wywołaniu: { $snapshot_goal }
cards-result-cards-replaces = {" "}· zastępuje { $replaces_id }
cards-result-cards-the-list-at-this-version = Lista w tej wersji nie jest zapisana.
web-search-card-these-sources-returned-nothing-so = Te źródła niczego nie zwróciły, więc wyniki pochodzą z mniejszej liczby źródeł, niż zamierzono
web-search-card-u-degraded = ⚠ ograniczone: { $degraded_len }
web-search-card-form = Forma { $index }: { $form }
web-search-card-no-results-from = Brak wyników z: { $degraded_text }
web-search-card-no-results-every-source-answered = Brak wyników. Każde źródło odpowiedziało i żadne nie miało nic dla tego zapytania.
web-search-card-the-lowest-ranked-results-were = Najniżej ocenione wyniki pominięto, aby to wywołanie mieściło się w zapisie rozmowy. Asystent widział je wszystkie.
web-search-card-view-search-details = Pokaż szczegóły wyszukiwania.
web-search-card-the-stored-result-could-not = nie udało się odczytać zapisanego wyniku jako JSON
web-search-card-nothing-was-stored-for-this = Dla tego wywołania nic nie zapisano.
web-search-card-forms = Formy: { $forms }
web-search-card-kind = Rodzaj: { $row_kind }
web-search-card-published = Opublikowano: { $row_published }
web-search-card-loading-search-detail-u = Wczytywanie szczegółów wyszukiwania…
web-search-card-could-not-load-the-search = Nie udało się wczytać szczegółów wyszukiwania: { $e }
web-search-card-malformed-detail = Nieprawidłowe szczegóły: { $e }
web-search-card-the-tool-returned-selected-results = Narzędzie zwróciło modelowi wybrane wyniki.
web-search-card-results-use-reciprocal-rank-fusion = Wyniki są łączone metodą reciprocal rank fusion.
web-search-card-returned-nothing = nic nie zwróciło: { $degraded }
web-search-card-all-candidates-use-fusion-order = Wszyscy kandydaci są w kolejności po fuzji.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoder porządkuje wybrane wyniki.
web-search-card-selected-results-use-fusion-order = Wybrane wyniki są w kolejności po fuzji.
web-search-card-search-detail = Szczegóły wyszukiwania
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Szukaj tego
chat-tool-disclosure-search-every-collection = Przeszukaj każdą kolekcję
chat-tool-disclosure-hide = Ukryj
chat-tool-disclosure-expand = Rozwiń
chat-tool-disclosure-this-step-was-recorded-before = Ten krok zapisano, zanim zaczęto przechowywać argumenty i wyniki narzędzi. Dostępne jest tylko poniższe podsumowanie.
chat-tool-disclosure-arguments = Argumenty
chat-tool-disclosure-result = Wynik
chat-tool-disclosure-hide-raw-json = Ukryj surowy JSON
chat-tool-disclosure-show-raw-json = Pokaż surowy JSON
chat-tool-disclosure-input-json = JSON wejściowy
chat-tool-disclosure-output-json = JSON wyjściowy
chat-transcript-ask-a-question-about-the = Zadaj pytanie o dokumenty w swoich kolekcjach.
chat-transcript-suggested-next = Proponowane dalej...
chat-transcript-earlier-answer = Wcześniejsza odpowiedź
chat-transcript-tokens-the-conversation-carries-the = Tokeny w rozmowie, największy pojedynczy kontekst naliczony w tej turze i jaką część okna modelu zajął
chat-transcript-instruction-to-the-agent = Instrukcja dla agenta
chat-transcript-the-context-stays-above-the = {" "}Kontekst pozostaje powyżej celu: { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}Nie udało się utworzyć części podsumowania: { $failed }. Zapis zawiera tylko listy.
chat-transcript-show-the-record = Pokaż zapis
chat-transcript-hide-reasoning = Ukryj tok rozumowania
chat-transcript-show-reasoning = Pokaż tok rozumowania
chat-transcript-from-u-hide = { $count ->
        [one] { $count } dokument
        [few] { $count } dokumenty
        [many] { $count } dokumentów
       *[other] { $count } dokumentu
    } z { $tool } – ukryj
chat-transcript-from-u-show = { $count ->
        [one] { $count } dokument
        [few] { $count } dokumenty
        [many] { $count } dokumentów
       *[other] { $count } dokumentu
    } z { $tool } – pokaż
chat-transcript-u-hide = { $summary } – ukryj
chat-transcript-u-show = { $summary } – pokaż
chat-transcript-citations-of-this-conversation-give = Cytowania w tej rozmowie nadają sygnaturę { $doc_handle } więcej niż jednemu dokumentowi. Odpowiedź nie łączy jej z żadnym z nich.
chat-transcript-report = Raport { $label }
chat-transcript-open-in-the-workspace = Otwórz w przestrzeni roboczej
chat-transcript-this-version-could-not-be = Nie udało się odczytać tej wersji. Poniżej jest tekst odpowiedzi z czatu.
chat-transcript-files = Pliki
chat-transcript-version = { $file_name }, wersja { $file_version }
chat-web-find-exact-text = Znajdź dokładny tekst
chat-web-previous-match = Poprzednie dopasowanie
chat-web-next-match = Następne dopasowanie
chat-web-close-preview = Zamknij podgląd
chat-web-the-captured-page-could-not = Nie udało się wczytać przechwyconej strony.
chat-web-loading = Wczytywanie…
chat-workspace-pane-workspace = Przestrzeń robocza
chat-workspace-pane-close-the-workspace = Zamknij przestrzeń roboczą
chat-workspace-pane-close = Zamknij
chat-workspace-pane-loading-the-files-u = Wczytywanie plików…
chat-workspace-pane-the-files-could-not-be = Nie udało się wczytać plików: { $error }
chat-workspace-pane-this-conversation-has-no-files = Ta rozmowa nie ma plików.
chat-workspace-pane-version = wersja { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Wybierz plik, aby go przeczytać.
chat-workspace-pane-loading-the-file-u = Wczytywanie pliku…
chat-workspace-pane-the-file-could-not-be = Nie udało się wczytać pliku: { $error }
chat-workspace-pane-version-2 = { $found_name }, wersja { $found_version }
chat-board-create-collections = Kolekcje
chat-board-create-loading-collections-u = Wczytywanie kolekcji…
chat-board-create-hoover-search-new-board = Hoover Search - Nowa tablica
chat-board-create-ai-chat = Czat AI
chat-board-create-new-investigation-board = Nowa tablica śledcza
chat-board-create-a-board-runs-its-goals = Tablica realizuje swoje cele jako ciąg eksploracji agenta. Każda eksploracja to czat, który kończy się jednym ustaleniem tablicy. Odpowiedź na każdy cel sprawdzasz Ty, a w trakcie pracy możesz odrzucać ustalenia i dodawać wskazówki.
chat-board-create-title = Tytuł
chat-board-create-goal = Cel
chat-board-create-remove-this-goal = Usuń ten cel
chat-board-create-remove = Usuń
chat-board-create-add-a-goal = Dodaj cel
chat-board-create-context-optional = Kontekst (opcjonalnie)
chat-board-create-hints-one-per-line-optional = Wskazówki, po jednej w wierszu (opcjonalnie)
chat-board-create-sources = Źródła
chat-board-create-internet-tools = Narzędzia internetowe
chat-board-create-creating-board = Tworzenie tablicy...
chat-board-create-create-board = Utwórz tablicę
ai-chat-board-hoover-search-board = Hoover Search - Tablica
ai-chat-board-loading-the-board-u = Wczytywanie tablicy…
ai-chat-board-show-the-board-overview = Pokaż przegląd tablicy
ai-chat-board-zoom-out = Pomniejsz
ai-chat-board-zoom-in = Powiększ
ai-chat-board-u-ai-chat = ← Czat AI
ai-chat-board-settings = Ustawienia
ai-chat-board-board-settings = Ustawienia tablicy
ai-chat-board-internet-tools = Narzędzia internetowe
ai-chat-board-the-next-explores-of-the = Kolejne eksploracje tablicy mogą przeszukiwać internet i czytać strony internetowe. Trwające eksploracje zachowują ustawienie, z którym się rozpoczęły.
ai-chat-board-collections = Kolekcje
ai-chat-board-the-collections-are-fixed-when = Kolekcje są ustalane przy tworzeniu tablicy.
ai-chat-board-confirm-drop = Potwierdź porzucenie
ai-chat-board-drop-the-board = Porzuć tablicę
ai-chat-board-close = Zamknij
ai-chat-board-the-board-used-its-explore = Tablica wykorzystała limit eksploracji
ai-chat-board-the-board-used-explores-the = Tablica wykorzystała eksploracje: { $explore_limit }, czyli limit jednej tablicy. Nie rozpocznie już nowej pracy. Nadal możesz rozstrzygać proponowane odpowiedzi.
ai-chat-board-create-a-new-board-to = Utwórz nową tablicę, aby kontynuować śledztwo
ai-chat-board-goal = Cel
ai-chat-board-goals = Cele
ai-chat-board-add-new-goal = Dodaj nowy cel...
ai-chat-board-a-new-goal = Nowy cel
ai-chat-board-add-goal = Dodaj cel
ai-chat-board-a-board-has-at-most = Tablica ma najwyżej { $max_goals } celów. Utwórz nową tablicę dla kolejnego celu.
ai-chat-board-background-context = Kontekst wyjściowy
ai-chat-board-continue-with-a-correction = Kontynuuj z poprawką
ai-chat-board-correction-what-is-wrong-or = Poprawka: co jest błędne lub czego brakuje. Tablica kontynuuje pracę z jej uwzględnieniem.
ai-chat-board-the-board-waits-for-your = Tablica czeka na Twój przegląd
ai-chat-board-the-board-used-its-budget = Tablica wykorzystała swój budżet eksploracji: { $snap_max_explores }.
ai-chat-board-the-assessments-gave-no-usable = Oceny nie wskazały żadnego użytecznego kierunku.
ai-chat-board-accept-or-reject-the-proposed = Zaakceptuj lub odrzuć proponowaną odpowiedź na każdy cel powyżej. Odrzucona odpowiedź pozwala tablicy od razu kontynuować pracę.
ai-chat-board-no-proposed-answer-waits-for = Żadna proponowana odpowiedź nie czeka na Twoją decyzję.
ai-chat-board-reopen-the-board-to-continue = Otwórz tablicę ponownie, aby kontynuować otwarte cele. Zachowuje ona swoje ustalenia i odpowiedzi.
ai-chat-board-close-the-board-to-accept = Zamknij tablicę, aby zaakceptować wszystkie proponowane odpowiedzi i ją zatrzymać, albo kontynuuj ją z poprawką.
ai-chat-board-close-the-board = Zamknij tablicę
ai-chat-board-or-reopen-the-board-to = Albo otwórz tablicę ponownie, aby kontynuować otwarte cele bez poprawki.
ai-chat-board-the-board-is-complete = Tablica jest ukończona
ai-chat-board-a-goal-has-no-accepted = Cel nie ma zaakceptowanej odpowiedzi. Otwórz tablicę ponownie, aby go kontynuować. Tablica zachowuje swoje ustalenia i odpowiedzi.
ai-chat-board-add-a-hint = Dodaj wskazówkę
ai-chat-board-the-next-assessment-reads-every = Następna ocena uwzględnia każdą wskazówkę. Wskazówka odpowiada też na pytanie zadane przez eksplorację.
ai-chat-board-add-hint = Dodaj wskazówkę
ai-chat-board-events = Zdarzenia
ai-chat-board-newest-first = Najnowsze na górze
ai-chat-board-date = Data
ai-chat-board-actor = Wykonawca
ai-chat-board-event = Zdarzenie
ai-chat-board-show-details = Pokaż szczegóły
ai-chat-board-open = Otwórz
ai-chat-board-show-the-newest-events = Pokaż najnowsze zdarzenia ({ $event_rows })
ai-chat-board-show-all-events = Pokaż wszystkie zdarzenia ({ $snap_events_len })
ai-chat-board-statistics = Statystyki
ai-chat-board-explores = Eksploracje
ai-chat-board-model-steps-per-explore = Kroki modelu na eksplorację
ai-chat-board-assessments = Oceny
ai-chat-board-intents = Zamiary
ai-chat-board-findings = Ustalenia
ai-chat-board-created = Utworzono
ai-chat-board-rejected-this-finding-on-the = Ustalenie odrzucone przez { $rejected_by } dnia { $format_utc_ms_fact_rejected_ms }. Tablica już go nie używa.
ai-chat-board-rejected-this-finding-the-board = Ustalenie odrzucone przez { $rejected_by }. Tablica już go nie używa.
ai-chat-board-no-reason-was-given = Nie podano powodu.
ai-chat-board-reason = Powód: { $fact_rejected_reason }
ai-chat-board-open-questions = Otwarte pytania
ai-chat-board-explored-in = Zbadano w{" "}
ai-chat-board-explore-this-question = Zbadaj to pytanie
ai-chat-board-your-questions = Twoje pytania
ai-chat-board-ask-about-the-background-context = Zapytaj o kontekst wyjściowy
ai-chat-board-ask-about-this-finding = Zapytaj o to ustalenie
ai-chat-board-a-follow-up-question-about = Pytanie uzupełniające o ten węzeł
ai-chat-board-ask = Zapytaj
ai-chat-board-checks-that-changed-this-finding = Sprawdzenia, które zmieniły to ustalenie
ai-chat-board-reject-this-correction = Odrzuć tę poprawkę
ai-chat-board-reject-this-finding = Odrzuć to ustalenie
ai-chat-board-not-answered-the-board-was = Bez odpowiedzi. Tablicę zakończono bez odpowiedzi na ten cel. Wskazówka lub ponowne otwarcie uruchamia go znowu.
ai-chat-board-no-answer-yet = Jeszcze brak odpowiedzi.
ai-chat-board-the-findings-of-this-answer = Ustalenia tej odpowiedzi to wyszukiwania, które niczego nie znalazły. Zaakceptuj ją, aby odnotować, że zapisy nie odpowiadają na cel, albo odrzuć ją, aby kontynuować śledztwo.
ai-chat-board-open-an-assessment-to-read = {"."} Otwórz ocenę, aby przeczytać, dlaczego.
ai-chat-board-from-the-findings = Z ustaleń{" "}
ai-chat-board-accept-answer = Zaakceptuj odpowiedź
ai-chat-board-why-the-answer-is-wrong = Dlaczego odpowiedź jest błędna lub niepełna
ai-chat-board-reject-answer = Odrzuć odpowiedź
ai-chat-board-intent = Zamiar
ai-chat-board-attempts-declared = Próby: { $intent_attempts }. Zgłoszono: { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Eksploracja zapytała
ai-chat-board-add-a-hint-in-the = Dodaj wskazówkę w przeglądzie tablicy, aby na nie odpowiedzieć.
ai-chat-board-last-error = Ostatni błąd
ai-chat-board-brief = Zadanie
ai-chat-board-open-the-explore-chat = Otwórz czat eksploracji
ai-chat-board-loading-the-assessment-u = Wczytywanie oceny…
ai-chat-board-assessment = Ocena { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model: { $a_model }. Wynik: { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Sprawdzenia, które go zmieniły
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Ta ocena odbyła się, zanim zaczęto zapisywać prompty.
ai-chat-board-response = Odpowiedź
ai-chat-history-hoover-search-chat-history = Hoover Search - Historia czatów
ai-chat-history-u-back = ← Wstecz
ai-chat-history-conversation-history = Historia rozmów
ai-chat-history-show-board-chats = Pokaż czaty tablic
ai-chat-history-loading-u = Wczytywanie…
ai-chat-history-could-not-load-history = Nie udało się wczytać historii: { $e }
ai-chat-history-no-conversations-yet = Nie ma jeszcze rozmów.
ai-chat-history-board = Tablica
ai-chat-history-new-chat = Nowy czat
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } wiadomość · zaktualizowano: { $s_updated_at }
    [few] { $s_message_count } wiadomości · zaktualizowano: { $s_updated_at }
    [many] { $s_message_count } wiadomości · zaktualizowano: { $s_updated_at }
    *[other] { $s_message_count } wiadomości · zaktualizowano: { $s_updated_at }
    }

ai-chat-history-delete-conversation = Usuń rozmowę
ai-chat-history-delete = Usuń
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Czat AI
ai-chat-homepage-what-are-you-researching = Co badasz?
ai-chat-homepage-view-all-conversations = Zobacz wszystkie rozmowy
ai-chat-homepage-starting-conversation-u = Rozpoczynanie rozmowy…
ai-chat-homepage-investigation-boards = Tablice śledcze
ai-chat-homepage-new-board = Nowa tablica
ai-chat-homepage-loading-boards-u = Wczytywanie tablic…
ai-chat-homepage-could-not-load-the-boards = Nie udało się wczytać tablic: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nie masz żadnej tablicy. Tablica prowadzi długie śledztwo jako ciąg eksploracji agenta, a Ty sprawdzasz jej odpowiedzi.
ai-chat-homepage-updated = Zaktualizowano: { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Czat AI
ai-chat-session-this-conversation-could-not-be = Nie udało się wczytać tej rozmowy.
ai-chat-session-loading-u = Wczytywanie…
ai-chat-session-u-chats = ← Czaty
ai-chat-session-history = Historia
ai-chat-session-show-the-files-that-the = Pokaż pliki, które asystent zapisał w tej rozmowie
ai-chat-session-workspace = Przestrzeń robocza
ai-chat-session-this-answer-was-interrupted-before = Ta odpowiedź została przerwana przed ukończeniem, ponieważ strona lub serwer zatrzymały się w trakcie tury. Zapytaj ponownie, aby spróbować jeszcze raz.
ai-chat-session-dismiss = Ukryj
ai-chat-session-board-explore-chats-are-read = Czaty eksploracji tablicy są tylko do odczytu.{" "}
ai-chat-session-open-the-board = Otwórz tablicę
chat-locked-options-on = { $label }: włączone
chat-locked-options-off = { $label }: wyłączone
chat-tool-cards-running-u = w toku…
cards-result-cards-quote-found = Cytat znaleziony
cards-result-cards-quote-not-found = Cytatu nie znaleziono
cards-result-cards-quote-not-checked = Cytat niesprawdzony
web-search-card-results = Wyniki: { $results_len }
chat-tool-disclosure-running-u = w toku…
chat-transcript-call = wywołanie
chat-transcript-calls = wywołania
ai-chat-board-a-board-without-collections-needs = Tablica bez kolekcji wymaga narzędzi internetowych.
ai-chat-board-of = { $snap_explores_used } z { $snap_max_explores }
ai-chat-board-assessment-2 = ocena { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } wiadomość
    [few] { $s_message_count } wiadomości
    [many] { $s_message_count } wiadomości
    *[other] { $s_message_count } wiadomości
    }

web-search-card-reranked-in = Cross-encoder uporządkował wyniki w { $ms } ms.
web-search-card-engine-results = { $name }: { $count } w { $ms } ms
web-search-card-score-was-rank = ocena { $score } · poprzednio RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Tura czeka na wolny slot modelu.
chat-activity-the-turn-waits-for-a-2 = Tura czeka na wolny slot narzędzia.
chat-locked-options-start-a-new-chat-to = Rozpocznij nowy czat, aby zmienić to ustawienie.
chat-locked-options-internet-tools = Narzędzia internetowe
chat-session-card-new-chat = Nowy czat
chat-tool-cards-first-frame-of-the-video = Pierwsza klatka wideo
chat-tool-cards-screenshot-of = Zrzut ekranu strony
chat-tool-cards-image = Obraz
cards-result-cards-the-agent-asked-a-question = Agent zadał pytanie.
chat-transcript-hide = Ukryj
chat-transcript-show = Pokaż
chat-transcript-unverified-quote-the-quoted-span = Cytat niezweryfikowany. Cytowany fragment jest zbyt krótki, aby go sprawdzić.
chat-transcript-unverified-quote-the-document-text = Cytat niezweryfikowany. Nie udało się odczytać tekstu dokumentu.
chat-transcript-unverified-quote-this-wording-was = Cytat niezweryfikowany. Nie znaleziono tego sformułowania w dokumencie.
chat-board-create-select-a-collection-or-turn = Wybierz kolekcję lub włącz narzędzia internetowe.
chat-board-create-select-at-least-one-collection = Wybierz co najmniej jedną kolekcję.
ai-chat-board-active = Aktywna
ai-chat-board-paused = Wstrzymana
ai-chat-board-waits-for-review = Czeka na przegląd
ai-chat-board-completed = Ukończona
ai-chat-board-dropped = Porzucona
ai-chat-board-unknown = Nieznana
ai-chat-board-pause-the-board = Wstrzymaj tablicę
ai-chat-board-resume-the-board = Wznów tablicę
ai-chat-board-none = Brak
ai-chat-board-reopen-with-the-remaining-budget = Otwórz ponownie z pozostałym budżetem
ai-chat-board-finding = Ustalenie
ai-chat-board-why-the-correction-is-wrong = Dlaczego poprawka jest błędna
ai-chat-board-reject-correction = Odrzuć poprawkę
ai-chat-board-why-the-finding-is-wrong = Dlaczego ustalenie jest błędne
ai-chat-board-reject-finding = Odrzuć ustalenie
ai-chat-board-answer = Odpowiedź
ai-chat-board-proposed-answer = Proponowana odpowiedź
ai-chat-homepage-active = Aktywna
ai-chat-homepage-paused = Wstrzymana
ai-chat-homepage-waits-for-review = Czeka na przegląd
ai-chat-homepage-completed = Ukończona
ai-chat-homepage-dropped = Porzucona
ai-chat-homepage-unknown = Nieznana
cards-result-cards-submitted-by-board = Przekazane przez tablicę: ustalenie z raportu, { $kind ->
        [sourced] ze źródłem
        [inferred] wywnioskowane
        [not_found] „nie znaleziono”
       *[other] nieznanego rodzaju
    }
cards-result-cards-finding-for-board = { $kind ->
        [sourced] Ustalenie ze źródłem dla tablicy
        [inferred] Ustalenie wywnioskowane dla tablicy
        [not_found] Ustalenie „nie znaleziono” dla tablicy
       *[other] Ustalenie nieznanego rodzaju dla tablicy
    }
chat-transcript-compacting = Zagęszczanie kontekstu: z { $before } do { $target } tokenów.
chat-transcript-compaction-failed = Nie udało się utworzyć podsumowania wcześniejszych kroków. Model otrzymał wcześniejsze kroki bez zmian, liczba tokenów: { $after }.
chat-transcript-compacted = Kontekst zagęszczony: podsumowane kroki: { $steps }, tokeny: z { $before } do { $after }.
ai-chat-board-reopen-with-more = Otwórz ponownie z dodatkowymi eksploracjami: { $grant }
ai-chat-board-goal-number = Cel { $number }
ai-chat-board-from-assessment-on = Z oceny { $number } z dnia { $date }.
ai-chat-board-from-assessment = Z oceny { $number }.
chat-board-create-goal-2 = Cel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = utracono połączenie z czatem: { $e }
ai-chat-session-could-not-stop-the-answer = nie udało się zatrzymać odpowiedzi: { $e } – nadal trwa
ai-chat-board-later-assessments-dropped-an-answer = Późniejsze oceny ({ $n }) porzuciły odpowiedź na ten cel:
ai-chat-board-prompt-and-completion-tokens = tokeny promptu: { $a_prompt_tokens }, tokeny odpowiedzi: { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = Ukończona, cele bez odpowiedzi: { $n }
board-graph-intent = zamiar, { $state }
chat-workspace-pane-characters = Liczba znaków: { $chars }
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + trwające { $if_joined_live_end_1_tr_chat_transcript_ } narzędzia: { $joined_live_end }
chat-transcript-running-tool-2 = Trwające { $if_turn_tool_rows_len_1_tr_chat_transcri } narzędzia: { $turn_tool_rows_len }
chat-transcript-answered-after-failed-attempt = Odpowiedź po nieudanych próbach: { $retries_len }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = Nieudane próby: { $retries_len }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, wersja { $report_version }
tool-run-summary-searched = { $n ->
        [one] wyszukano { $n } wyrażenie
        [few] wyszukano { $n } wyrażenia
        [many] wyszukano { $n } wyrażeń
       *[other] wyszukano { $n } wyrażenia
    }
tool-run-summary-read = { $n ->
        [one] przeczytano { $n } dokument
        [few] przeczytano { $n } dokumenty
        [many] przeczytano { $n } dokumentów
       *[other] przeczytano { $n } dokumentu
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] wyszukano w internecie { $n } wyrażenie
        [few] wyszukano w internecie { $n } wyrażenia
        [many] wyszukano w internecie { $n } wyrażeń
       *[other] wyszukano w internecie { $n } wyrażenia
    }
tool-run-summary-read-web = { $n ->
        [one] przeczytano { $n } stronę internetową
        [few] przeczytano { $n } strony internetowe
        [many] przeczytano { $n } stron internetowych
       *[other] przeczytano { $n } strony internetowej
    }
tool-run-summary-browser = { $n ->
        [one] { $n } działanie w przeglądarce
        [few] { $n } działania w przeglądarce
        [many] { $n } działań w przeglądarce
       *[other] { $n } działania w przeglądarce
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] wypisano encje { $n } dokumentu
        [few] wypisano encje { $n } dokumentów
        [many] wypisano encje { $n } dokumentów
       *[other] wypisano encje { $n } dokumentu
    }
tool-run-summary-cited = { $n ->
        [one] zacytowano { $n } dokument
        [few] zacytowano { $n } dokumenty
        [many] zacytowano { $n } dokumentów
       *[other] zacytowano { $n } dokumentu
    }
tool-run-summary-cited-web = { $n ->
        [one] zacytowano { $n } stronę internetową
        [few] zacytowano { $n } strony internetowe
        [many] zacytowano { $n } stron internetowych
       *[other] zacytowano { $n } strony internetowej
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] przeczytano { $n } umiejętność i opisy narzędzi
        [few] przeczytano { $n } umiejętności i opisy narzędzi
        [many] przeczytano { $n } umiejętności i opisy narzędzi
       *[other] przeczytano { $n } umiejętności i opisy narzędzi
    }
tool-run-summary-saved = { $n ->
        [one] zapisano { $n } notatkę
        [few] zapisano { $n } notatki
        [many] zapisano { $n } notatek
       *[other] zapisano { $n } notatki
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } wywołanie listy zadań
        [few] { $n } wywołania listy zadań
        [many] { $n } wywołań listy zadań
       *[other] { $n } wywołania listy zadań
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instrukcja dla agenta
        [few] { $n } instrukcje dla agenta
        [many] { $n } instrukcji dla agenta
       *[other] { $n } instrukcji dla agenta
    }
tool-run-summary-other = { $n ->
        [one] { $n } inne wywołanie
        [few] { $n } inne wywołania
        [many] { $n } innych wywołań
       *[other] { $n } innego wywołania
    }
tool-run-summary-failed = nieudane: { $failures }
tool-run-summary-took = trwało { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } wiadomość
    [few] { $session_message_count } wiadomości
    [many] { $session_message_count } wiadomości
    *[other] { $session_message_count } wiadomości
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } element
        [few] { $count } elementy
        [many] { $count } elementów
       *[other] { $count } elementu
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } pole
        [few] { $count } pola
        [many] { $count } pól
       *[other] { $count } pola
    }
chat-tool-disclosure-searched-collections = przeszukano kolekcje{ $filters }
chat-tool-disclosure-searched-collections-2 = przeszukano kolekcje · { $query }{ $filters }
chat-tool-disclosure-cited-documents = zacytowano dokumenty: { $n }
chat-tool-disclosure-read-document = przeczytano dokument · { $path }
chat-tool-disclosure-searched-the-web = przeszukano internet · { $q }
chat-tool-disclosure-opened-page = otwarto stronę · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = wywołano { $other }
chat-tool-disclosure-called-2 = wywołano { $other } · { $short }
cards-browser-card-opened = otwarto { $url }
cards-browser-card-could-not-open = nie udało się otworzyć { $url }
cards-browser-card-clicked = kliknięto { $element }
cards-browser-card-could-not-click = nie udało się kliknąć { $element }
cards-browser-card-typed-into = wpisano w { $element }
cards-browser-card-could-not-type-into = nie udało się wpisać w { $element }
cards-browser-card-typed = wpisano „{ $text }”
cards-browser-card-could-not-type = nie udało się wpisać „{ $text }”
cards-browser-card-pressed = naciśnięto { $key }
cards-browser-card-could-not-press = nie udało się nacisnąć { $key }
cards-browser-card-chose-an-option-in = wybrano opcję w { $element }
cards-browser-card-could-not-choose-an-option = nie udało się wybrać opcji w { $element }
cards-browser-card-hovered = najechano na { $element }
cards-browser-card-could-not-hover = nie udało się najechać na { $element }
cards-browser-card-failed = { $bare } – niepowodzenie
cards-entities-card-listed-entities-document = wypisano encje · dokumenty: { $count }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · część { $part } z { $name } #{ $seq }
cards-result-cards-documents = {" "}· dokumenty: { $value }
cards-result-cards-forms = { $tool_name } · formy: { $forms }
cards-result-cards-in = {" "}w: { $collections }
cards-result-cards-page = {" "}· strona { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · dokumenty: { $citations_len } · nieznalezione cytaty: { $missing }
cards-result-cards-version-unchanged = { $tool_name } · wersja { $version } · bez zmian
cards-result-cards-version = { $tool_name } · wersja { $version }
web-search-card-results-in-after-deduplication = Wyniki na wejściu: { $json_u64_doc_total_before_dedupe }, po usunięciu duplikatów: { $json_u64_doc_total_after_dedupe }

board-status-on = Włączone

board-status-off = Wyłączone

chat-transcript-generic-tool = narzędzie
