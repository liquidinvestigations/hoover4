# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = Dwa ostatnie wyszukiwania nie znalazły żadnego nowego źródła. Przeczytaj teraz najlepsze strony wyników: umieść do 6 ich adresów URL w jednym wywołaniu read_page, na liście `urls`. Szukaj ponownie tylko z innym pytaniem.
note-discovery-l3-web = Odpowiedź padła, zanim przeczytano jakąkolwiek stronę źródłową. Wywołaj read_page raz z adresami URL stron, które potwierdzają Twoje punkty, do 6 na liście `urls`. Potem napisz odpowiedź jeszcze raz ze źródłami, które ją potwierdzają.
note-discovery-l3-documents = Odpowiedź padła, zanim przeczytano jakikolwiek dokument. Przeczytaj dokumenty, które potwierdzają Twoje punkty, za pomocą read_documents, z kilkoma skrótami plików w jednym wywołaniu. Potem napisz odpowiedź jeszcze raz ze źródłami, które ją potwierdzają.
note-discovery-l4 = Przeczytaj teraz strony wyników, które mogą odpowiedzieć na żądanie: umieść do 6 ich adresów URL w jednym wywołaniu read_page, na liście `urls`. Jedno wywołanie czyta je wszystkie jednocześnie.

## Page captures

note-capture-empty = Przechwycona strona { $urls } nie zawiera tekstu artykułu. Przeczytaj inne źródło. Nie cytuj tej strony.

## Sources

note-web-tools-absent = Ta tura nie ma narzędzi internetowych, więc nie może czytać publicznych stron internetowych. Użyj wybranych kolekcji i napisz, na którą część żądania one nie odpowiadają.
note-sources-documents = Najpierw przeszukaj dozwolone kolekcje dokumentów. Przeczytaj ich odpowiednie dokumenty.
note-sources-documents-before-web = Najpierw przeszukaj dozwolone kolekcje dokumentów. Przeczytaj ich odpowiednie dokumenty. Przeczytaj te dokumenty, zanim użyjesz internetu.

## Named things

note-absent-collection = Żadna dozwolona kolekcja nie nazywa się { $name }. Dozwolone kolekcje: { $collections }.
note-absent-name = Wybrane kolekcje nie mają zindeksowanego dopasowania dla: { $name }.
note-absent-close-forms = Zindeksowane zbliżone formy: { $forms }. Nie używaj zbliżonej formy jako szukanej nazwy. Gdy wyszukasz taką formę, nazwij ją w odpowiedzi inną pisownią.
note-absent-close-form = { $form } (dokumenty: { $count })
note-absent-web = Narzędzia internetowe tej tury mogą wyszukać tę nazwę.

## Search progress

note-progress-level = Poziom postępu wyszukiwania: { $level }.
note-progress-searches = Wykonane już wyszukiwania:
note-progress-search = { $name } { $args }: elementy: { $items }, dopasowania słów kluczowych: { $matches }.
note-progress-available = Pozostałe dostępne kroki wyszukiwania:
note-progress-complete = Dostępne kroki wyszukiwania są zakończone.
note-progress-write-now = Napisz teraz odpowiedź lub raport. Napisz, czego nie zawierają przeczytane źródła, i wymień wykonane wyszukiwania.
note-progress-answer-next = Następną odpowiedzią musi być odpowiedź końcowa. Napisz, jakich faktów brakuje, i wymień wyszukiwania, które wykonano.
note-progress-step-quoted = Wyszukaj każdą nazwę jako frazę w cudzysłowie za pomocą search_collections.
note-progress-step-variants = Wyszukaj słowa bez cudzysłowu i warianty nazw. Przeczytaj liczby słów i kandydatów pisowni.
note-progress-step-filters = Usuwaj filtry po jednym i wykonaj wyszukiwanie bez filtrów.
note-progress-step-facets = Sprawdź wartości filtrów za pomocą search_facet_values.
note-progress-step-dates = Sprawdź daty za pomocą search_histogram.
note-progress-step-passages = Wyszukaj opis treści za pomocą search_passages.
note-progress-step-folder = Użyj { $tool } dla żądanego folderu, ścieżki lub pliku.
note-progress-step-read-hits = Przeczytaj 1 do 3 najlepszych trafień za pomocą { $tool }.
note-progress-step-web-search = Wyszukaj w internecie za pomocą web_search i przeczytaj najlepsze strony wyników.
note-progress-step-page-find = Przeszukaj zachowany tekst długiej strony za pomocą read_page i find.
note-progress-step-page-retry = Przeczytaj inny adres z wyników lub zarchiwizowaną kopię strony, która się nie powiodła.
note-advice-stuck = Kontrola czatu szacuje, że ostatnie wyszukiwania powtarzają swoje wyniki. Umiejętność no_results opisuje inne formy wyszukiwania.
note-advice-absent = Kontrola czatu szacuje, że wyniki nie zawierają tego, czego wymaga zadanie. Opisz przeszukany zakres, zanim zgłosisz brak.
note-advice-completion = Kontrola czatu szacuje, że wyniki mogą odpowiedzieć na zadanie. Zanim odpowiesz, porównaj każdą żądaną część ze źródłami, które przeczytano.
note-progress-ended = Uruchomienie zakończyło się po powtarzanych wyszukiwaniach bez postępu.
note-progress-ended-none = Nie znaleziono żadnego źródła dopasowanego do słów kluczowych.
note-progress-ended-some = Wyszukiwania znalazły źródła dopasowane do słów kluczowych: { $count }. Agent nie dokończył odpowiedzi.
note-progress-ended-searches = Wykonane wyszukiwania:
