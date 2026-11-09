# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Zugriff auf die Administration erforderlich
admin-guard-signed-in-as = Angemeldet als { $u_username }.
admin-guard-ask-an-administrator-for-access = Bitten Sie einen Administrator um Zugriff auf diesen Bereich.
admin-shell-dashboard = Dashboard
admin-shell-collections = Sammlungen
admin-shell-operations = Vorgänge
admin-shell-errors-failures = Fehler/Fehlschläge
admin-shell-feedback = Feedback
admin-shell-users = Benutzer
admin-shell-groups = Gruppen
admin-shell-settings = Einstellungen
admin-shell-llm = LLM
admin-shell-ai-status = KI-Status
admin-shell-metrics = Metriken
admin-shell-administration = Administration
dataset-create-panel-add-a-dataset = Datensatz hinzufügen
dataset-create-panel-the-dataset-mounts-could-not = Die Datensatz-Mounts konnten nicht gelesen werden, es gibt also nichts zur Auswahl: { $err }
dataset-create-panel-loading-the-dataset-mounts = Datensatz-Mounts werden geladen.
dataset-create-panel-no-dataset-mount-is-configured = Es ist kein Datensatz-Mount konfiguriert.
dataset-create-panel-the-mount-folder-could-not = Der Mount-Ordner konnte nicht gelesen werden, es gibt also nichts zur Auswahl: { $err }
dataset-create-panel-no-subfolders-were-found-in = In diesem Mount wurden keine Unterordner gefunden.{" "}
dataset-create-panel-folder = Ordner
dataset-create-panel-select-a-folder = Ordner auswählen
dataset-create-panel-new-folder = Neuer Ordner
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } Einträge), bereits ein Datensatz
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } Einträge)
dataset-create-panel-the-server-creates-this-folder = Der Server erstellt diesen Ordner im Mount, wenn Sie den Datensatz erstellen.{" "}
dataset-create-panel-the-list-shows-the-direct = Die Liste zeigt die direkten Unterordner des Mounts.
dataset-create-panel-dataset-name = Name des Datensatzes
dataset-create-panel-a-name-has-lowercase-letters = Ein Name besteht aus Kleinbuchstaben, Ziffern und Unterstrichen. Großbuchstaben werden zu Kleinbuchstaben,{" "}
dataset-create-panel-the-dataset-is-saved-as = Der Datensatz wird gespeichert als: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Diese Sammlung hat einen Datensatz mit dem Namen { $saved_name }.
dataset-create-panel-accept-uploads = Uploads akzeptieren
dataset-create-panel-creating-u = Wird erstellt…
dataset-create-panel-create-and-ingest = Erstellen und einlesen
dataset-create-panel-mount = Mount
dataset-ocr-panel-last-operation = Letzter Vorgang: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , gestartet am { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Kein Fortschritt seit { $current_stale_seconds_60 } Minuten. Prüfen Sie den Temporal-Workflow und brechen Sie den Vorgang ab, wenn er hängt.
dataset-ocr-panel-loading-u = Wird geladen…
dataset-ocr-panel-stored-text-variants = Gespeicherte Textvarianten
dataset-ocr-panel-searchable-pdfs = Durchsuchbare PDFs
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } Dateien · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = Laufende LLM-Chats
live-chats-panel-agent-turns-running-right-now = Runden des Agenten, die gerade laufen, die am längsten laufende zuerst. Aktualisierung alle 2 s. Aus Temporal gelesen, daher erscheint hier auch eine Runde, die vor dem letzten Neustart der Website begonnen hat.
live-chats-panel-loading-u = Wird geladen…
live-chats-panel-no-chats-running = Keine laufenden Chats.
live-chats-panel-user = Benutzer
live-chats-panel-conversation = Unterhaltung
live-chats-panel-question = Frage
live-chats-panel-internet = Internet
live-chats-panel-running = Läuft
live-chats-panel-started = Gestartet
live-chats-panel-cancels-the-workflow-the-turn = Bricht den Workflow ab. Die Runde endet mit einer Markierung „gestoppt“ im Verlauf, statt zu verschwinden.
live-chats-panel-kill = Beenden
processing-updates-panel-loading-u = Wird geladen…
processing-updates-panel-open-the-operation = Vorgang öffnen
processing-updates-panel-the-pipeline-has-not-calculated = Die Pipeline hat diese Updates noch nicht berechnet.
processing-updates-panel-calculated-at-in-ms = Berechnet um { $view_checked_at } in { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatische Updates sind in dieser Installation ausgeschaltet. Starten Sie die Updates mit der Schaltfläche.
processing-updates-panel-step = Schritt
processing-updates-panel-count = Anzahl
processing-updates-panel-state = Status
processing-updates-panel-last-run = Letzter Lauf
processing-updates-panel-runs = Läufe: { $step_runs }
processing-updates-panel-a-run-again-would-select = Ein erneuter Lauf würde etwa so viele { $step_unit } auswählen.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } bei einem erneuten Lauf
processing-updates-panel-never = Nie
processing-updates-panel-update-collection = Sammlung aktualisieren
processing-updates-panel-update-processing = Verarbeitung aktualisieren
processing-updates-panel-check-again = Erneut prüfen
processing-updates-panel-dataset = Datensatz
processing-updates-panel-processing-updates = Verarbeitungsupdates
admin-ai-status-admin-ai-status = Administration: KI-Status
admin-ai-status-ai-status = KI-Status
admin-ai-status-the-configured-service-and-the = Der konfigurierte Dienst und der Dienst, der tatsächlich antwortet. Ein Fallback auf den CPU-Dienst erscheint nur hier.
admin-ai-status-loading-u = Wird geladen…
admin-ai-status-config-fingerprint = Fingerabdruck der Konfiguration
admin-ai-status-website-worker = Website / Worker
admin-ai-status-ai-server = KI-Server
admin-ai-status-match = Übereinstimmung
admin-ai-status-embeddings-probe = Embedding-Probe
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } Dimensionen
admin-ai-status-llm-configured = LLM konfiguriert
admin-ai-status-capabilities = Funktionen
admin-ai-status-capability = Funktion
admin-ai-status-configured = Konfiguriert
admin-ai-status-serving = Im Einsatz
admin-ai-status-model = Modell
admin-ai-status-reachable = Erreichbar
admin-ai-status-detail = Detail
admin-ai-status-no = NEIN
admin-ai-status-vector-shard-dims-vs-probe = Dimensionen der Vektor-Shards im Vergleich zur Probe
admin-ai-status-no-collections-yet = Noch keine Sammlungen.
admin-ai-status-collection = Sammlung
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Deckt sich mit der Probe
admin-ai-status-browser-router = Browser-Router
admin-ai-status-live-sessions = Aktive Sitzungen: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Aktuelle LLM-Aktivität (24 h)
admin-ai-status-no-llm-call-events-yet = Noch keine llm_call_events.
admin-ai-status-user = Benutzer
admin-ai-status-calls = Aufrufe
admin-ai-status-errors = Fehler
admin-ai-status-service-use-24-h = Dienstauslastung % (24 h)
admin-ai-status-busy-seconds-in-the-last = Ausgelastete Sekunden in den letzten 24 Stunden, als Anteil am Tag.
admin-ai-status-no-samples-yet = Noch keine Stichproben.
admin-ai-status-service = Dienst
admin-ai-status-busy-s = Ausgelastet s
admin-ai-status-use = Auslastung %
admin-collection-detail-admin-collection = Administration: Sammlung { $collection_id }
admin-collection-detail-failed-to-load-collection = Sammlung konnte nicht geladen werden
admin-collection-detail-loading = Wird geladen...
admin-collection-detail-datasets = Datensätze
admin-collection-detail-dataset = Datensatz
admin-collection-detail-documents = Dokumente
admin-collection-detail-size = Größe
admin-collection-detail-indexed = Indiziert
admin-collection-detail-errors = Fehler
admin-collection-detail-state = Status
admin-collection-detail-created = Erstellt
admin-collection-detail-settings = Einstellungen
admin-collection-detail-the-collection-database-is-not = Die Sammlungsdatenbank ist noch nicht bereit.
admin-collection-detail-the-last-storage-provisioning-failed = Die letzte Speicherbereitstellung ist fehlgeschlagen: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Verarbeitungsfortschritt und Schätzungen
admin-collection-detail-display-name = Anzeigename
admin-collection-detail-display-name-2 = Anzeigename
admin-collection-detail-save = Speichern
admin-collection-detail-access = Zugriff
admin-collection-detail-public-every-signed-in-user = Öffentlich. Jeder angemeldete Benutzer kann diese Sammlung durchsuchen und lesen.
admin-collection-detail-restricted-only-members-of-the = Eingeschränkt. Nur Mitglieder der folgenden Gruppen können diese Sammlung durchsuchen und lesen.
admin-collection-detail-the-collection-is-now-public = Die Sammlung ist jetzt öffentlich.
admin-collection-detail-the-collection-is-now-restricted = Die Sammlung ist jetzt eingeschränkt.
admin-collection-detail-make-restricted = Eingeschränkt machen
admin-collection-detail-make-public = Öffentlich machen
admin-collection-detail-group-permissions = Gruppenberechtigungen
admin-collection-detail-no-group-can-read-this = Es kann noch keine Gruppe diese Sammlung lesen.
admin-collection-detail-revoke = Entziehen
admin-collection-detail-grant-group-u = Gruppe zuweisen…
admin-collection-detail-grant = Zuweisen
admin-collection-detail-danger-zone = Gefahrenzone
admin-collection-detail-a-collection-can-only-be = Eine Sammlung kann nur gelöscht werden, wenn sie keine Datensätze enthält.
admin-collection-detail-deleting-the-collection-also-drops = Beim Löschen der Sammlung wird auch ihre Datenbank{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}samt allem Inhalt gelöscht. Das kann nicht rückgängig gemacht werden. Geben Sie zur Bestätigung den Namen der Sammlung ein.
admin-collection-detail-collection-name = Sammlungsname
admin-collection-detail-delete-collection = Sammlung löschen
admin-collection-detail-features = Funktionen
admin-collection-detail-vectors = Vektoren
admin-collection-detail-this-installation-runs-no-embedding = Diese Installation führt keinen Embedding-Service aus, daher verwendet keine Sammlung Vektoren.
admin-collection-detail-vectors-find-passages-by-meaning = Vektoren finden Textstellen nach ihrer Bedeutung. „Aus“ stoppt neue Vektoren und die Nutzung der gespeicherten Vektoren in der Suche. Die gespeicherten Vektoren bleiben erhalten. „An“ berechnet die fehlenden Vektoren jedes Datensatzes, einen Datensatz nach dem anderen.
admin-collection-detail-this-collection-follows-the-installation = Diese Sammlung folgt der Installation, die Vektoren verwendet. Vektoren finden Textstellen nach ihrer Bedeutung. „Aus“ stoppt neue Vektoren und die Nutzung der gespeicherten Vektoren in der Suche. Die gespeicherten Vektoren bleiben erhalten.
admin-collection-processing-could-not-load-this-panel = Dieser Bereich konnte nicht geladen werden: { $message }
admin-collection-processing-admin-processing-of = Administration: Verarbeitung von { $collection_id }
admin-collection-processing-u-back-to-collection = ← Zurück zur Sammlung
admin-collection-processing-processing-stages = Verarbeitungsstufen
admin-collection-processing-loading-u = Wird geladen…
admin-collection-processing-the-collection-database-is-still = Die Sammlungsdatenbank wird noch bereitgestellt.
admin-collection-processing-this-collection-has-no-datasets = Diese Sammlung hat noch keine Datensätze.
admin-collection-processing-eta = Voraussichtlicher Abschluss { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Noch keine Schätzwerte. Sie werden gesammelt, während der Datensatz verarbeitet wird.
admin-collection-processing-estimated-completion = Voraussichtlicher Abschluss:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(in { $humanize_seconds_c_eta_seconds }, eine bestmögliche Schätzung, keine Terminzusage)
admin-collection-processing-no-current-estimate-the-pipeline = Keine aktuelle Schätzung. Die Pipeline ist fertig oder macht keinen messbaren Fortschritt.
admin-collection-processing-where-processing-time-goes = Wohin die Verarbeitungszeit geht
admin-collection-processing-no-task-executions-recorded-yet = Noch keine Aufgabenausführungen erfasst. Jede Aktivität der Pipeline schreibt hier eine Zeile, daher bedeutet eine leere Tabelle, dass seit der Bereitstellung der Instrumentierung nichts verarbeitet wurde.
admin-collection-processing-summed-task-time = Summierte Aufgabenzeit
admin-collection-processing-wall-clock = Verstrichene Zeit
admin-collection-processing-achieved-parallelism = Erreichte Parallelität
admin-collection-processing-summed-task-time-divided-by = Die summierte Aufgabenzeit geteilt durch die verstrichene Zeit ist die Parallelität, die die Pipeline tatsächlich erreicht hat. Nahe 1 heißt: Die oberste Aufgabe unten verursacht die gesamten Kosten, und eine Optimierung lohnt sich. Nahe der Anzahl der Worker-Slots heißt: Die Slots sind ausgelastet, und mehr Worker sind die günstigere Lösung. Die verstrichene Zeit reicht von der ersten bis zur letzten Ausführung, Leerlauf eingeschlossen.
admin-collection-processing-task = Aufgabe
admin-collection-processing-total = Gesamt
admin-collection-processing-share = Anteil
admin-collection-processing-executions = Ausführungen
admin-collection-processing-mean = Mittelwert
admin-collection-processing-max = Max
admin-collection-processing-failed = Fehlgeschlagen
admin-collection-processing-live-activity = Live-Aktivität
admin-collection-processing-nothing-running-no-activity-finished = Es läuft nichts. In den letzten { $live_window_seconds } s wurde keine Aktivität abgeschlossen, und kein Worker meldet etwas in Bearbeitung.
admin-collection-processing-in-flight = In Bearbeitung
admin-collection-processing-average-concurrency = Durchschnittliche Parallelität
admin-collection-processing-task-time-in-window = Aufgabenzeit im Fenster
admin-collection-processing-share-of-processing-time-over = Anteil der Verarbeitungszeit in den letzten { $live_window_seconds } s, alle 5 s aktualisiert. Eine Ausführung, die über den Rand des Fensters reicht, zählt nur mit dem Teil im Fenster. Eine Zeile mit laufenden Ausführungen, aber ohne Anteil, hat vor dem Fenster begonnen und ist noch nicht beendet. Prüfen Sie ihr Alter.
admin-collection-processing-share-of-window = Anteil am Fenster
admin-collection-processing-task-time = Aufgabenzeit
admin-collection-processing-completed = Abgeschlossen
admin-collection-processing-oldest-running = Am längsten laufend
admin-collection-processing-temporal-workflows = Temporal-Workflows
admin-collection-processing-workflows-of-this-collection-s = Workflows der Datensätze dieser Sammlung, einschließlich untergeordneter Workflows.
admin-collection-processing-no-workflows-match-this-filter = Keine Workflows entsprechen diesem Filter.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Typ
admin-collection-processing-status = Status
admin-collection-processing-started = Gestartet
admin-collection-processing-closed = Beendet
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = offen ↗
admin-collection-processing-failed-tasks = Fehlgeschlagene Aufgaben
admin-collection-processing-no-task-failures-recorded = Keine fehlgeschlagenen Aufgaben erfasst.
admin-collection-processing-dataset = Datensatz
admin-collection-processing-errors = Fehler
admin-collection-processing-documents = Dokumente
admin-collection-processing-last-seen = Zuletzt gesehen
admin-collection-processing-sample = Stichprobe
admin-collection-processing-retry = Wiederholen
admin-collection-processing-failures-per-document = Fehlschläge pro Dokument
admin-collection-processing-no-document-failures-recorded = Keine fehlgeschlagenen Dokumente erfasst.
admin-collection-processing-document = Dokument
admin-collections-list-admin-collections = Administration: Sammlungen
admin-collections-list-collections = Sammlungen
admin-collections-list-loading-collections-u = Sammlungen werden geladen…
admin-collections-list-datasets = Datensätze
admin-collections-list-loading-datasets-u = Datensätze werden geladen…
admin-collections-list-add-a-collection = Sammlung hinzufügen
admin-collections-list-name-for-example-enron = Name, zum Beispiel enron
admin-collections-list-display-name = Anzeigename
admin-collections-list-add-collection = Sammlung hinzufügen
admin-collections-list-a-name-has-lowercase-letters = Ein Name besteht aus Kleinbuchstaben, Ziffern und Unterstrichen. Großbuchstaben werden zu Kleinbuchstaben,{" "}
admin-collections-list-the-collection-is-saved-as = Die Sammlung wird gespeichert als: { $new_name }
admin-collections-list-a-collection-with-the-name = Eine Sammlung mit dem Namen { $new_name } existiert bereits.
admin-collections-list-collection = Sammlung
admin-collections-list-documents = Dokumente
admin-collections-list-size = Größe
admin-collections-list-errors = Fehler
admin-collections-list-state = Status
admin-collections-list-access = Zugriff
admin-collections-list-database-not-ready = Datenbank nicht bereit
admin-collections-list-public = Öffentlich
admin-collections-list-1-group = 1 Gruppe
admin-collections-list-not-counted-yet = Noch nicht gezählt
admin-collections-list-unknown = Unbekannt
admin-collections-list-no-collection-has-a-dataset = Keine Sammlung hat einen Datensatz.
admin-collections-list-dataset = Datensatz
admin-collections-list-indexed = Indiziert
admin-collections-list-created = Erstellt
admin-dashboard-admin-dashboard = Administration: Dashboard
admin-dashboard-administration = Administration
admin-dashboard-users = Benutzer
admin-dashboard-groups = Gruppen
admin-dashboard-collections = Sammlungen
admin-dashboard-datasets = Datensätze
admin-dashboard-failed-to-load-counts = Zähler konnten nicht geladen werden: { $e }
admin-dataset-detail-admin-dataset = Administration: Datensatz { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Datensatz konnte nicht geladen werden
admin-dataset-detail-loading = Wird geladen...
admin-dataset-detail-metadata = Metadaten
admin-dataset-detail-display-name = Anzeigename
admin-dataset-detail-name = Name
admin-dataset-detail-type = Typ
admin-dataset-detail-path = Pfad
admin-dataset-detail-created = Erstellt
admin-dataset-detail-collection = Sammlung
admin-dataset-detail-save = Speichern
admin-dataset-detail-statistics = Statistiken
admin-dataset-detail-state = Status
admin-dataset-detail-documents = Dokumente
admin-dataset-detail-size = Größe
admin-dataset-detail-indexed = Indiziert
admin-dataset-detail-errors = Fehler
admin-dataset-detail-plans-finished = Pläne abgeschlossen
admin-dataset-detail-disk = Festplatte
admin-dataset-detail-rescan-disk-reads-the-dataset = „Festplatte neu scannen“ liest den Datensatzordner erneut, fügt neue und geänderte Dateien hinzu und verarbeitet sie.
admin-dataset-detail-rescan-disk = Festplatte neu scannen
admin-dataset-detail-danger-zone = Gefahrenzone
admin-dataset-detail-this-deletes-the-dataset-and = Dadurch werden der Datensatz und alle daraus extrahierten Daten gelöscht. Das kann nicht rückgängig gemacht werden.
admin-dataset-detail-delete-dataset-and-its-data = Datensatz und dessen Daten löschen
admin-dataset-detail-accept-uploads = Uploads annehmen
admin-dataset-detail-the-folder-of-this-dataset = Der Ordner dieses Datensatzes befindet sich nicht in einem beschreibbaren Datensatz-Mount, daher werden keine Uploads angenommen.
admin-dataset-detail-starting-u = Wird gestartet…
admin-failure-detail-admin-failure = Administration: Fehlschlag { $op_id }
admin-failure-detail-loading-tree = Baum wird geladen…
admin-failure-detail-back-to-errors-and-failures = Zurück zu Fehlern und Fehlschlägen
admin-failure-detail-operations = Vorgänge
admin-failure-detail-scrubbed-copy-written-to-the = Bereinigte Kopie in die Zwischenablage geschrieben.
admin-failure-detail-this-tree-is-truncated-at = Dieser Baum ist abgeschnitten. Mindestens eine Aufnahme hat Knoten verworfen.
admin-failure-detail-the-captured-tree-has-expired = Der erfasste Baum ist abgelaufen. Die Zeile des Vorgangs ist noch vorhanden.
admin-failure-detail-no-captured-nodes-for-this = Für diesen Vorgang gibt es keine erfassten Knoten.
admin-failure-detail-operation = Vorgang
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } Wurzel(n) · { $tree_nodes_len } Knoten
admin-failure-detail-open-in-temporal = In Temporal öffnen
admin-failure-detail-scrubbed-copy = Bereinigte Kopie
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Die bereinigte Kopie ersetzt Datensatzpfade durch Hashes und lange Werte durch deren Länge.
admin-failure-detail-copy-scrubbed-record = Bereinigten Eintrag kopieren
admin-failure-detail-tree = Baum
admin-failure-detail-root = Wurzel ·{" "}
admin-failure-detail-node-parent-depth-source-stage = Knoten { $node_node_index } · übergeordnet { $node_parent_index } · Tiefe { $node_depth } · Quelle { $node_source } · Stufe { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = Workflow { $node_workflow_id } · Lauf { $node_run_id } · Aktivität { $node_activity_id } · Versuch { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } Knoten bei dieser Aufnahme verworfen
admin-failures-admin-errors-and-failures = Administration: Fehler und Fehlschläge
admin-failures-errors-failures = Fehler/Fehlschläge
admin-failures-loading-failures = Fehlschläge werden geladen…
admin-failures-operational-failures = Betriebliche Fehlschläge
admin-failures-no-operational-failures-at-this = Zur Zeit keine betrieblichen Fehlschläge.
admin-failures-collection = Sammlung
admin-failures-dataset = Datensatz
admin-failures-task-name = Aufgabenname
admin-failures-error-class = Fehlerklasse
admin-failures-operation-kind = Vorgangsart
admin-failures-from = Von
admin-failures-to = Bis
admin-failures-no-captured-failures-match-these = Keine erfassten Fehlschläge passen zu diesen Filtern.
admin-failures-signature = Signatur
admin-failures-count = Anzahl
admin-failures-class = Klasse
admin-failures-task = Aufgabe
admin-failures-last-seen = Zuletzt gesehen
admin-failures-newer = Neuer
admin-failures-page = Seite { $current_page_1 }
admin-failures-older = Älter
admin-failures-per-page = Pro Seite
admin-failures-loading-instances = Instanzen werden geladen…
admin-failures-no-instances-for-this-signature = Keine Instanzen für diese Signatur.
admin-failures-node = {" "}Knoten { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Dokumentfehler
admin-failures-error-text = Fehlertext
admin-failures-loading-document-errors-u = Dokumentfehler werden geladen…
admin-failures-no-document-errors-match-these = Keine Dokumentfehler passen zu diesen Filtern.
admin-failures-errors-by-dataset-and-task = Fehler nach Datensatz und Aufgabe
admin-failures-documents = Dokumente
admin-failures-show-only-this-dataset-and = Nur diesen Datensatz und diese Aufgabe anzeigen
admin-failures-total = Gesamt
admin-failures-errors = Fehler
admin-failures-document = Dokument
admin-failures-runs = Ausführungen
admin-failures-error = Fehler
admin-failures-dataset-step = Datensatzschritt
admin-failures-previous-page = Vorherige Seite
admin-failures-page-of-1-error = Seite { $page } von { $pages }, 1 Fehler
admin-failures-page-of-errors = Seite { $page } von { $pages }, { $data_total } Fehler
admin-failures-next-page = Nächste Seite
admin-feedback-admin-feedback = Administration: Feedback
admin-feedback-feedback = Feedback
admin-feedback-search-titles-descriptions-accounts-and = Nach Titeln, Beschreibungen, Konten und Adressen suchen
admin-feedback-search = Suchen
admin-feedback-loading-reports-u = Berichte werden geladen…
admin-feedback-1-report-matches = 1 Bericht gefunden.
admin-feedback-reports-match = { $data_total } Berichte gefunden.
admin-feedback-received = Eingegangen
admin-feedback-type = Typ
admin-feedback-title = Titel
admin-feedback-from = Von
admin-feedback-captures = Erfassungen
admin-feedback-state = Status
admin-feedback-previous-page = Vorherige Seite
admin-feedback-page-of = Seite { $page } von { $pages }
admin-feedback-next-page = Nächste Seite
admin-feedback-image = Bild { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Gelesen
admin-feedback-unread = Ungelesen
admin-feedback-archived = Archiviert
admin-feedback-mark-unread = Als ungelesen markieren
admin-feedback-mark-read = Als gelesen markieren
admin-feedback-restore = Wiederherstellen
admin-feedback-archive = Archivieren
admin-feedback-page = Seite:{" "}
admin-feedback-the-report-has-no-description = Der Bericht hat keine Beschreibung.
admin-feedback-open-the-page-image = Seitenbild öffnen
admin-feedback-open-the-dom-copy = DOM-Kopie öffnen
admin-feedback-page-image-of-the-report = Seitenbild des Berichts
admin-feedback-debug-context-and-browser-log = Debug-Kontext und Browser-Protokoll
admin-feedback-loading-u = Wird geladen…
admin-group-detail-admin-group = Administration: Gruppe { $groupname }
admin-group-detail-failed-to-load-group = Gruppe konnte nicht geladen werden
admin-group-detail-loading = Wird geladen…
admin-group-detail-group = Gruppe
admin-group-detail-display-name = Anzeigename
admin-group-detail-display-name-2 = Anzeigename
admin-group-detail-save = Speichern
admin-group-detail-members = Mitglieder
admin-group-detail-saving-membership = Mitgliedschaft wird gespeichert…
admin-group-detail-username = Benutzername
admin-group-detail-origin = Herkunft
admin-group-detail-group-admin = Gruppenadministrator
admin-group-detail-uploader = Uploader
admin-group-detail-remove = Entfernen
admin-group-detail-username-to-add = Benutzername zum Hinzufügen
admin-group-detail-add-member = Mitglied hinzufügen
admin-group-detail-collection-access = Sammlungszugriff
admin-group-detail-this-group-has-no-collection = Diese Gruppe hat keine Berechtigungen für Sammlungen.
admin-group-detail-revoke = Entziehen
admin-group-detail-grant-collection-u = Sammlung zuweisen…
admin-group-detail-grant = Zuweisen
admin-group-detail-danger-zone = Gefahrenzone
admin-group-detail-delete-group = Gruppe löschen
admin-groups-list-admin-groups = Administration: Gruppen
admin-groups-list-groups = Gruppen
admin-groups-list-add-group = Gruppe hinzufügen
admin-groups-list-display-name = Anzeigename
admin-groups-list-use-lowercase-letters-digits-underscores = Verwenden Sie im Namen nur kleine Buchstaben, Ziffern, Unterstriche und Bindestriche. Der Name kann später nicht mehr geändert werden.
admin-groups-list-add-group-2 = Gruppe hinzufügen +
admin-groups-list-group = Gruppe
admin-groups-list-display-name-2 = Anzeigename
admin-groups-list-members = Mitglieder
admin-groups-list-collections = Sammlungen
admin-groups-list-loading = Wird geladen…
admin-llm-config-admin-llm = Administration: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Wird geladen…
admin-llm-config-no-llm-provider-is-configured = Es ist kein LLM-Anbieter konfiguriert. Legen Sie LLM_BASE_URL / LLM_MODEL in hoover4.ini fest und stellen Sie erneut bereit.
admin-llm-config-providers = Anbieter
admin-llm-config-the-refresh-runs-in-the = Die Aktualisierung läuft im Hintergrund. Die aktuelle Liste bleibt dabei sichtbar.
admin-llm-config-refresh-in-flight-u = {" "}Aktualisierung läuft…
admin-llm-config-provider = Anbieter
admin-llm-config-models = Modelle
admin-llm-config-freshest = Aktuellste
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Katalog aktualisieren
admin-llm-config-agent-turns-board-assessments-and = Runden des Agenten, Board-Bewertungen und Berichtskonvertierungen
admin-llm-config-titles-summaries-and-board-labels = Titel, Zusammenfassungen und Board-Bezeichnungen
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini legt diese Modelle fest: quality_model des LLM-Anbieters für Runden des Agenten, Board-Bewertungen und Berichtskonvertierungen, wenn es gesetzt ist, und das Modell des Anbieters für alles andere.
admin-llm-config-thinking = Denken
admin-llm-config-the-model-reasons-before-each = Das Modell überlegt vor jedem Werkzeugaufruf und jeder Antwort.
admin-llm-config-catalog = Katalog
admin-llm-config-filter-models-u = Modelle filtern…
admin-llm-config-model = Modell
admin-llm-config-flags = Merkmale
admin-llm-config-calls-14d = Aufrufe 14 T
admin-llm-config-ai-status = KI-Status
admin-llm-config-shows-the-serving-health = {" "}zeigt den Betriebszustand an.
admin-llm-reports-reports = Berichte
admin-llm-reports-each-report-runs-when-you = Jeder Bericht wird ausgeführt, wenn Sie seine Schaltfläche auswählen.
admin-llm-reports-running-u = Wird ausgeführt…
admin-llm-reports-run-report = Bericht ausführen
admin-llm-reports-read-at = Gelesen am { $read_at }
admin-llm-reports-errors = Fehler
admin-llm-reports-failed-attempts-by-step-and = Fehlgeschlagene Versuche nach Schritt und Fehlerklasse sowie Läufe des Agenten, die fehlgeschlagen sind oder vorzeitig endeten, nach ihrem Endgrund.
admin-llm-reports-source = Quelle
admin-llm-reports-class = Klasse
admin-llm-reports-no-errors-in-30-days = Keine Fehler in 30 Tagen.
admin-llm-reports-recent-errors = Aktuelle Fehler
admin-llm-reports-the-newest-100-failed-attempts = Die neuesten 100 fehlgeschlagenen Versuche der letzten 7 Tage. Öffnen Sie eine Zeile, um den Fehler zu lesen.
admin-llm-reports-time = Zeit
admin-llm-reports-user = Benutzer
admin-llm-reports-name = Name
admin-llm-reports-error = Fehler
admin-llm-reports-no-errors-in-7-days = In 7 Tagen keine Fehler.
admin-llm-reports-show = Anzeigen
admin-llm-reports-tool-calls = Werkzeugaufrufe
admin-llm-reports-one-row-for-each-tool = Eine Zeile je Werkzeug, nach Aufrufen in 30 Tagen. Ein Fehler ist ein fehlgeschlagener Aufruf.
admin-llm-reports-tool = Werkzeug
admin-llm-reports-calls-24-h = Aufrufe 24 h
admin-llm-reports-error-24-h = Fehler % 24 h
admin-llm-reports-avg-ms-24-h = Ø ms 24 h
admin-llm-reports-calls-7-d = Aufrufe 7 d
admin-llm-reports-error-7-d = Fehler % 7 d
admin-llm-reports-avg-ms-7-d = Ø ms 7 d
admin-llm-reports-calls-30-d = Aufrufe 30 d
admin-llm-reports-error-30-d = Fehler % 30 d
admin-llm-reports-avg-ms-30-d = Ø ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Keine Werkzeugaufrufe in 30 Tagen.
admin-llm-reports-top-users = Meistnutzende Benutzer
admin-llm-reports-the-30-users-with-the = Die 30 Benutzer mit der meisten Modellzeit im Zeitraum.
admin-llm-reports-30-days = 30 Tage
admin-llm-reports-7-days = 7 Tage
admin-llm-reports-24-hours = 24 Stunden
admin-llm-reports-tool-time = Werkzeugzeit
admin-llm-reports-model-calls = Modellaufrufe
admin-llm-reports-model-time = Modellzeit
admin-llm-reports-tokens-in = Token ein
admin-llm-reports-tokens-out = Token aus
admin-llm-reports-no-agent-use-in-the = Keine Nutzung des Agenten im Zeitraum.
admin-llm-reports-system-one-checks = System-One-Prüfungen
admin-llm-reports-requests-are-grouped-by-hook = Anfragen werden nach Hook und Regel gruppiert. Latenzen sind in Millisekunden angegeben. Anteile beziehen sich auf Anfragen aus den letzten 30 Tagen.
admin-llm-reports-counts = Anzahl
admin-llm-reports-recent-failures = Aktuelle Fehlschläge
admin-llm-reports-select-run-report-to-read = Wählen Sie „Bericht ausführen“, um die Statistiken zu lesen.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Regel
admin-llm-reports-outcome = Ausgang
admin-llm-reports-questions = Fragen
admin-llm-reports-median-ms = Median ms
admin-llm-reports-95th-percentile-ms = 95. Perzentil ms
admin-llm-reports-error-2 = Fehler %
admin-llm-reports-positive = Positiv %
admin-llm-reports-actions = Aktionen
admin-metrics-admin-metrics = Administration: Metriken
admin-metrics-metrics = Metriken
admin-metrics-the-last-24-hours = Die letzten 24 Stunden.
admin-metrics-loading-u = Wird geladen…
admin-metrics-manticore-load-now = Manticore-Last (jetzt)
admin-metrics-ram-is-the-memory-of = RAM ist der Speicher der Tabellen. Die Thread-Last gilt für die letzten 1, 5 und 15 Minuten.
admin-metrics-manticore-status-could-not-be = Manticore-Status konnte nicht gelesen werden: { $error }
admin-metrics-thread-load-1-5-15 = Thread-Last (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Primäre Thread-Last (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Sekundäre Thread-Last (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Ausgelastete Worker-Threads / gesamt
admin-metrics-work-queue = Arbeitswarteschlange
admin-metrics-ram-held-by-tables = Von Tabellen belegter RAM
admin-metrics-disk-used-by-tables = Von Tabellen belegter Festplattenplatz
admin-metrics-tables-merging = Tabellen werden zusammengeführt
admin-metrics-tables-read = Tabellen gelesen
admin-metrics-read-at = Gelesen am
admin-metrics-largest-tables-by-ram = Größte Tabellen nach RAM
admin-metrics-table = Tabelle
admin-metrics-ram = RAM
admin-metrics-disk = Festplatte
admin-metrics-disk-chunks = Festplatten-Chunks
admin-metrics-merging = Zusammenführung
admin-metrics-usage-last-24-h = Nutzung (letzte 24 h)
admin-metrics-events-by-type = Ereignisse nach Typ
admin-metrics-event = Ereignis
admin-metrics-count = Anzahl
admin-metrics-events-per-hour = Ereignisse pro Stunde
admin-metrics-no-events-recorded-yet = Es wurden noch keine Ereignisse erfasst.
admin-metrics-busiest-users = Aktivste Benutzer
admin-metrics-user = Benutzer
admin-metrics-events = Ereignisse
admin-metrics-events-2 = { $point_bucket }: { $point_count } Ereignisse
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API-Aufrufe (letzte 24 h)
admin-metrics-no-api-calls-recorded-yet = Es wurden noch keine API-Aufrufe erfasst.
admin-metrics-function = Funktion
admin-metrics-calls = Aufrufe
admin-metrics-errors = Fehler
admin-metrics-error-rate = Fehlerquote
admin-metrics-bytes-in = Bytes ein
admin-metrics-bytes-out = Bytes aus
admin-operation-detail-admin-operation = Administration: Vorgang { $op_id }
admin-operation-detail-loading-operation = Vorgang wird geladen…
admin-operation-detail-back-to-operations = Zurück zu den Vorgängen
admin-operation-detail-operation = Vorgang
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · in der Warteschlange seit { $row_started_at }
admin-operation-detail-not-started = nicht gestartet
admin-operation-detail-re-run-counts-are-not = Zahlen zur Wiederholung sind nicht verfügbar.
admin-operation-detail-failed-document-s-task-failure = { $documents } fehlgeschlagene(s) Dokument(e), { $row_failed_tasks_unwrap_or_0 } fehlgeschlagene Aufgabe(n)
admin-operation-detail-failures-were-not-counted = Fehlschläge wurden nicht gezählt.
admin-operation-detail-open-captured-failure-tree = Erfassten Fehlschlagbaum öffnen
admin-operation-detail-open-in-temporal = In Temporal öffnen
admin-operation-detail-plans = Pläne
admin-operation-detail-plan-s-page = { $data_plans_total } Plan/Pläne, Seite { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Für diesen Vorgang wurden keine Pläne erfasst.
admin-operation-detail-dataset = Datensatz
admin-operation-detail-plan-hash = Plan-Hash
admin-operation-detail-source = Quelle
admin-operation-detail-finished = Abgeschlossen
admin-operation-detail-previous = Zurück
admin-operation-detail-next = Weiter
admin-operation-detail-error-events = Fehlerereignisse
admin-operation-detail-error-event-s-page = { $data_events_total } Fehlerereignis(se), Seite { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Für diesen Vorgang wurden keine Fehlerereignisse erfasst.
admin-operation-detail-time = Zeit
admin-operation-detail-hash = Hash
admin-operation-detail-task = Aufgabe
admin-operation-detail-event = Ereignis
admin-operation-detail-error-excerpt = Fehlerausschnitt
admin-operations-admin-operations = Administration: Vorgänge
admin-operations-operations = Vorgänge
admin-operations-loading-operations = Vorgänge werden geladen…
admin-operations-filters = Filter
admin-operations-state = Status
admin-operations-any-state = Jeder Status
admin-operations-collection = Sammlung
admin-operations-all-collections = Alle Sammlungen
admin-operations-choose-a-collection-to-see = Wählen Sie eine Sammlung aus, um deren Fehlerquoten je Aufgabe anzuzeigen.
admin-operations-operations-newest-first = Vorgänge, neueste zuerst
admin-operations-newer = Neuer
admin-operations-page = Seite { $current_page_1 }
admin-operations-older = Älter
admin-operations-failure-rate-by-task-type = Fehlerquote nach Aufgabentyp ({ $collectionname })
admin-operations-one-row-per-activity-execution = Eine Zeile je Ausführung einer Aktivität, Wiederholungen eingeschlossen. Eine Quote über{" "}
admin-operations-is-marked = {" "}wird markiert.
admin-operations-no-task-executions-recorded-for = Für diese Sammlung wurden noch keine Aufgabenausführungen erfasst.
admin-operations-task = Aufgabe
admin-operations-error-rate = Fehlerquote
admin-operations-failed-total-executions = Fehlgeschlagen / Ausführungen insgesamt
admin-operations-documents-affected = Betroffene Dokumente
admin-operations-above-the-line = oberhalb der Linie
admin-operations-no-operations-recorded-for-this = Für diesen Filter wurden keine Vorgänge erfasst.
admin-operations-kind = Art
admin-operations-target = Ziel
admin-operations-workflow = Workflow
admin-operations-queued-at = Eingereiht um
admin-operations-started = Gestartet
admin-operations-duration = Dauer
admin-operations-progress = Fortschritt
admin-operations-eta = Voraussichtlicher Abschluss
admin-operations-outcome = Ergebnis
admin-operations-destructive = Destruktiv
admin-operations-repeated-run = Wiederholte Ausführung
admin-operations-no-estimate-yet = noch keine Schätzung
admin-operations-cancel = Abbrechen
admin-operations-type-to-confirm = Zur Bestätigung { $target } eingeben
admin-operations-re-run = Wiederholen
admin-operations-waiting-for-a-free-slot = wartet auf einen freien Slot oder ein freies Ziel
admin-operations-counting-work = Arbeit wird gezählt…
admin-operations-open-captured-tree = Erfassten Baum öffnen
admin-operations-no-captured-tree = kein erfasster Baum
admin-operations-no-failed-documents = keine fehlgeschlagenen Dokumente
admin-operations-document-s-failed = { $n } Dokument(e) fehlgeschlagen
admin-operations-task-failure-s = { $t } fehlgeschlagene Aufgabe(n)
admin-operations-failures-not-counted = Fehlschläge nicht gezählt
admin-operations-the-newest-ten-operations-of = Die zehn neuesten Vorgänge dieser Sammlung.{" "}
admin-operations-all-operations = Alle Vorgänge
admin-settings-admin-settings = Administration: Einstellungen
admin-settings-server-settings = Servereinstellungen
admin-settings-key = Schlüssel
admin-settings-value = Wert
admin-settings-description = Beschreibung
admin-settings-save = Speichern
admin-settings-loading = Wird geladen…
admin-settings-deployment-configuration-read-only = Bereitstellungskonfiguration (nur lesbar)
admin-settings-not-set = (nicht festgelegt)
admin-user-detail-admin-user = Administration: Benutzer { $username }
admin-user-detail-failed-to-load-user = Benutzer konnte nicht geladen werden
admin-user-detail-loading = Wird geladen…
admin-user-detail-user = Benutzer
admin-user-detail-the-next-login-replaces-the = Die nächste Anmeldung ersetzt bei einem Benutzer vom Login-Proxy den vollständigen Namen, die E-Mail-Adresse und den Superuser-Status.
admin-user-detail-llm-usage-u = LLM-Nutzung →
admin-user-detail-full-name = Vollständiger Name
admin-user-detail-full-name-2 = voller Name
admin-user-detail-email = E-Mail
admin-user-detail-superuser = Superuser
admin-user-detail-save = Speichern
admin-user-detail-groups = Gruppen
admin-user-detail-saving-membership = Mitgliedschaft wird gespeichert…
admin-user-detail-group = Gruppe
admin-user-detail-origin = Herkunft
admin-user-detail-group-admin = Gruppenadministrator
admin-user-detail-uploader = Uploader
admin-user-detail-remove = Entfernen
admin-user-detail-add-to-group-u = Zu Gruppe hinzufügen…
admin-user-detail-add = Hinzufügen
admin-user-detail-danger-zone = Gefahrenzone
admin-user-detail-delete-user = Benutzer löschen
admin-user-llm-admin-llm-use-by = Administration: LLM-Nutzung durch { $username }
admin-user-llm-u-back-to-user = ← Zurück zum Benutzer
admin-user-llm-loading-u = Wird geladen…
admin-user-llm-totals-all-time = Gesamtwerte (gesamter Zeitraum)
admin-user-llm-chat-sessions = Chat-Sitzungen
admin-user-llm-messages = Nachrichten
admin-user-llm-tool-calls = Werkzeugaufrufe
admin-user-llm-model-and-tool-time = Modell- und Werkzeugzeit
admin-user-llm-model-and-tool-time-of = Modell- und Werkzeugzeit der Schritte des Agenten dieses Benutzers. Parallele Werkzeugaufrufe zählen vollständig
admin-user-llm-rate-limit-usage-current-windows = Auslastung der Ratenbegrenzung (aktuelle Zeitfenster)
admin-user-llm-in-process-counters-of-the = Prozessinterne Zähler des laufenden Website-Containers. Chat-Limit { $metrics_chat_per_minute }/min, API-Limit { $metrics_api_per_minute }/min, mit einer abklingenden Dauerrate über die längeren Zeitfenster.
admin-user-llm-chat-messages = Chat-Nachrichten
admin-user-llm-api-calls = API-Aufrufe
admin-user-llm-window = Zeitfenster
admin-user-llm-used = Verwendet
admin-user-llm-budget = Budget
admin-user-llm-no-chat-sessions = Keine Chat-Sitzungen.
admin-user-llm-title = Titel
admin-user-llm-created = Erstellt
admin-users-list-admin-users = Administration: Benutzer
admin-users-list-users = Benutzer
admin-users-list-search-users = Benutzer suchen
admin-users-list-username = Benutzername
admin-users-list-full-name = Vollständiger Name
admin-users-list-email-address = E-Mail-Adresse
admin-users-list-superuser = Superuser
admin-users-list-groups = Gruppen
admin-users-list-created = Erstellt
admin-users-list-last-login = Letzte Anmeldung
admin-users-list-loading = Wird geladen…
dataset-create-panel-put-the-documents-in-a = Legen Sie die Dokumente in einem Ordner ab und laden Sie diese Seite neu.
dataset-create-panel-the-name-cannot-start-with = Der Name darf nicht mit einem Punkt beginnen und darf keinen Schrägstrich enthalten.
dataset-create-panel-and-a-dash-a-space = und ein Bindestrich, ein Leerzeichen oder ein Punkt wird zu einem Unterstrich. Der Name kann später nicht mehr geändert werden.
live-chats-panel-off = aus
processing-updates-panel-the-waiting-steps-change-each = Die wartenden Schritte ändern sich bei { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), jede Datei einmal gezählt, in { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = und ein Bindestrich, ein Leerzeichen oder ein Punkt wird zu einem Unterstrich. Der Name kann später nicht mehr geändert werden.
admin-llm-config-fresh = frisch
admin-llm-config-tools = Werkzeuge{" "}
admin-llm-config-vision = Vision{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (schreibgeschützt)
live-chats-panel-on = an
processing-updates-panel-up-to-date-select-it = Aktuell. Auswählen, um erneut auszuführen.
admin-ai-status-yes = ja
admin-ai-status-no-2 = nein
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } Fehler
admin-collection-processing-done = erledigt
admin-collection-processing-failed-2 = { $stage_failed_documents } fehlgeschlagen
admin-collection-processing-left = verbleibend
admin-collection-processing-dataset-level = Datensatzebene
admin-collections-list-groups = { $c_group_count } Gruppen
admin-failures-operation-s = { $group_operation_count } Vorgänge
admin-groups-list-groupname = Gruppenname
admin-llm-config-stale = veraltet
admin-llm-config-thinking-is-on = Denken ist eingeschaltet
admin-llm-config-thinking-is-off = Denken ist ausgeschaltet
admin-llm-config-shown = { $models_len } angezeigt
admin-llm-config-reasoning = Überlegungen
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } von { $load_table_count }
admin-metrics-yes = ja
admin-metrics-no = nein
admin-metrics-max = max
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = gestartet am { $run_started_at }
admin-operation-detail-yes = ja
admin-operation-detail-no = nein
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = E-Mail
admin-user-llm-untitled = (unbenannt)
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } Seiten
admin-processing-updates-panel-prerequisites-waiting = Die Sammlung braucht zuerst ein Update: { $steps }. Schritte, die in den Suchindex schreiben, warten darauf.
admin-operations-no-task-type-failing = Kein Aufgabentyp liegt über { $threshold }% Fehlern.
admin-operations-task-types-failing = { $count } Aufgabentyp(en) mit mehr als { $threshold }% Fehlern.
processing-updates-panel-collection-updates = Sammlungsupdates
admin-collections-list-some-datasets-are-not-counted = Einige Datensätze sind noch nicht gezählt.
admin-failures-hide = Ausblenden
admin-failures-show = Einblenden
admin-settings-web-session-lifetime-in-seconds = Lebensdauer der Websitzung in Sekunden (Standard: 604800 = 1 Woche)
admin-settings-turns-every-new-chat-turn = Schaltet jede neue Chat-Runde aus, wenn der Wert false ist (Standard: true). Eine laufende Runde wird beendet. Gilt ab dem nächsten Senden, ohne erneute Bereitstellung.
admin-settings-written-by-main-py-probe = Geschrieben von `main.py probe-embeddings`. Der Wert gibt an, was der Endpunkt TATSÄCHLICH bereitstellt. Eine manuelle Änderung ändert den Server nicht.
admin-settings-the-folder-whose-subfolders-the = Der Ordner, dessen Unterordner das Datensatzformular für diesen Mount auflistet. Eine Änderung in hoover4.ini erfordert eine erneute Bereitstellung.
admin-settings-from-hoover4-ini-changing-it = Aus hoover4.ini. Eine Änderung erfordert eine erneute Bereitstellung.
admin-feedback-bug = Fehler
admin-operations-state-name =
    { $state ->
        [pending] ausstehend
        [queued] in der Warteschlange
        [running] läuft
        [finished] abgeschlossen
        [errored] fehlgeschlagen
        [cancelled] abgebrochen
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Fehlschlagbaum von { $op_id }
admin-failure-detail-showing-of-characters = { $node_stack_trace_chars_count } von { $node_stack_trace_original_len } Zeichen angezeigt
admin-operations-operation = Vorgang { $state }.
admin-operations-dispatched = Ausgelöst: { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } Zeilen
admin-operations-plans = { $row_progress_done } / { $row_progress_total } Pläne
admin-group-detail-group-2 = Gruppe { $groupname }
admin-settings-the-setting-was-saved-successfully = Die Einstellung „{ $k }“ wurde erfolgreich gespeichert.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Die Gruppe „{ $g }“ wurde erfolgreich hinzugefügt.
admin-user-detail-user-2 = Benutzer { $username }
admin-dataset-detail-dataset = Datensatz { $dataset_id }
admin-dataset-detail-collections = Sammlungen › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } von { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Die Upload-Einstellung konnte nicht gelesen werden: { $err }
admin-dataset-detail-operation-started = Vorgang gestartet: { $run_id }
admin-collection-detail-collection = Sammlung { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Die Vektor-Einstellung konnte nicht gelesen werden: { $err }
admin-collection-processing-processing-of = Verarbeitung von { $collection_id }
admin-collection-processing-collections = Sammlungen › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } Ausführungen
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = Stand: { $at }
admin-collection-processing-over-the-last-s = in den letzten { $live_window_seconds } s
admin-collection-processing-retry-started-run = Wiederholung gestartet (Durchlauf { $run }).
admin-collection-processing-document-retry-started-run = Wiederholung für das Dokument gestartet (Durchlauf { $run }).
admin-operation-detail-operation-2 = Vorgang { $op_id }
admin-user-llm-llm-usage-of = LLM-Nutzung von { $username }
admin-user-llm-users = Benutzer › { $username }
processing-updates-panel-the-processing-updates-could-not = Die Verarbeitungsupdates konnten nicht gelesen werden: { $e }
processing-updates-panel-update-started = Update gestartet: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } von { $operation_progress_total } Plänen
dataset-ocr-panel-adding = Hinzufügen: { $added }
dataset-ocr-panel-removing = Entfernen: { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } Plan/Pläne erneut geöffnet
processing-updates-unit =
    { $unit ->
        [folders]
            { $count ->
                [one] Ordner
               *[other] Ordner
            }
        [tables]
            { $count ->
                [one] Tabelle
               *[other] Tabellen
            }
       *[files]
            { $count ->
                [one] Datei
               *[other] Dateien
            }
    }
processing-updates-step-runs =
    { $count ->
        [one] Schrittdurchlauf
       *[other] Schrittdurchläufe
    }
processing-update-search_schema-title = Schema des Suchindexes
processing-update-search_schema-explanation =
    { $files ->
        [one] Bei { $count } Suchtabelle der Sammlung fehlt eine Spalte, die der Suchindex braucht.
       *[other] Bei { $count } Suchtabellen der Sammlung fehlt eine Spalte, die der Suchindex braucht.
    } Die Spalte wird jeder Tabelle hinzugefügt. Die Suche funktioniert weiter.
processing-update-search_schema-runs = Tabellen des Suchindexes
processing-update-unfinished-title = Nicht abgeschlossene Verarbeitung
processing-update-unfinished-explanation =
    { $files ->
        [one] { $count } Datei wurde nicht bis zum Ende verarbeitet.
       *[other] { $count } Dateien wurden nicht bis zum Ende verarbeitet.
    } Dazu gehören Dateien ohne Verarbeitungsplan, zum Beispiel nach einem unterbrochenen Einlesen. Ihre Verarbeitung wird abgeschlossen.
processing-update-unfinished-runs = Alle Verarbeitungsstufen für diese Dateien
processing-update-failed_files-title = Fehlgeschlagene Dateien
processing-update-failed_files-explanation =
    { $files ->
        [one] { $count } Datei hat einen Verarbeitungsfehler.
       *[other] { $count } Dateien haben einen Verarbeitungsfehler.
    } Für sie laufen die fehlgeschlagenen Stufen erneut. Der automatische Lauf wiederholt eine Datei einmal je neuer Version der fehlgeschlagenen Stufe.
processing-update-failed_files-runs = Die fehlgeschlagenen Stufen, danach die Entitätenerkennung, Einbettung und Indizierung
processing-update-virus_scan-title = Virenscan
processing-update-virus_scan-explanation =
    { $files ->
        [one] { $count } Datei hat kein Virenscan-Ergebnis.
       *[other] { $count } Dateien haben kein Virenscan-Ergebnis.
    } Sie werden gescannt. Eine Datei, die der Scanner als infiziert erkennt, wird in der Suche markiert, und der Download ihres Originals und ihrer durchsuchbaren PDF-Datei wird abgelehnt.
processing-update-virus_scan-runs = Virenscan, danach das Suchattribut infizierter Dateien
processing-update-tables-title = Tabellen
processing-update-tables-explanation = { $files ->
    [one] { $count } Datei hat eine ältere Tabellenlesung oder unvollständige Folgeergebnisse. Ihre gespeicherten Ergebnisse werden aktualisiert.
    *[other] { $count } Dateien haben ältere Tabellenlesungen oder unvollständige Folgeergebnisse. Ihre gespeicherten Ergebnisse werden aktualisiert.
    }

processing-update-tables-runs = Tabellenlesen, Entitäten, Signale, Einbettungen und beide Indizes
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Dateien mit Bedarf an automatischer OCR: { $count }. Frühere OCR-Texte in der erkannten Sprache bleiben ohne neue OCR erhalten. Die anderen Seiten erhalten OCR mit dem installierten Modell der erkannten Sprache. Abgelöste Varianten werden entfernt, wenn der Ersatz vollständig ist.
processing-update-ocr-runs = OCR und durchsuchbare PDFs, danach die Entitätenerkennung, Einbettung und Indizierung des neuen Textes
processing-update-ocr_detection-title = OCR-Erkennung
processing-update-ocr_detection-explanation = Dateien ohne aktuelle Text-, Schrift- oder Spracherkennung: { $count }. Jedes geeignete Bild und jede geeignete PDF-Seite werden in begrenzten Stapeln untersucht.
processing-update-ocr_detection-runs = Erkennung, danach die Suchattribute dieser Dateien
processing-update-pdf_text-title = Text durchsuchbarer PDFs
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } Datei hat durchsuchbare PDFs mit einer früheren Textebene.
   *[other] { $count } Dateien haben durchsuchbare PDFs mit einer früheren Textebene.
} Diese Ebene kopierte jeden Buchstaben außerhalb der westeuropäischen Alphabete als schwarzes Quadrat. PDFs von Sprachen mit nur westeuropäischen Buchstaben bleiben unverändert. Die anderen PDFs werden gelesen, und die Teile mit schwarzen Quadraten werden neu erstellt. Ein Bild-PDF verwendet die gespeicherten OCR-Wörter. Eine PDF-Seite erhält eine neue OCR-Anfrage.
processing-update-pdf_text-runs = Teile durchsuchbarer PDFs, danach die Indizierung des OCR-Textes der neu erstellten PDFs
processing-update-page_text-title = Indizierter Seitentext
processing-update-page_text-explanation = Dateien mit unvollständigem Suchtext: { $count }. Ein Steuerzeichen auf einer Seite hat ihren indizierten Text beendet. Der vollständige Text wird indiziert.
processing-update-page_text-runs = Suchindextext dieser Seiten
processing-update-text_rows-title = Textaufteilung
processing-update-text_rows-explanation = Dateien mit Text aus einer früheren Aufteilung: { $count }. PDF-Text wandert in eine Zeile je PDF-Teil, und langer Text wird mit einer kurzen Überlappung getrennt. Es laufen kein neues OCR und kein neues Parsen.
processing-update-text_rows-runs = Textaufteilung, danach die Entitätenerkennung, Einbettung und Indizierung des neuen Textes
processing-update-vectors-title = Vektoren
processing-update-vectors-explanation =
    { $files ->
        [one] { $count } Datei mit Text hat keine Vektoren des Einbettungsmodells, das die Installation bereitstellt.
       *[other] { $count } Dateien mit Text haben keine Vektoren des Einbettungsmodells, das die Installation bereitstellt.
    } Deren Vektoren werden berechnet und indiziert.
processing-update-vectors-runs = Einbettung und Vektorindizierung
processing-update-folder_counts-title = Ordnerzähler
processing-update-folder_counts-explanation =
    { $files ->
        [one] Bei { $count } Ordner fehlen Dateianzahl und -größe, oder er hat Werte einer früheren Version.
       *[other] Bei { $count } Ordnern fehlen Dateianzahl und -größe, oder sie haben Werte einer früheren Version.
    } Die Zähler werden erneut berechnet.
processing-update-folder_counts-runs = Ordnerbaum
admin-uploads-badge = Uploads
admin-uploads-badge-title = Nimmt Uploads an

processing-update-archive_members-title = Archivmitglieder

processing-update-archive_members-explanation = { $files ->
    [one] { $count } geteiltes Archiv benötigt eine aktuelle Dateiliste. Seine Dateien und Suchdaten werden aktualisiert.
    *[other] { $count } geteilte Archive benötigen aktuelle Dateilisten. Ihre Dateien und Suchdaten werden aktualisiert.
    }

processing-update-archive_members-runs = Archivextraktion, Datei abgleich und abhängige Verarbeitung

processing-update-image_previews-title = Bildvorschauen

processing-update-image_previews-explanation = { $files ->
    [one] { $count } seltenes Bild hat keine Vorschau. Seine Vorschau wird erneut erstellt.
    *[other] { $count } seltene Bilder haben keine Vorschau. Ihre Vorschauen werden erneut erstellt.
    }

processing-update-image_previews-runs = Erstellung und Prüfung der Bildvorschauen

processing-update-search_terms-title = Suchbegriffe

processing-update-search_terms-explanation = { $files ->
    [one] { $count } Suchtabelle benötigt aktuelle Filterbegriffe. Begriffe zu Sprache, OCR, Schrift und Warnsignalen werden durchsuchbar.
    *[other] Suchtabellen, die aktuelle Filterbegriffe benötigen: { $count }. Begriffe zu Sprache, OCR, Schrift und Warnsignalen werden durchsuchbar.
    }

processing-update-search_terms-runs = Indexierung und Prüfung der Filterbegriffe

automatic-ocr-title = Automatische OCR
automatic-ocr-refresh = Status aktualisieren
automatic-ocr-coverage = Seitenabdeckung
automatic-ocr-pages = Seiten
automatic-ocr-models = OCR-Modelle
automatic-ocr-reason = Grund
automatic-ocr-truncated = Die Diagnoseliste ist unvollständig.
automatic-ocr-presence = Hat veröffentlichten OCR-Text
automatic-ocr-policy = OCR wählt installierte Modelle nach erkannter Schrift und Sprache jeder geeigneten Seite. Tesseract wird zuerst verwendet, EasyOCR für nicht abgedeckte Schriften.
automatic-ocr-unknown = Es ist keine aktuelle Veröffentlichung erfasst. Fehlende Erkennung und fehlgeschlagene Verarbeitung belegen keine Abwesenheit.
automatic-ocr-retry = Wiederholen Sie unvollständige oder fehlgeschlagene Arbeit nach der Fehlerbehebung über Verarbeitungsaktualisierungen. Nicht unterstützte Abdeckung erfordert passende installierte Modelle.
automatic-ocr-state = { $state ->
    [candidate] Ausstehend
    [planned] Geplant
    [failed] Fehlgeschlagen
    [incomplete] Unvollständig
    [unsupported] Nicht unterstützt
    [published] Veröffentlicht
    [applied] Verifiziert
    [ready] Text erkannt
    [no_text] Kein Text erkannt
    *[other] { $state }
    }

processing-update-entities-title = Benannte Entitäten
processing-update-entities-explanation = Dateien mit Bedarf an aktueller Entitätsextraktion oder durchsuchbaren Ergebnissen: { $count }. Frühere erfolgreiche Ergebnisse werden nach Abschluss der Inferenz ersetzt.
processing-update-entities-runs = Extraktion benannter Entitäten, Textattribute und durchsuchbare Entitätsbegriffe

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Schrift nicht erkannt
    [tesseract_capabilities_unavailable] Tesseract-Abdeckung nicht verfügbar
    [detected_language] Modell passt zur erkannten Sprache
    [unknown_language_script_coverage] Sprache unbekannt. Ein Schriftmodell ist ausgewählt.
    [language_script_mismatch_script_coverage] Sprache und Schrift weichen ab. Ein Schriftmodell ist ausgewählt.
    [language_model_unavailable_script_coverage] Sprachmodell nicht verfügbar. Ein Schriftmodell ist ausgewählt.
    [easyocr_capabilities_unavailable] EasyOCR-Abdeckung nicht verfügbar
    [tesseract_script_unavailable] Tesseract deckt die Schrift nicht ab. EasyOCR ist ausgewählt.
    [script_coverage_unavailable] Kein installiertes Modell deckt diese Schrift ab.
    *[other] { $reason }
    }

processing-updates-check-requested = Die Pipeline berechnet die Aktualisierungen. Die Zahlen ändern sich nach Abschluss der Berechnung.
