# Translation of en/notes.ftl. Change it together with the English catalog.

note-discovery-l2 = Die letzten zwei Suchen haben keine neue Quelle gefunden. Lesen Sie jetzt die besten Ergebnisseiten: Geben Sie bis zu 6 ihrer URLs in einem Aufruf von `read_page` in dessen Liste `urls` an. Suchen Sie nur mit einer anderen Frage erneut.
note-discovery-l3-web = Sie haben geantwortet, bevor Sie eine Quellenseite gelesen haben. Rufen Sie `read_page` einmal mit den URLs der Seiten auf, die Ihre Angaben stützen, bis zu 6 in dessen Liste `urls`. Schreiben Sie danach die Antwort erneut, mit den Quellen, die sie stützen.
note-discovery-l3-documents = Sie haben geantwortet, bevor Sie ein Dokument gelesen haben. Lesen Sie die Dokumente, die Ihre Angaben stützen, mit `read_documents`, mehrere Datei-Hashes in einem Aufruf. Schreiben Sie danach die Antwort erneut, mit den Quellen, die sie stützen.
note-discovery-l4 = Lesen Sie jetzt die Ergebnisseiten, die die Anfrage beantworten könnten: Geben Sie bis zu 6 ihrer URLs in einem Aufruf von `read_page` in dessen Liste `urls` an. Ein Aufruf liest sie alle gleichzeitig.

note-capture-empty = Die Erfassung von { $urls } enthält keinen Artikeltext. Lesen Sie eine andere Quelle. Belegen Sie nichts mit dieser Seite.

note-web-tools-absent = Diese Runde hat keine Web-Werkzeuge und kann deshalb keine öffentlichen Webseiten lesen. Verwenden Sie die ausgewählten Sammlungen und nennen Sie den Teil der Anfrage, den sie nicht beantworten.
note-sources-documents = Durchsuchen Sie zuerst die erlaubten Dokumentsammlungen. Lesen Sie die relevanten Dokumente daraus.
note-sources-documents-before-web = Durchsuchen Sie zuerst die erlaubten Dokumentsammlungen. Lesen Sie die relevanten Dokumente daraus. Lesen Sie diese Dokumente, bevor Sie das Web verwenden.

note-absent-collection = Keine erlaubte Sammlung heißt { $name }. Die erlaubten Sammlungen sind { $collections }.
note-absent-name = Die ausgewählten Sammlungen haben keinen indizierten Treffer für { $name }.
note-absent-close-forms = Indizierte ähnliche Formen: { $forms }. Verwenden Sie keine ähnliche Form als den angeforderten Namen. Wenn Sie nach einer suchen, nennen Sie sie in der Antwort als abweichende Schreibweise.
note-absent-close-form = { $form } ({ $count } Dokumente)
note-absent-web = Die Web-Werkzeuge dieser Runde können nach dem Namen suchen.

note-progress-level = Stufe { $level } des Suchfortschritts.
note-progress-searches = Bereits ausgeführte Suchen:
note-progress-search = { $name } { $args }: { $items } Einträge, { $matches } Treffer für Schlüsselwörter.
note-progress-available = Noch verfügbare Suchschritte:
note-progress-complete = Die verfügbaren Suchschritte sind abgeschlossen.
note-progress-write-now = Schreiben Sie jetzt die Antwort oder den Bericht. Nennen Sie, was die gelesenen Quellen nicht enthalten, und nennen Sie die Suchen.
note-progress-answer-next = Ihre nächste Antwort muss die Antwort sein. Nennen Sie die fehlenden Fakten und die Suchen, die Sie ausgeführt haben.
note-progress-step-quoted = Suchen Sie jeden Namen als Phrase in Anführungszeichen mit `search_collections`.
note-progress-step-variants = Suchen Sie Wörter ohne Anführungszeichen und Namensvarianten. Lesen Sie die Worthäufigkeiten und die Kandidaten für Schreibweisen.
note-progress-step-filters = Entfernen Sie die Filter einzeln und führen Sie eine Suche ohne Filter aus.
note-progress-step-facets = Prüfen Sie Filterwerte mit `search_facet_values`.
note-progress-step-dates = Prüfen Sie Daten mit `search_histogram`.
note-progress-step-passages = Suchen Sie eine Beschreibung des Inhalts mit `search_passages`.
note-progress-step-folder = Verwenden Sie { $tool } für den angeforderten Ordner, Pfad oder die angeforderte Datei.
note-progress-step-read-hits = Lesen Sie die besten 1 bis 3 Treffer mit { $tool }.
note-progress-step-web-search = Suchen Sie im Web mit `web_search` und lesen Sie die besten Ergebnisseiten.
note-progress-step-page-find = Durchsuchen Sie den gespeicherten Text einer langen Seite mit `read_page` und `find`.
note-progress-step-page-retry = Lesen Sie eine andere Ergebnisadresse oder die archivierte Kopie einer fehlgeschlagenen Seite.
note-advice-stuck = Eine Chat-Prüfung schätzt, dass die letzten Suchen ihre Ergebnisse wiederholen. Der Skill `no_results` beschreibt andere Formen einer Suche.
note-advice-absent = Eine Chat-Prüfung schätzt, dass die Ergebnisse nicht enthalten, was die Aufgabe verlangt. Nennen Sie den durchsuchten Bereich, bevor Sie eine Abwesenheit melden.
note-advice-completion = Eine Chat-Prüfung schätzt, dass die Ergebnisse die Aufgabe beantworten können. Vergleichen Sie vor Ihrer Antwort jeden angeforderten Teil mit den Quellen, die Sie gelesen haben.
note-progress-ended = Der Durchlauf endete nach wiederholten Suchen ohne Fortschritt.
note-progress-ended-none = Es wurde keine Quelle mit Schlüsselwort-Treffer gefunden.
note-progress-ended-some = Die Suchen haben { $count } Quellen mit Schlüsselwort-Treffer gefunden. Der Agent hat seine Antwort nicht abgeschlossen.
note-progress-ended-searches = Ausgeführte Suchen:
