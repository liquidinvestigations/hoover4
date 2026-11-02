# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Der Bot arbeitet…
chat-composer-ask-the-bot = Fragen Sie den Bot…
chat-composer-internet-tools = Internetwerkzeuge
chat-composer-agent-language-title = Der Agent antwortet in { $language }. Ändern Sie die Sprache in den Einstellungen, in einem neuen Tab.
chat-composer-try-again-in-s = In { $secs } s erneut versuchen
chat-composer-stop-the-answer-the-partial = Antwort stoppen (die Teilantwort wird nicht in der Unterhaltung gespeichert)
chat-composer-starting-the-conversation-u = Unterhaltung wird gestartet…
chat-composer-send = Senden
chat-conversation-find-search-in-conversation = In der Unterhaltung suchen
chat-conversation-find-previous-match = Vorheriger Treffer
chat-conversation-find-next-match = Nächster Treffer
chat-conversation-find-investigation-board = Ermittlungsboard
doc-ref-card-not-openable = Nicht zu öffnen: { $reason }.
doc-ref-card-the-search-term-was = Der Suchbegriff war{" "}
doc-ref-card-open = Öffnen
doc-ref-card-not-openable-2 = Nicht zu öffnen
chat-markdown-text-show-the-cited-source = Zitierte Quelle anzeigen
chat-markdown-text-no-citation-of-this-conversation = Kein Beleg dieser Unterhaltung hat diese Belegkennung vergeben, daher steht kein Dokument dahinter.
chat-markdown-text-citations-of-this-conversation-gave = Belege dieser Unterhaltung haben diese Belegkennung mehreren Dokumenten gegeben, daher verweist sie auf keines davon.
cards-browser-card-open-the-archived-page = Archivierte Seite öffnen
cards-browser-card-the-page-itself-was-not = Die Seite selbst wurde nicht archiviert (Status: { $artifact_status }). Aufbewahrt wurde der Screenshot oben.
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
cards-entities-card-no-card-this-conversation-never = Keine Karte: Diese Unterhaltung hat den Datensatz, aus dem diese Werte stammen, nie genannt, und die Dokumentansicht wird über den Datensatz angesprochen.
cards-entities-card-more-all-of-them-in = { $rest } weitere, alle im Entitätenbereich des Dokuments.{" "}
cards-entities-card-names-organisations-and-places-above = Die Namen, Organisationen und Orte oben sind die Lesart des Fließtexts durch ein Modell. Keine Regel hat sie geprüft, daher gibt es nichts zu erklären, und sie öffnen nichts.
cards-entities-card-nothing-extracted-from-this-document = Aus diesem Dokument wurde nichts extrahiert.
chat-tool-cards-hide = Ausblenden
chat-tool-cards-expand = Einblenden
chat-tool-cards-hide-raw-json = Roh-JSON ausblenden
chat-tool-cards-show-raw-json = Roh-JSON anzeigen
cards-result-cards-search-this = Dies durchsuchen
cards-result-cards-search-every-collection = Alle Sammlungen durchsuchen
cards-result-cards-form = Wortform { $index }: { $form }
cards-result-cards-show-full-text = Volltext anzeigen
cards-result-cards-quote = Zitat: { $quote }
cards-result-cards-reason = Grund: { $why }
cards-result-cards-open-question = Offene Frage: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Die Erkundung hat diese Antwort als { $kind ->
        [sourced] eine belegte
        [inferred] eine abgeleitete
        [not_found] eine nicht gefundene
       *[other] eine unbekannte
    } Erkenntnis an ihr Board übergeben.
cards-result-cards-it-left-no-open-question = Es blieb keine offene Frage.
cards-result-cards-open-questions-for-the-board = Offene Fragen für das Board:
cards-result-cards-arguments = Argumente
cards-result-cards-list-after-the-call = Liste nach dem Aufruf: { $snapshot_goal }
cards-result-cards-replaces = {" "}· ersetzt { $replaces_id }
cards-result-cards-the-list-at-this-version = Die Liste in dieser Version wird nicht gespeichert.
web-search-card-these-sources-returned-nothing-so = Diese Quellen haben nichts geliefert, daher stammen die Ergebnisse aus weniger Quellen als vorgesehen
web-search-card-u-degraded = ⚠ { $degraded_len } eingeschränkt
web-search-card-form = Wortform { $index }: { $form }
web-search-card-no-results-from = Keine Ergebnisse aus: { $degraded_text }
web-search-card-no-results-every-source-answered = Keine Ergebnisse. Jede Quelle hat geantwortet, und keine hatte etwas zu dieser Suchanfrage.
web-search-card-the-lowest-ranked-results-were = Die am niedrigsten eingestuften Ergebnisse wurden verworfen, damit dieser Aufruf in den Unterhaltungsverlauf passt. Der Assistent hat alle gesehen.
web-search-card-view-search-details = Suchdetails anzeigen.
web-search-card-the-stored-result-could-not = das gespeicherte Ergebnis konnte nicht als JSON gelesen werden
web-search-card-nothing-was-stored-for-this = Für diesen Aufruf wurde nichts gespeichert.
web-search-card-forms = Wortformen: { $forms }
web-search-card-kind = Art: { $row_kind }
web-search-card-published = Veröffentlicht: { $row_published }
web-search-card-loading-search-detail-u = Suchdetail wird geladen…
web-search-card-could-not-load-the-search = Suchdetail konnte nicht geladen werden: { $e }
web-search-card-malformed-detail = Ungültiges Detail: { $e }
web-search-card-the-tool-returned-selected-results = Das Werkzeug hat ausgewählte Ergebnisse an das Modell zurückgegeben.
web-search-card-results-use-reciprocal-rank-fusion = Die Ergebnisse nutzen Reciprocal Rank Fusion.
web-search-card-returned-nothing = lieferte nichts: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle Kandidaten verwenden die Fusionsreihenfolge.
web-search-card-the-cross-encoder-ranks-selected = Der Cross-Encoder ordnet die ausgewählten Ergebnisse neu.
web-search-card-selected-results-use-fusion-order = Ausgewählte Ergebnisse verwenden die Fusionsreihenfolge.
web-search-card-search-detail = Suchdetail
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Dies durchsuchen
chat-tool-disclosure-search-every-collection = Alle Sammlungen durchsuchen
chat-tool-disclosure-hide = Ausblenden
chat-tool-disclosure-expand = Einblenden
chat-tool-disclosure-this-step-was-recorded-before = Dieser Schritt wurde aufgezeichnet, bevor die Argumente und Ergebnisse der Werkzeuge gespeichert wurden. Nur die folgende Zusammenfassung ist verfügbar.
chat-tool-disclosure-arguments = Argumente
chat-tool-disclosure-result = Ergebnis
chat-tool-disclosure-hide-raw-json = Roh-JSON ausblenden
chat-tool-disclosure-show-raw-json = Roh-JSON anzeigen
chat-tool-disclosure-input-json = Eingabe-JSON
chat-tool-disclosure-output-json = Ausgabe-JSON
chat-transcript-ask-a-question-about-the = Stellen Sie eine Frage zu den Dokumenten in Ihren Sammlungen.
chat-transcript-suggested-next = Als Nächstes vorgeschlagen…
chat-transcript-earlier-answer = Frühere Antwort
chat-transcript-tokens-the-conversation-carries-the = Token, die die Unterhaltung enthält, der größte einzelne Kontext, der in dieser Runde berechnet wurde, und wie viel vom Fenster des Modells er belegt hat
chat-transcript-instruction-to-the-agent = Anweisung an den Agenten
chat-transcript-the-context-stays-above-the = {" "}Der Kontext bleibt über dem Zielwert von { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}Bei { $failed } Teilen der Zusammenfassung ist ein Fehler aufgetreten. Die Aufzeichnung enthält nur die Listen.
chat-transcript-show-the-record = Aufzeichnung anzeigen
chat-transcript-hide-reasoning = Überlegungen ausblenden
chat-transcript-show-reasoning = Überlegungen anzeigen
chat-transcript-from-u-hide = { $count } { $noun } aus { $tool } – ausblenden
chat-transcript-from-u-show = { $count } { $noun } aus { $tool } – anzeigen
chat-transcript-u-hide = { $summary } – ausblenden
chat-transcript-u-show = { $summary } – anzeigen
chat-transcript-citations-of-this-conversation-give = Belege dieser Unterhaltung geben { $doc_handle } mehr als einem Dokument. Die Antwort verlinkt es mit keinem davon.
chat-transcript-report = Bericht { $label }
chat-transcript-open-in-the-workspace = Im Arbeitsbereich öffnen
chat-transcript-this-version-could-not-be = Diese Version konnte nicht gelesen werden. Der Chat-Text der Antwort folgt.
chat-transcript-files = Dateien
chat-transcript-version = { $file_name }, Version { $file_version }
chat-web-find-exact-text = Exakten Text suchen
chat-web-previous-match = Vorheriger Treffer
chat-web-next-match = Nächster Treffer
chat-web-close-preview = Vorschau schließen
chat-web-the-captured-page-could-not = Die erfasste Seite konnte nicht geladen werden.
chat-web-loading = Wird geladen…
chat-workspace-pane-workspace = Arbeitsbereich
chat-workspace-pane-close-the-workspace = Arbeitsbereich schließen
chat-workspace-pane-close = Schließen
chat-workspace-pane-loading-the-files-u = Dateien werden geladen…
chat-workspace-pane-the-files-could-not-be = Die Dateien konnten nicht geladen werden: { $error }
chat-workspace-pane-this-conversation-has-no-files = Diese Unterhaltung hat keine Dateien.
chat-workspace-pane-version = Version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Wählen Sie eine Datei aus, um sie zu lesen.
chat-workspace-pane-loading-the-file-u = Datei wird geladen…
chat-workspace-pane-the-file-could-not-be = Die Datei konnte nicht geladen werden: { $error }
chat-workspace-pane-version-2 = { $found_name }, Version { $found_version }
chat-board-create-collections = Sammlungen
chat-board-create-loading-collections-u = Sammlungen werden geladen…
chat-board-create-hoover-search-new-board = Hoover-Suche – Neues Board
chat-board-create-ai-chat = KI-Chat
chat-board-create-new-investigation-board = Neues Ermittlungsboard
chat-board-create-a-board-runs-its-goals = Ein Board arbeitet seine Ziele als Abfolge von Erkundungen des Agenten ab. Jede Erkundung ist ein Chat, der mit einer Erkenntnis des Boards endet. Sie prüfen die Antwort zu jedem Ziel und können Erkenntnisse ablehnen und Hinweise hinzufügen, während das Board läuft.
chat-board-create-title = Titel
chat-board-create-goal = Ziel
chat-board-create-remove-this-goal = Dieses Ziel entfernen
chat-board-create-remove = Entfernen
chat-board-create-add-a-goal = Ziel hinzufügen
chat-board-create-context-optional = Kontext (optional)
chat-board-create-hints-one-per-line-optional = Hinweise, einer pro Zeile (optional)
chat-board-create-sources = Quellen
chat-board-create-internet-tools = Internetwerkzeuge
chat-board-create-creating-board = Board wird erstellt…
chat-board-create-create-board = Board erstellen
ai-chat-board-hoover-search-board = Hoover-Suche – Board
ai-chat-board-loading-the-board-u = Board wird geladen…
ai-chat-board-show-the-board-overview = Board-Übersicht anzeigen
ai-chat-board-zoom-out = Verkleinern
ai-chat-board-zoom-in = Vergrößern
ai-chat-board-u-ai-chat = ← KI-Chat
ai-chat-board-settings = Einstellungen
ai-chat-board-board-settings = Board-Einstellungen
ai-chat-board-internet-tools = Internetwerkzeuge
ai-chat-board-the-next-explores-of-the = Die nächsten Erkundungen des Boards können das Web durchsuchen und Webseiten lesen. Laufende Erkundungen behalten die Einstellung, mit der sie gestartet wurden.
ai-chat-board-collections = Sammlungen
ai-chat-board-the-collections-are-fixed-when = Die Sammlungen sind festgelegt, wenn das Board erstellt wird.
ai-chat-board-confirm-drop = Verwerfen bestätigen
ai-chat-board-drop-the-board = Board verwerfen
ai-chat-board-close = Schließen
ai-chat-board-the-board-used-its-explore = Das Board hat sein Erkundungslimit erreicht
ai-chat-board-the-board-used-explores-the = Das Board hat { $explore_limit } Erkundungen verbraucht, das Limit eines Boards. Es startet keine weitere Arbeit. Sie können die vorgeschlagenen Antworten weiterhin entscheiden.
ai-chat-board-create-a-new-board-to = Erstellen Sie ein neues Board, um die Untersuchung fortzusetzen
ai-chat-board-goal = Ziel
ai-chat-board-goals = Ziele
ai-chat-board-add-new-goal = Neues Ziel hinzufügen…
ai-chat-board-a-new-goal = Ein neues Ziel
ai-chat-board-add-goal = Ziel hinzufügen
ai-chat-board-a-board-has-at-most = Ein Board hat höchstens { $max_goals } Ziele. Erstellen Sie ein neues Board für ein weiteres Ziel.
ai-chat-board-background-context = Hintergrundkontext
ai-chat-board-continue-with-a-correction = Mit einer Korrektur fortsetzen
ai-chat-board-correction-what-is-wrong-or = Korrektur: Was falsch ist oder fehlt. Das Board macht damit weiter.
ai-chat-board-the-board-waits-for-your = Das Board wartet auf Ihre Prüfung
ai-chat-board-the-board-used-its-budget = Das Board hat sein Budget von { $snap_max_explores } Erkundungen verwendet.
ai-chat-board-the-assessments-gave-no-usable = Die Bewertungen lieferten keine verwertbare Richtung.
ai-chat-board-accept-or-reject-the-proposed = Nehmen Sie die vorgeschlagene Antwort jedes Ziels oben an oder lehnen Sie sie ab. Eine abgelehnte Antwort lässt das Board sofort weiterarbeiten.
ai-chat-board-no-proposed-answer-waits-for = Keine vorgeschlagene Antwort wartet auf Ihre Entscheidung.
ai-chat-board-reopen-the-board-to-continue = Öffnen Sie das Board erneut, um die offenen Ziele fortzuführen. Es behält seine Erkenntnisse und Antworten.
ai-chat-board-close-the-board-to-accept = Schließen Sie das Board, um alle vorgeschlagenen Antworten anzunehmen und es zu beenden, oder setzen Sie es mit einer Korrektur fort.
ai-chat-board-close-the-board = Board schließen
ai-chat-board-or-reopen-the-board-to = Oder öffnen Sie das Board erneut, um die offenen Ziele ohne Korrektur fortzuführen.
ai-chat-board-the-board-is-complete = Das Board ist vollständig
ai-chat-board-a-goal-has-no-accepted = Ein Ziel hat keine angenommene Antwort. Öffnen Sie das Board erneut, um es fortzuführen. Das Board behält seine Erkenntnisse und Antworten.
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
ai-chat-board-findings = Erkenntnisse
ai-chat-board-created = Erstellt
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } hat diese Erkenntnis am { $format_utc_ms_fact_rejected_ms } abgelehnt. Das Board verwendet sie nicht mehr.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } hat diese Erkenntnis abgelehnt. Das Board verwendet sie nicht mehr.
ai-chat-board-no-reason-was-given = Es wurde kein Grund angegeben.
ai-chat-board-reason = Grund: { $fact_rejected_reason }
ai-chat-board-open-questions = Offene Fragen
ai-chat-board-explored-in = Erkundet in{" "}
ai-chat-board-explore-this-question = Diese Frage erkunden
ai-chat-board-your-questions = Ihre Fragen
ai-chat-board-ask-about-the-background-context = Zum Hintergrundkontext fragen
ai-chat-board-ask-about-this-finding = Zu dieser Erkenntnis fragen
ai-chat-board-a-follow-up-question-about = Eine Folgefrage zu diesem Knoten
ai-chat-board-ask = Fragen
ai-chat-board-checks-that-changed-this-finding = Prüfungen, die diese Erkenntnis geändert haben
ai-chat-board-reject-this-correction = Diese Korrektur ablehnen
ai-chat-board-reject-this-finding = Diese Erkenntnis ablehnen
ai-chat-board-not-answered-the-board-was = Nicht beantwortet. Das Board wurde ohne Antwort auf dieses Ziel beendet. Ein Hinweis oder ein erneutes Öffnen öffnet es wieder.
ai-chat-board-no-answer-yet = Noch keine Antwort.
ai-chat-board-the-findings-of-this-answer = Die Erkenntnisse dieser Antwort sind Suchen ohne Treffer. Nehmen Sie sie an, um festzuhalten, dass die Unterlagen das Ziel nicht beantworten, oder lehnen Sie sie ab, um die Untersuchung fortzusetzen.
ai-chat-board-open-an-assessment-to-read = {"."} Öffnen Sie eine Bewertung, um den Grund zu lesen.
ai-chat-board-from-the-findings = Aus den Erkenntnissen{" "}
ai-chat-board-accept-answer = Antwort annehmen
ai-chat-board-why-the-answer-is-wrong = Warum die Antwort falsch oder unvollständig ist
ai-chat-board-reject-answer = Antwort ablehnen
ai-chat-board-intent = Absicht
ai-chat-board-attempts-declared = Versuche: { $intent_attempts }. Angelegt { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Die Erkundung hat gefragt
ai-chat-board-add-a-hint-in-the = Fügen Sie in der Board-Übersicht einen Hinweis hinzu, um sie zu beantworten.
ai-chat-board-last-error = Letzter Fehler
ai-chat-board-brief = Briefing
ai-chat-board-open-the-explore-chat = Erkundungs-Chat öffnen
ai-chat-board-loading-the-assessment-u = Bewertung wird geladen…
ai-chat-board-assessment = Bewertung { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Ausgang { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Prüfungen, die sie geändert haben
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Diese Bewertung lief, bevor die Prompts gespeichert wurden.
ai-chat-board-response = Antwort
ai-chat-history-hoover-search-chat-history = Hoover-Suche – Chat-Verlauf
ai-chat-history-u-back = ← Zurück
ai-chat-history-conversation-history = Verlauf der Unterhaltungen
ai-chat-history-show-board-chats = Board-Chats anzeigen
ai-chat-history-loading-u = Wird geladen…
ai-chat-history-could-not-load-history = Verlauf konnte nicht geladen werden: { $e }
ai-chat-history-no-conversations-yet = Noch keine Unterhaltungen.
ai-chat-history-board = Board
ai-chat-history-new-chat = Neuer Chat
ai-chat-history-messages-updated = { $s_message_count } Nachrichten · aktualisiert { $s_updated_at }
ai-chat-history-delete-conversation = Unterhaltung löschen
ai-chat-history-delete = Löschen
ai-chat-homepage-hoover-search-ai-chat = Hoover-Suche – KI-Chat
ai-chat-homepage-what-are-you-researching = Woran recherchieren Sie?
ai-chat-homepage-view-all-conversations = Alle Unterhaltungen anzeigen
ai-chat-homepage-starting-conversation-u = Unterhaltung wird gestartet…
ai-chat-homepage-investigation-boards = Ermittlungsboards
ai-chat-homepage-new-board = Neues Board
ai-chat-homepage-loading-boards-u = Boards werden geladen…
ai-chat-homepage-could-not-load-the-boards = Die Boards konnten nicht geladen werden: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Sie haben kein Board. Ein Board führt eine lange Untersuchung als Abfolge von Erkundungen des Agenten aus, und Sie prüfen die Antworten.
ai-chat-homepage-updated = Aktualisiert { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover-Suche – KI-Chat
ai-chat-session-this-conversation-could-not-be = Diese Unterhaltung konnte nicht geladen werden.
ai-chat-session-loading-u = Wird geladen…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = Verlauf
ai-chat-session-show-the-files-that-the = Dateien anzeigen, die der Assistent in dieser Unterhaltung geschrieben hat
ai-chat-session-workspace = Arbeitsbereich
ai-chat-session-this-answer-was-interrupted-before = Diese Antwort wurde unterbrochen, bevor sie fertig war, weil die Seite oder der Server mitten in der Runde angehalten hat. Fragen Sie erneut, um es noch einmal zu versuchen.
ai-chat-session-dismiss = Schließen
ai-chat-session-board-explore-chats-are-read = Chats der Board-Erkundungen sind schreibgeschützt.{" "}
ai-chat-session-open-the-board = Board öffnen
chat-locked-options-on = { $label }: an
chat-locked-options-off = { $label }: aus
chat-tool-cards-running-u = läuft…
cards-result-cards-quote-found = Zitat gefunden
cards-result-cards-quote-not-found = Zitat nicht gefunden
cards-result-cards-quote-not-checked = Zitat nicht geprüft
web-search-card-results = { $results_len } Ergebnisse
chat-tool-disclosure-running-u = läuft…
chat-transcript-call = Aufruf
chat-transcript-calls = Aufrufe
ai-chat-board-a-board-without-collections-needs = Ein Board ohne Sammlungen braucht Internetwerkzeuge.
ai-chat-board-of = { $snap_explores_used } von { $snap_max_explores }
ai-chat-board-assessment-2 = Bewertung { $number }
ai-chat-history-messages = { $s_message_count } Nachrichten
web-search-card-reranked-in = Der Cross-Encoder hat die Ergebnisse in { $ms } ms neu geordnet.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = Score { $score } · vorher RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Die Runde wartet auf einen freien Modell-Slot.
chat-activity-the-turn-waits-for-a-2 = Die Runde wartet auf einen freien Werkzeug-Slot.
chat-locked-options-start-a-new-chat-to = Starten Sie einen neuen Chat, um diese Einstellung zu ändern.
chat-locked-options-internet-tools = Internetwerkzeuge
chat-session-card-new-chat = Neuer Chat
chat-tool-cards-first-frame-of-the-video = Erstes Bild des Videos
chat-tool-cards-screenshot-of = Screenshot von
chat-tool-cards-image = Bild
cards-result-cards-the-agent-asked-a-question = Der Agent hat eine Frage gestellt.
chat-transcript-hide = Ausblenden
chat-transcript-show = Einblenden
chat-transcript-unverified-quote-the-quoted-span = Nicht überprüftes Zitat. Der zitierte Abschnitt ist zu kurz für eine Prüfung.
chat-transcript-unverified-quote-the-document-text = Nicht überprüftes Zitat. Der Dokumenttext konnte nicht gelesen werden.
chat-transcript-unverified-quote-this-wording-was = Nicht überprüftes Zitat. Diese Formulierung wurde im Dokument nicht gefunden.
chat-board-create-select-a-collection-or-turn = Wählen Sie eine Sammlung aus oder schalten Sie die Internetwerkzeuge ein.
chat-board-create-select-at-least-one-collection = Wählen Sie mindestens eine Sammlung aus.
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
ai-chat-board-finding = Erkenntnis
ai-chat-board-why-the-correction-is-wrong = Warum die Korrektur falsch ist
ai-chat-board-reject-correction = Korrektur ablehnen
ai-chat-board-why-the-finding-is-wrong = Warum die Erkenntnis falsch ist
ai-chat-board-reject-finding = Erkenntnis ablehnen
ai-chat-board-answer = Antwort
ai-chat-board-proposed-answer = Vorgeschlagene Antwort
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pausiert
ai-chat-homepage-waits-for-review = Wartet auf Prüfung
ai-chat-homepage-completed = Abgeschlossen
ai-chat-homepage-dropped = Verworfen
ai-chat-homepage-unknown = Unbekannt
cards-result-cards-submitted-by-board =
    Vom Board übermittelt: { $kind ->
        [sourced] eine belegte
        [inferred] eine abgeleitete
        [not_found] eine nicht gefundene
       *[other] eine unbekannte
    } Erkenntnis aus dem Bericht
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Eine belegte
        [inferred] Eine abgeleitete
        [not_found] Eine nicht gefundene
       *[other] Eine unbekannte
    } Erkenntnis für das Board
chat-transcript-compacting = Kontext wird komprimiert: { $before } Token auf einen Zielwert von { $target }.
chat-transcript-compaction-failed = Die Zusammenfassung der früheren Schritte ist fehlgeschlagen. Das Modell hat die früheren Schritte unverändert erhalten, { $after } Token.
chat-transcript-compacted = Kontext komprimiert: { $steps } Schritte zusammengefasst, { $before } Token auf { $after }.
ai-chat-board-reopen-with-more = Mit { $grant } weiteren Erkundungen erneut öffnen
ai-chat-board-goal-number = Ziel { $number }
ai-chat-board-from-assessment-on = Von Bewertung { $number } am { $date }.
ai-chat-board-from-assessment = Von Bewertung { $number }.
chat-board-create-goal-2 = Ziel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = Verbindung zum Chat verloren: { $e }
ai-chat-session-could-not-stop-the-answer = Die Antwort konnte nicht gestoppt werden: { $e } – sie läuft noch
ai-chat-board-later-assessments-dropped-an-answer = { $n } spätere Bewertungen haben eine Antwort für dieses Ziel verworfen:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } Prompt-Token und { $a_completion_tokens } Completion-Token
ai-chat-homepage-completed-goals-not-answered = Abgeschlossen, { $n } Ziele nicht beantwortet
board-graph-intent = Absicht, { $state }
chat-workspace-pane-characters = { $chars } Zeichen
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } Werkzeug-{ $if_joined_live_end_1_tr_chat_transcript_ } in Ausführung
chat-transcript-running-tool-2 = { $turn_tool_rows_len } Werkzeug-{ $if_turn_tool_rows_len_1_tr_chat_transcri } in Ausführung
chat-transcript-answered-after-failed-attempt =
    Beantwortet nach { $retries_len } { $retries_len -> 
        [one] fehlgeschlagenem Versuch
       *[other] fehlgeschlagenen Versuchen
    }{ $if_retries_len_1_else_s -> 
       *[other] {""}
    }
chat-transcript-failed-attempt =
    { $retries_len } { $retries_len -> 
        [one] fehlgeschlagener Versuch
       *[other] fehlgeschlagene Versuche
    }{ $if_retries_len_1_else_s -> 
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, Version { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] nach { $n } Begriff gesucht
       *[other] nach { $n } Begriffen gesucht
    }
tool-run-summary-read =
    { $n ->
        [one] { $n } Dokument gelesen
       *[other] { $n } Dokumente gelesen
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] im Web nach { $n } Begriff gesucht
       *[other] im Web nach { $n } Begriffen gesucht
    }
tool-run-summary-read-web =
    { $n ->
        [one] { $n } Webseite gelesen
       *[other] { $n } Webseiten gelesen
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } Browseraktion
       *[other] { $n } Browseraktionen
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] Entitäten von { $n } Dokument aufgelistet
       *[other] Entitäten von { $n } Dokumenten aufgelistet
    }
tool-run-summary-cited =
    { $n ->
        [one] { $n } Dokument zitiert
       *[other] { $n } Dokumente zitiert
    }
tool-run-summary-cited-web =
    { $n ->
        [one] { $n } Webseite zitiert
       *[other] { $n } Webseiten zitiert
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] { $n } Skill und Werkzeugtexte gelesen
       *[other] { $n } Skills und Werkzeugtexte gelesen
    }
tool-run-summary-saved =
    { $n ->
        [one] { $n } Notiz gespeichert
       *[other] { $n } Notizen gespeichert
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } Aufruf der Aufgabenliste
       *[other] { $n } Aufrufe der Aufgabenliste
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } Anweisung an den Agenten
       *[other] { $n } Anweisungen an den Agenten
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } anderer Aufruf
       *[other] { $n } andere Aufrufe
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
chat-tool-disclosure-searched-collections = Sammlungen durchsucht{ $filters }
chat-tool-disclosure-searched-collections-2 = Sammlungen durchsucht · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } Dokumente zitiert
chat-tool-disclosure-read-document = Dokument gelesen · { $path }
chat-tool-disclosure-searched-the-web = Web durchsucht · { $q }
chat-tool-disclosure-opened-page = Seite geöffnet · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = { $other } aufgerufen
chat-tool-disclosure-called-2 = { $other } aufgerufen · { $short }
cards-browser-card-opened = { $url } geöffnet
cards-browser-card-could-not-open = { $url } konnte nicht geöffnet werden
cards-browser-card-clicked = auf { $element } geklickt
cards-browser-card-could-not-click = Klick auf { $element } fehlgeschlagen
cards-browser-card-typed-into = in { $element } eingegeben
cards-browser-card-could-not-type-into = Eingabe in { $element } fehlgeschlagen
cards-browser-card-typed = „{ $text }“ eingegeben
cards-browser-card-could-not-type = „{ $text }“ konnte nicht eingegeben werden
cards-browser-card-pressed = { $key } gedrückt
cards-browser-card-could-not-press = { $key } konnte nicht gedrückt werden
cards-browser-card-chose-an-option-in = Option in { $element } gewählt
cards-browser-card-could-not-choose-an-option = Option in { $element } konnte nicht gewählt werden
cards-browser-card-hovered = mit der Maus über { $element } gefahren
cards-browser-card-could-not-hover = Mauszeiger konnte nicht über { $element } bewegt werden
cards-browser-card-failed = { $bare } – fehlgeschlagen
cards-entities-card-listed-entities-document =
    Entitäten aufgelistet · { $count } { $count -> 
        [one] Dokument
       *[other] Dokumente
    }{ $if_count_1_else_s -> 
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · Teil { $part } von { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } Dokumente
cards-result-cards-forms = { $tool_name } · { $forms } Wortformen
cards-result-cards-in = {" "}in { $collections }
cards-result-cards-page = {" "}· Seite { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } Dokumente · { $missing } Zitate nicht gefunden
cards-result-cards-version-unchanged = { $tool_name } · Version { $version } · unverändert
cards-result-cards-version = { $tool_name } · Version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } Ergebnisse eingegangen, { $json_u64_doc_total_after_dedupe } nach Deduplizierung
