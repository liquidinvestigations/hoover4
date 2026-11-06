# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Απαιτείται πρόσβαση διαχείρισης
admin-guard-signed-in-as = Έχετε συνδεθεί ως { $u_username }.
admin-guard-ask-an-administrator-for-access = Ζητήστε από έναν διαχειριστή πρόσβαση σε αυτή την ενότητα.
admin-shell-dashboard = Πίνακας ελέγχου
admin-shell-collections = Συλλογές
admin-shell-operations = Εργασίες
admin-shell-errors-failures = Σφάλματα/Αποτυχίες
admin-shell-feedback = Σχόλια
admin-shell-users = Χρήστες
admin-shell-groups = Ομάδες
admin-shell-settings = Ρυθμίσεις
admin-shell-llm = LLM
admin-shell-ai-status = Κατάσταση AI
admin-shell-metrics = Μετρικές
admin-shell-administration = Διαχείριση
dataset-create-panel-add-a-dataset = Προσθήκη συνόλου δεδομένων
dataset-create-panel-the-dataset-mounts-could-not = Τα σημεία προσάρτησης συνόλων δεδομένων δεν μπόρεσαν να διαβαστούν, επομένως δεν υπάρχει τίποτα για επιλογή: { $err }
dataset-create-panel-loading-the-dataset-mounts = Φόρτωση των σημείων προσάρτησης συνόλων δεδομένων.
dataset-create-panel-no-dataset-mount-is-configured = Δεν έχει ρυθμιστεί σημείο προσάρτησης συνόλων δεδομένων.
dataset-create-panel-the-mount-folder-could-not = Ο φάκελος του σημείου προσάρτησης δεν μπόρεσε να διαβαστεί, επομένως δεν υπάρχει τίποτα για επιλογή: { $err }
dataset-create-panel-no-subfolders-were-found-in = Δεν βρέθηκαν υποφάκελοι σε αυτό το σημείο προσάρτησης.{" "}
dataset-create-panel-folder = Φάκελος
dataset-create-panel-select-a-folder = Επιλογή φακέλου
dataset-create-panel-new-folder = Νέος φάκελος
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } καταχωρίσεις), ήδη σύνολο δεδομένων
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } καταχωρίσεις)
dataset-create-panel-the-server-creates-this-folder = Ο διακομιστής δημιουργεί αυτόν τον φάκελο στο σημείο προσάρτησης όταν δημιουργήσετε το σύνολο δεδομένων.{" "}
dataset-create-panel-the-list-shows-the-direct = Η λίστα εμφανίζει τους άμεσους υποφακέλους του σημείου προσάρτησης.
dataset-create-panel-dataset-name = Όνομα συνόλου δεδομένων
dataset-create-panel-a-name-has-lowercase-letters = Ένα όνομα έχει πεζά γράμματα, ψηφία και κάτω παύλες. Τα κεφαλαία γράμματα γίνονται πεζά,{" "}
dataset-create-panel-the-dataset-is-saved-as = Το σύνολο δεδομένων αποθηκεύεται ως: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Αυτή η συλλογή έχει ήδη σύνολο δεδομένων με το όνομα { $saved_name }.
dataset-create-panel-accept-uploads = Αποδοχή μεταφορτώσεων
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Αποθηκεύτηκε ως προεπιλογές αυτής της συλλογής. Κανένα σύνολο δεδομένων δεν αλλάζει γλώσσες.
dataset-create-panel-saving-u = Αποθήκευση…
dataset-create-panel-save-as-collection-defaults = Αποθήκευση ως προεπιλογές συλλογής
dataset-create-panel-creating-u = Δημιουργία…
dataset-create-panel-create-and-ingest = Δημιουργία και εισαγωγή
dataset-create-panel-mount = Σημείο προσάρτησης
dataset-ocr-panel-last-operation = Τελευταία εργασία: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , ξεκίνησε { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Καμία πρόοδος για { $current_stale_seconds_60 } λεπτά. Ελέγξτε τη ροή εργασίας του Temporal και ακυρώστε την εργασία αν έχει κολλήσει.
dataset-ocr-panel-filter-languages = Φιλτράρισμα γλωσσών
dataset-ocr-panel-ocr-languages = Γλώσσες OCR
dataset-ocr-panel-failed-to-load-the-ocr = Η φόρτωση των ρυθμίσεων OCR για αυτό το σύνολο δεδομένων απέτυχε
dataset-ocr-panel-loading-u = Φόρτωση…
dataset-ocr-panel-each-easyocr-script-group-adds = Κάθε ομάδα γραφής του EasyOCR προσθέτει ένα πέρασμα OCR στο σύνολο δεδομένων. Το Tesseract διαβάζει όλες τις γλώσσες του σε ένα πέρασμα.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = Σε ισχύ: { $panel_tesseract_languages }, από { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = Χρήση { $source_label_panel_inherited_tesseract_s }: { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = Η υπηρεσία Tesseract δεν απάντησε, επομένως οι εγκατεστημένες γλώσσες είναι άγνωστες.{" "}
dataset-ocr-panel-the-image-also-has-script = Η εικόνα έχει επίσης { $script_models } μοντέλα γραφής, για παράδειγμα Latin. Η φόρμα δεν τα προσφέρει, επειδή η ρύθμιση γίνεται μέρος ενός κλειδιού αποθήκευσης και δέχεται μόνο κωδικούς με πεζά γράμματα.
dataset-ocr-panel-the-first-language-is-the = Η πρώτη γλώσσα είναι η κύρια. Επιλεγμένες:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = Το EasyOCR είναι απενεργοποιημένο σε αυτή την εγκατάσταση, επομένως αυτή η ρύθμιση δεν έχει αποτέλεσμα μέχρι να ενεργοποιηθεί.
dataset-ocr-panel-in-force-off-from = Σε ισχύ: απενεργοποιημένο, από { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = Σε ισχύ: { $panel_easyocr_languages }, από { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = Χρήση { $source_label_panel_inherited_easyocr_sou }: απενεργοποιημένο
dataset-ocr-panel-use-2 = Χρήση { $source_label_panel_inherited_easyocr_sou }: { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Ενεργοποιημένο
dataset-ocr-panel-the-easyocr-service-did-not = Η υπηρεσία EasyOCR δεν ανέφερε τις γλώσσες που υποστηρίζει.
dataset-ocr-panel-a-model-download-failed = Η λήψη ενός μοντέλου απέτυχε: { $failure }
dataset-ocr-panel-stored-text-variants = Αποθηκευμένες παραλλαγές κειμένου
dataset-ocr-panel-removing-a-language-deletes-its = Η αφαίρεση μιας γλώσσας διαγράφει το κείμενό της, τις γραμμές αναζήτησής της και το PDF με δυνατότητα αναζήτησης.
dataset-ocr-panel-searchable-pdfs = PDF με δυνατότητα αναζήτησης
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } αρχεία · { $variant_total_bytes_1024_1024 } MB
dataset-ocr-panel-searchable-pdfs-are-off-on = Τα PDF με δυνατότητα αναζήτησης είναι απενεργοποιημένα σε αυτή την εγκατάσταση.
dataset-ocr-panel-saving-u = Αποθήκευση…
dataset-ocr-panel-apply = Εφαρμογή
dataset-ocr-panel-no-changes-to-apply = Δεν υπάρχουν αλλαγές για εφαρμογή.
live-chats-panel-live-llm-chats = Ζωντανές συνομιλίες LLM
live-chats-panel-agent-turns-running-right-now = Γύροι του πράκτορα που εκτελούνται αυτή τη στιγμή, πρώτοι οι μακροβιότεροι. Ανανεώνεται κάθε 2 δ. Διαβάζεται από το Temporal, επομένως εμφανίζεται και ένας γύρος που ξεκίνησε πριν από την τελευταία επανεκκίνηση του ιστότοπου.
live-chats-panel-loading-u = Φόρτωση…
live-chats-panel-no-chats-running = Δεν εκτελείται καμία συνομιλία.
live-chats-panel-user = Χρήστης
live-chats-panel-conversation = Συνομιλία
live-chats-panel-question = Ερώτηση
live-chats-panel-internet = Διαδίκτυο
live-chats-panel-running = Σε εκτέλεση
live-chats-panel-started = Έναρξη
live-chats-panel-cancels-the-workflow-the-turn = Ακυρώνει τη ροή εργασίας. Ο γύρος τελειώνει με ένδειξη διακοπής στο ιστορικό αντί να εξαφανιστεί.
live-chats-panel-kill = Τερματισμός
processing-updates-panel-loading-u = Φόρτωση…
processing-updates-panel-open-the-operation = Άνοιγμα της εργασίας
processing-updates-panel-the-pipeline-has-not-calculated = Η ροή επεξεργασίας δεν έχει υπολογίσει ακόμη αυτές τις ενημερώσεις.
processing-updates-panel-calculated-at-in-ms = Υπολογίστηκε στις { $view_checked_at } σε { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Οι αυτόματες ενημερώσεις είναι απενεργοποιημένες σε αυτή την εγκατάσταση. Ξεκινήστε τις ενημερώσεις με το κουμπί.
processing-updates-panel-step = Βήμα
processing-updates-panel-count = Πλήθος
processing-updates-panel-state = Κατάσταση
processing-updates-panel-last-run = Τελευταία εκτέλεση
processing-updates-panel-runs = Εκτελέσεις: { $step_runs }
processing-updates-panel-a-run-again-would-select = Μια νέα εκτέλεση θα επέλεγε περίπου τόσα: { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } σε νέα εκτέλεση
processing-updates-panel-never = Ποτέ
processing-updates-panel-update-collection = Ενημέρωση συλλογής
processing-updates-panel-update-processing = Ενημέρωση επεξεργασίας
processing-updates-panel-check-again = Έλεγχος ξανά
processing-updates-panel-dataset = Σύνολο δεδομένων
processing-updates-panel-processing-updates = Ενημερώσεις επεξεργασίας
admin-ai-status-admin-ai-status = Διαχείριση: κατάσταση AI
admin-ai-status-ai-status = Κατάσταση AI
admin-ai-status-the-configured-service-and-the = Η υπηρεσία που έχει ρυθμιστεί και η υπηρεσία που απαντά πραγματικά. Η εναλλαγή στην υπηρεσία CPU εμφανίζεται μόνο εδώ.
admin-ai-status-loading-u = Φόρτωση…
admin-ai-status-config-fingerprint = Αποτύπωμα ρυθμίσεων
admin-ai-status-website-worker = Ιστότοπος / εργάτης
admin-ai-status-ai-server = Διακομιστής AI
admin-ai-status-match = Ταύτιση
admin-ai-status-embeddings-probe = Δοκιμή embeddings
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } διαστάσεις
admin-ai-status-llm-configured = Ρυθμισμένο LLM
admin-ai-status-capabilities = Δυνατότητες
admin-ai-status-capability = Δυνατότητα
admin-ai-status-configured = Ρυθμισμένο
admin-ai-status-serving = Σε λειτουργία
admin-ai-status-model = Μοντέλο
admin-ai-status-reachable = Προσβάσιμο
admin-ai-status-detail = Λεπτομέρεια
admin-ai-status-no = ΟΧΙ
admin-ai-status-vector-shard-dims-vs-probe = Διαστάσεις θραύσματος διανυσμάτων έναντι δοκιμής
admin-ai-status-no-collections-yet = Δεν υπάρχουν ακόμη συλλογές.
admin-ai-status-collection = Συλλογή
admin-ai-status-shard = Θραύσμα
admin-ai-status-matches-probe = Ταιριάζει με τη δοκιμή
admin-ai-status-browser-router = Δρομολογητής προγράμματος περιήγησης
admin-ai-status-live-sessions = Ενεργές συνεδρίες: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Πρόσφατη κίνηση LLM (24 ώ)
admin-ai-status-no-llm-call-events-yet = Δεν υπάρχουν ακόμη llm_call_events.
admin-ai-status-user = Χρήστης
admin-ai-status-calls = Κλήσεις
admin-ai-status-errors = Σφάλματα
admin-ai-status-service-use-24-h = Χρήση υπηρεσίας % (24 ώ)
admin-ai-status-busy-seconds-in-the-last = Δευτερόλεπτα απασχόλησης τις τελευταίες 24 ώρες, ως ποσοστό του εικοσιτετραώρου.
admin-ai-status-no-samples-yet = Δεν υπάρχουν ακόμη δείγματα.
admin-ai-status-service = Υπηρεσία
admin-ai-status-busy-s = Απασχόληση δ
admin-ai-status-use = Χρήση %
admin-collection-detail-admin-collection = Διαχείριση: συλλογή { $collection_id }
admin-collection-detail-failed-to-load-collection = Η φόρτωση της συλλογής απέτυχε
admin-collection-detail-loading = Φόρτωση...
admin-collection-detail-datasets = Σύνολα δεδομένων
admin-collection-detail-dataset = Σύνολο δεδομένων
admin-collection-detail-documents = Έγγραφα
admin-collection-detail-size = Μέγεθος
admin-collection-detail-indexed = Ευρετηριασμένα
admin-collection-detail-errors = Σφάλματα
admin-collection-detail-state = Κατάσταση
admin-collection-detail-created = Δημιουργήθηκε
admin-collection-detail-settings = Ρυθμίσεις
admin-collection-detail-the-collection-database-is-not = Η βάση δεδομένων της συλλογής δεν είναι ακόμη έτοιμη.
admin-collection-detail-the-last-storage-provisioning-failed = Η τελευταία προετοιμασία αποθήκευσης απέτυχε: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Πρόοδος επεξεργασίας και εκτιμήσεις
admin-collection-detail-display-name = Εμφανιζόμενο όνομα
admin-collection-detail-display-name-2 = εμφανιζόμενο όνομα
admin-collection-detail-save = Αποθήκευση
admin-collection-detail-access = Πρόσβαση
admin-collection-detail-public-every-signed-in-user = Δημόσια. Κάθε συνδεδεμένος χρήστης μπορεί να αναζητά και να διαβάζει αυτή τη συλλογή.
admin-collection-detail-restricted-only-members-of-the = Περιορισμένη. Μόνο τα μέλη των παρακάτω ομάδων μπορούν να αναζητούν και να διαβάζουν αυτή τη συλλογή.
admin-collection-detail-the-collection-is-now-public = Η συλλογή είναι πλέον δημόσια.
admin-collection-detail-the-collection-is-now-restricted = Η συλλογή είναι πλέον περιορισμένη.
admin-collection-detail-make-restricted = Περιορισμός
admin-collection-detail-make-public = Δημοσιοποίηση
admin-collection-detail-group-permissions = Δικαιώματα ομάδων
admin-collection-detail-no-group-can-read-this = Καμία ομάδα δεν μπορεί ακόμη να διαβάσει αυτή τη συλλογή.
admin-collection-detail-revoke = Ανάκληση
admin-collection-detail-grant-group-u = Παραχώρηση σε ομάδα…
admin-collection-detail-grant = Παραχώρηση
admin-collection-detail-danger-zone = Επικίνδυνη ζώνη
admin-collection-detail-a-collection-can-only-be = Μια συλλογή μπορεί να διαγραφεί μόνο όταν δεν έχει σύνολα δεδομένων.
admin-collection-detail-deleting-the-collection-also-drops = Η διαγραφή της συλλογής διαγράφει επίσης τη βάση δεδομένων της{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}και ό,τι περιέχει. Δεν μπορεί να αναιρεθεί. Πληκτρολογήστε το όνομα της συλλογής για επιβεβαίωση.
admin-collection-detail-collection-name = Όνομα συλλογής
admin-collection-detail-delete-collection = Διαγραφή συλλογής
admin-collection-detail-features = Λειτουργίες
admin-collection-detail-vectors = Διανύσματα
admin-collection-detail-this-installation-runs-no-embedding = Αυτή η εγκατάσταση δεν εκτελεί υπηρεσία embedding, επομένως καμία συλλογή δεν χρησιμοποιεί διανύσματα.
admin-collection-detail-vectors-find-passages-by-meaning = Τα διανύσματα βρίσκουν αποσπάσματα με βάση το νόημα. Η απενεργοποίηση σταματά τα νέα διανύσματα και σταματά την αναζήτηση από το να χρησιμοποιεί τα αποθηκευμένα, τα οποία παραμένουν. Η ενεργοποίηση υπολογίζει τα διανύσματα που λείπουν σε κάθε σύνολο δεδομένων, ένα σύνολο τη φορά.
admin-collection-detail-this-collection-follows-the-installation = Αυτή η συλλογή ακολουθεί την εγκατάσταση, η οποία χρησιμοποιεί διανύσματα. Τα διανύσματα βρίσκουν αποσπάσματα με βάση το νόημα. Η απενεργοποίηση σταματά τα νέα διανύσματα και σταματά την αναζήτηση από το να χρησιμοποιεί τα αποθηκευμένα, τα οποία παραμένουν.
admin-collection-processing-could-not-load-this-panel = Δεν ήταν δυνατή η φόρτωση αυτού του πλαισίου: { $message }
admin-collection-processing-admin-processing-of = Διαχείριση: επεξεργασία του { $collection_id }
admin-collection-processing-u-back-to-collection = ← Πίσω στη συλλογή
admin-collection-processing-processing-stages = Στάδια επεξεργασίας
admin-collection-processing-loading-u = Φόρτωση…
admin-collection-processing-the-collection-database-is-still = Η βάση δεδομένων της συλλογής βρίσκεται ακόμη σε προετοιμασία.
admin-collection-processing-this-collection-has-no-datasets = Αυτή η συλλογή δεν έχει ακόμη σύνολα δεδομένων.
admin-collection-processing-eta = Εκτίμηση ολοκλήρωσης { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Δεν υπάρχουν ακόμη δείγματα εκτίμησης. Συλλέγονται όσο το σύνολο δεδομένων υφίσταται επεξεργασία.
admin-collection-processing-estimated-completion = Εκτιμώμενη ολοκλήρωση:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(σε { $humanize_seconds_c_eta_seconds }, μια εκτίμηση βέλτιστης προσπάθειας και όχι υπόσχεση χρονοπρογραμματισμού)
admin-collection-processing-no-current-estimate-the-pipeline = Δεν υπάρχει τρέχουσα εκτίμηση. Η ροή επεξεργασίας έχει τελειώσει ή δεν σημειώνει μετρήσιμη πρόοδο.
admin-collection-processing-where-processing-time-goes = Πού καταναλώνεται ο χρόνος επεξεργασίας
admin-collection-processing-no-task-executions-recorded-yet = Δεν έχουν καταγραφεί ακόμη εκτελέσεις εργασιών. Κάθε δραστηριότητα που εκτελεί η ροή επεξεργασίας γράφει εδώ μία γραμμή, επομένως ένας κενός πίνακας σημαίνει ότι δεν έχει επεξεργαστεί τίποτα από την ανάπτυξη της καταγραφής.
admin-collection-processing-summed-task-time = Συνολικός χρόνος εργασιών
admin-collection-processing-wall-clock = Πραγματικός χρόνος
admin-collection-processing-achieved-parallelism = Επιτευχθείς παραλληλισμός
admin-collection-processing-summed-task-time-divided-by = Ο συνολικός χρόνος εργασιών διαιρεμένος με τον πραγματικό χρόνο είναι ο παραλληλισμός που πέτυχε πραγματικά η ροή επεξεργασίας. Τιμή κοντά στο 1 σημαίνει ότι η πρώτη εργασία παρακάτω είναι ολόκληρο το κόστος και αξίζει βελτιστοποίηση. Τιμή κοντά στον αριθμό των θέσεων εργατών σημαίνει ότι οι θέσεις είναι κορεσμένες και η προσθήκη εργατών είναι η φθηνότερη λύση. Ο πραγματικός χρόνος καλύπτει από την πρώτη έως την τελευταία εκτέλεση, μαζί με τον αδρανή χρόνο.
admin-collection-processing-task = Εργασία
admin-collection-processing-total = Σύνολο
admin-collection-processing-share = Μερίδιο
admin-collection-processing-executions = Εκτελέσεις
admin-collection-processing-mean = Μέσος όρος
admin-collection-processing-max = Μέγιστο
admin-collection-processing-failed = Απέτυχαν
admin-collection-processing-live-activity = Ζωντανή δραστηριότητα
admin-collection-processing-nothing-running-no-activity-finished = Δεν εκτελείται τίποτα. Καμία δραστηριότητα δεν ολοκληρώθηκε τα τελευταία { $live_window_seconds } δ και κανένας εργάτης δεν αναφέρει κάτι σε εξέλιξη.
admin-collection-processing-in-flight = Σε εξέλιξη
admin-collection-processing-average-concurrency = Μέση ταυτοχρονία
admin-collection-processing-task-time-in-window = Χρόνος εργασιών στο παράθυρο
admin-collection-processing-share-of-processing-time-over = Μερίδιο του χρόνου επεξεργασίας τα τελευταία { $live_window_seconds } δ, με ανανέωση κάθε 5 δ. Μια εκτέλεση που διασχίζει το όριο του παραθύρου μετράει μόνο για το μέρος που βρίσκεται μέσα σε αυτό. Μια γραμμή με εκτελέσεις σε εξέλιξη αλλά χωρίς μερίδιο είναι μια εκτέλεση που ξεκίνησε πριν από το παράθυρο και δεν έχει τελειώσει. Ελέγξτε την ηλικία της.
admin-collection-processing-share-of-window = Μερίδιο παραθύρου
admin-collection-processing-task-time = Χρόνος εργασίας
admin-collection-processing-completed = Ολοκληρώθηκαν
admin-collection-processing-oldest-running = Παλαιότερη σε εκτέλεση
admin-collection-processing-temporal-workflows = Ροές εργασίας Temporal
admin-collection-processing-workflows-of-this-collection-s = Ροές εργασίας των συνόλων δεδομένων αυτής της συλλογής, μαζί με τις θυγατρικές ροές.
admin-collection-processing-no-workflows-match-this-filter = Καμία ροή εργασίας δεν ταιριάζει με αυτό το φίλτρο.
admin-collection-processing-workflow = Ροή εργασίας
admin-collection-processing-type = Τύπος
admin-collection-processing-status = Κατάσταση
admin-collection-processing-started = Έναρξη
admin-collection-processing-closed = Λήξη
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = άνοιγμα ↗
admin-collection-processing-failed-tasks = Εργασίες που απέτυχαν
admin-collection-processing-no-task-failures-recorded = Δεν έχουν καταγραφεί αποτυχίες εργασιών.
admin-collection-processing-dataset = Σύνολο δεδομένων
admin-collection-processing-errors = Σφάλματα
admin-collection-processing-documents = Έγγραφα
admin-collection-processing-last-seen = Τελευταία εμφάνιση
admin-collection-processing-sample = Δείγμα
admin-collection-processing-retry = Επανάληψη
admin-collection-processing-failures-per-document = Αποτυχίες ανά έγγραφο
admin-collection-processing-no-document-failures-recorded = Δεν έχουν καταγραφεί αποτυχίες εγγράφων.
admin-collection-processing-document = Έγγραφο
admin-collections-list-admin-collections = Διαχείριση: συλλογές
admin-collections-list-collections = Συλλογές
admin-collections-list-loading-collections-u = Φόρτωση συλλογών…
admin-collections-list-datasets = Σύνολα δεδομένων
admin-collections-list-loading-datasets-u = Φόρτωση συνόλων δεδομένων…
admin-collections-list-add-a-collection = Προσθήκη συλλογής
admin-collections-list-name-for-example-enron = Όνομα, για παράδειγμα enron
admin-collections-list-display-name = Εμφανιζόμενο όνομα
admin-collections-list-add-collection = Προσθήκη συλλογής
admin-collections-list-a-name-has-lowercase-letters = Ένα όνομα έχει πεζά γράμματα, ψηφία και κάτω παύλες. Τα κεφαλαία γράμματα γίνονται πεζά,{" "}
admin-collections-list-the-collection-is-saved-as = Η συλλογή αποθηκεύεται ως: { $new_name }
admin-collections-list-a-collection-with-the-name = Υπάρχει ήδη συλλογή με το όνομα { $new_name }.
admin-collections-list-collection = Συλλογή
admin-collections-list-documents = Έγγραφα
admin-collections-list-size = Μέγεθος
admin-collections-list-errors = Σφάλματα
admin-collections-list-state = Κατάσταση
admin-collections-list-access = Πρόσβαση
admin-collections-list-database-not-ready = Η βάση δεδομένων δεν είναι έτοιμη
admin-collections-list-public = Δημόσια
admin-collections-list-1-group = 1 ομάδα
admin-collections-list-not-counted-yet = Δεν έχει μετρηθεί ακόμη
admin-collections-list-unknown = Άγνωστο
admin-collections-list-no-collection-has-a-dataset = Καμία συλλογή δεν έχει σύνολο δεδομένων.
admin-collections-list-dataset = Σύνολο δεδομένων
admin-collections-list-indexed = Ευρετηριασμένα
admin-collections-list-created = Δημιουργήθηκε
admin-dashboard-admin-dashboard = Διαχείριση: πίνακας ελέγχου
admin-dashboard-administration = Διαχείριση
admin-dashboard-users = Χρήστες
admin-dashboard-groups = Ομάδες
admin-dashboard-collections = Συλλογές
admin-dashboard-datasets = Σύνολα δεδομένων
admin-dashboard-failed-to-load-counts = Η φόρτωση των μετρήσεων απέτυχε: { $e }
admin-dataset-detail-admin-dataset = Διαχείριση: σύνολο δεδομένων { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Η φόρτωση του συνόλου δεδομένων απέτυχε
admin-dataset-detail-loading = Φόρτωση...
admin-dataset-detail-metadata = Μεταδεδομένα
admin-dataset-detail-display-name = Εμφανιζόμενο όνομα
admin-dataset-detail-name = Όνομα
admin-dataset-detail-type = Τύπος
admin-dataset-detail-path = Διαδρομή
admin-dataset-detail-created = Δημιουργήθηκε
admin-dataset-detail-collection = Συλλογή
admin-dataset-detail-save = Αποθήκευση
admin-dataset-detail-statistics = Στατιστικά
admin-dataset-detail-state = Κατάσταση
admin-dataset-detail-documents = Έγγραφα
admin-dataset-detail-size = Μέγεθος
admin-dataset-detail-indexed = Ευρετηριασμένα
admin-dataset-detail-errors = Σφάλματα
admin-dataset-detail-plans-finished = Ολοκληρωμένα σχέδια
admin-dataset-detail-disk = Δίσκος
admin-dataset-detail-rescan-disk-reads-the-dataset = Η Νέα σάρωση δίσκου διαβάζει ξανά τον φάκελο του συνόλου δεδομένων, προσθέτει τα νέα και τροποποιημένα αρχεία και τα επεξεργάζεται.
admin-dataset-detail-rescan-disk = Νέα σάρωση δίσκου
admin-dataset-detail-danger-zone = Επικίνδυνη ζώνη
admin-dataset-detail-this-deletes-the-dataset-and = Διαγράφει το σύνολο δεδομένων και όλα τα δεδομένα που εξήχθησαν από αυτό. Δεν μπορεί να αναιρεθεί.
admin-dataset-detail-delete-dataset-and-its-data = Διαγραφή συνόλου δεδομένων και των δεδομένων του
admin-dataset-detail-accept-uploads = Αποδοχή μεταφορτώσεων
admin-dataset-detail-the-folder-of-this-dataset = Ο φάκελος αυτού του συνόλου δεδομένων δεν βρίσκεται σε εγγράψιμο σημείο προσάρτησης συνόλων δεδομένων, επομένως δεν δέχεται μεταφορτώσεις.
admin-dataset-detail-starting-u = Έναρξη…
admin-failure-detail-admin-failure = Διαχείριση: αποτυχία { $op_id }
admin-failure-detail-loading-tree = Φόρτωση δέντρου…
admin-failure-detail-back-to-errors-and-failures = Πίσω στα σφάλματα και τις αποτυχίες
admin-failure-detail-operations = Εργασίες
admin-failure-detail-scrubbed-copy-written-to-the = Το ανωνυμοποιημένο αντίγραφο γράφτηκε στο πρόχειρο.
admin-failure-detail-this-tree-is-truncated-at = Αυτό το δέντρο είναι περικομμένο. Τουλάχιστον μία καταγραφή απέρριψε κόμβους.
admin-failure-detail-the-captured-tree-has-expired = Το καταγεγραμμένο δέντρο έχει λήξει. Η γραμμή της εργασίας υπάρχει ακόμη.
admin-failure-detail-no-captured-nodes-for-this = Δεν υπάρχουν καταγεγραμμένοι κόμβοι για αυτή την εργασία.
admin-failure-detail-operation = Εργασία
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } ρίζα(ες) · { $tree_nodes_len } κόμβος(οι)
admin-failure-detail-open-in-temporal = Άνοιγμα στο Temporal
admin-failure-detail-scrubbed-copy = Ανωνυμοποιημένο αντίγραφο
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Το ανωνυμοποιημένο αντίγραφο αντικαθιστά τις διαδρομές των συνόλων δεδομένων με κατακερματισμούς και τις μεγάλες τιμές με το μήκος τους.
admin-failure-detail-copy-scrubbed-record = Αντιγραφή ανωνυμοποιημένης εγγραφής
admin-failure-detail-tree = Δέντρο
admin-failure-detail-root = Ρίζα ·{" "}
admin-failure-detail-node-parent-depth-source-stage = κόμβος { $node_node_index } · γονικός { $node_parent_index } · βάθος { $node_depth } · πηγή { $node_source } · στάδιο { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = ροή εργασίας { $node_workflow_id } · εκτέλεση { $node_run_id } · δραστηριότητα { $node_activity_id } · προσπάθεια { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } κόμβος(οι) απορρίφθηκαν σε αυτή την καταγραφή
admin-failures-admin-errors-and-failures = Διαχείριση: σφάλματα και αποτυχίες
admin-failures-errors-failures = Σφάλματα/Αποτυχίες
admin-failures-loading-failures = Φόρτωση αποτυχιών…
admin-failures-operational-failures = Λειτουργικές αποτυχίες
admin-failures-no-operational-failures-at-this = Δεν υπάρχουν λειτουργικές αποτυχίες αυτή τη στιγμή.
admin-failures-collection = Συλλογή
admin-failures-dataset = Σύνολο δεδομένων
admin-failures-task-name = Όνομα εργασίας
admin-failures-error-class = Κλάση σφάλματος
admin-failures-operation-kind = Είδος εργασίας
admin-failures-from = Από
admin-failures-to = Έως
admin-failures-no-captured-failures-match-these = Καμία καταγεγραμμένη αποτυχία δεν ταιριάζει με αυτά τα φίλτρα.
admin-failures-signature = Υπογραφή
admin-failures-count = Πλήθος
admin-failures-class = Κλάση
admin-failures-task = Εργασία
admin-failures-last-seen = Τελευταία εμφάνιση
admin-failures-newer = Νεότερα
admin-failures-page = Σελίδα { $current_page_1 }
admin-failures-older = Παλαιότερα
admin-failures-per-page = Ανά σελίδα
admin-failures-loading-instances = Φόρτωση περιπτώσεων…
admin-failures-no-instances-for-this-signature = Δεν υπάρχουν περιπτώσεις για αυτή την υπογραφή.
admin-failures-node = {" "}κόμβος { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Σφάλματα εγγράφων
admin-failures-error-text = Κείμενο σφάλματος
admin-failures-loading-document-errors-u = Φόρτωση σφαλμάτων εγγράφων…
admin-failures-no-document-errors-match-these = Κανένα σφάλμα εγγράφου δεν ταιριάζει με αυτά τα φίλτρα.
admin-failures-errors-by-dataset-and-task = Σφάλματα ανά σύνολο δεδομένων και εργασία
admin-failures-documents = Έγγραφα
admin-failures-show-only-this-dataset-and = Εμφάνιση μόνο αυτού του συνόλου δεδομένων και αυτής της εργασίας
admin-failures-total = Σύνολο
admin-failures-errors = Σφάλματα
admin-failures-document = Έγγραφο
admin-failures-runs = Εκτελέσεις
admin-failures-error = Σφάλμα
admin-failures-dataset-step = Βήμα συνόλου δεδομένων
admin-failures-previous-page = Προηγούμενη σελίδα
admin-failures-page-of-1-error = Σελίδα { $page } από { $pages }, 1 σφάλμα
admin-failures-page-of-errors = Σελίδα { $page } από { $pages }, { $data_total } σφάλματα
admin-failures-next-page = Επόμενη σελίδα
admin-feedback-admin-feedback = Διαχείριση: σχόλια
admin-feedback-feedback = Σχόλια
admin-feedback-search-titles-descriptions-accounts-and = Αναζήτηση τίτλων, περιγραφών, λογαριασμών και διευθύνσεων
admin-feedback-search = Αναζήτηση
admin-feedback-loading-reports-u = Φόρτωση αναφορών…
admin-feedback-1-report-matches = 1 αναφορά ταιριάζει.
admin-feedback-reports-match = { $data_total } αναφορές ταιριάζουν.
admin-feedback-received = Λήψη
admin-feedback-type = Τύπος
admin-feedback-title = Τίτλος
admin-feedback-from = Από
admin-feedback-captures = Καταγραφές
admin-feedback-state = Κατάσταση
admin-feedback-previous-page = Προηγούμενη σελίδα
admin-feedback-page-of = Σελίδα { $page } από { $pages }
admin-feedback-next-page = Επόμενη σελίδα
admin-feedback-image = Εικόνα { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Αναγνωσμένο
admin-feedback-unread = Μη αναγνωσμένο
admin-feedback-archived = Αρχειοθετημένο
admin-feedback-mark-unread = Σήμανση ως μη αναγνωσμένου
admin-feedback-mark-read = Σήμανση ως αναγνωσμένου
admin-feedback-restore = Επαναφορά
admin-feedback-archive = Αρχειοθέτηση
admin-feedback-page = Σελίδα:{" "}
admin-feedback-the-report-has-no-description = Η αναφορά δεν έχει περιγραφή.
admin-feedback-open-the-page-image = Άνοιγμα της εικόνας της σελίδας
admin-feedback-open-the-dom-copy = Άνοιγμα του αντιγράφου DOM
admin-feedback-page-image-of-the-report = Εικόνα σελίδας της αναφοράς
admin-feedback-debug-context-and-browser-log = Πλαίσιο αποσφαλμάτωσης και αρχείο καταγραφής του προγράμματος περιήγησης
admin-feedback-loading-u = Φόρτωση…
admin-group-detail-admin-group = Διαχείριση: ομάδα { $groupname }
admin-group-detail-failed-to-load-group = Η φόρτωση της ομάδας απέτυχε
admin-group-detail-loading = Φόρτωση...
admin-group-detail-group = Ομάδα
admin-group-detail-display-name = Εμφανιζόμενο όνομα
admin-group-detail-display-name-2 = εμφανιζόμενο όνομα
admin-group-detail-save = Αποθήκευση
admin-group-detail-members = Μέλη
admin-group-detail-saving-membership = Αποθήκευση συμμετοχής...
admin-group-detail-username = Όνομα χρήστη
admin-group-detail-origin = Προέλευση
admin-group-detail-group-admin = Διαχειριστής ομάδας
admin-group-detail-uploader = Μεταφορτωτής
admin-group-detail-remove = Αφαίρεση
admin-group-detail-username-to-add = όνομα χρήστη προς προσθήκη
admin-group-detail-add-member = Προσθήκη μέλους
admin-group-detail-collection-access = Πρόσβαση σε συλλογές
admin-group-detail-this-group-has-no-collection = Αυτή η ομάδα δεν έχει δικαιώματα σε συλλογές.
admin-group-detail-revoke = Ανάκληση
admin-group-detail-grant-collection-u = Παραχώρηση συλλογής…
admin-group-detail-grant = Παραχώρηση
admin-group-detail-danger-zone = Επικίνδυνη ζώνη
admin-group-detail-delete-group = Διαγραφή ομάδας
admin-groups-list-admin-groups = Διαχείριση: ομάδες
admin-groups-list-groups = Ομάδες
admin-groups-list-add-group = Προσθήκη ομάδας
admin-groups-list-display-name = εμφανιζόμενο όνομα
admin-groups-list-use-lowercase-letters-digits-underscores = Χρησιμοποιήστε πεζά γράμματα, ψηφία, κάτω παύλες και παύλες στο όνομα. Το όνομα δεν μπορεί να αλλάξει αργότερα.
admin-groups-list-add-group-2 = Προσθήκη ομάδας +
admin-groups-list-group = Ομάδα
admin-groups-list-display-name-2 = Εμφανιζόμενο όνομα
admin-groups-list-members = Μέλη
admin-groups-list-collections = Συλλογές
admin-groups-list-loading = Φόρτωση...
admin-llm-config-admin-llm = Διαχείριση: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Φόρτωση…
admin-llm-config-no-llm-provider-is-configured = Δεν έχει ρυθμιστεί πάροχος LLM. Ορίστε τα LLM_BASE_URL / LLM_MODEL στο hoover4.ini και κάντε νέα ανάπτυξη.
admin-llm-config-providers = Πάροχοι
admin-llm-config-the-refresh-runs-in-the = Η ανανέωση εκτελείται στο παρασκήνιο. Η τρέχουσα λίστα παραμένει ορατή στο μεταξύ.
admin-llm-config-refresh-in-flight-u = {" "}Ανανέωση σε εξέλιξη…
admin-llm-config-provider = Πάροχος
admin-llm-config-models = Μοντέλα
admin-llm-config-freshest = Πιο πρόσφατη
admin-llm-config-status = Κατάσταση
admin-llm-config-refresh-catalog = Ανανέωση καταλόγου
admin-llm-config-agent-turns-board-assessments-and = Γύροι του πράκτορα, αξιολογήσεις ερευνητικών πινάκων και μετατροπές εκθέσεων
admin-llm-config-titles-summaries-and-board-labels = Τίτλοι, περιλήψεις και ετικέτες ερευνητικών πινάκων
admin-llm-config-hoover4-ini-sets-these-models = Το hoover4.ini ορίζει αυτά τα μοντέλα: το quality_model του παρόχου LLM για τους γύρους του πράκτορα, τις αξιολογήσεις ερευνητικών πινάκων και τις μετατροπές εκθέσεων όταν έχει οριστεί, και το μοντέλο του για τα υπόλοιπα.
admin-llm-config-thinking = Thinking
admin-llm-config-the-model-reasons-before-each = Το μοντέλο συλλογίζεται πριν από κάθε κλήση εργαλείου και κάθε απάντηση.
admin-llm-config-catalog = Κατάλογος
admin-llm-config-filter-models-u = Φιλτράρισμα μοντέλων…
admin-llm-config-model = Μοντέλο
admin-llm-config-flags = Σημαίες
admin-llm-config-calls-14d = Κλήσεις 14 ημ.
admin-llm-config-ai-status = Κατάσταση AI
admin-llm-config-shows-the-serving-health = {" "}εμφανίζει την υγεία της λειτουργίας.
admin-llm-reports-reports = Αναφορές
admin-llm-reports-each-report-runs-when-you = Κάθε αναφορά εκτελείται όταν επιλέξετε το κουμπί της.
admin-llm-reports-running-u = Εκτέλεση…
admin-llm-reports-run-report = Εκτέλεση αναφοράς
admin-llm-reports-read-at = Ανάγνωση στις { $read_at }
admin-llm-reports-errors = Σφάλματα
admin-llm-reports-failed-attempts-by-step-and = Αποτυχημένες προσπάθειες ανά βήμα και κλάση σφάλματος, και εκτελέσεις του πράκτορα που απέτυχαν ή τελείωσαν νωρίς, ανά λόγο λήξης.
admin-llm-reports-source = Πηγή
admin-llm-reports-class = Κλάση
admin-llm-reports-no-errors-in-30-days = Κανένα σφάλμα σε 30 ημέρες.
admin-llm-reports-recent-errors = Πρόσφατα σφάλματα
admin-llm-reports-the-newest-100-failed-attempts = Οι 100 νεότερες αποτυχημένες προσπάθειες των 7 ημερών. Ανοίξτε μια γραμμή για να διαβάσετε το σφάλμα της.
admin-llm-reports-time = Ώρα
admin-llm-reports-user = Χρήστης
admin-llm-reports-name = Όνομα
admin-llm-reports-error = Σφάλμα
admin-llm-reports-no-errors-in-7-days = Κανένα σφάλμα σε 7 ημέρες.
admin-llm-reports-show = Εμφάνιση
admin-llm-reports-tool-calls = Κλήσεις εργαλείων
admin-llm-reports-one-row-for-each-tool = Μία γραμμή για κάθε εργαλείο, κατά κλήσεις σε 30 ημέρες. Σφάλμα είναι μια κλήση που απέτυχε.
admin-llm-reports-tool = Εργαλείο
admin-llm-reports-calls-24-h = Κλήσεις 24 ώ
admin-llm-reports-error-24-h = Σφάλματα % 24 ώ
admin-llm-reports-avg-ms-24-h = Μέσο ms 24 ώ
admin-llm-reports-calls-7-d = Κλήσεις 7 ημ.
admin-llm-reports-error-7-d = Σφάλματα % 7 ημ.
admin-llm-reports-avg-ms-7-d = Μέσο ms 7 ημ.
admin-llm-reports-calls-30-d = Κλήσεις 30 ημ.
admin-llm-reports-error-30-d = Σφάλματα % 30 ημ.
admin-llm-reports-avg-ms-30-d = Μέσο ms 30 ημ.
admin-llm-reports-no-tool-calls-in-30 = Καμία κλήση εργαλείου σε 30 ημέρες.
admin-llm-reports-top-users = Κορυφαίοι χρήστες
admin-llm-reports-the-30-users-with-the = Οι 30 χρήστες με τον περισσότερο χρόνο μοντέλου στο παράθυρο.
admin-llm-reports-30-days = 30 ημέρες
admin-llm-reports-7-days = 7 ημέρες
admin-llm-reports-24-hours = 24 ώρες
admin-llm-reports-tool-time = Χρόνος εργαλείων
admin-llm-reports-model-calls = Κλήσεις μοντέλου
admin-llm-reports-model-time = Χρόνος μοντέλου
admin-llm-reports-tokens-in = Token εισόδου
admin-llm-reports-tokens-out = Token εξόδου
admin-llm-reports-no-agent-use-in-the = Καμία χρήση του πράκτορα στο παράθυρο.
admin-llm-reports-system-one-checks = Έλεγχοι System one
admin-llm-reports-requests-are-grouped-by-hook = Τα αιτήματα ομαδοποιούνται ανά hook και κανόνα. Οι καθυστερήσεις είναι σε χιλιοστά του δευτερολέπτου. Τα ποσοστά χρησιμοποιούν αιτήματα των τελευταίων 30 ημερών.
admin-llm-reports-counts = Πλήθη
admin-llm-reports-recent-failures = Πρόσφατες αποτυχίες
admin-llm-reports-select-run-report-to-read = Επιλέξτε Εκτέλεση αναφοράς για να διαβάσετε τα στατιστικά.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Κανόνας
admin-llm-reports-outcome = Αποτέλεσμα
admin-llm-reports-questions = Ερωτήσεις
admin-llm-reports-median-ms = Διάμεσος ms
admin-llm-reports-95th-percentile-ms = 95ο εκατοστημόριο ms
admin-llm-reports-error-2 = Σφάλματα %
admin-llm-reports-positive = Θετικά %
admin-llm-reports-actions = Ενέργειες
admin-metrics-admin-metrics = Διαχείριση: μετρικές
admin-metrics-metrics = Μετρικές
admin-metrics-the-last-24-hours = Οι τελευταίες 24 ώρες.
admin-metrics-loading-u = Φόρτωση…
admin-metrics-manticore-load-now = Φορτίο Manticore (τώρα)
admin-metrics-ram-is-the-memory-of = Η RAM είναι η μνήμη των πινάκων. Το φορτίο νημάτων αφορά το τελευταίο 1, 5 και 15 λεπτό.
admin-metrics-manticore-status-could-not-be = Η κατάσταση του Manticore δεν μπόρεσε να διαβαστεί: { $error }
admin-metrics-thread-load-1-5-15 = Φορτίο νημάτων (1, 5, 15 λεπτά)
admin-metrics-primary-thread-load-1-5 = Φορτίο κύριων νημάτων (1, 5, 15 λεπτά)
admin-metrics-secondary-thread-load-1-5 = Φορτίο δευτερευόντων νημάτων (1, 5, 15 λεπτά)
admin-metrics-worker-threads-busy-total = Νήματα εργατών σε χρήση / σύνολο
admin-metrics-work-queue = Ουρά εργασιών
admin-metrics-ram-held-by-tables = RAM που κατέχουν οι πίνακες
admin-metrics-disk-used-by-tables = Δίσκος που χρησιμοποιούν οι πίνακες
admin-metrics-tables-merging = Πίνακες σε συγχώνευση
admin-metrics-tables-read = Πίνακες που διαβάστηκαν
admin-metrics-read-at = Ανάγνωση στις
admin-metrics-largest-tables-by-ram = Μεγαλύτεροι πίνακες κατά RAM
admin-metrics-table = Πίνακας
admin-metrics-ram = RAM
admin-metrics-disk = Δίσκος
admin-metrics-disk-chunks = Τμήματα δίσκου
admin-metrics-merging = Συγχώνευση
admin-metrics-usage-last-24-h = Χρήση (τελευταίες 24 ώ)
admin-metrics-events-by-type = Συμβάντα ανά τύπο
admin-metrics-event = Συμβάν
admin-metrics-count = Πλήθος
admin-metrics-events-per-hour = Συμβάντα ανά ώρα
admin-metrics-no-events-recorded-yet = Δεν έχουν καταγραφεί ακόμη συμβάντα.
admin-metrics-busiest-users = Πιο δραστήριοι χρήστες
admin-metrics-user = Χρήστης
admin-metrics-events = Συμβάντα
admin-metrics-events-2 = { $point_bucket }: { $point_count } συμβάντα
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = Κλήσεις API (τελευταίες 24 ώ)
admin-metrics-no-api-calls-recorded-yet = Δεν έχουν καταγραφεί ακόμη κλήσεις API.
admin-metrics-function = Συνάρτηση
admin-metrics-calls = Κλήσεις
admin-metrics-errors = Σφάλματα
admin-metrics-error-rate = Ποσοστό σφαλμάτων
admin-metrics-bytes-in = Byte εισόδου
admin-metrics-bytes-out = Byte εξόδου
admin-operation-detail-admin-operation = Διαχείριση: εργασία { $op_id }
admin-operation-detail-loading-operation = Φόρτωση εργασίας…
admin-operation-detail-back-to-operations = Πίσω στις εργασίες
admin-operation-detail-operation = Εργασία
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · στην ουρά από { $row_started_at }
admin-operation-detail-not-started = δεν ξεκίνησε
admin-operation-detail-re-run-counts-are-not = Τα πλήθη επανεκτέλεσης δεν είναι διαθέσιμα.
admin-operation-detail-failed-document-s-task-failure = { $documents } έγγραφα που απέτυχαν, { $row_failed_tasks_unwrap_or_0 } αποτυχίες εργασιών
admin-operation-detail-failures-were-not-counted = Οι αποτυχίες δεν μετρήθηκαν.
admin-operation-detail-open-captured-failure-tree = Άνοιγμα καταγεγραμμένου δέντρου αποτυχίας
admin-operation-detail-open-in-temporal = Άνοιγμα στο Temporal
admin-operation-detail-plans = Σχέδια
admin-operation-detail-plan-s-page = { $data_plans_total } σχέδια, σελίδα { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Δεν καταγράφηκαν σχέδια για αυτή την εργασία.
admin-operation-detail-dataset = Σύνολο δεδομένων
admin-operation-detail-plan-hash = Κατακερματισμός σχεδίου
admin-operation-detail-source = Πηγή
admin-operation-detail-finished = Ολοκληρώθηκε
admin-operation-detail-previous = Προηγούμενη
admin-operation-detail-next = Επόμενη
admin-operation-detail-error-events = Συμβάντα σφάλματος
admin-operation-detail-error-event-s-page = { $data_events_total } συμβάντα σφάλματος, σελίδα { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Δεν καταγράφηκαν συμβάντα σφάλματος για αυτή την εργασία.
admin-operation-detail-time = Ώρα
admin-operation-detail-hash = Κατακερματισμός
admin-operation-detail-task = Εργασία
admin-operation-detail-event = Συμβάν
admin-operation-detail-error-excerpt = Απόσπασμα σφάλματος
admin-operations-admin-operations = Διαχείριση: εργασίες
admin-operations-operations = Εργασίες
admin-operations-loading-operations = Φόρτωση εργασιών…
admin-operations-filters = Φίλτρα
admin-operations-state = Κατάσταση
admin-operations-any-state = Οποιαδήποτε κατάσταση
admin-operations-collection = Συλλογή
admin-operations-all-collections = Όλες οι συλλογές
admin-operations-choose-a-collection-to-see = Επιλέξτε μια συλλογή για να δείτε τα ποσοστά σφαλμάτων ανά εργασία.
admin-operations-operations-newest-first = Εργασίες, πρώτες οι νεότερες
admin-operations-newer = Νεότερα
admin-operations-page = Σελίδα { $current_page_1 }
admin-operations-older = Παλαιότερα
admin-operations-failure-rate-by-task-type = Ποσοστό αποτυχιών ανά τύπο εργασίας ({ $collectionname })
admin-operations-one-row-per-activity-execution = Μία γραμμή ανά εκτέλεση δραστηριότητας, μαζί με τις επαναλήψεις. Ένα ποσοστό πάνω από{" "}
admin-operations-is-marked = {" "}επισημαίνεται.
admin-operations-no-task-executions-recorded-for = Δεν έχουν καταγραφεί ακόμη εκτελέσεις εργασιών για αυτή τη συλλογή.
admin-operations-task = Εργασία
admin-operations-error-rate = Ποσοστό σφαλμάτων
admin-operations-failed-total-executions = Εκτελέσεις που απέτυχαν / σύνολο
admin-operations-documents-affected = Έγγραφα που επηρεάστηκαν
admin-operations-above-the-line = πάνω από το όριο
admin-operations-no-operations-recorded-for-this = Δεν έχουν καταγραφεί εργασίες για αυτό το φίλτρο.
admin-operations-kind = Είδος
admin-operations-target = Στόχος
admin-operations-workflow = Ροή εργασίας
admin-operations-queued-at = Στην ουρά από
admin-operations-started = Έναρξη
admin-operations-duration = Διάρκεια
admin-operations-progress = Πρόοδος
admin-operations-eta = Εκτίμηση ολοκλήρωσης
admin-operations-outcome = Αποτέλεσμα
admin-operations-destructive = Καταστροφική
admin-operations-repeated-run = Επαναλαμβανόμενη εκτέλεση
admin-operations-no-estimate-yet = δεν υπάρχει ακόμη εκτίμηση
admin-operations-cancel = Ακύρωση
admin-operations-type-to-confirm = πληκτρολογήστε { $target } για επιβεβαίωση
admin-operations-re-run = Επανεκτέλεση
admin-operations-waiting-for-a-free-slot = αναμονή για ελεύθερη θέση ή ελεύθερο στόχο
admin-operations-counting-work = καταμέτρηση εργασίας…
admin-operations-open-captured-tree = Άνοιγμα καταγεγραμμένου δέντρου
admin-operations-no-captured-tree = κανένα καταγεγραμμένο δέντρο
admin-operations-no-failed-documents = κανένα έγγραφο δεν απέτυχε
admin-operations-document-s-failed = { $n } έγγραφα απέτυχαν
admin-operations-task-failure-s = { $t } αποτυχίες εργασιών
admin-operations-failures-not-counted = οι αποτυχίες δεν μετρήθηκαν
admin-operations-the-newest-ten-operations-of = Οι δέκα νεότερες εργασίες αυτής της συλλογής.{" "}
admin-operations-all-operations = Όλες οι εργασίες
admin-settings-admin-settings = Διαχείριση: ρυθμίσεις
admin-settings-server-settings = Ρυθμίσεις διακομιστή
admin-settings-key = Κλειδί
admin-settings-value = Τιμή
admin-settings-description = Περιγραφή
admin-settings-save = Αποθήκευση
admin-settings-loading = Φόρτωση...
admin-settings-deployment-configuration-read-only = Ρύθμιση ανάπτυξης (μόνο για ανάγνωση)
admin-settings-not-set = (δεν έχει οριστεί)
admin-user-detail-admin-user = Διαχείριση: χρήστης { $username }
admin-user-detail-failed-to-load-user = Η φόρτωση του χρήστη απέτυχε
admin-user-detail-loading = Φόρτωση...
admin-user-detail-user = Χρήστης
admin-user-detail-the-next-login-replaces-the = Η επόμενη σύνδεση αντικαθιστά το πλήρες όνομα, το email και την κατάσταση υπερχρήστη ενός χρήστη από τον διακομιστή μεσολάβησης σύνδεσης.
admin-user-detail-llm-usage-u = Χρήση LLM →
admin-user-detail-full-name = Πλήρες όνομα
admin-user-detail-full-name-2 = πλήρες όνομα
admin-user-detail-email = Email
admin-user-detail-superuser = Υπερχρήστης
admin-user-detail-save = Αποθήκευση
admin-user-detail-groups = Ομάδες
admin-user-detail-saving-membership = Αποθήκευση συμμετοχής...
admin-user-detail-group = Ομάδα
admin-user-detail-origin = Προέλευση
admin-user-detail-group-admin = Διαχειριστής ομάδας
admin-user-detail-uploader = Μεταφορτωτής
admin-user-detail-remove = Αφαίρεση
admin-user-detail-add-to-group-u = Προσθήκη σε ομάδα…
admin-user-detail-add = Προσθήκη
admin-user-detail-danger-zone = Επικίνδυνη ζώνη
admin-user-detail-delete-user = Διαγραφή χρήστη
admin-user-llm-admin-llm-use-by = Διαχείριση: χρήση LLM από τον χρήστη { $username }
admin-user-llm-u-back-to-user = ← Πίσω στον χρήστη
admin-user-llm-loading-u = Φόρτωση…
admin-user-llm-totals-all-time = Σύνολα (συνολικά)
admin-user-llm-chat-sessions = Συνεδρίες συνομιλίας
admin-user-llm-messages = Μηνύματα
admin-user-llm-tool-calls = Κλήσεις εργαλείων
admin-user-llm-model-and-tool-time = Χρόνος μοντέλου και εργαλείων
admin-user-llm-model-and-tool-time-of = χρόνος μοντέλου και εργαλείων των βημάτων του πράκτορα αυτού του χρήστη. Οι παράλληλες κλήσεις εργαλείων μετρούν ολόκληρες
admin-user-llm-rate-limit-usage-current-windows = Χρήση ορίων ρυθμού (τρέχοντα παράθυρα)
admin-user-llm-in-process-counters-of-the = Μετρητές εντός της διεργασίας του κοντέινερ του ιστότοπου που εκτελείται. Όριο συνομιλίας { $metrics_chat_per_minute }/λεπτό, όριο API { $metrics_api_per_minute }/λεπτό, με φθίνοντα διατηρούμενο ρυθμό στα μεγαλύτερα παράθυρα.
admin-user-llm-chat-messages = Μηνύματα συνομιλίας
admin-user-llm-api-calls = Κλήσεις API
admin-user-llm-window = Παράθυρο
admin-user-llm-used = Χρησιμοποιήθηκε
admin-user-llm-budget = Όριο
admin-user-llm-no-chat-sessions = Δεν υπάρχουν συνεδρίες συνομιλίας.
admin-user-llm-title = Τίτλος
admin-user-llm-created = Δημιουργήθηκε
admin-users-list-admin-users = Διαχείριση: χρήστες
admin-users-list-users = Χρήστες
admin-users-list-search-users = Αναζήτηση χρηστών
admin-users-list-username = Όνομα χρήστη
admin-users-list-full-name = Πλήρες όνομα
admin-users-list-email-address = Διεύθυνση email
admin-users-list-superuser = Υπερχρήστης
admin-users-list-groups = Ομάδες
admin-users-list-created = Δημιουργήθηκε
admin-users-list-last-login = Τελευταία σύνδεση
admin-users-list-loading = Φόρτωση...
dataset-create-panel-put-the-documents-in-a = Τοποθετήστε τα έγγραφα σε έναν φάκελο εκεί και φορτώστε ξανά αυτή τη σελίδα.
dataset-create-panel-the-name-cannot-start-with = Το όνομα δεν μπορεί να αρχίζει με τελεία ή να περιέχει κάθετο.
dataset-create-panel-and-a-dash-a-space = και μια παύλα, ένα διάστημα ή μια τελεία γίνεται κάτω παύλα. Το όνομα δεν μπορεί να αλλάξει αργότερα.
dataset-create-panel-the-form-starts-with-the = Η φόρμα ξεκινά με τις προεπιλογές της συλλογής. Ένα σύνολο δεδομένων που δημιουργείται με τις προεπιλογές ακολουθεί τις μελλοντικές αλλαγές τους,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Η Εφαρμογή αποθηκεύει τις γλώσσες και η ενημέρωση OCR αυτού του συνόλου δεδομένων ξεκινά τότε από μόνη της.
dataset-ocr-panel-the-list-comes-from-the = Η λίστα προέρχεται από την εικόνα που εκτελείται και όχι από τη ρύθμιση.
live-chats-panel-off = ανενεργό
processing-updates-panel-the-waiting-steps-change-each = Τα βήματα σε αναμονή αλλάζουν { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), με κάθε αρχείο να μετριέται μία φορά, σε { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = και μια παύλα, ένα διάστημα ή μια τελεία γίνεται κάτω παύλα. Το όνομα δεν μπορεί να αλλάξει αργότερα.
admin-llm-config-fresh = πρόσφατο
admin-llm-config-tools = εργαλεία{" "}
admin-llm-config-vision = όραση{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-and-a-dataset-created-with = και ένα σύνολο δεδομένων που δημιουργείται με άλλες τιμές κρατά τις δικές του. Μια αλλαγή στη σελίδα του συνόλου δεδομένων εκτελεί ξανά το OCR.
dataset-create-panel-read-only = { $option_name } (μόνο για ανάγνωση)
live-chats-panel-on = ενεργό
processing-updates-panel-up-to-date-select-it = Ενημερωμένο. Επιλέξτε το για να εκτελεστεί ξανά.
admin-ai-status-yes = ναι
admin-ai-status-no-2 = όχι
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } σφάλματα
admin-collection-processing-done = ολοκληρώθηκε
admin-collection-processing-failed-2 = { $stage_failed_documents } απέτυχαν
admin-collection-processing-left = απομένουν
admin-collection-processing-dataset-level = επίπεδο συνόλου δεδομένων
admin-collections-list-groups = { $c_group_count } ομάδες
admin-failures-operation-s = { $group_operation_count } εργασίες
admin-groups-list-groupname = όνομα ομάδας
admin-llm-config-stale = παλιό
admin-llm-config-thinking-is-on = Το Thinking είναι ενεργό
admin-llm-config-thinking-is-off = Το Thinking είναι ανενεργό
admin-llm-config-shown = { $models_len } εμφανίζονται
admin-llm-config-reasoning = συλλογισμός
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } από { $load_table_count }
admin-metrics-yes = ναι
admin-metrics-no = όχι
admin-metrics-max = μέγ.
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = ξεκίνησε { $run_started_at }
admin-operation-detail-yes = ναι
admin-operation-detail-no = όχι
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = email
admin-user-llm-untitled = (χωρίς τίτλο)
admin-dataset-ocr-panel-models-not-in-image = Τα μοντέλα για { $languages } δεν υπάρχουν στην εικόνα. Η υπηρεσία τα κατεβάζει στην πρώτη χρήση, κάτι που απαιτεί πρόσβαση στο διαδίκτυο.
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } σελίδες
admin-processing-updates-panel-prerequisites-waiting = Η συλλογή χρειάζεται πρώτα ενημέρωση: { $steps }. Τα βήματα που γράφουν στο ευρετήριο αναζήτησης περιμένουν γι' αυτήν.
admin-operations-no-task-type-failing = Κανένας τύπος εργασίας δεν αποτυγχάνει πάνω από { $threshold }%.
admin-operations-task-types-failing = { $count } τύποι εργασιών αποτυγχάνουν πάνω από { $threshold }%.
processing-updates-panel-collection-updates = Ενημερώσεις συλλογής
admin-collections-list-some-datasets-are-not-counted = Ορισμένα σύνολα δεδομένων δεν έχουν μετρηθεί ακόμη.
admin-failures-hide = Απόκρυψη
admin-failures-show = Εμφάνιση
admin-settings-web-session-lifetime-in-seconds = Διάρκεια ζωής της συνεδρίας ιστού σε δευτερόλεπτα (προεπιλογή: 604800 = 1 εβδομάδα)
admin-settings-turns-every-new-chat-turn = Απενεργοποιεί κάθε νέο γύρο συνομιλίας όταν είναι false (προεπιλογή: true). Ένας γύρος σε εξέλιξη ολοκληρώνεται. Ισχύει από την επόμενη αποστολή, χωρίς νέα ανάπτυξη.
admin-settings-written-by-main-py-probe = Γράφεται από το `main.py probe-embeddings` και είναι αυτό που εξυπηρετεί ΠΡΑΓΜΑΤΙΚΑ το endpoint. Η χειροκίνητη επεξεργασία του δεν αλλάζει τον διακομιστή.
admin-settings-the-folder-whose-subfolders-the = Ο φάκελος του οποίου τους υποφακέλους εμφανίζει η φόρμα συνόλου δεδομένων. Η αλλαγή του απαιτεί νέα ανάπτυξη.
admin-settings-from-hoover4-ini-changing-it = Από το hoover4.ini. Η αλλαγή του απαιτεί νέα ανάπτυξη.
admin-feedback-bug = Σφάλμα
admin-operations-state-name = { $state ->
        [pending] σε εκκρεμότητα
        [queued] στην ουρά
        [running] σε εκτέλεση
        [finished] ολοκληρώθηκε
        [errored] με σφάλμα
        [cancelled] ακυρώθηκε
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Δέντρο αποτυχίας του { $op_id }
admin-failure-detail-showing-of-characters = εμφανίζονται { $node_stack_trace_chars_count } από { $node_stack_trace_original_len } χαρακτήρες
admin-operations-operation = Εργασία { $state }.
admin-operations-dispatched = Στάλθηκε το { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } γραμμές
admin-operations-plans = { $row_progress_done } / { $row_progress_total } σχέδια
admin-group-detail-group-2 = Ομάδα { $groupname }
admin-settings-the-setting-was-saved-successfully = Η ρύθμιση «{ $k }» αποθηκεύτηκε με επιτυχία.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Η ομάδα «{ $g }» προστέθηκε με επιτυχία.
admin-user-detail-user-2 = Χρήστης { $username }
admin-dataset-detail-dataset = Σύνολο δεδομένων { $dataset_id }
admin-dataset-detail-collections = Συλλογές › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } από { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Η ρύθμιση μεταφόρτωσης δεν μπόρεσε να διαβαστεί: { $err }
admin-dataset-detail-operation-started = Η εργασία ξεκίνησε: { $run_id }
admin-collection-detail-collection = Συλλογή { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Η ρύθμιση διανυσμάτων δεν μπόρεσε να διαβαστεί: { $err }
admin-collection-processing-processing-of = Επεξεργασία του { $collection_id }
admin-collection-processing-collections = Συλλογές › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } εκτελέσεις
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = στις { $at }
admin-collection-processing-over-the-last-s = τα τελευταία { $live_window_seconds } δ
admin-collection-processing-retry-started-run = Η επανάληψη ξεκίνησε (εκτέλεση { $run }).
admin-collection-processing-document-retry-started-run = Η επανάληψη του εγγράφου ξεκίνησε (εκτέλεση { $run }).
admin-operation-detail-operation-2 = Εργασία { $op_id }
admin-user-llm-llm-usage-of = Χρήση LLM από τον χρήστη { $username }
admin-user-llm-users = Χρήστες › { $username }
processing-updates-panel-the-processing-updates-could-not = Οι ενημερώσεις επεξεργασίας δεν μπόρεσαν να διαβαστούν: { $e }
processing-updates-panel-update-started = Η ενημέρωση ξεκίνησε: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } από { $operation_progress_total } σχέδια
dataset-ocr-panel-adding = προσθήκη { $added }
dataset-ocr-panel-removing = αφαίρεση { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } σχέδια άνοιξαν ξανά
dataset-create-panel-saved-as-this-collection-s-2 = Αποθηκεύτηκε ως προεπιλογές αυτής της συλλογής. Αυτά τα σύνολα δεδομένων τις κληρονομούν και οι ενημερώσεις OCR τους ξεκινούν μία τη φορά: { $changed_join }. Τα σύνολα δεδομένων με δικές τους γλώσσες τις κρατούν.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] φάκελο
       *[other] φακέλους
    }
    [tables] { $count ->
        [one] πίνακα
       *[other] πίνακες
    }
   *[files] { $count ->
        [one] αρχείο
       *[other] αρχεία
    }
}
processing-updates-step-runs = { $count ->
    [one] εκτέλεση βήματος
   *[other] εκτελέσεις βήματος
}
processing-update-search_schema-title = Σχήμα ευρετηρίου αναζήτησης
processing-update-search_schema-explanation = { $files ->
    [one] { $count } πίνακας αναζήτησης της συλλογής δεν έχει μια στήλη που χρειάζεται το ευρετήριο αναζήτησης.
   *[other] { $count } πίνακες αναζήτησης της συλλογής δεν έχουν μια στήλη που χρειάζεται το ευρετήριο αναζήτησης.
} Η στήλη προστίθεται σε κάθε πίνακα. Η αναζήτηση συνεχίζει να λειτουργεί.
processing-update-search_schema-runs = Πίνακες ευρετηρίου αναζήτησης
processing-update-unfinished-title = Ημιτελής επεξεργασία
processing-update-unfinished-explanation = { $files ->
    [one] { $count } αρχείο δεν έχει επεξεργαστεί μέχρι το τέλος.
   *[other] { $count } αρχεία δεν έχουν επεξεργαστεί μέχρι το τέλος.
} Αυτό περιλαμβάνει αρχεία χωρίς σχέδιο επεξεργασίας, για παράδειγμα μετά από διακοπή της εισαγωγής. Η επεξεργασία τους ολοκληρώνεται.
processing-update-unfinished-runs = Όλα τα στάδια επεξεργασίας για αυτά τα αρχεία
processing-update-failed_files-title = Αρχεία που απέτυχαν
processing-update-failed_files-explanation = { $files ->
    [one] { $count } αρχείο έχει σφάλμα επεξεργασίας.
   *[other] { $count } αρχεία έχουν σφάλμα επεξεργασίας.
} Τα στάδια που απέτυχαν εκτελούνται ξανά για αυτά. Η αυτόματη εκτέλεση επαναλαμβάνει ένα αρχείο μία φορά για κάθε νέα έκδοση του σταδίου που απέτυχε.
processing-update-failed_files-runs = Τα στάδια που απέτυχαν, έπειτα εξαγωγή οντοτήτων, embedding και ευρετηρίαση
processing-update-virus_scan-title = Έλεγχος για ιούς
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } αρχείο δεν έχει απόφαση antivirus.
   *[other] { $count } αρχεία δεν έχουν απόφαση antivirus.
} Ελέγχονται. Ένα αρχείο που ο σαρωτής βρίσκει μολυσμένο επισημαίνεται στην αναζήτηση και οι λήψεις του πρωτοτύπου και του PDF με δυνατότητα αναζήτησης απορρίπτονται.
processing-update-virus_scan-runs = Έλεγχος antivirus, έπειτα το χαρακτηριστικό αναζήτησης των μολυσμένων αρχείων
processing-update-tables-title = Πίνακες
processing-update-tables-explanation = { $files ->
    [one] { $count } αρχείο έχει παλιότερη ανάγνωση πίνακα ή ελλιπή εξαρτώμενα αποτελέσματα. Τα αποθηκευμένα αποτελέσματα ενημερώνονται.
    *[other] Αρχεία με παλιότερες αναγνώσεις πινάκων ή ελλιπή εξαρτώμενα αποτελέσματα: { $count }. Τα αποθηκευμένα αποτελέσματα ενημερώνονται.
    }

processing-update-tables-runs = Ανάγνωση πινάκων, οντότητες, σήματα, ενσωματώσεις και οι δύο δείκτες
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Αρχεία που χρειάζονται αυτόματο OCR: { $count }. Οι ανιχνευμένες σελίδες επιλέγουν εγκατεστημένα μοντέλα. Τα πλήρη νέα αποτελέσματα αφαιρούν προηγούμενες παραλλαγές.
processing-update-ocr-runs = OCR και PDF με δυνατότητα αναζήτησης, έπειτα εξαγωγή οντοτήτων, embedding και ευρετηρίαση του νέου κειμένου
processing-update-ocr_detection-title = Εντοπισμός OCR
processing-update-ocr_detection-explanation = Αρχεία χωρίς τρέχουσα ανίχνευση κειμένου, γραφής ή γλώσσας: { $count }. Κάθε επιλέξιμη εικόνα και σελίδα PDF εξετάζεται σε περιορισμένες παρτίδες.
processing-update-ocr_detection-runs = Εντοπισμός, έπειτα τα χαρακτηριστικά αναζήτησης αυτών των αρχείων
processing-update-pdf_text-title = Κείμενο αναζητήσιμων PDF
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } αρχείο έχει αναζητήσιμα PDF με προηγούμενο επίπεδο κειμένου.
   *[other] { $count } αρχεία έχουν αναζητήσιμα PDF με προηγούμενο επίπεδο κειμένου.
} Εκείνο το επίπεδο αντέγραφε κάθε γράμμα εκτός των δυτικοευρωπαϊκών αλφαβήτων ως μαύρο τετράγωνο. Τα PDF γλωσσών με μόνο δυτικοευρωπαϊκά γράμματα παραμένουν. Τα άλλα PDF διαβάζονται και τα τμήματα με μαύρα τετράγωνα δημιουργούνται ξανά. Ένα PDF εικόνας χρησιμοποιεί τις αποθηκευμένες λέξεις OCR. Μια σελίδα PDF λαμβάνει νέο αίτημα OCR.
processing-update-pdf_text-runs = Τμήματα αναζητήσιμων PDF, έπειτα η ευρετηρίαση του κειμένου OCR των PDF που δημιουργήθηκαν ξανά
processing-update-vectors-title = Διανύσματα
processing-update-vectors-explanation = { $files ->
    [one] { $count } αρχείο με κείμενο δεν έχει διανύσματα του μοντέλου embedding που εξυπηρετεί η εγκατάσταση.
   *[other] { $count } αρχεία με κείμενο δεν έχουν διανύσματα του μοντέλου embedding που εξυπηρετεί η εγκατάσταση.
} Τα διανύσματά τους υπολογίζονται και ευρετηριάζονται.
processing-update-vectors-runs = Embedding και ευρετηρίαση διανυσμάτων
processing-update-folder_counts-title = Πλήθη φακέλων
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } φάκελος δεν έχει πλήθος αρχείων ή μέγεθος, ή έχει τιμές παλαιότερης έκδοσης.
   *[other] { $count } φάκελοι δεν έχουν πλήθος αρχείων ή μέγεθος, ή έχουν τιμές παλαιότερης έκδοσης.
} Τα πλήθη υπολογίζονται ξανά.
processing-update-folder_counts-runs = Δέντρο φακέλων
admin-uploads-badge = Μεταφορτώσεις
admin-uploads-badge-title = Δέχεται μεταφορτώσεις

processing-update-archive_members-title = Μέλη αρχείων

processing-update-archive_members-explanation = { $files ->
    [one] { $count } διαιρεμένο αρχείο χρειάζεται τρέχουσα λίστα μελών. Τα μέλη και τα αποτελέσματα αναζήτησης ενημερώνονται.
    *[other] Διαιρεμένα αρχεία που χρειάζονται τρέχουσες λίστες μελών: { $count }. Τα μέλη και τα αποτελέσματα αναζήτησης ενημερώνονται.
    }

processing-update-archive_members-runs = Εξαγωγή αρχείων, συμφωνία μελών και εξαρτώμενη επεξεργασία

processing-update-image_previews-title = Προεπισκοπήσεις εικόνων

processing-update-image_previews-explanation = { $files ->
    [one] { $count } ασυνήθιστη εικόνα δεν έχει προεπισκόπηση. Η προεπισκόπηση δημιουργείται ξανά.
    *[other] Ασυνήθιστες εικόνες χωρίς προεπισκόπηση: { $count }. Οι προεπισκοπήσεις δημιουργούνται ξανά.
    }

processing-update-image_previews-runs = Δημιουργία και επαλήθευση προεπισκοπήσεων εικόνων

processing-update-search_terms-title = Όροι αναζήτησης

processing-update-search_terms-explanation = { $files ->
    [one] { $count } πίνακας αναζήτησης χρειάζεται τρέχοντες όρους φίλτρων. Οι όροι γλώσσας, OCR, γραφής και κόκκινων σημαιών γίνονται αναζητήσιμοι.
    *[other] Πίνακες αναζήτησης που χρειάζονται τρέχοντες όρους φίλτρων: { $count }. Οι όροι γλώσσας, OCR, γραφής και κόκκινων σημαιών γίνονται αναζητήσιμοι.
    }

processing-update-search_terms-runs = Ευρετηρίαση και επαλήθευση όρων φίλτρων

automatic-ocr-title = Αυτόματο OCR
automatic-ocr-refresh = Ανανέωση κατάστασης
automatic-ocr-coverage = Κάλυψη σελίδων
automatic-ocr-pages = Σελίδες
automatic-ocr-models = Μοντέλα OCR
automatic-ocr-reason = Αιτία
automatic-ocr-truncated = Η λίστα διαγνωστικών είναι ελλιπής.
automatic-ocr-presence = Έχει δημοσιευμένο κείμενο OCR
automatic-ocr-policy = Το OCR επιλέγει εγκατεστημένα μοντέλα από τη γραφή και τη γλώσσα κάθε επιλέξιμης σελίδας. Πρώτα εκτελείται Tesseract και μετά EasyOCR για ακάλυπτες γραφές.
automatic-ocr-unknown = Δεν έχει καταγραφεί τρέχουσα δημοσίευση. Η έλλειψη ανίχνευσης και η αποτυχία επεξεργασίας δεν αποδεικνύουν απουσία.
automatic-ocr-retry = Χρησιμοποιήστε ενημερώσεις επεξεργασίας για επανάληψη ελλιπούς ή αποτυχημένης εργασίας μετά τη διόρθωση. Η μη υποστηριζόμενη κάλυψη απαιτεί συμβατά εγκατεστημένα μοντέλα.
automatic-ocr-presence-help = Το φίλτρο βρίσκει μόνο επαληθευμένο δημοσιευμένο κείμενο OCR. Η ανίχνευση και οι απόπειρες επεξεργασίας δεν αποδεικνύουν δημοσίευση.
automatic-ocr-state = { $state ->
    [candidate] Σε αναμονή
    [planned] Προγραμματισμένο
    [failed] Αποτυχία
    [incomplete] Ελλιπές
    [unsupported] Δεν υποστηρίζεται
    [published] Δημοσιευμένο
    [applied] Επαληθευμένο
    [ready] Εντοπίστηκε κείμενο
    [no_text] Δεν εντοπίστηκε κείμενο
    *[other] { $state }
    }

processing-update-entities-title = Ονομαστικές οντότητες
processing-update-entities-explanation = Αρχεία που χρειάζονται τρέχουσα εξαγωγή οντοτήτων ή αναζητήσιμα αποτελέσματα: { $count }. Τα προηγούμενα επιτυχή αποτελέσματα αντικαθίστανται μετά την εξαγωγή συμπερασμάτων.
processing-update-entities-runs = Εξαγωγή ονομαστικών οντοτήτων, ιδιότητες κειμένου και αναζητήσιμοι όροι οντοτήτων

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Η γραφή δεν αναγνωρίστηκε
    [tesseract_capabilities_unavailable] Μη διαθέσιμη κάλυψη Tesseract
    [detected_language] Το μοντέλο αντιστοιχεί στην ανιχνευμένη γλώσσα
    [unknown_language_script_coverage] Άγνωστη γλώσσα. Επιλέχθηκε μοντέλο γραφής.
    [language_script_mismatch_script_coverage] Η γλώσσα και η γραφή διαφέρουν. Επιλέχθηκε μοντέλο γραφής.
    [language_model_unavailable_script_coverage] Μη διαθέσιμο μοντέλο γλώσσας. Επιλέχθηκε μοντέλο γραφής.
    [easyocr_capabilities_unavailable] Μη διαθέσιμη κάλυψη EasyOCR
    [tesseract_script_unavailable] Το Tesseract δεν καλύπτει τη γραφή. Επιλέχθηκε EasyOCR.
    [script_coverage_unavailable] Κανένα εγκατεστημένο μοντέλο δεν καλύπτει αυτή τη γραφή.
    *[other] { $reason }
    }

processing-updates-check-requested = Η διαδικασία υπολογίζει τις ενημερώσεις. Οι αριθμοί αλλάζουν όταν ολοκληρωθεί ο υπολογισμός.
