# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = Le ultime due ricerche non hanno trovato nessuna fonte nuova. Leggi ora le pagine dei risultati migliori: inserisci fino a 6 dei loro URL in un'unica chiamata read_page, nell'elenco `urls`. Cerca di nuovo solo con una domanda diversa.
note-discovery-l3-web = Hai risposto prima di leggere una qualsiasi pagina di fonte. Chiama read_page una sola volta con gli URL delle pagine che sostengono i tuoi elementi, fino a 6 nell'elenco `urls`. Poi scrivi di nuovo la risposta con le fonti che la sostengono.
note-discovery-l3-documents = Hai risposto prima di leggere un qualsiasi documento. Leggi con read_documents i documenti che sostengono i tuoi elementi, con più hash di file in un'unica chiamata. Poi scrivi di nuovo la risposta con le fonti che la sostengono.
note-discovery-l4 = Leggi ora le pagine dei risultati che possono rispondere alla richiesta: inserisci fino a 6 dei loro URL in un'unica chiamata read_page, nell'elenco `urls`. Una sola chiamata le legge tutte nello stesso momento.

## Page captures

note-capture-empty = L'acquisizione di { $urls } non contiene il testo di un articolo. Leggi un'altra fonte. Non citare questa pagina.

## Sources

note-web-tools-absent = Questo turno non ha strumenti web, quindi non può leggere pagine web pubbliche. Usa le raccolte selezionate e indica quale parte della richiesta esse non coprono.
note-sources-documents = Cerca prima nelle raccolte di documenti consentite. Leggi i loro documenti pertinenti.
note-sources-documents-before-web = Cerca prima nelle raccolte di documenti consentite. Leggi i loro documenti pertinenti. Leggi questi documenti prima di usare il web.

## Named things

note-absent-collection = Nessuna raccolta consentita si chiama { $name }. Le raccolte consentite sono { $collections }.
note-absent-name = Le raccolte selezionate non hanno nessuna corrispondenza indicizzata per { $name }.
note-absent-close-forms = Forme simili indicizzate: { $forms }. Non usare una forma simile come nome richiesto. Quando ne cerchi una, indicala nella risposta come grafia diversa.
note-absent-close-form = { $form } ({ $count } documenti)
note-absent-web = Gli strumenti web di questo turno possono cercare il nome.

## Search progress

note-progress-level = Livello di avanzamento della ricerca: { $level }.
note-progress-searches = Ricerche già eseguite:
note-progress-search = { $name } { $args }: { $items } elementi, { $matches } corrispondenze di parole chiave.
note-progress-available = Passaggi di ricerca ancora disponibili:
note-progress-complete = I passaggi di ricerca disponibili sono completi.
note-progress-write-now = Scrivi ora la risposta o il report. Indica che cosa le fonti lette non contengono e nomina le ricerche.
note-progress-answer-next = La prossima risposta deve essere la risposta finale. Indica i fatti mancanti e le ricerche che hai eseguito.
note-progress-step-quoted = Cerca ogni nome come frase tra virgolette con search_collections.
note-progress-step-variants = Cerca parole senza virgolette e varianti dei nomi. Leggi i conteggi delle parole e i candidati di grafia.
note-progress-step-filters = Rimuovi i filtri uno alla volta ed esegui una ricerca senza filtri.
note-progress-step-facets = Verifica i valori dei filtri con search_facet_values.
note-progress-step-dates = Verifica le date con search_histogram.
note-progress-step-passages = Cerca la descrizione di un contenuto con search_passages.
note-progress-step-folder = Usa { $tool } per la cartella, il percorso o il file richiesto.
note-progress-step-read-hits = Leggi i migliori 1-3 risultati con { $tool }.
note-progress-step-web-search = Cerca sul web con web_search e leggi le pagine dei risultati migliori.
note-progress-step-page-find = Cerca nel testo conservato di una pagina lunga con read_page e find.
note-progress-step-page-retry = Leggi un altro indirizzo tra i risultati, oppure la copia archiviata di una pagina non riuscita.
note-advice-stuck = Un controllo della chat stima che le ultime ricerche ripetano i loro risultati. La skill no_results descrive altre forme di ricerca.
note-advice-absent = Un controllo della chat stima che i risultati non contengano ciò che l'attività richiede. Indica l'ambito cercato prima di segnalare un'assenza.
note-advice-completion = Un controllo della chat stima che i risultati possano rispondere all'attività. Prima di rispondere, confronta ogni parte richiesta con le fonti che hai letto.
note-progress-ended = L'esecuzione è terminata dopo ricerche ripetute senza progressi.
note-progress-ended-none = Non è stata trovata nessuna fonte con corrispondenze di parole chiave.
note-progress-ended-some = Le ricerche hanno trovato { $count } fonti con corrispondenze di parole chiave. L'agente non ha completato la risposta.
note-progress-ended-searches = Ricerche eseguite:
