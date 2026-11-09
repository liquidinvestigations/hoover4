# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Wymagany dostęp administracyjny
admin-guard-signed-in-as = Zalogowano jako { $u_username }.
admin-guard-ask-an-administrator-for-access = Poproś administratora o dostęp do tej sekcji.
admin-shell-dashboard = Panel
admin-shell-collections = Kolekcje
admin-shell-operations = Operacje
admin-shell-errors-failures = Błędy/Niepowodzenia
admin-shell-feedback = Opinie
admin-shell-users = Użytkownicy
admin-shell-groups = Grupy
admin-shell-settings = Ustawienia
admin-shell-llm = LLM
admin-shell-ai-status = Stan AI
admin-shell-metrics = Metryki
admin-shell-administration = Administracja
dataset-create-panel-add-a-dataset = Dodaj zbiór danych
dataset-create-panel-the-dataset-mounts-could-not = Nie udało się odczytać punktów montowania zbiorów danych, więc nie ma z czego wybierać: { $err }
dataset-create-panel-loading-the-dataset-mounts = Wczytywanie punktów montowania zbiorów danych.
dataset-create-panel-no-dataset-mount-is-configured = Nie skonfigurowano żadnego punktu montowania zbiorów danych.
dataset-create-panel-the-mount-folder-could-not = Nie udało się odczytać folderu punktu montowania, więc nie ma z czego wybierać: { $err }
dataset-create-panel-no-subfolders-were-found-in = W tym punkcie montowania nie znaleziono podfolderów.{" "}
dataset-create-panel-folder = Folder
dataset-create-panel-select-a-folder = Wybierz folder
dataset-create-panel-new-folder = Nowy folder
dataset-create-panel-entries-already-a-dataset = { $option_name } (wpisy: { $option_entry_count }), już zbiór danych
dataset-create-panel-entries = { $option_name } (wpisy: { $option_entry_count })
dataset-create-panel-the-server-creates-this-folder = Serwer tworzy ten folder w punkcie montowania po utworzeniu zbioru danych.{" "}
dataset-create-panel-the-list-shows-the-direct = Lista pokazuje bezpośrednie podfoldery punktu montowania.
dataset-create-panel-dataset-name = Nazwa zbioru danych
dataset-create-panel-a-name-has-lowercase-letters = Nazwa zawiera małe litery, cyfry i podkreślenia. Wielkie litery zmieniają się w małe,{" "}
dataset-create-panel-the-dataset-is-saved-as = Zbiór danych zostanie zapisany jako: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Ta kolekcja ma zbiór danych o nazwie { $saved_name }.
dataset-create-panel-accept-uploads = Przyjmuj przesłane pliki
dataset-create-panel-creating-u = Tworzenie…
dataset-create-panel-create-and-ingest = Utwórz i zaimportuj
dataset-create-panel-mount = Punkt montowania
dataset-ocr-panel-last-operation = Ostatnia operacja: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , rozpoczęta { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Brak postępu od { $current_stale_seconds_60 } min. Sprawdź workflow Temporal i anuluj operację, jeśli utknęła.
dataset-ocr-panel-loading-u = Wczytywanie…
dataset-ocr-panel-stored-text-variants = Zapisane warianty tekstu
dataset-ocr-panel-searchable-pdfs = PDF-y z możliwością przeszukiwania
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · pliki: { $variant_pdf_count } · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = Czaty LLM na żywo
live-chats-panel-agent-turns-running-right-now = Tury agenta uruchomione w tej chwili, najdłużej trwające na początku. Odświeża się co 2 s. Dane pochodzą z Temporal, więc tura rozpoczęta przed ostatnim restartem witryny też tu jest.
live-chats-panel-loading-u = Wczytywanie…
live-chats-panel-no-chats-running = Żaden czat nie jest uruchomiony.
live-chats-panel-user = Użytkownik
live-chats-panel-conversation = Rozmowa
live-chats-panel-question = Pytanie
live-chats-panel-internet = Internet
live-chats-panel-running = Trwa
live-chats-panel-started = Rozpoczęto
live-chats-panel-cancels-the-workflow-the-turn = Anuluje workflow. Tura kończy się znacznikiem zatrzymania w zapisie rozmowy i nie znika.
live-chats-panel-kill = Przerwij
processing-updates-panel-loading-u = Wczytywanie…
processing-updates-panel-open-the-operation = Otwórz operację
processing-updates-panel-the-pipeline-has-not-calculated = Potok przetwarzania jeszcze nie obliczył tych aktualizacji.
processing-updates-panel-calculated-at-in-ms = Obliczono: { $view_checked_at }, w { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Aktualizacje automatyczne są wyłączone w tej instalacji. Uruchom aktualizacje przyciskiem.
processing-updates-panel-step = Krok
processing-updates-panel-count = Liczba
processing-updates-panel-state = Stan
processing-updates-panel-last-run = Ostatnie uruchomienie
processing-updates-panel-runs = Uruchomienia: { $step_runs }
processing-updates-panel-a-run-again-would-select = Przy ponownym uruchomieniu zostałaby wybrana mniej więcej taka liczba (jednostka: { $step_unit }).
processing-updates-panel-on-a-run-again = Przy ponownym uruchomieniu: { $step_pending } { $unit }
processing-updates-panel-never = Nigdy
processing-updates-panel-update-collection = Zaktualizuj kolekcję
processing-updates-panel-update-processing = Zaktualizuj przetwarzanie
processing-updates-panel-check-again = Sprawdź ponownie
processing-updates-panel-dataset = Zbiór danych
processing-updates-panel-processing-updates = Aktualizacje przetwarzania
admin-ai-status-admin-ai-status = Administracja: stan AI
admin-ai-status-ai-status = Stan AI
admin-ai-status-the-configured-service-and-the = Skonfigurowana usługa i usługa, która faktycznie odpowiada. Przełączenie awaryjne na usługę CPU widać tylko tutaj.
admin-ai-status-loading-u = Wczytywanie…
admin-ai-status-config-fingerprint = Odcisk konfiguracji
admin-ai-status-website-worker = Witryna / worker
admin-ai-status-ai-server = Serwer AI
admin-ai-status-match = Zgodność
admin-ai-status-embeddings-probe = Sonda embeddingów
admin-ai-status-dims = { $status_embeddings_serving_model } · wymiary: { $status_embeddings_serving_dim }
admin-ai-status-llm-configured = Skonfigurowany LLM
admin-ai-status-capabilities = Możliwości
admin-ai-status-capability = Możliwość
admin-ai-status-configured = Skonfigurowano
admin-ai-status-serving = Obsługuje
admin-ai-status-model = Model
admin-ai-status-reachable = Osiągalny
admin-ai-status-detail = Szczegóły
admin-ai-status-no = NIE
admin-ai-status-vector-shard-dims-vs-probe = Wymiary shardów wektorów a sonda
admin-ai-status-no-collections-yet = Nie ma jeszcze kolekcji.
admin-ai-status-collection = Kolekcja
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Zgodny z sondą
admin-ai-status-browser-router = Router przeglądarek
admin-ai-status-live-sessions = Sesje na żywo: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Ostatni ruch LLM (24 h)
admin-ai-status-no-llm-call-events-yet = Brak jeszcze llm_call_events.
admin-ai-status-user = Użytkownik
admin-ai-status-calls = Wywołania
admin-ai-status-errors = Błędy
admin-ai-status-service-use-24-h = Wykorzystanie usług % (24 h)
admin-ai-status-busy-seconds-in-the-last = Sekundy zajętości w ostatnich 24 godzinach jako udział doby.
admin-ai-status-no-samples-yet = Brak jeszcze próbek.
admin-ai-status-service = Usługa
admin-ai-status-busy-s = Zajęte s
admin-ai-status-use = Użycie %
admin-collection-detail-admin-collection = Administracja: kolekcja { $collection_id }
admin-collection-detail-failed-to-load-collection = Nie udało się wczytać kolekcji
admin-collection-detail-loading = Ładowanie...
admin-collection-detail-datasets = Zbiory danych
admin-collection-detail-dataset = Zbiór danych
admin-collection-detail-documents = Dokumenty
admin-collection-detail-size = Rozmiar
admin-collection-detail-indexed = Zindeksowane
admin-collection-detail-errors = Błędy
admin-collection-detail-state = Stan
admin-collection-detail-created = Utworzono
admin-collection-detail-settings = Ustawienia
admin-collection-detail-the-collection-database-is-not = Baza danych kolekcji nie jest jeszcze gotowa.
admin-collection-detail-the-last-storage-provisioning-failed = Ostatnie udostępnianie magazynu nie powiodło się: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Postęp przetwarzania i szacunki
admin-collection-detail-display-name = Nazwa wyświetlana
admin-collection-detail-display-name-2 = nazwa wyświetlana
admin-collection-detail-save = Zapisz
admin-collection-detail-access = Dostęp
admin-collection-detail-public-every-signed-in-user = Publiczna. Każdy zalogowany użytkownik może przeszukiwać i czytać tę kolekcję.
admin-collection-detail-restricted-only-members-of-the = Ograniczona. Tylko członkowie poniższych grup mogą przeszukiwać i czytać tę kolekcję.
admin-collection-detail-the-collection-is-now-public = Kolekcja jest teraz publiczna.
admin-collection-detail-the-collection-is-now-restricted = Kolekcja jest teraz ograniczona.
admin-collection-detail-make-restricted = Ogranicz dostęp
admin-collection-detail-make-public = Udostępnij publicznie
admin-collection-detail-group-permissions = Uprawnienia grup
admin-collection-detail-no-group-can-read-this = Żadna grupa nie może jeszcze czytać tej kolekcji.
admin-collection-detail-revoke = Odbierz
admin-collection-detail-grant-group-u = Nadaj grupie…
admin-collection-detail-grant = Nadaj
admin-collection-detail-danger-zone = Strefa zagrożenia
admin-collection-detail-a-collection-can-only-be = Kolekcję można usunąć tylko wtedy, gdy nie ma zbiorów danych.
admin-collection-detail-deleting-the-collection-also-drops = Usunięcie kolekcji usuwa też jej bazę danych{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}i wszystko, co w niej jest. Nie można tego cofnąć. Wpisz nazwę kolekcji, aby potwierdzić.
admin-collection-detail-collection-name = Nazwa kolekcji
admin-collection-detail-delete-collection = Usuń kolekcję
admin-collection-detail-features = Funkcje
admin-collection-detail-vectors = Wektory
admin-collection-detail-this-installation-runs-no-embedding = Ta instalacja nie uruchamia usługi embeddingów, więc żadna kolekcja nie używa wektorów.
admin-collection-detail-vectors-find-passages-by-meaning = Wektory znajdują fragmenty według znaczenia. Wyłączenie zatrzymuje tworzenie nowych wektorów i używanie zapisanych w wyszukiwaniu, a zapisane wektory zostają. Włączenie oblicza brakujące wektory każdego zbioru danych, po jednym zbiorze naraz.
admin-collection-detail-this-collection-follows-the-installation = Ta kolekcja podąża za instalacją, która używa wektorów. Wektory znajdują fragmenty według znaczenia. Wyłączenie zatrzymuje tworzenie nowych wektorów i używanie zapisanych w wyszukiwaniu, a zapisane wektory zostają.
admin-collection-processing-could-not-load-this-panel = Nie udało się wczytać tego panelu: { $message }
admin-collection-processing-admin-processing-of = Administracja: przetwarzanie { $collection_id }
admin-collection-processing-u-back-to-collection = ← Wróć do kolekcji
admin-collection-processing-processing-stages = Etapy przetwarzania
admin-collection-processing-loading-u = Wczytywanie…
admin-collection-processing-the-collection-database-is-still = Baza danych kolekcji jest jeszcze przygotowywana.
admin-collection-processing-this-collection-has-no-datasets = Ta kolekcja nie ma jeszcze zbiorów danych.
admin-collection-processing-eta = ETA { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Brak jeszcze próbek do szacunku. Są zbierane w trakcie przetwarzania zbioru danych.
admin-collection-processing-estimated-completion = Szacowane ukończenie:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(za { $humanize_seconds_c_eta_seconds }, szacunek orientacyjny, nie gwarancja terminu)
admin-collection-processing-no-current-estimate-the-pipeline = Brak aktualnego szacunku. Potok przetwarzania zakończył pracę lub nie robi mierzalnych postępów.
admin-collection-processing-where-processing-time-goes = Na co idzie czas przetwarzania
admin-collection-processing-no-task-executions-recorded-yet = Nie zapisano jeszcze żadnych wykonań zadań. Każda aktywność uruchamiana przez potok zapisuje tu jeden wiersz, więc pusta tabela oznacza, że od wdrożenia instrumentacji nic nie przetworzono.
admin-collection-processing-summed-task-time = Łączny czas zadań
admin-collection-processing-wall-clock = Czas rzeczywisty
admin-collection-processing-achieved-parallelism = Osiągnięta równoległość
admin-collection-processing-summed-task-time-divided-by = Łączny czas zadań podzielony przez czas rzeczywisty to równoległość, którą potok faktycznie osiągnął. Wartość bliska 1 oznacza, że cały koszt tworzy najwyższe zadanie poniżej i warto je zoptymalizować. Wartość bliska liczbie slotów workerów oznacza, że sloty są nasycone, a tańszym rozwiązaniem jest dodanie workerów. Czas rzeczywisty obejmuje okres od pierwszego do ostatniego wykonania, razem z czasem bezczynności.
admin-collection-processing-task = Zadanie
admin-collection-processing-total = Razem
admin-collection-processing-share = Udział
admin-collection-processing-executions = Wykonania
admin-collection-processing-mean = Średnia
admin-collection-processing-max = Maks.
admin-collection-processing-failed = Nieudane
admin-collection-processing-live-activity = Aktywność na żywo
admin-collection-processing-nothing-running-no-activity-finished = Nic nie działa. W ciągu ostatnich { $live_window_seconds } s nie zakończyła się żadna aktywność i żaden worker nie zgłasza niczego w toku.
admin-collection-processing-in-flight = W toku
admin-collection-processing-average-concurrency = Średnia współbieżność
admin-collection-processing-task-time-in-window = Czas zadań w oknie
admin-collection-processing-share-of-processing-time-over = Udział w czasie przetwarzania w ciągu ostatnich { $live_window_seconds } s, odświeżany co 5 s. Wykonanie, które przecina brzeg okna, liczy się tylko w części wewnątrz okna. Wiersz z wykonaniami w toku, ale bez udziału, to zadanie rozpoczęte przed oknem i jeszcze niezakończone. Sprawdź jego wiek.
admin-collection-processing-share-of-window = Udział w oknie
admin-collection-processing-task-time = Czas zadań
admin-collection-processing-completed = Ukończone
admin-collection-processing-oldest-running = Najstarsze w toku
admin-collection-processing-temporal-workflows = Workflow Temporal
admin-collection-processing-workflows-of-this-collection-s = Workflow zbiorów danych tej kolekcji, razem z workflow podrzędnymi.
admin-collection-processing-no-workflows-match-this-filter = Żaden workflow nie pasuje do tego filtra.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Typ
admin-collection-processing-status = Status
admin-collection-processing-started = Rozpoczęto
admin-collection-processing-closed = Zamknięto
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = otwórz ↗
admin-collection-processing-failed-tasks = Nieudane zadania
admin-collection-processing-no-task-failures-recorded = Nie zapisano żadnych niepowodzeń zadań.
admin-collection-processing-dataset = Zbiór danych
admin-collection-processing-errors = Błędy
admin-collection-processing-documents = Dokumenty
admin-collection-processing-last-seen = Ostatnio widziano
admin-collection-processing-sample = Próbka
admin-collection-processing-retry = Ponów
admin-collection-processing-failures-per-document = Niepowodzenia według dokumentu
admin-collection-processing-no-document-failures-recorded = Nie zapisano żadnych niepowodzeń dokumentów.
admin-collection-processing-document = Dokument
admin-collections-list-admin-collections = Administracja: kolekcje
admin-collections-list-collections = Kolekcje
admin-collections-list-loading-collections-u = Wczytywanie kolekcji…
admin-collections-list-datasets = Zbiory danych
admin-collections-list-loading-datasets-u = Wczytywanie zbiorów danych…
admin-collections-list-add-a-collection = Dodaj kolekcję
admin-collections-list-name-for-example-enron = Nazwa, na przykład enron
admin-collections-list-display-name = Nazwa wyświetlana
admin-collections-list-add-collection = Dodaj kolekcję
admin-collections-list-a-name-has-lowercase-letters = Nazwa zawiera małe litery, cyfry i podkreślenia. Wielkie litery zmieniają się w małe,{" "}
admin-collections-list-the-collection-is-saved-as = Kolekcja zostanie zapisana jako: { $new_name }
admin-collections-list-a-collection-with-the-name = Kolekcja o nazwie { $new_name } już istnieje.
admin-collections-list-collection = Kolekcja
admin-collections-list-documents = Dokumenty
admin-collections-list-size = Rozmiar
admin-collections-list-errors = Błędy
admin-collections-list-state = Stan
admin-collections-list-access = Dostęp
admin-collections-list-database-not-ready = Baza danych niegotowa
admin-collections-list-public = Publiczna
admin-collections-list-1-group = 1 grupa
admin-collections-list-not-counted-yet = Jeszcze nie policzono
admin-collections-list-unknown = Nieznany
admin-collections-list-no-collection-has-a-dataset = Żadna kolekcja nie ma zbioru danych.
admin-collections-list-dataset = Zbiór danych
admin-collections-list-indexed = Zindeksowane
admin-collections-list-created = Utworzono
admin-dashboard-admin-dashboard = Administracja: panel
admin-dashboard-administration = Administracja
admin-dashboard-users = Użytkownicy
admin-dashboard-groups = Grupy
admin-dashboard-collections = Kolekcje
admin-dashboard-datasets = Zbiory danych
admin-dashboard-failed-to-load-counts = Nie udało się wczytać liczników: { $e }
admin-dataset-detail-admin-dataset = Administracja: zbiór danych { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Nie udało się wczytać zbioru danych
admin-dataset-detail-loading = Ładowanie...
admin-dataset-detail-metadata = Metadane
admin-dataset-detail-display-name = Nazwa wyświetlana
admin-dataset-detail-name = Nazwa
admin-dataset-detail-type = Typ
admin-dataset-detail-path = Ścieżka
admin-dataset-detail-created = Utworzono
admin-dataset-detail-collection = Kolekcja
admin-dataset-detail-save = Zapisz
admin-dataset-detail-statistics = Statystyki
admin-dataset-detail-state = Stan
admin-dataset-detail-documents = Dokumenty
admin-dataset-detail-size = Rozmiar
admin-dataset-detail-indexed = Zindeksowane
admin-dataset-detail-errors = Błędy
admin-dataset-detail-plans-finished = Ukończone plany
admin-dataset-detail-disk = Dysk
admin-dataset-detail-rescan-disk-reads-the-dataset = Przeskanuj dysk ponownie czyta folder zbioru danych, dodaje nowe i zmienione pliki oraz je przetwarza.
admin-dataset-detail-rescan-disk = Przeskanuj dysk
admin-dataset-detail-danger-zone = Strefa zagrożenia
admin-dataset-detail-this-deletes-the-dataset-and = To usuwa zbiór danych i wszystkie dane z niego wyodrębnione. Nie można tego cofnąć.
admin-dataset-detail-delete-dataset-and-its-data = Usuń zbiór danych i jego dane
admin-dataset-detail-accept-uploads = Przyjmuj przesłane pliki
admin-dataset-detail-the-folder-of-this-dataset = Folder tego zbioru danych nie leży w zapisywalnym punkcie montowania zbiorów danych, więc nie przyjmuje przesyłanych plików.
admin-dataset-detail-starting-u = Uruchamianie…
admin-failure-detail-admin-failure = Administracja: niepowodzenie { $op_id }
admin-failure-detail-loading-tree = Wczytywanie drzewa…
admin-failure-detail-back-to-errors-and-failures = Wróć do błędów i niepowodzeń
admin-failure-detail-operations = Operacje
admin-failure-detail-scrubbed-copy-written-to-the = Oczyszczoną kopię zapisano w schowku.
admin-failure-detail-this-tree-is-truncated-at = To drzewo jest obcięte. Co najmniej jedno przechwycenie pominęło węzły.
admin-failure-detail-the-captured-tree-has-expired = Przechwycone drzewo wygasło. Wiersz operacji nadal istnieje.
admin-failure-detail-no-captured-nodes-for-this = Brak przechwyconych węzłów dla tej operacji.
admin-failure-detail-operation = Operacja
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · korzenie: { $root_count } · węzły: { $tree_nodes_len }
admin-failure-detail-open-in-temporal = Otwórz w Temporal
admin-failure-detail-scrubbed-copy = Oczyszczona kopia
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Oczyszczona kopia zastępuje ścieżki zbiorów danych skrótami, a długie wartości ich długościami.
admin-failure-detail-copy-scrubbed-record = Kopiuj oczyszczony zapis
admin-failure-detail-tree = Drzewo
admin-failure-detail-root = Korzeń ·{" "}
admin-failure-detail-node-parent-depth-source-stage = węzeł { $node_node_index } · rodzic { $node_parent_index } · głębokość { $node_depth } · źródło { $node_source } · etap { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = workflow { $node_workflow_id } · uruchomienie { $node_run_id } · aktywność { $node_activity_id } · próba { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = Pominięte węzły przy tym przechwyceniu: { $node_nodes_dropped }
admin-failures-admin-errors-and-failures = Administracja: błędy i niepowodzenia
admin-failures-errors-failures = Błędy/Niepowodzenia
admin-failures-loading-failures = Wczytywanie niepowodzeń…
admin-failures-operational-failures = Niepowodzenia operacji
admin-failures-no-operational-failures-at-this = W tej chwili nie ma niepowodzeń operacji.
admin-failures-collection = Kolekcja
admin-failures-dataset = Zbiór danych
admin-failures-task-name = Nazwa zadania
admin-failures-error-class = Klasa błędu
admin-failures-operation-kind = Rodzaj operacji
admin-failures-from = Od
admin-failures-to = Do
admin-failures-no-captured-failures-match-these = Żadne przechwycone niepowodzenie nie pasuje do tych filtrów.
admin-failures-signature = Sygnatura
admin-failures-count = Liczba
admin-failures-class = Klasa
admin-failures-task = Zadanie
admin-failures-last-seen = Ostatnio widziano
admin-failures-newer = Nowsze
admin-failures-page = Strona { $current_page_1 }
admin-failures-older = Starsze
admin-failures-per-page = Na stronę
admin-failures-loading-instances = Wczytywanie wystąpień…
admin-failures-no-instances-for-this-signature = Brak wystąpień dla tej sygnatury.
admin-failures-node = {" "}węzeł { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Błędy dokumentów
admin-failures-error-text = Treść błędu
admin-failures-loading-document-errors-u = Wczytywanie błędów dokumentów…
admin-failures-no-document-errors-match-these = Żaden błąd dokumentu nie pasuje do tych filtrów.
admin-failures-errors-by-dataset-and-task = Błędy według zbioru danych i zadania
admin-failures-documents = Dokumenty
admin-failures-show-only-this-dataset-and = Pokaż tylko ten zbiór danych i zadanie
admin-failures-total = Razem
admin-failures-errors = Błędy
admin-failures-document = Dokument
admin-failures-runs = Uruchomienia
admin-failures-error = Błąd
admin-failures-dataset-step = Krok zbioru danych
admin-failures-previous-page = Poprzednia strona
admin-failures-page-of-1-error = Strona { $page } z { $pages }, 1 błąd
admin-failures-page-of-errors = Strona { $page } z { $pages }, błędy: { $data_total }
admin-failures-next-page = Następna strona
admin-feedback-admin-feedback = Administracja: opinie
admin-feedback-feedback = Opinie
admin-feedback-search-titles-descriptions-accounts-and = Szukaj w tytułach, opisach, kontach i adresach
admin-feedback-search = Szukaj
admin-feedback-loading-reports-u = Wczytywanie zgłoszeń…
admin-feedback-1-report-matches = Pasuje 1 zgłoszenie.
admin-feedback-reports-match = Pasujące zgłoszenia: { $data_total }.
admin-feedback-received = Odebrano
admin-feedback-type = Typ
admin-feedback-title = Tytuł
admin-feedback-from = Od
admin-feedback-captures = Przechwycenia
admin-feedback-state = Stan
admin-feedback-previous-page = Poprzednia strona
admin-feedback-page-of = Strona { $page } z { $pages }
admin-feedback-next-page = Następna strona
admin-feedback-image = Obraz { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Przeczytane
admin-feedback-unread = Nieprzeczytane
admin-feedback-archived = Zarchiwizowane
admin-feedback-mark-unread = Oznacz jako nieprzeczytane
admin-feedback-mark-read = Oznacz jako przeczytane
admin-feedback-restore = Przywróć
admin-feedback-archive = Archiwizuj
admin-feedback-page = Strona:{" "}
admin-feedback-the-report-has-no-description = Zgłoszenie nie ma opisu.
admin-feedback-open-the-page-image = Otwórz obraz strony
admin-feedback-open-the-dom-copy = Otwórz kopię DOM
admin-feedback-page-image-of-the-report = Obraz strony ze zgłoszenia
admin-feedback-debug-context-and-browser-log = Kontekst diagnostyczny i dziennik przeglądarki
admin-feedback-loading-u = Wczytywanie…
admin-group-detail-admin-group = Administracja: grupa { $groupname }
admin-group-detail-failed-to-load-group = Nie udało się wczytać grupy
admin-group-detail-loading = Ładowanie...
admin-group-detail-group = Grupa
admin-group-detail-display-name = Nazwa wyświetlana
admin-group-detail-display-name-2 = nazwa wyświetlana
admin-group-detail-save = Zapisz
admin-group-detail-members = Członkowie
admin-group-detail-saving-membership = Zapisywanie członkostwa...
admin-group-detail-username = Nazwa użytkownika
admin-group-detail-origin = Pochodzenie
admin-group-detail-group-admin = Administrator grupy
admin-group-detail-uploader = Przesyłający
admin-group-detail-remove = Usuń
admin-group-detail-username-to-add = nazwa użytkownika do dodania
admin-group-detail-add-member = Dodaj członka
admin-group-detail-collection-access = Dostęp do kolekcji
admin-group-detail-this-group-has-no-collection = Ta grupa nie ma uprawnień do żadnej kolekcji.
admin-group-detail-revoke = Odbierz
admin-group-detail-grant-collection-u = Nadaj kolekcję…
admin-group-detail-grant = Nadaj
admin-group-detail-danger-zone = Strefa zagrożenia
admin-group-detail-delete-group = Usuń grupę
admin-groups-list-admin-groups = Administracja: grupy
admin-groups-list-groups = Grupy
admin-groups-list-add-group = Dodaj grupę
admin-groups-list-display-name = nazwa wyświetlana
admin-groups-list-use-lowercase-letters-digits-underscores = W nazwie używaj małych liter, cyfr, podkreśleń i myślników. Nazwy nie można później zmienić.
admin-groups-list-add-group-2 = Dodaj grupę +
admin-groups-list-group = Grupa
admin-groups-list-display-name-2 = Nazwa wyświetlana
admin-groups-list-members = Członkowie
admin-groups-list-collections = Kolekcje
admin-groups-list-loading = Ładowanie...
admin-llm-config-admin-llm = Administracja: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Wczytywanie…
admin-llm-config-no-llm-provider-is-configured = Nie skonfigurowano żadnego dostawcy LLM. Ustaw LLM_BASE_URL / LLM_MODEL w hoover4.ini i wdróż ponownie.
admin-llm-config-providers = Dostawcy
admin-llm-config-the-refresh-runs-in-the = Odświeżanie działa w tle. Dotychczasowa lista pozostaje widoczna.
admin-llm-config-refresh-in-flight-u = {" "}Trwa odświeżanie…
admin-llm-config-provider = Dostawca
admin-llm-config-models = Modele
admin-llm-config-freshest = Najświeższy
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Odśwież katalog
admin-llm-config-agent-turns-board-assessments-and = Tury agenta, oceny tablic i konwersje raportów
admin-llm-config-titles-summaries-and-board-labels = Tytuły, podsumowania i etykiety tablic
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini ustawia te modele: quality_model dostawcy LLM dla tur agenta, ocen tablic i konwersji raportów, jeśli jest ustawiony, a jego model dla reszty.
admin-llm-config-thinking = Thinking
admin-llm-config-the-model-reasons-before-each = Model rozumuje przed każdym wywołaniem narzędzia i każdą odpowiedzią.
admin-llm-config-catalog = Katalog
admin-llm-config-filter-models-u = Filtruj modele…
admin-llm-config-model = Model
admin-llm-config-flags = Flagi
admin-llm-config-calls-14d = Wywołania 14 d
admin-llm-config-ai-status = Stan AI
admin-llm-config-shows-the-serving-health = {" "}pokazuje stan obsługi.
admin-llm-reports-reports = Raporty
admin-llm-reports-each-report-runs-when-you = Każdy raport uruchamia się po wybraniu jego przycisku.
admin-llm-reports-running-u = Uruchamianie…
admin-llm-reports-run-report = Uruchom raport
admin-llm-reports-read-at = Odczytano: { $read_at }
admin-llm-reports-errors = Błędy
admin-llm-reports-failed-attempts-by-step-and = Nieudane próby według kroku i klasy błędu oraz uruchomienia agenta, które zakończyły się błędem lub wcześniej, według powodu zakończenia.
admin-llm-reports-source = Źródło
admin-llm-reports-class = Klasa
admin-llm-reports-no-errors-in-30-days = Brak błędów w ciągu 30 dni.
admin-llm-reports-recent-errors = Ostatnie błędy
admin-llm-reports-the-newest-100-failed-attempts = Najnowsze 100 nieudanych prób z 7 dni. Otwórz wiersz, aby przeczytać jego błąd.
admin-llm-reports-time = Czas
admin-llm-reports-user = Użytkownik
admin-llm-reports-name = Nazwa
admin-llm-reports-error = Błąd
admin-llm-reports-no-errors-in-7-days = Brak błędów w ciągu 7 dni.
admin-llm-reports-show = Pokaż
admin-llm-reports-tool-calls = Wywołania narzędzi
admin-llm-reports-one-row-for-each-tool = Jeden wiersz na narzędzie, według liczby wywołań w 30 dniach. Błąd to nieudane wywołanie.
admin-llm-reports-tool = Narzędzie
admin-llm-reports-calls-24-h = Wywołania 24 h
admin-llm-reports-error-24-h = Błędy % 24 h
admin-llm-reports-avg-ms-24-h = Śr. ms 24 h
admin-llm-reports-calls-7-d = Wywołania 7 d
admin-llm-reports-error-7-d = Błędy % 7 d
admin-llm-reports-avg-ms-7-d = Śr. ms 7 d
admin-llm-reports-calls-30-d = Wywołania 30 d
admin-llm-reports-error-30-d = Błędy % 30 d
admin-llm-reports-avg-ms-30-d = Śr. ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Brak wywołań narzędzi w ciągu 30 dni.
admin-llm-reports-top-users = Najaktywniejsi użytkownicy
admin-llm-reports-the-30-users-with-the = 30 użytkowników z największym czasem modelu w oknie.
admin-llm-reports-30-days = 30 dni
admin-llm-reports-7-days = 7 dni
admin-llm-reports-24-hours = 24 godziny
admin-llm-reports-tool-time = Czas narzędzi
admin-llm-reports-model-calls = Wywołania modelu
admin-llm-reports-model-time = Czas modelu
admin-llm-reports-tokens-in = Tokeny wejściowe
admin-llm-reports-tokens-out = Tokeny wyjściowe
admin-llm-reports-no-agent-use-in-the = Brak użycia agenta w oknie.
admin-llm-reports-system-one-checks = Kontrole System one
admin-llm-reports-requests-are-grouped-by-hook = Żądania są grupowane według hooka i reguły. Opóźnienia podano w milisekundach. Udziały liczono z żądań z ostatnich 30 dni.
admin-llm-reports-counts = Liczby
admin-llm-reports-recent-failures = Ostatnie niepowodzenia
admin-llm-reports-select-run-report-to-read = Wybierz Uruchom raport, aby przeczytać statystyki.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Reguła
admin-llm-reports-outcome = Wynik
admin-llm-reports-questions = Pytania
admin-llm-reports-median-ms = Mediana ms
admin-llm-reports-95th-percentile-ms = 95. percentyl ms
admin-llm-reports-error-2 = Błędy %
admin-llm-reports-positive = Pozytywne %
admin-llm-reports-actions = Akcje
admin-metrics-admin-metrics = Administracja: metryki
admin-metrics-metrics = Metryki
admin-metrics-the-last-24-hours = Ostatnie 24 godziny.
admin-metrics-loading-u = Wczytywanie…
admin-metrics-manticore-load-now = Obciążenie Manticore (teraz)
admin-metrics-ram-is-the-memory-of = RAM to pamięć tabel. Obciążenie wątków dotyczy ostatnich 1, 5 i 15 minut.
admin-metrics-manticore-status-could-not-be = Nie udało się odczytać stanu Manticore: { $error }
admin-metrics-thread-load-1-5-15 = Obciążenie wątków (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Obciążenie wątków głównych (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Obciążenie wątków dodatkowych (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Wątki robocze zajęte / razem
admin-metrics-work-queue = Kolejka pracy
admin-metrics-ram-held-by-tables = RAM zajęty przez tabele
admin-metrics-disk-used-by-tables = Dysk zajęty przez tabele
admin-metrics-tables-merging = Tabele w scalaniu
admin-metrics-tables-read = Odczytane tabele
admin-metrics-read-at = Odczytano
admin-metrics-largest-tables-by-ram = Największe tabele według RAM
admin-metrics-table = Tabela
admin-metrics-ram = RAM
admin-metrics-disk = Dysk
admin-metrics-disk-chunks = Fragmenty dyskowe
admin-metrics-merging = Scalanie
admin-metrics-usage-last-24-h = Użycie (ostatnie 24 h)
admin-metrics-events-by-type = Zdarzenia według typu
admin-metrics-event = Zdarzenie
admin-metrics-count = Liczba
admin-metrics-events-per-hour = Zdarzenia na godzinę
admin-metrics-no-events-recorded-yet = Nie zapisano jeszcze zdarzeń.
admin-metrics-busiest-users = Najaktywniejsi użytkownicy
admin-metrics-user = Użytkownik
admin-metrics-events = Zdarzenia
admin-metrics-events-2 = { $point_bucket }: zdarzenia: { $point_count }
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = Wywołania API (ostatnie 24 h)
admin-metrics-no-api-calls-recorded-yet = Nie zapisano jeszcze wywołań API.
admin-metrics-function = Funkcja
admin-metrics-calls = Wywołania
admin-metrics-errors = Błędy
admin-metrics-error-rate = Odsetek błędów
admin-metrics-bytes-in = Bajty wejściowe
admin-metrics-bytes-out = Bajty wyjściowe
admin-operation-detail-admin-operation = Administracja: operacja { $op_id }
admin-operation-detail-loading-operation = Wczytywanie operacji…
admin-operation-detail-back-to-operations = Wróć do operacji
admin-operation-detail-operation = Operacja
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · w kolejce od: { $row_started_at }
admin-operation-detail-not-started = nie rozpoczęto
admin-operation-detail-re-run-counts-are-not = Liczniki ponownych uruchomień są niedostępne.
admin-operation-detail-failed-document-s-task-failure = Nieudane dokumenty: { $documents }, niepowodzenia zadań: { $row_failed_tasks_unwrap_or_0 }
admin-operation-detail-failures-were-not-counted = Niepowodzeń nie policzono.
admin-operation-detail-open-captured-failure-tree = Otwórz przechwycone drzewo niepowodzeń
admin-operation-detail-open-in-temporal = Otwórz w Temporal
admin-operation-detail-plans = Plany
admin-operation-detail-plan-s-page = Plany: { $data_plans_total }, strona { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Dla tej operacji nie zapisano żadnych planów.
admin-operation-detail-dataset = Zbiór danych
admin-operation-detail-plan-hash = Skrót planu
admin-operation-detail-source = Źródło
admin-operation-detail-finished = Zakończono
admin-operation-detail-previous = Poprzednia
admin-operation-detail-next = Następna
admin-operation-detail-error-events = Zdarzenia błędów
admin-operation-detail-error-event-s-page = Zdarzenia błędów: { $data_events_total }, strona { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Dla tej operacji nie zapisano żadnych zdarzeń błędów.
admin-operation-detail-time = Czas
admin-operation-detail-hash = Skrót
admin-operation-detail-task = Zadanie
admin-operation-detail-event = Zdarzenie
admin-operation-detail-error-excerpt = Fragment błędu
admin-operations-admin-operations = Administracja: operacje
admin-operations-operations = Operacje
admin-operations-loading-operations = Wczytywanie operacji…
admin-operations-filters = Filtry
admin-operations-state = Stan
admin-operations-any-state = Dowolny stan
admin-operations-collection = Kolekcja
admin-operations-all-collections = Wszystkie kolekcje
admin-operations-choose-a-collection-to-see = Wybierz kolekcję, aby zobaczyć odsetki błędów według zadań.
admin-operations-operations-newest-first = Operacje, najnowsze na początku
admin-operations-newer = Nowsze
admin-operations-page = Strona { $current_page_1 }
admin-operations-older = Starsze
admin-operations-failure-rate-by-task-type = Odsetek niepowodzeń według typu zadania ({ $collectionname })
admin-operations-one-row-per-activity-execution = Jeden wiersz na wykonanie aktywności, razem z ponowieniami. Odsetek powyżej{" "}
admin-operations-is-marked = {" "}jest oznaczony.
admin-operations-no-task-executions-recorded-for = Dla tej kolekcji nie zapisano jeszcze wykonań zadań.
admin-operations-task = Zadanie
admin-operations-error-rate = Odsetek błędów
admin-operations-failed-total-executions = Nieudane / wszystkie wykonania
admin-operations-documents-affected = Dotknięte dokumenty
admin-operations-above-the-line = powyżej progu
admin-operations-no-operations-recorded-for-this = Dla tego filtra nie zapisano operacji.
admin-operations-kind = Rodzaj
admin-operations-target = Cel
admin-operations-workflow = Workflow
admin-operations-queued-at = W kolejce od
admin-operations-started = Rozpoczęto
admin-operations-duration = Czas trwania
admin-operations-progress = Postęp
admin-operations-eta = ETA
admin-operations-outcome = Wynik
admin-operations-destructive = Destrukcyjna
admin-operations-repeated-run = Powtórne uruchomienie
admin-operations-no-estimate-yet = brak jeszcze szacunku
admin-operations-cancel = Anuluj
admin-operations-type-to-confirm = wpisz { $target }, aby potwierdzić
admin-operations-re-run = Uruchom ponownie
admin-operations-waiting-for-a-free-slot = czeka na wolny slot lub wolny cel
admin-operations-counting-work = liczenie pracy…
admin-operations-open-captured-tree = Otwórz przechwycone drzewo
admin-operations-no-captured-tree = brak przechwyconego drzewa
admin-operations-no-failed-documents = brak nieudanych dokumentów
admin-operations-document-s-failed = nieudane dokumenty: { $n }
admin-operations-task-failure-s = niepowodzenia zadań: { $t }
admin-operations-failures-not-counted = niepowodzeń nie policzono
admin-operations-the-newest-ten-operations-of = Dziesięć najnowszych operacji tej kolekcji.{" "}
admin-operations-all-operations = Wszystkie operacje
admin-settings-admin-settings = Administracja: ustawienia
admin-settings-server-settings = Ustawienia serwera
admin-settings-key = Klucz
admin-settings-value = Wartość
admin-settings-description = Opis
admin-settings-save = Zapisz
admin-settings-loading = Ładowanie...
admin-settings-deployment-configuration-read-only = Konfiguracja wdrożenia (tylko do odczytu)
admin-settings-not-set = (nie ustawiono)
admin-user-detail-admin-user = Administracja: użytkownik { $username }
admin-user-detail-failed-to-load-user = Nie udało się wczytać użytkownika
admin-user-detail-loading = Ładowanie...
admin-user-detail-user = Użytkownik
admin-user-detail-the-next-login-replaces-the = Następne logowanie zastępuje imię i nazwisko, e-mail i status superużytkownika użytkownika z proxy logowania.
admin-user-detail-llm-usage-u = Użycie LLM →
admin-user-detail-full-name = Imię i nazwisko
admin-user-detail-full-name-2 = imię i nazwisko
admin-user-detail-email = E-mail
admin-user-detail-superuser = Superużytkownik
admin-user-detail-save = Zapisz
admin-user-detail-groups = Grupy
admin-user-detail-saving-membership = Zapisywanie członkostwa...
admin-user-detail-group = Grupa
admin-user-detail-origin = Pochodzenie
admin-user-detail-group-admin = Administrator grupy
admin-user-detail-uploader = Przesyłający
admin-user-detail-remove = Usuń
admin-user-detail-add-to-group-u = Dodaj do grupy…
admin-user-detail-add = Dodaj
admin-user-detail-danger-zone = Strefa zagrożenia
admin-user-detail-delete-user = Usuń użytkownika
admin-user-llm-admin-llm-use-by = Administracja: użycie LLM przez { $username }
admin-user-llm-u-back-to-user = ← Wróć do użytkownika
admin-user-llm-loading-u = Wczytywanie…
admin-user-llm-totals-all-time = Sumy (cały czas)
admin-user-llm-chat-sessions = Sesje czatu
admin-user-llm-messages = Wiadomości
admin-user-llm-tool-calls = Wywołania narzędzi
admin-user-llm-model-and-tool-time = Czas modelu i narzędzi
admin-user-llm-model-and-tool-time-of = czas modelu i narzędzi w krokach agenta tego użytkownika. Równoległe wywołania narzędzi liczą się w całości
admin-user-llm-rate-limit-usage-current-windows = Wykorzystanie limitów (bieżące okna)
admin-user-llm-in-process-counters-of-the = Liczniki w procesie działającego kontenera witryny. Limit czatu: { $metrics_chat_per_minute }/min, limit API: { $metrics_api_per_minute }/min, z malejącą stałą szybkością w dłuższych oknach.
admin-user-llm-chat-messages = Wiadomości czatu
admin-user-llm-api-calls = Wywołania API
admin-user-llm-window = Okno
admin-user-llm-used = Użyto
admin-user-llm-budget = Budżet
admin-user-llm-no-chat-sessions = Brak sesji czatu.
admin-user-llm-title = Tytuł
admin-user-llm-created = Utworzono
admin-users-list-admin-users = Administracja: użytkownicy
admin-users-list-users = Użytkownicy
admin-users-list-search-users = Szukaj użytkowników
admin-users-list-username = Nazwa użytkownika
admin-users-list-full-name = Imię i nazwisko
admin-users-list-email-address = Adres e-mail
admin-users-list-superuser = Superużytkownik
admin-users-list-groups = Grupy
admin-users-list-created = Utworzono
admin-users-list-last-login = Ostatnie logowanie
admin-users-list-loading = Ładowanie...
dataset-create-panel-put-the-documents-in-a = Umieść tam dokumenty w folderze i wczytaj tę stronę ponownie.
dataset-create-panel-the-name-cannot-start-with = Nazwa nie może zaczynać się od kropki ani zawierać ukośnika.
dataset-create-panel-and-a-dash-a-space = a myślnik, spacja lub kropka zmienia się w podkreślenie. Nazwy nie można później zmienić.
live-chats-panel-off = wyłączone
processing-updates-panel-the-waiting-steps-change-each = Oczekujące kroki zmieniają { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), każdy plik liczony raz. Do wykonania: { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = a myślnik, spacja lub kropka zmienia się w podkreślenie. Nazwy nie można później zmienić.
admin-llm-config-fresh = aktualny
admin-llm-config-tools = narzędzia{" "}
admin-llm-config-vision = wizja{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (tylko do odczytu)
live-chats-panel-on = włączone
processing-updates-panel-up-to-date-select-it = Aktualne. Wybierz, aby uruchomić ponownie.
admin-ai-status-yes = tak
admin-ai-status-no-2 = nie
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = Błędy: { $ds_error_count }
admin-collection-processing-done = gotowe
admin-collection-processing-failed-2 = nieudane: { $stage_failed_documents }
admin-collection-processing-left = pozostało
admin-collection-processing-dataset-level = na poziomie zbioru danych
admin-collections-list-groups = grupy: { $c_group_count }
admin-failures-operation-s = operacje: { $group_operation_count }
admin-groups-list-groupname = nazwa grupy
admin-llm-config-stale = nieaktualny
admin-llm-config-thinking-is-on = Thinking jest włączone
admin-llm-config-thinking-is-off = Thinking jest wyłączone
admin-llm-config-shown = pokazano: { $models_len }
admin-llm-config-reasoning = rozumowanie
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } z { $load_table_count }
admin-metrics-yes = tak
admin-metrics-no = nie
admin-metrics-max = maks.
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = rozpoczęto { $run_started_at }
admin-operation-detail-yes = tak
admin-operation-detail-no = nie
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = e-mail
admin-user-llm-untitled = (bez tytułu)
admin-dataset-ocr-panel-variant-pages = { $source } · strony: { $pages }
admin-processing-updates-panel-prerequisites-waiting = Kolekcja wymaga najpierw aktualizacji: { $steps }. Kroki zapisujące do indeksu wyszukiwania czekają na nią.
admin-operations-no-task-type-failing = Żaden typ zadania nie przekracza { $threshold }% niepowodzeń.
admin-operations-task-types-failing = Typy zadań z niepowodzeniami powyżej { $threshold }%: { $count }.
processing-updates-panel-collection-updates = Aktualizacje kolekcji
admin-collections-list-some-datasets-are-not-counted = Niektóre zbiory danych nie zostały jeszcze policzone.
admin-failures-hide = Ukryj
admin-failures-show = Pokaż
admin-settings-web-session-lifetime-in-seconds = Czas życia sesji webowej w sekundach (domyślnie: 604800 = 1 tydzień)
admin-settings-turns-every-new-chat-turn = Gdy wartość to false, wyłącza każdą nową turę czatu (domyślnie: true). Tura w toku kończy się normalnie. Zmiana działa od następnego wysłania, bez ponownego wdrożenia.
admin-settings-written-by-main-py-probe = Zapisuje to `main.py probe-embeddings`. Wartość odpowiada temu, co endpoint FAKTYCZNIE obsługuje. Ręczna edycja nie zmienia serwera.
admin-settings-the-folder-whose-subfolders-the = Folder, którego podfoldery formularz zbioru danych wyświetla dla tego punktu montowania. Zmiana w hoover4.ini wymaga ponownego wdrożenia.
admin-settings-from-hoover4-ini-changing-it = Z hoover4.ini. Zmiana wymaga ponownego wdrożenia.
admin-feedback-bug = Błąd
admin-operations-state-name = { $state ->
        [pending] oczekuje
        [queued] w kolejce
        [running] trwa
        [finished] zakończona
        [errored] z błędem
        [cancelled] anulowana
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Drzewo niepowodzeń { $op_id }
admin-failure-detail-showing-of-characters = pokazano znaków: { $node_stack_trace_chars_count } z { $node_stack_trace_original_len }
admin-operations-operation = Operacja: { $state }.
admin-operations-dispatched = Wysłano { $new_id }.
admin-operations-rows = wiersze: { $row_progress_done } / { $row_progress_total }
admin-operations-plans = plany: { $row_progress_done } / { $row_progress_total }
admin-group-detail-group-2 = Grupa { $groupname }
admin-settings-the-setting-was-saved-successfully = Ustawienie „{ $k }” zostało zapisane.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Grupa „{ $g }” została dodana.
admin-user-detail-user-2 = Użytkownik { $username }
admin-dataset-detail-dataset = Zbiór danych { $dataset_id }
admin-dataset-detail-collections = Kolekcje › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } z { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Nie udało się odczytać ustawienia przesyłania: { $err }
admin-dataset-detail-operation-started = Rozpoczęto operację: { $run_id }
admin-collection-detail-collection = Kolekcja { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Nie udało się odczytać ustawienia wektorów: { $err }
admin-collection-processing-processing-of = Przetwarzanie { $collection_id }
admin-collection-processing-collections = Kolekcje › { $collection_id }
admin-collection-processing-executions-2 = Wykonania: { $b_total_executions }
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = stan na { $at }
admin-collection-processing-over-the-last-s = w ciągu ostatnich { $live_window_seconds } s
admin-collection-processing-retry-started-run = Rozpoczęto ponowienie (uruchomienie { $run }).
admin-collection-processing-document-retry-started-run = Rozpoczęto ponowienie dla dokumentu (uruchomienie { $run }).
admin-operation-detail-operation-2 = Operacja { $op_id }
admin-user-llm-llm-usage-of = Użycie LLM przez { $username }
admin-user-llm-users = Użytkownicy › { $username }
processing-updates-panel-the-processing-updates-could-not = Nie udało się odczytać aktualizacji przetwarzania: { $e }
processing-updates-panel-update-started = Rozpoczęto aktualizację: { $op_id }
dataset-ocr-panel-of-plans = Plany: { $operation_progress_done } z { $operation_progress_total }
dataset-ocr-panel-adding = dodawane: { $added }
dataset-ocr-panel-removing = usuwane: { $removed }
dataset-ocr-panel-plan-s-reopened = Ponownie otwarte plany: { $plans }
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] folder
        [few] foldery
        [many] folderów
       *[other] folderu
    }
    [tables] { $count ->
        [one] tabela
        [few] tabele
        [many] tabel
       *[other] tabeli
    }
   *[files] { $count ->
        [one] plik
        [few] pliki
        [many] plików
       *[other] pliku
    }
}
processing-updates-step-runs = { $count ->
    [one] uruchomienie kroku
    [few] uruchomienia kroku
    [many] uruchomień kroku
   *[other] uruchomienia kroku
}
processing-update-search_schema-title = Schemat indeksu wyszukiwania
processing-update-search_schema-explanation = { $files ->
    [one] { $count } tabela wyszukiwania kolekcji nie ma kolumny, której potrzebuje indeks wyszukiwania.
    [few] { $count } tabele wyszukiwania kolekcji nie mają kolumny, której potrzebuje indeks wyszukiwania.
    [many] { $count } tabel wyszukiwania kolekcji nie ma kolumny, której potrzebuje indeks wyszukiwania.
   *[other] { $count } tabeli wyszukiwania kolekcji nie ma kolumny, której potrzebuje indeks wyszukiwania.
} Kolumna zostanie dodana do każdej tabeli. Wyszukiwanie nadal działa.
processing-update-search_schema-runs = Tabele indeksu wyszukiwania
processing-update-unfinished-title = Niedokończone przetwarzanie
processing-update-unfinished-explanation = { $files ->
    [one] { $count } plik nie jest przetworzony do końca.
    [few] { $count } pliki nie są przetworzone do końca.
    [many] { $count } plików nie jest przetworzonych do końca.
   *[other] { $count } pliku nie jest przetworzone do końca.
} Obejmuje to pliki bez planu przetwarzania, na przykład po przerwanym imporcie. Ich przetwarzanie zostanie dokończone.
processing-update-unfinished-runs = Wszystkie etapy przetwarzania tych plików
processing-update-failed_files-title = Pliki z niepowodzeniem
processing-update-failed_files-explanation = { $files ->
    [one] { $count } plik ma błąd przetwarzania.
    [few] { $count } pliki mają błąd przetwarzania.
    [many] { $count } plików ma błąd przetwarzania.
   *[other] { $count } pliku ma błąd przetwarzania.
} Nieudane etapy zostaną dla nich uruchomione ponownie. Uruchomienie automatyczne ponawia plik raz dla każdej nowej wersji etapu, który się nie powiódł.
processing-update-failed_files-runs = Nieudane etapy, potem wyodrębnianie encji, embedding i indeksowanie
processing-update-virus_scan-title = Skanowanie antywirusowe
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } plik nie ma werdyktu antywirusa.
    [few] { $count } pliki nie mają werdyktu antywirusa.
    [many] { $count } plików nie ma werdyktu antywirusa.
   *[other] { $count } pliku nie ma werdyktu antywirusa.
} Zostaną przeskanowane. Plik, który skaner uzna za zainfekowany, jest oznaczany w wyszukiwaniu, a pobranie jego oryginału i PDF z możliwością przeszukiwania jest odrzucane.
processing-update-virus_scan-runs = Skan antywirusowy, potem atrybut wyszukiwania zainfekowanych plików
processing-update-tables-title = Tabele
processing-update-tables-explanation = { $files ->
    [one] { $count } plik ma starszy odczyt tabeli lub niepełne wyniki zależne. Jego zapisane wyniki zostaną zaktualizowane.
    [few] Pliki ze starszym odczytem tabel lub niepełnymi wynikami zależnymi: { $count }. Ich zapisane wyniki zostaną zaktualizowane.
    [many] Pliki ze starszym odczytem tabel lub niepełnymi wynikami zależnymi: { $count }. Ich zapisane wyniki zostaną zaktualizowane.
    *[other] Pliki ze starszym odczytem tabel lub niepełnymi wynikami zależnymi: { $count }. Ich zapisane wyniki zostaną zaktualizowane.
    }

processing-update-tables-runs = Odczyt tabel, encje, sygnały, osadzenia i oba indeksy
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Pliki wymagające automatycznego OCR: { $count }. Wcześniejszy tekst OCR w wykrytym języku zostaje zachowany bez nowego OCR. Pozostałe strony otrzymują OCR z zainstalowanym modelem wykrytego języka. Poprzednie warianty są usuwane, gdy zastąpienie jest pełne.
processing-update-ocr-runs = OCR i PDF-y z możliwością przeszukiwania, potem wyodrębnianie encji, embedding i indeksowanie nowego tekstu
processing-update-ocr_detection-title = Wykrywanie OCR
processing-update-ocr_detection-explanation = Pliki bez bieżącego wykrywania tekstu, pisma lub języka: { $count }. Każdy odpowiedni obraz i strona PDF są badane w ograniczonych partiach.
processing-update-ocr_detection-runs = Wykrywanie, a potem atrybuty wyszukiwania tych plików
processing-update-pdf_text-title = Tekst przeszukiwalnych plików PDF
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } plik ma przeszukiwalne pliki PDF z wcześniejszą warstwą tekstu.
    [few] { $count } pliki mają przeszukiwalne pliki PDF z wcześniejszą warstwą tekstu.
    [many] { $count } plików ma przeszukiwalne pliki PDF z wcześniejszą warstwą tekstu.
   *[other] { $count } pliku ma przeszukiwalne pliki PDF z wcześniejszą warstwą tekstu.
} Ta warstwa kopiowała każdą literę spoza alfabetów zachodnioeuropejskich jako czarny kwadrat. Pliki PDF języków, które mają tylko litery zachodnioeuropejskie, pozostają bez zmian. Pozostałe pliki PDF są odczytywane, a części z czarnymi kwadratami są tworzone ponownie. PDF obrazu używa zapisanych słów OCR. Strona PDF otrzymuje nowe żądanie OCR.
processing-update-pdf_text-runs = Części przeszukiwalnych plików PDF, potem indeksowanie tekstu OCR odtworzonych plików PDF
processing-update-page_text-title = Zindeksowany tekst stron
processing-update-page_text-explanation = Pliki z niepełnym tekstem wyszukiwania: { $count }. Znak sterujący na stronie zakończył jej zindeksowany tekst. Indeksowany jest pełny tekst.
processing-update-page_text-runs = Tekst indeksu wyszukiwania tych stron
processing-update-text_rows-title = Podział tekstu
processing-update-text_rows-explanation = Pliki z tekstem z wcześniejszego podziału: { $count }. Tekst PDF przechodzi do jednego wiersza na każdą część PDF, a długi tekst jest cięty z krótkim nakładaniem. Nie jest uruchamiany nowy OCR ani nowa analiza.
processing-update-text_rows-runs = Podział tekstu, potem wyodrębnianie encji, embedding i indeksowanie nowego tekstu
processing-update-vectors-title = Wektory
processing-update-vectors-explanation = { $files ->
    [one] { $count } plik z tekstem nie ma wektorów modelu embeddingów, który obsługuje instalacja.
    [few] { $count } pliki z tekstem nie mają wektorów modelu embeddingów, który obsługuje instalacja.
    [many] { $count } plików z tekstem nie ma wektorów modelu embeddingów, który obsługuje instalacja.
   *[other] { $count } pliku z tekstem nie ma wektorów modelu embeddingów, który obsługuje instalacja.
} Ich wektory zostaną obliczone i zaindeksowane.
processing-update-vectors-runs = Embedding i indeksowanie wektorów
processing-update-folder_counts-title = Liczniki folderów
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } folder nie ma liczby plików ani rozmiaru albo ma wartości z wcześniejszej wersji.
    [few] { $count } foldery nie mają liczby plików ani rozmiaru albo mają wartości z wcześniejszej wersji.
    [many] { $count } folderów nie ma liczby plików ani rozmiaru albo ma wartości z wcześniejszej wersji.
   *[other] { $count } folderu nie ma liczby plików ani rozmiaru albo ma wartości z wcześniejszej wersji.
} Liczniki zostaną obliczone ponownie.
processing-update-folder_counts-runs = Drzewo folderów
admin-uploads-badge = Przesyłanie
admin-uploads-badge-title = Przyjmuje przesłane pliki

processing-update-archive_members-title = Elementy archiwów

processing-update-archive_members-explanation = { $files ->
    [one] { $count } archiwum dzielone wymaga aktualnej listy elementów. Jego elementy i wyniki wyszukiwania zostaną zaktualizowane.
    [few] Archiwa dzielone wymagające aktualnych list elementów: { $count }. Ich elementy i wyniki wyszukiwania zostaną zaktualizowane.
    [many] Archiwa dzielone wymagające aktualnych list elementów: { $count }. Ich elementy i wyniki wyszukiwania zostaną zaktualizowane.
    *[other] Archiwa dzielone wymagające aktualnych list elementów: { $count }. Ich elementy i wyniki wyszukiwania zostaną zaktualizowane.
    }

processing-update-archive_members-runs = Rozpakowanie archiwów, uzgodnienie elementów i przetwarzanie zależne

processing-update-image_previews-title = Podglądy obrazów

processing-update-image_previews-explanation = { $files ->
    [one] { $count } obraz nietypowego formatu nie ma podglądu. Jego podgląd zostanie utworzony ponownie.
    [few] Obrazy nietypowych formatów bez podglądu: { $count }. Ich podglądy zostaną utworzone ponownie.
    [many] Obrazy nietypowych formatów bez podglądu: { $count }. Ich podglądy zostaną utworzone ponownie.
    *[other] Obrazy nietypowych formatów bez podglądu: { $count }. Ich podglądy zostaną utworzone ponownie.
    }

processing-update-image_previews-runs = Tworzenie i weryfikacja podglądów obrazów

processing-update-search_terms-title = Hasła wyszukiwania

processing-update-search_terms-explanation = { $files ->
    [one] { $count } tabela wyszukiwania wymaga aktualnych haseł filtrów. Można wyszukiwać hasła języka, OCR, pisma i czerwonych flag.
    [few] Tabele wyszukiwania wymagające aktualnych haseł filtrów: { $count }. Można wyszukiwać hasła języka, OCR, pisma i czerwonych flag.
    [many] Tabele wyszukiwania wymagające aktualnych haseł filtrów: { $count }. Można wyszukiwać hasła języka, OCR, pisma i czerwonych flag.
    *[other] Tabele wyszukiwania wymagające aktualnych haseł filtrów: { $count }. Można wyszukiwać hasła języka, OCR, pisma i czerwonych flag.
    }

processing-update-search_terms-runs = Indeksowanie i weryfikacja haseł filtrów

automatic-ocr-title = Automatyczny OCR
automatic-ocr-refresh = Odśwież stan
automatic-ocr-coverage = Pokrycie stron
automatic-ocr-pages = Strony
automatic-ocr-models = Modele OCR
automatic-ocr-reason = Przyczyna
automatic-ocr-truncated = Lista diagnostyczna jest niepełna.
automatic-ocr-presence = Ma opublikowany tekst OCR
automatic-ocr-policy = OCR wybiera zainstalowane modele według wykrytego pisma i języka każdej kwalifikującej się strony. Najpierw działa Tesseract, a EasyOCR obsługuje niepokryte pisma.
automatic-ocr-unknown = Nie zarejestrowano bieżącej publikacji. Brak wykrywania i nieudane przetwarzanie nie potwierdzają nieobecności.
automatic-ocr-retry = Po usunięciu przyczyny ponów niepełną lub nieudaną pracę przez aktualizacje przetwarzania. Nieobsługiwane pokrycie wymaga zgodnych zainstalowanych modeli.
automatic-ocr-state = { $state ->
    [candidate] Oczekuje
    [planned] Zaplanowano
    [failed] Niepowodzenie
    [incomplete] Niepełne
    [unsupported] Nieobsługiwane
    [published] Opublikowano
    [applied] Zweryfikowano
    [ready] Wykryto tekst
    [no_text] Nie wykryto tekstu
    *[other] { $state }
    }

processing-update-entities-title = Encje nazwane
processing-update-entities-explanation = Pliki wymagające bieżącej ekstrakcji encji lub wyników wyszukiwania: { $count }. Poprzednie udane wyniki są zastępowane po zakończeniu inferencji.
processing-update-entities-runs = Ekstrakcja encji nazwanych, atrybuty tekstu i wyszukiwalne terminy encji

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Nie rozpoznano pisma
    [tesseract_capabilities_unavailable] Pokrycie Tesseract niedostępne
    [detected_language] Model odpowiada wykrytemu językowi
    [unknown_language_script_coverage] Nieznany język. Wybrano model pisma.
    [language_script_mismatch_script_coverage] Język i pismo różnią się. Wybrano model pisma.
    [language_model_unavailable_script_coverage] Model języka niedostępny. Wybrano model pisma.
    [easyocr_capabilities_unavailable] Pokrycie EasyOCR niedostępne
    [tesseract_script_unavailable] Tesseract nie obsługuje pisma. Wybrano EasyOCR.
    [script_coverage_unavailable] Żaden zainstalowany model nie obsługuje tego pisma.
    *[other] { $reason }
    }

processing-updates-check-requested = Potok oblicza aktualizacje. Liczby zmienią się po zakończeniu obliczeń.
