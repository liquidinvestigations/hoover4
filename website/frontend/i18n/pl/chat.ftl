# Machine translation of en/chat.ftl. Do not edit by hand: change the English catalog
# and run scripts/i18n/translate_catalogs.py. See translations.json for the producer.

chat-activity-the-bot-is-working = Bot pracuje...
chat-composer-ask-the-bot = Zapytaj bota...
chat-composer-internet-tools = Narzędzia internetowe
chat-composer-agent-language-title = Agent odpowiada w języku { $language }. Zmień język w ustawieniach, w nowej karcie.
chat-composer-try-again-in-s = Spróbuj ponownie za { $secs } s
chat-composer-stop-the-answer-the-partial = Zatrzymaj odpowiedź (częściowa odpowiedź nie jest zapisana w rozmowie)
chat-composer-starting-the-conversation-u = Rozpoczęcie rozmowie…
chat-composer-send = Wyślij
chat-conversation-find-search-in-conversation = Szukaj w rozmowie
chat-conversation-find-previous-match = Poprzecznym dopasowaniu
chat-conversation-find-next-match = Następne dopasowanie
chat-conversation-find-investigation-board = Tablica śledcza
doc-ref-card-not-openable = Nieotwiralne: { $reason }.
doc-ref-card-the-search-term-was = Wyszukiwane słowo{ " " }
doc-ref-card-open = Otwórz
doc-ref-card-not-openable-2 = Nieotwiralne
chat-markdown-text-show-the-cited-source = Pokaż cytowane źródło
chat-markdown-text-no-citation-of-this-conversation = Żadne cytaty tej rozmowy nie przyznały tego oznaczenia, więc nie stoi za nim żaden dokument.
chat-markdown-text-citations-of-this-conversation-gave = Cytaty tej rozmowy przyznały tego oznaczenia więcej niż jednym dokumentom, więc nie łączy z żadnym z nich.
cards-browser-card-open-the-archived-page = Otwórz zarchiwizowaną stronę
cards-browser-card-the-page-itself-was-not = Sama strona nie została zarchiwizowana (status: { $artifact_status }). Powyższy zrzut ekranu to to, co zachowano.
cards-browser-card-click-the-screenshot-to-open = Kliknij zrzut ekranu, aby otworzyć zarchiwizowaną stronę.
cards-browser-card-show-less = Pokaż mniej
cards-browser-card-show-all = Pokaż wszystkie
cards-browser-card-archived-page = Zarchiwizowana strona
cards-browser-card-download = Pobierz
cards-browser-card-archived-copy-of = Zarchiwizowana kopia { $artifact_url }
cards-browser-card-this-page-was-not-archived = Ta strona nie została zarchiwizowana (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } z kartą
cards-entities-card-the-entity-list-was-cut = Lista encji została obcięta.
cards-entities-card-open-the-card-for-this = Otwórz kartę dla tej wartości ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Żadna karta: ta rozmowa nigdy nie wskazała zbioru danych, z którego pochodzą te wartości, a odbiorca jest adresowany przez zbiór danych.
cards-entities-card-more-all-of-them-in = { $rest } więcej, wszystkie w panelu encji dokumentu.
cards-entities-card-names-organisations-and-places-above = Nazwy, organizacje i miejsca powyżej to odczyt prozy przez model. Żadne reguły ich nie zweryfikowały, więc nie ma czego wyjaśniać i nic nie otwierają.
cards-entities-card-nothing-extracted-from-this-document = Nic nie wyekstrahowano z tego dokumentu.
chat-tool-cards-hide = Ukryj
chat-tool-cards-expand = Rozwiń
chat-tool-cards-hide-raw-json = Ukryj surowy JSON
chat-tool-cards-show-raw-json = Pokaż surowy JSON
cards-result-cards-search-this = Szukaj tego
cards-result-cards-search-every-collection = Szukaj we wszystkich kolekcjach
cards-result-cards-form = Formularz { $index }: { $form }
cards-result-cards-show-full-text = Pokaż pełny tekst
cards-result-cards-quote = Cytat: { $quote }
cards-result-cards-reason = Powód: { $why }
cards-result-cards-open-question = Otwarte pytanie: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Eksploracja dała ten wynik swojej tablicy jako { $kind ->
        [sourced] wynik ze źródła
        [inferred] wynik wnioskowany
        [not_found] wynik nie znaleziony
       *[other] wynik nieznanego rodzaju
    }.
cards-result-cards-it-left-no-open-question = Nie zostawiło otwartego pytania.
cards-result-cards-open-questions-for-the-board = Otwarte pytania dla tablicy:
cards-result-cards-arguments = Argumenty
cards-result-cards-list-after-the-call = Lista po wywołaniu: { $snapshot_goal }
cards-result-cards-replaces = { " " }· zastępuje { $replaces_id }
cards-result-cards-the-list-at-this-version = Lista w tej wersji nie jest przechowywana.
web-search-card-these-sources-returned-nothing-so = Te źródła zwróciły nic, więc wyniki pochodzą z mniej niż zamierzono
web-search-card-u-degraded = ⚠ { $degraded_len } pogorszonych
web-search-card-form = Formularz { $index }: { $form }
web-search-card-no-results-from = Bez wyników z: { $degraded_text }
web-search-card-no-results-every-source-answered = Bez wyników. Każde źródło odpowiedziało i żadne nie miało nic dla tego zapytania.
web-search-card-the-lowest-ranked-results-were = Najniższe wyniki zostały odrzucone, żeby to wywołanie zmieściło się w transkrypcji. Asystent widział wszystkie.
web-search-card-view-search-details = Zobacz szczegóły wyszukiwania.
web-search-card-the-stored-result-could-not = przechowyany wynik nie mógł zostać odczytany jako JSON
web-search-card-nothing-was-stored-for-this = Nic nie zostało zapisane dla tego wywołania.
web-search-card-forms = Formularze: { $forms }
web-search-card-kind = Rodzaj: { $row_kind }
web-search-card-published = Opublikowano: { $row_published }
web-search-card-loading-search-detail-u = Ładowanie szczegółów wyszukiwania…
web-search-card-could-not-load-the-search = Nie udało się załadować szczegółów wyszukiwania: { $e }
web-search-card-malformed-detail = Niepoprawne szczegóły: { $e }
web-search-card-the-tool-returned-selected-results = Narzędie zwrócono wybrane wyniki dla modelu.
web-search-card-results-use-reciprocal-rank-fusion = Wyniki korzystają z fuzji reciprokowego rankingu.
web-search-card-returned-nothing = zwrócono nic: { $degraded }
web-search-card-all-candidates-use-fusion-order = Wszystkie kandydaci korzystają z kolejności fuzji.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoder rankuje wybrane wyniki.
web-search-card-selected-results-use-fusion-order = Wybrane wyniki korzystają z kolejności fuzji.
web-search-card-search-detail = Szczegóły wyszukiwania
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Szukaj tutaj
chat-tool-disclosure-search-every-collection = Szukaj we wszystkich kolekcjach
chat-tool-disclosure-hide = Ukryj
chat-tool-disclosure-expand = Rozwiń
chat-tool-disclosure-this-step-was-recorded-before = Ten krok został zarejestrowany przed zapisaniem argumentów i wyników narzędzia. Dostępny jest tylko poniższe podsumowanie.
chat-tool-disclosure-arguments = Argumenty
chat-tool-disclosure-result = Wynik
chat-tool-disclosure-hide-raw-json = Ukryj surowy JSON
chat-tool-disclosure-show-raw-json = Pokaż surowy JSON
chat-tool-disclosure-input-json = JSON wejściowy
chat-tool-disclosure-output-json = JSON wyjściowy
chat-transcript-ask-a-question-about-the = Zadaj pytanie dotyczące dokumentów w swoich kolekcjach.
chat-transcript-suggested-next = Sugerowany kolejny...
chat-transcript-earlier-answer = Poprzednia odpowiedź
chat-transcript-tokens-the-conversation-carries-the = Tokeny, które przenosi rozmowa, największy pojedynczy kontekst rozliczony w tej turze oraz ile miejsca z okna modelu zostało wykorzystane
chat-transcript-instruction-to-the-agent = Instrukcja dla agenta
chat-transcript-the-context-stays-above-the = Kontekst pozostaje powyżej celu { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } części podsumowań nie powiodły się. Rekord zawiera tylko listy.
chat-transcript-show-the-record = Pokaż rekord
chat-transcript-hide-reasoning = Ukryj rozumowanie
chat-transcript-show-reasoning = Pokaż rozumowanie
chat-transcript-from-u-hide = { $count } { $noun } z { $tool } — ukryj
chat-transcript-from-u-show = { $count } { $noun } z { $tool } — pokaż
chat-transcript-u-hide = { $summary } — ukryj
chat-transcript-u-show = { $summary } — pokaż
chat-transcript-citations-of-this-conversation-give = Cytaty tej rozmowy wskazują { $doc_handle } na więcej niż jeden dokument. Odpowiedź łączy go z żadnym z nich.
chat-transcript-report = Zgłoś { $label }
chat-transcript-open-in-the-workspace = Otwórz w przestrzeni roboczej
chat-transcript-this-version-could-not-be = Tej wersji nie można było odczytać. Poniżej znajduje się tekst czatu odpowiedzi.
chat-transcript-files = Pliki
chat-transcript-version = { $file_name }, wersja { $file_version }
chat-web-find-exact-text = Znajdokładny tekst
chat-web-previous-match = Poprzeczne dopasowanie
chat-web-next-match = Następane dopasowanie
chat-web-close-preview = Zamknij podgląd
chat-web-the-captured-page-could-not = Przechwyconą stronę nie można było załadować.
chat-web-loading = Ładowanie…
chat-workspace-pane-workspace = Przestrzeń robocza
chat-workspace-pane-close-the-workspace = Zamknij przestrzeń roboczą
chat-workspace-pane-close = Zamknij
chat-workspace-pane-loading-the-files-u = Ładowanie plików…
chat-workspace-pane-the-files-could-not-be = Pliki nie mogły zostać załadowane: { $error }
chat-workspace-pane-this-conversation-has-no-files = Ta rozmowa nie ma plików.
chat-workspace-pane-version = wersja { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Wybierz plik, aby go przeczytać.
chat-workspace-pane-loading-the-file-u = Przesyłanie pliku…
chat-workspace-pane-the-file-could-not-be = Nie udało się przesłać pliku: { $error }
chat-workspace-pane-version-2 = { $found_name }, wersja { $found_version }
chat-board-create-collections = Kolekcje
chat-board-create-loading-collections-u = Przesyłanie kolekcji…
chat-board-create-hoover-search-new-board = Hoover Search – nowa tablica
chat-board-create-ai-chat = Czat AI
chat-board-create-new-investigation-board = Nowa tablica śledcza
chat-board-create-a-board-runs-its-goals = Tablica realizuje swoje cele jako ciąg eksploracji przez agenta. Każda eksploracja to czat, który kończy się jednym wynikiem tablicy. Przeglądasz odpowiedź każdego celu i możesz odrzucać wyniki oraz dodawać wskazówki w trakcie działania.
chat-board-create-title = Tytuł
chat-board-create-goal = Cel
chat-board-create-remove-this-goal = Usuń ten cel
chat-board-create-remove = Usuń
chat-board-create-add-a-goal = Dodaj cel
chat-board-create-context-optional = Kontekst (opcjonalnie)
chat-board-create-hints-one-per-line-optional = Wskazówki, po jednej w linii (opcjonalnie)
chat-board-create-sources = Źródła
chat-board-create-internet-tools = Narzędzia internetowe
chat-board-create-creating-board = Tworzenie tablicy...
chat-board-create-create-board = Tworzenie tablicy
ai-chat-board-hoover-search-board = Hoover Search – tablica
ai-chat-board-loading-the-board-u = Przesyłanie tablicy…
ai-chat-board-show-the-board-overview = Pokaż przegląd tablicy
ai-chat-board-zoom-out = Pomniejsz
ai-chat-board-zoom-in = Powiększ
ai-chat-board-u-ai-chat = ← Czat AI
ai-chat-board-settings = Ustawienia
ai-chat-board-board-settings = Ustawienia tablicy
ai-chat-board-internet-tools = Narzędzia internetowe
ai-chat-board-the-next-explores-of-the = Następujące eksploracje tablicy mogą szukać w sieci i czytać strony internetowe. Trwające eksploracje zachowują ustawienie, z którego zaczęły.
ai-chat-board-collections = Kolekcje
ai-chat-board-the-collections-are-fixed-when = Kolekcje są ustalone w momencie utworzenia tablicy.
ai-chat-board-confirm-drop = Potwierdź usunięcie
ai-chat-board-drop-the-board = Usuń tablicę
ai-chat-board-close = Zamknij
ai-chat-board-the-board-used-its-explore = Tablica wyczerpała limit przeglądania
ai-chat-board-the-board-used-explores-the = Tablica wykorzystała { $explore_limit } przeglądania, czyli limit jednej tablicy. Nie uruchamia więcej pracy. Możesz nadal decydować o proponowanych odpowiedziach.
ai-chat-board-create-a-new-board-to = Utwórz nową tablicę, aby kontynuować śledzenie
ai-chat-board-goal = Cel
ai-chat-board-goals = Cele
ai-chat-board-add-new-goal = Dodaj nowy cel...
ai-chat-board-a-new-goal = Nowy cel
ai-chat-board-add-goal = Dodaj cel
ai-chat-board-a-board-has-at-most = Tablica może mieć najwyżej { $max_goals } celów. Utwórz nową tablicę dla innego celu.
ai-chat-board-background-context = Kontekst tła
ai-chat-board-continue-with-a-correction = Kontynuuj z poprawką
ai-chat-board-correction-what-is-wrong-or = Poprawka: co jest błędne lub brakujące. Tablica kontynuuje z nią.
ai-chat-board-the-board-waits-for-your = Tablica oczekuje na Twoją ocenę
ai-chat-board-the-board-used-its-budget = Tablica wyczerpała swój budżet { $snap_max_explores } przeglądania.
ai-chat-board-the-assessments-gave-no-usable = Oceny nie dały używalnego kierunku.
ai-chat-board-accept-or-reject-the-proposed = Zacceptuj lub odrzuć proponowaną odpowiedź każdego celu powyżej. Odrzucona odpowiedź pozwala tablicy kontynuować od razu.
ai-chat-board-no-proposed-answer-waits-for = Brak proponowanej odpowiedzi oczekującej na Twoją decyzję.
ai-chat-board-reopen-the-board-to-continue = Otwórz ponownie tablicę, aby kontynuować otwarte cele. Zachowuje swoje wyniki i odpowiedzi.
ai-chat-board-close-the-board-to-accept = Zamknij tablicę, aby zaakceptować wszystkie proponowane odpowiedzi i ją zatrzymać, lub kontynuować ją z poprawką.
ai-chat-board-close-the-board = Zamknij tablicę
ai-chat-board-or-reopen-the-board-to = Albo otwórz ponownie tablicę, aby kontynuować otwarte cele bez poprawki.
ai-chat-board-the-board-is-complete = Tablica jest kompletna
ai-chat-board-a-goal-has-no-accepted = Cel nie ma zaakceptowanej odpowiedzi. Otwórz ponownie tablicę, aby ją kontynuować. Tablica zachowuje swoje wyniki i odpowiedzi.
ai-chat-board-add-a-hint = Dodaj podpowiedź
ai-chat-board-the-next-assessment-reads-every = Następująca ocena odczyta każdą podpowiedź. Podpowiedź odpowiada też za przeglądanie, które zadało pytanie.
ai-chat-board-add-hint = Dodaj wskazówkę
ai-chat-board-events = Zdarzenia
ai-chat-board-newest-first = Najnowsze pierwsze
ai-chat-board-date = Data
ai-chat-board-actor = Wykonawca
ai-chat-board-event = Zdarzenie
ai-chat-board-show-details = Pokaż szczegóły
ai-chat-board-open = Otwórz
ai-chat-board-show-the-newest-events = Pokaż najnowsze { $event_rows } zdarzeń
ai-chat-board-show-all-events = Pokaż wszystkie { $snap_events_len } zdarzeń
ai-chat-board-statistics = Statystyki
ai-chat-board-explores = Badania
ai-chat-board-model-steps-per-explore = Kroki modelu w ramach jednego badania
ai-chat-board-assessments = Oceny
ai-chat-board-intents = Intencje
ai-chat-board-findings = Wyniki
ai-chat-board-created = Utworzono
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } odrzucił ten wynik w { $format_utc_ms_fact_rejected_ms }. Tablica przestała go używać.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } odrzucił ten wynik. Tablica przestała go używać.
ai-chat-board-no-reason-was-given = Nie podano powodu.
ai-chat-board-reason = Powód: { $fact_rejected_reason }
ai-chat-board-open-questions = Otwarte pytania
ai-chat-board-explored-in = Zbadano w{ " " }
ai-chat-board-explore-this-question = Zbadaj to pytanie
ai-chat-board-your-questions = Twoje pytania
ai-chat-board-ask-about-the-background-context = Zapytaj o kontekst tła
ai-chat-board-ask-about-this-finding = Zapytaj o ten wynik
ai-chat-board-a-follow-up-question-about = Pytanie uzupełniające dotyczące tego węzła
ai-chat-board-ask = Zapytaj
ai-chat-board-checks-that-changed-this-finding = Sprawdzenia, które zmieniły ten wynik
ai-chat-board-reject-this-correction = Odrzuć tę poprawkę
ai-chat-board-reject-this-finding = Odrzuć ten wynik
ai-chat-board-not-answered-the-board-was = Nie odpowiedziano. Tablica została zakończona bez odpowiedzi na ten cel. Wskazówka lub ponowne otwarcie ją przywraca.
ai-chat-board-no-answer-yet = Brak odpowiedzi.
ai-chat-board-the-findings-of-this-answer = Wyniki tej odpowiedzi to wyszukiwania, które nic nie znalazły. Zaakceptuj, aby odnotować, że rekordy nie odpowiadają na cel, lub odrzuć, aby kontynuować śledzenie.
ai-chat-board-open-an-assessment-to-read = { "." } Otwórz ocenę, aby przeczytać, dlaczego.
ai-chat-board-from-the-findings = Z wyników{ " " }
ai-chat-board-accept-answer = Zaakceptuj odpowiedź
ai-chat-board-why-the-answer-is-wrong = Dlaczego odpowiedź jest błędna lub niekompletna
ai-chat-board-reject-answer = Odrzuć odpowiedź
ai-chat-board-intent = Cel
ai-chat-board-attempts-declared = Próby: { $intent_attempts }. Ogłoszono { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Badanie zapytało
ai-chat-board-add-a-hint-in-the = Dodaj wskazówkę w przeglądzie tablicy, aby na nią odpowiedzieć.
ai-chat-board-last-error = Ostatni błąd
ai-chat-board-brief = Krótko
ai-chat-board-open-the-explore-chat = Otwórz czat badawczy
ai-chat-board-loading-the-assessment-u = Ładowanie oceny…
ai-chat-board-assessment = Ocena { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Wynik { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Sprawdzenia, które to zmieniły
ai-chat-board-prompt = Zapytanie
ai-chat-board-this-assessment-ran-before-the = Ta ocena uruchomiła się przed zapisaniem zapytań.
ai-chat-board-response = Odpowiedź
ai-chat-history-hoover-search-chat-history = Hoover Search — Historia czatu
ai-chat-history-u-back = ← Wróć
ai-chat-history-conversation-history = Historia rozmowy
ai-chat-history-show-board-chats = Pokaż czaty tablicy
ai-chat-history-loading-u = Ładowanie…
ai-chat-history-could-not-load-history = Nie udało się załadować historii: { $e }
ai-chat-history-no-conversations-yet = Brak dotychczasowych rozmów.
ai-chat-history-board = Tablica
ai-chat-history-new-chat = Nowa rozmowa
ai-chat-history-messages-updated = { $s_message_count } wiadomości · zaktualizowano { $s_updated_at }
ai-chat-history-delete-conversation = Usuń rozmowę
ai-chat-history-delete = Usuń
ai-chat-homepage-hoover-search-ai-chat = Hoover Search – Czat AI
ai-chat-homepage-what-are-you-researching = Nad czym pracujesz?
ai-chat-homepage-view-all-conversations = Zobacz wszystkie rozmowy
ai-chat-homepage-starting-conversation-u = Rozpoczynam rozmowę…
ai-chat-homepage-investigation-boards = Tablice śledcze
ai-chat-homepage-new-board = Nowa tablica
ai-chat-homepage-loading-boards-u = Ładowanie tablic…
ai-chat-homepage-could-not-load-the-boards = Nie udało się załadować tablic: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Nie masz żadnej tablicy. Tablica prowadzi długie śledztwo jako ciąg eksploracji przez agenta, a Ty przeglądasz jego odpowiedzi.
ai-chat-homepage-updated = Zaktualizowano { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search – Czat AI
ai-chat-session-this-conversation-could-not-be = Nie udało się załadować tej rozmowy.
ai-chat-session-loading-u = Ładowanie…
ai-chat-session-u-chats = ← Czat
ai-chat-session-history = Historia
ai-chat-session-show-the-files-that-the = Pokaż pliki, które asystent zapisał w tej rozmowie
ai-chat-session-workspace = Przestrzeń robocza
ai-chat-session-this-answer-was-interrupted-before = Ta odpowiedź została przerwana przed zakończeniem, ponieważ strona lub serwer zatrzymały się w trakcie odpowiedzi. Poproś ponownie, aby ponowić próbę.
ai-chat-session-dismiss = Zamknij
ai-chat-session-board-explore-chats-are-read = Rozmowy eksploracyjne tablicy mają charakter tylko do odczytu.{ " " }
ai-chat-session-open-the-board = Otwórz tablicę
chat-locked-options-on = { $label }: włącz
chat-locked-options-off = { $label }: wyłącz
chat-tool-cards-running-u = uruchamianie…
cards-result-cards-quote-found = Cytat znaleziony
cards-result-cards-quote-not-found = Cytat nie znaleziony
cards-result-cards-quote-not-checked = Cytat nie sprawdzony
web-search-card-results = { $results_len } wyników
chat-tool-disclosure-running-u = przetwarzanie…
chat-transcript-call = połączenie
chat-transcript-calls = połączenia
ai-chat-board-a-board-without-collections-needs = Tablica bez kolekcji wymaga narzędzi internetowych.
ai-chat-board-of = { $snap_explores_used } z { $snap_max_explores }
ai-chat-board-assessment-2 = ocena { $number }
ai-chat-history-messages = { $s_message_count } wiadomości
web-search-card-reranked-in = Cross-encoder posortował wyniki w ciągu { $ms } ms.
web-search-card-engine-results = { $name }: { $count } w { $ms } ms
web-search-card-score-was-rank = wynik { $score } · pozycja RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Tura czeka na wolne miejsce modelu.
chat-activity-the-turn-waits-for-a-2 = Tura czeka na wolne miejsce narzędzia.
chat-locked-options-start-a-new-chat-to = Rozpocznij nową rozmowę, aby zmienić to ustawienie.
chat-locked-options-internet-tools = Narzędzia internetowe
chat-session-card-new-chat = Nowa rozmowa
chat-tool-cards-first-frame-of-the-video = Pierwsza klatka wideo
chat-tool-cards-screenshot-of = Zrzut ekranu
chat-tool-cards-image = Obraz
cards-result-cards-the-agent-asked-a-question = Agent zadał pytanie.
chat-transcript-hide = Ukryj
chat-transcript-show = Pokaż
chat-transcript-unverified-quote-the-quoted-span = Niezweryfikowany cytat. Wycięty fragment jest zbyt krótki, aby go sprawdzić.
chat-transcript-unverified-quote-the-document-text = Niezweryfikowany cytat. Tekst dokumentu nie mógł zostać odczytany.
chat-transcript-unverified-quote-this-wording-was = Niezweryfikowany cytat. To sformułowanie nie zostało znalezione w dokumencie.
chat-board-create-select-a-collection-or-turn = Wybierz kolekcję lub włącz narzędzia internetowe.
chat-board-create-select-at-least-one-collection = Wybierz przynajmniej jedną kolekcję.
ai-chat-board-active = Aktywny
ai-chat-board-paused = Wstrzymano
ai-chat-board-waits-for-review = Oczekuje na recenzję
ai-chat-board-completed = Ukończono
ai-chat-board-dropped = Odrzucono
ai-chat-board-unknown = Nieznany
ai-chat-board-pause-the-board = Wstrzymaj tablicę
ai-chat-board-resume-the-board = Wznów tablicę
ai-chat-board-none = Brak
ai-chat-board-reopen-with-the-remaining-budget = Otwórz ponownie z pozostałym budżetem
ai-chat-board-finding = Wynik
ai-chat-board-why-the-correction-is-wrong = Dlaczego korekta jest błędna
ai-chat-board-reject-correction = Odrzuź korektę
ai-chat-board-why-the-finding-is-wrong = Dlaczego wynik jest błędny
ai-chat-board-reject-finding = Odrzuź wynik
ai-chat-board-answer = Odpowiedź
ai-chat-board-proposed-answer = Proponowana odpowiedź
ai-chat-homepage-active = Aktywny
ai-chat-homepage-paused = Wstrzymano
ai-chat-homepage-waits-for-review = Oczekuje na recenzję
ai-chat-homepage-completed = Ukończono
ai-chat-homepage-dropped = Odrzucono
ai-chat-homepage-unknown = Nieznany
cards-result-cards-submitted-by-board =
    Zgłoszone przez tablicę: { $kind ->
        [sourced] źródłowy
        [inferred] wywnioskowany
        [not_found] nie znaleziono
       *[other] nieznany rodzaj
    } wynik z raportu
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Źródłowy
        [inferred] Wywnioskowany
        [not_found] Nie znaleziono
       *[other] Nieznany rodzaj
    } wynik dla tablicy
chat-transcript-compacting = Kompaktowanie kontekstu: { $before } tokenów do celu { $target }.
chat-transcript-compaction-failed = Podsumowanie wcześniejszych kroków nie powiodło się. Model otrzymał wcześniejsze kroki bez zmian, { $after } tokenów.
chat-transcript-compacted = Kontekst skompaktowany: podsumowano { $steps } krok(ów), z { $before } tokenów na { $after }.
ai-chat-board-reopen-with-more = Otwórz ponownie o { $grant } dodatkowych eksploracji
ai-chat-board-goal-number = Cel { $number }
ai-chat-board-from-assessment-on = Z oceny { $number } na { $date }.
ai-chat-board-from-assessment = Z oceny { $number }.
chat-board-create-goal-2 = Cel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = utrata kontaktu z czatem: { $e }
ai-chat-session-could-not-stop-the-answer = nie udało się zatrzymać odpowiedzi: { $e } — nadal działa
ai-chat-board-later-assessments-dropped-an-answer = { $n } późniejszych ocen utraciło odpowiedź dla tego celu:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokenów promptu i { $a_completion_tokens } tokenów uzupełnienia
ai-chat-homepage-completed-goals-not-answered = Ukończone, { $n } celów bez odpowiedzi
board-graph-intent = intencja, { $state }
chat-workspace-pane-characters = { $chars } znaków
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } uruchamianie narzędzia { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } działanie narzędzia { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Odpowiedziano po { $retries_len } nieudanej próbie{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } nieudana próba{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, wersja { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] wyszukano { $n } termin
        [few] wyszukano { $n } terminy
        [many] wyszukano { $n } terminów
       *[other] wyszukano { $n } terminów
    }
tool-run-summary-read =
    { $n ->
        [one] odczytano { $n } dokument
        [few] odczytano { $n } dokumenty
        [many] odczytano { $n } dokumentów
       *[other] odczytano { $n } dokumentów
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] wyszukano w sieci { $n } termin
        [few] wyszukano w sieci { $n } terminy
        [many] wyszukano w sieci { $n } terminów
       *[other] wyszukano w sieci { $n } terminów
    }
tool-run-summary-read-web =
    { $n ->
        [one] odczytano { $n } stronę internetową
        [few] odczytano { $n } strony internetowe
        [many] odczytano { $n } stron internetowych
       *[other] odczytano { $n } stron internetowych
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } działanie przeglądarki
        [few] { $n } działania przeglądarki
        [many] { $n } działań przeglądarki
       *[other] { $n } działań przeglądarki
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] wymieniono encje { $n } dokumentu
        [few] wymieniono encje { $n } dokumentów
        [many] wymieniono encje { $n } dokumentów
       *[other] wymieniono encje { $n } dokumentów
    }
tool-run-summary-cited =
    { $n ->
        [one] cytowano { $n } dokument
        [few] cytowano { $n } dokumenty
        [many] cytowano { $n } dokumentów
       *[other] cytowano { $n } dokumentów
    }
tool-run-summary-cited-web =
    { $n ->
        [one] cytowano { $n } stronę internetową
        [few] cytowano { $n } strony internetowe
        [many] cytowano { $n } stron internetowych
       *[other] cytowano { $n } stron internetowych
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] odczytano { $n } tekst umiejętności i narzędzia
        [few] odczytano { $n } teksty umiejętności i narzędzi
        [many] odczytano { $n } teksty umiejętności i narzędzi
       *[other] odczytano { $n } teksty umiejętności i narzędzi
    }
tool-run-summary-saved =
    { $n ->
        [one] zapisano { $n } notatkę
        [few] zapisano { $n } notatki
        [many] zapisano { $n } notatek
       *[other] zapisano { $n } notatek
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } wywołanie listy zadań
        [few] { $n } wywołania listy zadań
        [many] { $n } wywołań listy zadań
       *[other] { $n } wywołań listy zadań
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } polecenie dla agenta
        [few] { $n } polecenia dla agenta
        [many] { $n } poleceń dla agenta
       *[other] { $n } poleceń dla agenta
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } inne wywołanie
        [few] { $n } inne wywołania
        [many] { $n } innych wywołań
       *[other] { $n } innych wywołań
    }
tool-run-summary-failed = { $failures } nieudanych
tool-run-summary-took = zajęło { $duration_text_ms }
chat-session-card-messages = { $session_message_count } wiadomości
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } element
       *[other] { $count } elementy
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } pole
       *[other] { $count } pola
    }
chat-tool-disclosure-searched-collections = przeszukane kolekcje{ $filters }
chat-tool-disclosure-searched-collections-2 = przeszukane kolekcje · { $query }{ $filters }
chat-tool-disclosure-cited-documents = cytowane { $n } dokumenty
chat-tool-disclosure-read-document = przeczytany dokument · { $path }
chat-tool-disclosure-searched-the-web = przeszukana sieć · { $q }
chat-tool-disclosure-opened-page = otwarta strona · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = wywołano { $other }
chat-tool-disclosure-called-2 = wywołano { $other } · { $short }
cards-browser-card-opened = otwarto { $url }
cards-browser-card-could-not-open = nie udało się otworzyć { $url }
cards-browser-card-clicked = kliknięto { $element }
cards-browser-card-could-not-click = nie udało się kliknąć { $element }
cards-browser-card-typed-into = wpisano do { $element }
cards-browser-card-could-not-type-into = nie udało się wpisywać do { $element }
cards-browser-card-typed = wpisano „{ $text }”
cards-browser-card-could-not-type = nie udało się wpisywać „{ $text }”
cards-browser-card-pressed = wciśnięto { $key }
cards-browser-card-could-not-press = nie udało się wcisnąć { $key }
cards-browser-card-chose-an-option-in = wybrano opcję w { $element }
cards-browser-card-could-not-choose-an-option = nie udało się wybrać opcji w { $element }
cards-browser-card-hovered = najechano kursorem na { $element }
cards-browser-card-could-not-hover = nie udało się najechać cursorem na { $element }
cards-browser-card-failed = { $bare } — niepowodzenie
cards-entities-card-listed-entities-document = wymienione encje · { $count } dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · część { $part } z { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } dokumenty
cards-result-cards-forms = { $tool_name } · { $forms } formularze
cards-result-cards-in = { " " }w { $collections }
cards-result-cards-page = { " " }· strona { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenty · { $missing } cytaty nie znalezione
cards-result-cards-version-unchanged = { $tool_name } · wersja { $version } · bez zmian
cards-result-cards-version = { $tool_name } · wersja { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } wyników, { $json_u64_doc_total_after_dedupe } po deduplikacji
