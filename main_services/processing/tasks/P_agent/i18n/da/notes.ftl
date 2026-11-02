# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = De to seneste søgninger fandt ingen ny kilde. Læs nu de bedste resultatsider: læg op til 6 af deres URL'er i ét kald til read_page, i dets `urls`-liste. Søg kun igen med et andet spørgsmål.
note-discovery-l3-web = Du svarede, før du havde læst nogen kildeside. Kald read_page én gang med URL'erne til de sider, der understøtter dine punkter, op til 6 i dets `urls`-liste. Skriv derefter svaret igen med de kilder, der understøtter det.
note-discovery-l3-documents = Du svarede, før du havde læst noget dokument. Læs de dokumenter, der understøtter dine punkter, med read_documents, flere filhashværdier i ét kald. Skriv derefter svaret igen med de kilder, der understøtter det.
note-discovery-l4 = Læs nu de resultatsider, der kan besvare forespørgslen: læg op til 6 af deres URL'er i ét kald til read_page, i dets `urls`-liste. Ét kald læser dem alle samtidig.

## Page captures

note-capture-empty = Indfangningen af { $urls } indeholder ingen artikeltekst. Læs en anden kilde. Henvis ikke til denne side.

## Sources

note-web-tools-absent = Denne runde har ingen webværktøjer, så den kan ikke læse offentlige websider. Brug de valgte samlinger, og angiv, hvilken del af forespørgslen de ikke besvarer.
note-sources-documents = Søg først i de tilladte dokumentsamlinger. Læs deres relevante dokumenter.
note-sources-documents-before-web = Søg først i de tilladte dokumentsamlinger. Læs deres relevante dokumenter. Læs disse dokumenter, før du bruger nettet.

## Named things

note-absent-collection = Ingen tilladt samling hedder { $name }. De tilladte samlinger er { $collections }.
note-absent-name = De valgte samlinger har ingen indekseret træf på { $name }.
note-absent-close-forms = Indekserede nærliggende former: { $forms }. Brug ikke en nærliggende form som det ønskede navn. Når du søger efter en af dem, så angiv i svaret, at det er en anden stavemåde.
note-absent-close-form = { $form } ({ $count } dokumenter)
note-absent-web = Denne rundes webværktøjer kan søge efter navnet.

## Search progress

note-progress-level = Søgefremgang, niveau { $level }.
note-progress-searches = Søgninger, der allerede er kørt:
note-progress-search = { $name } { $args }: { $items } elementer, { $matches } søgeordstræf.
note-progress-available = Søgetrin, der stadig er tilgængelige:
note-progress-complete = De tilgængelige søgetrin er gennemført.
note-progress-write-now = Skriv nu svaret eller rapporten. Angiv, hvad de læste kilder ikke indeholder, og nævn søgningerne.
note-progress-answer-next = Dit næste svar skal være selve svaret. Angiv de manglende fakta og de søgninger, du har kørt.
note-progress-step-quoted = Søg efter hvert navn som en citeret frase med search_collections.
note-progress-step-variants = Søg efter ord uden citationstegn og navnevarianter. Læs ordantal og stavekandidater.
note-progress-step-filters = Fjern filtre ét ad gangen, og kør en søgning uden filtre.
note-progress-step-facets = Kontrollér filterværdier med search_facet_values.
note-progress-step-dates = Kontrollér datoer med search_histogram.
note-progress-step-passages = Søg efter en beskrivelse af indholdet med search_passages.
note-progress-step-folder = Brug { $tool } til den ønskede mappe, sti eller fil.
note-progress-step-read-hits = Læs de 1 til 3 bedste træf med { $tool }.
note-progress-step-web-search = Søg på nettet med web_search, og læs de bedste resultatsider.
note-progress-step-page-find = Søg i den gemte tekst på en lang side med read_page og find.
note-progress-step-page-retry = Læs en anden resultatadresse eller den arkiverede kopi af en side, der mislykkedes.
note-advice-stuck = Et chattjek vurderer, at de seneste søgninger gentager deres resultater. Færdigheden no_results beskriver andre former for en søgning.
note-advice-absent = Et chattjek vurderer, at resultaterne ikke indeholder det, opgaven beder om. Angiv det søgte område, før du melder, at noget mangler.
note-advice-completion = Et chattjek vurderer, at resultaterne kan besvare opgaven. Sammenlign hver ønsket del med de kilder, du har læst, før du svarer.
note-progress-ended = Kørslen sluttede efter gentagne søgninger uden fremgang.
note-progress-ended-none = Der blev ikke fundet nogen kilde med søgeordstræf.
note-progress-ended-some = Søgningerne fandt { $count } kilder med søgeordstræf. Agenten gennemførte ikke sit svar.
note-progress-ended-searches = Kørte søgninger:
