# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Der Bot ist tätig…
chat-composer-ask-the-bot = Fragen Sie den Bot…
chat-composer-internet-tools = Internet-Tools
chat-composer-agent-language-title = Der Agent antwortet in { $language }. Ändern Sie die Sprache in den Einstellungen, in einem neuen Tab.
chat-composer-try-again-in-s = In { $secs } s erneut versuchen
chat-composer-stop-the-answer-the-partial = Antwort stoppen (der Teilantwort wird nicht im Chat gespeichert)
chat-composer-starting-the-conversation-u = Unterhaltung wird gestartet…
chat-composer-send = Senden
chat-conversation-find-search-in-conversation = In der Unterhaltung suchen
chat-conversation-find-previous-match = Vorheriges Ergebnis
chat-conversation-find-next-match = Nächstes Ergebnis
chat-conversation-find-investigation-board = Ermittlungsboard
doc-ref-card-not-openable = Nicht öffnbar: { $reason }.
doc-ref-card-the-search-term-was = Der Suchbegriff war{ " " }
doc-ref-card-open = Öffnen
doc-ref-card-not-openable-2 = Nicht öffnbar
chat-markdown-text-show-the-cited-source = Angezogene Quelle anzeigen
chat-markdown-text-no-citation-of-this-conversation = Keine Belegstelle dieser Unterhaltung vergab dieses Kürzel, daher steht kein Dokument dahinter.
chat-markdown-text-citations-of-this-conversation-gave = Belegstellen dieser Unterhaltung vergaben dieses Kürzel für mehr als ein Dokument, daher wird keines davon verlinkt.
cards-browser-card-open-the-archived-page = Archivierte Seite öffnen
cards-browser-card-the-page-itself-was-not = Die Seite selbst wurde nicht archiviert (Status: { $artifact_status }). Der obige Screenshot ist die erhaltene Version.
cards-browser-card-click-the-screenshot-to-open = Klicken Sie auf den Screenshot, um die archivierte Seite zu öffnen.
cards-browser-card-show-less = Weniger anzeigen
cards-browser-card-show-all = Alle anzeigen
cards-browser-card-archived-page = Archivierte Seite
cards-browser-card-download = Herunterladen
cards-browser-card-archived-copy-of = Archivierte Kopie von { $artifact_url }
cards-browser-card-this-page-was-not-archived = Diese Seite wurde nicht archiviert (Status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } mit einer Karte
cards-entities-card-the-entity-list-was-cut = Die Entitätsliste wurde gekürzt.
cards-entities-card-open-the-card-for-this = Karte für diesen Wert öffnen ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Keine Karte: Dieses Gespräch hat den Datensatz, aus dem diese Werte stammen, nie benannt, und der Betrachter wird nach Datensatz angesprochen.
cards-entities-card-more-all-of-them-in = { $rest } weitere, alle davon im Entitätenbereich des Dokuments.{ " " }
cards-entities-card-names-organisations-and-places-above = Die Namen, Organisationen und Orte oben sind die Interpretation des Textes durch ein Modell. Es gibt keine Regel, die sie geprüft hat, es gibt also nichts zu erklären, und sie öffnen nichts.
cards-entities-card-nothing-extracted-from-this-document = Aus diesem Dokument wurde nichts extrahiert.
chat-tool-cards-hide = Ausblenden
chat-tool-cards-expand = Einblenden
chat-tool-cards-hide-raw-json = Rohes JSON ausblenden
chat-tool-cards-show-raw-json = Rohes JSON einblenden
cards-result-cards-search-this = Dies suchen
cards-result-cards-search-every-collection = Alle Sammlungen durchsuchen
cards-result-cards-form = Formular { $index }: { $form }
cards-result-cards-show-full-text = Volltext anzeigen
cards-result-cards-quote = Zitat: { $quote }
cards-result-cards-reason = Grund: { $why }
cards-result-cards-open-question = Offene Frage: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Die Erkundung gab diesem Board diese Antwort als { $kind ->
        [sourced] eine Quelle
        [inferred] eine abgeleitete
        [not_found] eine nicht gefundene
       *[other] eine unbekannte Art
    } Ergebnis.
cards-result-cards-it-left-no-open-question = Es blieb keine offene Frage.
cards-result-cards-open-questions-for-the-board = Offene Fragen für das Board:
cards-result-cards-arguments = Argumente
cards-result-cards-list-after-the-call = Liste nach dem Aufruf: { $snapshot_goal }
cards-result-cards-replaces = { " " }· ersetzt { $replaces_id }
cards-result-cards-the-list-at-this-version = Die Liste in dieser Version wird nicht gespeichert.
web-search-card-these-sources-returned-nothing-so = Diese Quellen haben nichts zurückgegeben, daher stammen die Ergebnisse aus weniger Quellen als geplant.
web-search-card-u-degraded = ⚠ { $degraded_len } reduziert
web-search-card-form = Formular { $index }: { $form }
web-search-card-no-results-from = Keine Ergebnisse aus: { $degraded_text }
web-search-card-no-results-every-source-answered = Keine Ergebnisse. Jede Quelle hat geantwortet, und keine hatte etwas für diese Abfrage.
web-search-card-the-lowest-ranked-results-were = Die am niedrigsten bewerteten Ergebnisse wurden verworfen, damit dieser Aufruf in das Transkript passt. Der Assistent hat sie alle gesehen.
web-search-card-view-search-details = Suchdetails anzeigen.
web-search-card-the-stored-result-could-not = das gespeicherte Ergebnis konnte nicht als JSON zurückgelesen werden.
web-search-card-nothing-was-stored-for-this = Für diesen Aufruf wurde nichts gespeichert.
web-search-card-forms = Formulare: { $forms }
web-search-card-kind = Art: { $row_kind }
web-search-card-published = Veröffentlicht: { $row_published }
web-search-card-loading-search-detail-u = Suchdetail wird geladen…
web-search-card-could-not-load-the-search = Suchdetail konnte nicht geladen werden: { $e }
web-search-card-malformed-detail = Fehlformatiertes Detail: { $e }
web-search-card-the-tool-returned-selected-results = Das Werkzeug hat ausgewählte Ergebnisse an das Modell zurückgegeben.
web-search-card-results-use-reciprocal-rank-fusion = Ergebnisse verwenden die reziproke Rangenfusion.
web-search-card-returned-nothing = gab nichts zurück: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle Kandidaten verwenden die Fusionsreihenfolge.
web-search-card-the-cross-encoder-ranks-selected = Der Cross-Encoder rangiert die ausgewählten Ergebnisse.
web-search-card-selected-results-use-fusion-order = Ausgewählte Ergebnisse verwenden die Fusionsreihenfolge.
web-search-card-search-detail = Suchdetail
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Dies durchsuchen
chat-tool-disclosure-search-every-collection = Jede Sammlung durchsuchen
chat-tool-disclosure-hide = Ausblenden
chat-tool-disclosure-expand = Erweitern
chat-tool-disclosure-this-step-was-recorded-before = Dieser Schritt wurde aufgezeichnet, bevor Werkzeugargumente und -ergebnisse gespeichert wurden. Nur die folgende Zusammenfassung ist verfügbar.
chat-tool-disclosure-arguments = Argumente
chat-tool-disclosure-result = Ergebnis
chat-tool-disclosure-hide-raw-json = Roh-JSON ausblenden
chat-tool-disclosure-show-raw-json = Roh-JSON anzeigen
chat-tool-disclosure-input-json = Eingabe-JSON
chat-tool-disclosure-output-json = Ausgabe-JSON
chat-transcript-ask-a-question-about-the = Stellen Sie eine Frage zu den Dokumenten in Ihren Sammlungen.
chat-transcript-suggested-next = Vorgeschlagen weiter…
chat-transcript-earlier-answer = Frühere Antwort
chat-transcript-tokens-the-conversation-carries-the = Tokens, die die Unterhaltung enthält, der größte einzelne Kontext, für den dieser Zug billingspflichtig war, und wie viel des Modellfensters dabei verwendet wurde
chat-transcript-instruction-to-the-agent = Anweisung an den Agent
chat-transcript-the-context-stays-above-the = Der Kontext bleibt über dem Ziel von { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } Zusammenfassungsteile sind fehlgeschlagen. Der Datensatz enthält nur die Listen.
chat-transcript-show-the-record = Datensatz anzeigen
chat-transcript-hide-reasoning = Begründung ausblenden
chat-transcript-show-reasoning = Begründung anzeigen
chat-transcript-from-u-hide = { $count } { $noun } aus { $tool } — ausblenden
chat-transcript-from-u-show = { $count } { $noun } aus { $tool } — anzeigen
chat-transcript-u-hide = { $summary } — ausblenden
chat-transcript-u-show = { $summary } — anzeigen
chat-transcript-citations-of-this-conversation-give = Belege dieser Unterhaltung geben { $doc_handle } an mehr als ein Dokument an. Die Antwort verlinkt sie mit keinem davon.
chat-transcript-report = Report { $label }
chat-transcript-open-in-the-workspace = Im Workspace öffnen
chat-transcript-this-version-could-not-be = Diese Version konnte nicht gelesen werden. Der Chat-Text der Antwort folgt.
chat-transcript-files = Dateien
chat-transcript-version = { $file_name }, Version { $file_version }
chat-web-find-exact-text = Exakten Text suchen
chat-web-previous-match = Vorheriges Ergebnis
chat-web-next-match = Nächstes Ergebnis
chat-web-close-preview = Vorschau schließen
chat-web-the-captured-page-could-not = Die erfasste Seite konnte nicht geladen werden.
chat-web-loading = Wird geladen…
chat-workspace-pane-workspace = Workspace
chat-workspace-pane-close-the-workspace = Workspace schließen
chat-workspace-pane-close = Schließen
chat-workspace-pane-loading-the-files-u = Dateien werden geladen…
chat-workspace-pane-the-files-could-not-be = Die Dateien konnten nicht geladen werden: { $error }
chat-workspace-pane-this-conversation-has-no-files = Diese Unterhaltung hat keine Dateien.
chat-workspace-pane-version = Version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Wählen Sie eine Datei, um sie zu lesen.
chat-workspace-pane-loading-the-file-u = Datei wird geladen…
chat-workspace-pane-the-file-could-not-be = Die Datei konnte nicht geladen werden: { $error }
chat-workspace-pane-version-2 = { $found_name }, Version { $found_version }
chat-board-create-collections = Sammlungen
chat-board-create-loading-collections-u = Sammlungen werden geladen…
chat-board-create-hoover-search-new-board = Hoover-Suche – Neues Board
chat-board-create-ai-chat = AI-Chat
chat-board-create-new-investigation-board = Neues Ermittlungspanel
chat-board-create-a-board-runs-its-goals = Ein Board führt seine Ziele als Abfolge von Agent-Erkundungen aus. Jede Erkundung ist ein Chat, der mit einem Board-Ergebnis endet. Sie prüfen die Antwort jedes Ziels und können Ergebnisse ablehnen sowie Hinweise hinzufügen, während es läuft.
chat-board-create-title = Titel
chat-board-create-goal = Ziel
chat-board-create-remove-this-goal = Dieses Ziel entfernen
chat-board-create-remove = Entfernen
chat-board-create-add-a-goal = Ziel hinzufügen
chat-board-create-context-optional = Kontext (optional)
chat-board-create-hints-one-per-line-optional = Hinweise, je eine pro Zeile (optional)
chat-board-create-sources = Quellen
chat-board-create-internet-tools = Internet-Tools
chat-board-create-creating-board = Board wird erstellt…
chat-board-create-create-board = Board erstellen
ai-chat-board-hoover-search-board = Hoover-Suche – Board
ai-chat-board-loading-the-board-u = Board wird geladen…
ai-chat-board-show-the-board-overview = Board-Übersicht anzeigen
ai-chat-board-zoom-out = Verkleinern
ai-chat-board-zoom-in = Vergrößern
ai-chat-board-u-ai-chat = ← AI-Chat
ai-chat-board-settings = Einstellungen
ai-chat-board-board-settings = Board-Einstellungen
ai-chat-board-internet-tools = Internet-Tools
ai-chat-board-the-next-explores-of-the = Die nächsten Erkundungen des Boards können das Internet durchsuchen und Webseiten lesen. Laufende Erkundungen behalten die Einstellung, mit der sie gestartet sind.
ai-chat-board-collections = Sammlungen
ai-chat-board-the-collections-are-fixed-when = Die Sammlungen sind festgelegt, wenn das Board erstellt wird.
ai-chat-board-confirm-drop = Abwurf bestätigen
ai-chat-board-drop-the-board = Lege das Board ab
ai-chat-board-close = Schließen
ai-chat-board-the-board-used-its-explore = Das Board hat seine Erkundungslimits verwendet
ai-chat-board-the-board-used-explores-the = Das Board verwendet { $explore_limit } Erkundungen, das Limit von einem Board. Es wird keine weitere Arbeit aufgenommen. Sie können die vorgeschlagenen Antworten weiterhin festlegen.
ai-chat-board-create-a-new-board-to = Erstellen Sie ein neues Board, um die Untersuchung fortzusetzen
ai-chat-board-goal = Ziel
ai-chat-board-goals = Ziele
ai-chat-board-add-new-goal = Neues Ziel hinzufügen...
ai-chat-board-a-new-goal = Ein neues Ziel
ai-chat-board-add-goal = Ziel hinzufügen
ai-chat-board-a-board-has-at-most = Ein Board hat höchstens { $max_goals } Ziele. Erstellen Sie ein neues Board für ein weiteres Ziel.
ai-chat-board-background-context = Überlagerter Kontext
ai-chat-board-continue-with-a-correction = Mit einer Korrektur fortfahren
ai-chat-board-correction-what-is-wrong-or = Korrektur: was falsch oder fehlt. Das Board setzt damit fort.
ai-chat-board-the-board-waits-for-your = Das Board wartet auf deine Prüfung
ai-chat-board-the-board-used-its-budget = Das Board hat sein Budget von { $snap_max_explores } Erkundungen verwendet.
ai-chat-board-the-assessments-gave-no-usable = Die Bewertungen lieferten keine verwertbare Richtung.
ai-chat-board-accept-or-reject-the-proposed = Akzeptieren oder Ablehnen der vorgeschlagenen Antwort jedes obigen Ziels. Eine abgelehnte Antwort lässt das Board sofort fortsetzen.
ai-chat-board-no-proposed-answer-waits-for = Es wartet kein vorgeschlagene Antwort auf deine Entscheidung.
ai-chat-board-reopen-the-board-to-continue = Wiederhole das Board, um mit den offenen Zielen fortzufahren. Dabei werden die Ergebnisse und Antworten beibehalten.
ai-chat-board-close-the-board-to-accept = Schließen Sie das Board, um alle vorgeschlagenen Antworten zu übernehmen und es zu beenden, oder setzen Sie es mit einer Korrektur fort.
ai-chat-board-close-the-board = Board schließen
ai-chat-board-or-reopen-the-board-to = Oder Board erneut öffnen, um die offenen Ziele ohne Korrektur fortzusetzen.
ai-chat-board-the-board-is-complete = Das Board ist vollständig
ai-chat-board-a-goal-has-no-accepted = Ein Ziel hat keine akzeptierte Antwort. Öffne das Board erneut, um es fortzusetzen. Das Board behält seine Ergebnisse und Antworten.
ai-chat-board-add-a-hint = Hinweis hinzufügen
ai-chat-board-the-next-assessment-reads-every = Die nächste Bewertung liest jeden Hinweis. Ein Hinweis beantwortet auch eine Erkundung, die eine Frage gestellt hat.
ai-chat-board-add-hint = Hinweis hinzufügen
ai-chat-board-events = Ereignisse
ai-chat-board-newest-first = Neueste zuerst
ai-chat-board-date = Datum
ai-chat-board-actor = Akteur
ai-chat-board-event = Ereignis
ai-chat-board-show-details = Details anzeigen
ai-chat-board-open = Öffnen
ai-chat-board-show-the-newest-events = Die neuesten { $event_rows } Ereignisse anzeigen
ai-chat-board-show-all-events = Alle { $snap_events_len } Ereignisse anzeigen
ai-chat-board-statistics = Statistiken
ai-chat-board-explores = Erkundungen
ai-chat-board-model-steps-per-explore = Modellschritte je Erkundung
ai-chat-board-assessments = Bewertungen
ai-chat-board-intents = Absichten
ai-chat-board-findings = Ergebnisse
ai-chat-board-created = Erstellt
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } hat dieses Ergebnis am { $format_utc_ms_fact_rejected_ms } verworfen. Das Board verwendet es nicht mehr.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } hat dieses Ergebnis verworfen. Das Board verwendet es nicht mehr.
ai-chat-board-no-reason-was-given = Es wurde kein Grund angegeben.
ai-chat-board-reason = Grund: { $fact_rejected_reason }
ai-chat-board-open-questions = Offene Fragen
ai-chat-board-explored-in = Erkundet in{ " " }
ai-chat-board-explore-this-question = Diese Frage erkunden
ai-chat-board-your-questions = Ihre Fragen
ai-chat-board-ask-about-the-background-context = Nach dem Hintergrundkontext fragen
ai-chat-board-ask-about-this-finding = Nach diesem Ergebnis fragen
ai-chat-board-a-follow-up-question-about = Eine Anschlussfrage zu diesem Knoten
ai-chat-board-ask = Fragen
ai-chat-board-checks-that-changed-this-finding = Prüfungen, die dieses Ergebnis geändert haben
ai-chat-board-reject-this-correction = Diese Korrektur ablehnen
ai-chat-board-reject-this-finding = Dieses Ergebnis ablehnen
ai-chat-board-not-answered-the-board-was = Beantwortet. Das Board wurde ohne Antwort auf dieses Ziel abgeschlossen. Ein Hinweis oder eine Wiedereröffnung öffnet es erneut.
ai-chat-board-no-answer-yet = Noch keine Antwort.
ai-chat-board-the-findings-of-this-answer = Die Ergebnisse dieser Antwort sind Suchen, die nichts gefunden haben. Akzeptiere sie, um zu dokumentieren, dass die Datensätze das Ziel nicht beantworten, oder lehne sie ab, um die Untersuchung fortzusetzen.
ai-chat-board-open-an-assessment-to-read = { "." } Öffne eine Bewertung, um zu lesen, warum.
ai-chat-board-from-the-findings = Aus den Ergebnissen{ " " }
ai-chat-board-accept-answer = Antwort akzeptieren
ai-chat-board-why-the-answer-is-wrong = Warum die Antwort falsch oder unvollständig ist
ai-chat-board-reject-answer = Antwort ablehnen
ai-chat-board-intent = Ziel
ai-chat-board-attempts-declared = Versuche: { $intent_attempts }. Angegeben { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Die Erkundung fragte
ai-chat-board-add-a-hint-in-the = Füge in der Board-Übersicht einen Hinweis hinzu, um es zu beantworten.
ai-chat-board-last-error = Letzter Fehler
ai-chat-board-brief = Kurz
ai-chat-board-open-the-explore-chat = Erkundungs-Chat öffnen
ai-chat-board-loading-the-assessment-u = Bewertung wird geladen…
ai-chat-board-assessment = Bewertung { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Ergebnis { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Prüfungen, die es geändert haben
ai-chat-board-prompt = Eingabe
ai-chat-board-this-assessment-ran-before-the = Diese Bewertung lief, bevor die Eingaben gespeichert wurden.
ai-chat-board-response = Antwort
ai-chat-history-hoover-search-chat-history = Hoover-Suche - Chat-Verlauf
ai-chat-history-u-back = ← Zurück
ai-chat-history-conversation-history = Gesprächsverlauf
ai-chat-history-show-board-chats = Board-Chats anzeigen
ai-chat-history-loading-u = Wird geladen…
ai-chat-history-could-not-load-history = Verlauf konnte nicht geladen werden: { $e }
ai-chat-history-no-conversations-yet = Noch keine Gespräche.
ai-chat-history-board = Board
ai-chat-history-new-chat = Neues Gespräch
ai-chat-history-messages-updated = { $s_message_count } Nachrichten · aktualisiert am { $s_updated_at }
ai-chat-history-delete-conversation = Gespräch löschen
ai-chat-history-delete = Löschen
ai-chat-homepage-hoover-search-ai-chat = Hoover-Suche – KI-Chat
ai-chat-homepage-what-are-you-researching = Woran forschen Sie?
ai-chat-homepage-view-all-conversations = Alle Gespräche anzeigen
ai-chat-homepage-starting-conversation-u = Gespräch wird gestartet…
ai-chat-homepage-investigation-boards = Untersuchungboards
ai-chat-homepage-new-board = Neues Board
ai-chat-homepage-loading-boards-u = Boards werden geladen…
ai-chat-homepage-could-not-load-the-boards = Die Boards konnten nicht geladen werden: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Sie haben kein Board. Ein Board führt eine lange Untersuchung als Abfolge von Agent-Erkundungen durch, und Sie prüfen deren Antworten.
ai-chat-homepage-updated = Aktualisiert am { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover-Suche – KI-Chat
ai-chat-session-this-conversation-could-not-be = Dieses Gespräch konnte nicht geladen werden.
ai-chat-session-loading-u = Wird geladen…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = Verlauf
ai-chat-session-show-the-files-that-the = Dateien anzeigen, die der Assistent in diesem geschrieben hat
ai-chat-session-workspace = Arbeitsbereich
ai-chat-session-this-answer-was-interrupted-before = Diese Antwort wurde unterbrochen, bevor sie abgeschlossen war, weil die Seite oder der Server mitten im Vorgang angehalten hat. Fordern Sie die Antwort erneut an, um es zu wiederholen.
ai-chat-session-dismiss = Schließen
ai-chat-session-board-explore-chats-are-read = Board-Erkundungs-Chats sind schreibgeschützt.
ai-chat-session-open-the-board = Board öffnen
chat-locked-options-on = { $label }: an
chat-locked-options-off = { $label }: aus
chat-tool-cards-running-u = läuft…
cards-result-cards-quote-found = Zitat gefunden
cards-result-cards-quote-not-found = Zitat nicht gefunden
cards-result-cards-quote-not-checked = Zitat nicht geprüft
web-search-card-results = { $results_len } Ergebnisse
chat-tool-disclosure-running-u = Läuft…
chat-transcript-call = Anruf
chat-transcript-calls = Anrufe
ai-chat-board-a-board-without-collections-needs = Ein Board ohne Sammlungen benötigt Internet-Tools.
ai-chat-board-of = { $snap_explores_used } von { $snap_max_explores }
ai-chat-board-assessment-2 = Bewertung { $number }
ai-chat-history-messages = { $s_message_count } Nachrichten
web-search-card-reranked-in = Der Cross-Encoder hat die Ergebnisse in { $ms } ms neu sortiert.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = Score { $score } · war RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Der Zug wartet auf einen freien Modellplatz.
chat-activity-the-turn-waits-for-a-2 = Der Zug wartet auf einen freien Werkzeugplatz.
chat-locked-options-start-a-new-chat-to = Starten Sie einen neuen Chat, um diese Einstellung zu ändern.
chat-locked-options-internet-tools = Internet-Tools
chat-session-card-new-chat = Neuer Chat
chat-tool-cards-first-frame-of-the-video = Erstes Bild des Videos
chat-tool-cards-screenshot-of = Screenshot von
chat-tool-cards-image = Bild
cards-result-cards-the-agent-asked-a-question = Der Agent hat eine Frage gestellt.
chat-transcript-hide = Ausblenden
chat-transcript-show = Einblenden
chat-transcript-unverified-quote-the-quoted-span = Ungeprüftes Zitat. Der zitierte Abschnitt ist zu kurz, um ihn zu prüfen.
chat-transcript-unverified-quote-the-document-text = Ungeprüftes Zitat. Der Dokumententext konnte nicht gelesen werden.
chat-transcript-unverified-quote-this-wording-was = Ungeprüftes Zitat. Diese Formulierung wurde nicht im Dokument gefunden.
chat-board-create-select-a-collection-or-turn = Wählen Sie eine Sammlung oder schalten Sie Internet-Tools ein.
chat-board-create-select-at-least-one-collection = Wählen Sie mindestens eine Sammlung.
ai-chat-board-active = Aktiv
ai-chat-board-paused = Pausiert
ai-chat-board-waits-for-review = Wartet auf Prüfung
ai-chat-board-completed = Abgeschlossen
ai-chat-board-dropped = Verworfen
ai-chat-board-unknown = Unbekannt
ai-chat-board-pause-the-board = Board pausieren
ai-chat-board-resume-the-board = Board fortsetzen
ai-chat-board-none = Keine
ai-chat-board-reopen-with-the-remaining-budget = Mit dem verbleibenden Budget erneut öffnen
ai-chat-board-finding = Ergebnis
ai-chat-board-why-the-correction-is-wrong = Warum die Korrektur falsch ist
ai-chat-board-reject-correction = Korrektur ablehnen
ai-chat-board-why-the-finding-is-wrong = Warum das Ergebnis falsch ist
ai-chat-board-reject-finding = Ergebnis ablehnen
ai-chat-board-answer = Antwort
ai-chat-board-proposed-answer = Vorgeschlagene Antwort
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pausiert
ai-chat-homepage-waits-for-review = Wartet auf Prüfung
ai-chat-homepage-completed = Abgeschlossen
ai-chat-homepage-dropped = Verworfen
ai-chat-homepage-unknown = Unbekannt
cards-result-cards-submitted-by-board =
    Vom Board eingereicht: { $kind ->
        [sourced] eine bezogene
        [inferred] eine abgeleitete
        [not_found] eine nicht gefundene
       *[other] eine unbekannte Art
    } Ergebnis aus dem Bericht
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Eine bezogene
        [inferred] Eine abgeleitete
        [not_found] Eine nicht gefundene
       *[other] Eine unbekannte Art
    } Ergebnis für das Board
chat-transcript-compacting = Kontext wird komprimiert: { $before } Tokens auf ein Ziel von { $target }.
chat-transcript-compaction-failed = Die Zusammenfassung der früheren Schritte fehlgeschlagen. Das Modell erhielt die früheren Schritte unverändert, { $after } Tokens.
chat-transcript-compacted = Kontext komprimiert: { $steps } Schritte zusammengefasst, { $before } Tokens auf { $after }.
ai-chat-board-reopen-with-more = Mit { $grant } weiteren Erkundungen erneut öffnen
ai-chat-board-goal-number = Ziel { $number }
ai-chat-board-from-assessment-on = Von Bewertung { $number } am { $date }.
ai-chat-board-from-assessment = Von Bewertung { $number }.
chat-board-create-goal-2 = Ziel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = Kontakt zum Chat verloren: { $e }
ai-chat-session-could-not-stop-the-answer = konnte die Antwort nicht stoppen: { $e } — sie läuft noch
ai-chat-board-later-assessments-dropped-an-answer = { $n } spätere Bewertungen haben eine Antwort für dieses Ziel verworfen:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } Prompt- und { $a_completion_tokens } Completion-Token
ai-chat-homepage-completed-goals-not-answered = Abgeschlossen, { $n } Ziele nicht beantwortet
board-graph-intent = Ziel, { $state }
chat-workspace-pane-characters = { $chars } Zeichen
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } Tool läuft { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } Tool läuft { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Beantwortet nach { $retries_len } fehlgeschlagenem Versuch{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } fehlgeschlagener Versuch{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, Version { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] { $n } Suchbegriff durchsucht
       *[other] { $n } Suchbegriffe durchsucht
    }
tool-run-summary-read =
    { $n ->
        [one] { $n } Dokument gelesen
       *[other] { $n } Dokumente gelesen
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] durchsuchte das Web nach { $n } Begriff
       *[other] durchsuchte das Web nach { $n } Begriffen
    }
tool-run-summary-read-web =
    { $n ->
        [one] las { $n } Webseite
       *[other] las { $n } Webseiten
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } Browser-Aktion
       *[other] { $n } Browser-Aktionen
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listete die Entitäten von { $n } Dokument
       *[other] listete die Entitäten von { $n } Dokumenten
    }
tool-run-summary-cited =
    { $n ->
        [one] zitierte { $n } Dokument
       *[other] zitierte { $n } Dokumente
    }
tool-run-summary-cited-web =
    { $n ->
        [one] zitierte { $n } Webseite
       *[other] zitierte { $n } Webseiten
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] las { $n } Skill- und Tool-Text
       *[other] las { $n } Skill- und Tool-Texte
    }
tool-run-summary-saved =
    { $n ->
        [one] speicherte { $n } Notiz
       *[other] speicherte { $n } Notizen
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } To-do-Liste-Aufruf
       *[other] { $n } To-do-Liste-Abrufe
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } Anweisung an den Agent
       *[other] { $n } Anweisungen an den Agent
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } anderer Aufruf
       *[other] { $n } andere Abrufe
    }
tool-run-summary-failed = { $failures } fehlgeschlagen
tool-run-summary-took = dauerte { $duration_text_ms }
chat-session-card-messages = { $session_message_count } Nachrichten
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } Element
       *[other] { $count } Elemente
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } Feld
       *[other] { $count } Felder
    }
chat-tool-disclosure-searched-collections = durchsuchte Sammlungen{ $filters }
chat-tool-disclosure-searched-collections-2 = durchsuchte Sammlungen · { $query }{ $filters }
chat-tool-disclosure-cited-documents = zitierte { $n } Dokumente
chat-tool-disclosure-read-document = Dokument gelesen · { $path }
chat-tool-disclosure-searched-the-web = durchsuchtes Web · { $q }
chat-tool-disclosure-opened-page = geöffnete Seite · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = aufgerufen { $other }
chat-tool-disclosure-called-2 = aufgerufen { $other } · { $short }
cards-browser-card-opened = geöffnet { $url }
cards-browser-card-could-not-open = konnte nicht geöffnet werden { $url }
cards-browser-card-clicked = geklickt auf { $element }
cards-browser-card-could-not-click = konnte nicht geklickt werden auf { $element }
cards-browser-card-typed-into = eingegeben in { $element }
cards-browser-card-could-not-type-into = konnte nicht eingegeben werden in { $element }
cards-browser-card-typed = „{ $text }“ eingegeben
cards-browser-card-could-not-type = „{ $text }“ konnte nicht eingegeben werden
cards-browser-card-pressed = gedrückt { $key }
cards-browser-card-could-not-press = konnte nicht gedrückt werden { $key }
cards-browser-card-chose-an-option-in = eine Option gewählt in { $element }
cards-browser-card-could-not-choose-an-option = konnte keine Option wählen in { $element }
cards-browser-card-hovered = über { $element } gefahren
cards-browser-card-could-not-hover = konnte nicht über { $element } fahren
cards-browser-card-failed = { $bare } — fehlgeschlagen
cards-entities-card-listed-entities-document = Entitäten aufgelistet · { $count } Dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · Teil { $part } von { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } Dokumente
cards-result-cards-forms = { $tool_name } · { $forms } Formulare
cards-result-cards-in = { " " }in { $collections }
cards-result-cards-page = { " " }· Seite { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } Dokumente · { $missing } Belege nicht gefunden
cards-result-cards-version-unchanged = { $tool_name } · Version { $version } · unverändert
cards-result-cards-version = { $tool_name } · Version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } Ergebnisse, { $json_u64_doc_total_after_dedupe } nach Deduplizierung
