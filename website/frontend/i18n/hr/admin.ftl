# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Potreban je pristup administraciji
admin-guard-signed-in-as = Prijavljeni ste kao { $u_username }.
admin-guard-ask-an-administrator-for-access = Zatražite od administratora pristup ovom odjeljku.
admin-shell-dashboard = Nadzorna ploča
admin-shell-collections = Zbirke
admin-shell-operations = Operacije
admin-shell-errors-failures = Pogreške/neuspjesi
admin-shell-feedback = Povratne informacije
admin-shell-users = Korisnici
admin-shell-groups = Grupe
admin-shell-settings = Postavke
admin-shell-llm = LLM
admin-shell-ai-status = AI status
admin-shell-metrics = Metrike
admin-shell-administration = Administracija
dataset-create-panel-add-a-dataset = Dodaj skup podataka
dataset-create-panel-the-dataset-mounts-could-not = Točke montiranja skupova podataka nije moguće pročitati, pa nema što odabrati: { $err }
dataset-create-panel-loading-the-dataset-mounts = Učitavanje točaka montiranja skupova podataka.
dataset-create-panel-no-dataset-mount-is-configured = Nije konfigurirana nijedna točka montiranja skupa podataka.
dataset-create-panel-the-mount-folder-could-not = Mapu točke montiranja nije moguće pročitati, pa nema što odabrati: { $err }
dataset-create-panel-no-subfolders-were-found-in = U ovoj točki montiranja nisu pronađene podmape.{" "}
dataset-create-panel-folder = Mapa
dataset-create-panel-select-a-folder = Odaberi mapu
dataset-create-panel-new-folder = Nova mapa
dataset-create-panel-entries-already-a-dataset = { $option_name } (unosa: { $option_entry_count }), već je skup podataka
dataset-create-panel-entries = { $option_name } (unosa: { $option_entry_count })
dataset-create-panel-the-server-creates-this-folder = Poslužitelj stvara ovu mapu u točki montiranja kad stvorite skup podataka.{" "}
dataset-create-panel-the-list-shows-the-direct = Popis prikazuje izravne podmape točke montiranja.
dataset-create-panel-dataset-name = Naziv skupa podataka
dataset-create-panel-a-name-has-lowercase-letters = Naziv sadrži mala slova, znamenke i podcrte. Velika slova postaju mala,{" "}
dataset-create-panel-the-dataset-is-saved-as = Skup podataka sprema se kao: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Ova zbirka ima skup podataka s nazivom { $saved_name }.
dataset-create-panel-accept-uploads = Prihvaćaj prijenose
dataset-create-panel-creating-u = Stvaranje…
dataset-create-panel-create-and-ingest = Stvori i unesi
dataset-create-panel-mount = Točka montiranja
dataset-ocr-panel-last-operation = Zadnja operacija: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , pokrenuta { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Nema napretka (minuta: { $current_stale_seconds_60 }). Provjerite Temporal tijek rada i otkažite operaciju ako je zaglavila.
dataset-ocr-panel-loading-u = Učitavanje…
dataset-ocr-panel-stored-text-variants = Pohranjene varijante teksta
dataset-ocr-panel-searchable-pdfs = PDF-ovi s mogućnošću pretraživanja
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · datoteka: { $variant_pdf_count } · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = LLM razgovori uživo
live-chats-panel-agent-turns-running-right-now = Krugovi agenta koji se upravo izvode, najdulji prvo. Osvježava se svake 2 s. Čita se iz Temporala, pa je ovdje i krug koji je započeo prije zadnjeg ponovnog pokretanja web stranice.
live-chats-panel-loading-u = Učitavanje…
live-chats-panel-no-chats-running = Nijedan razgovor nije u tijeku.
live-chats-panel-user = Korisnik
live-chats-panel-conversation = Razgovor
live-chats-panel-question = Pitanje
live-chats-panel-internet = Internet
live-chats-panel-running = U tijeku
live-chats-panel-started = Pokrenuto
live-chats-panel-cancels-the-workflow-the-turn = Otkazuje tijek rada. Krug završava oznakom zaustavljanja u transkriptu i ne nestaje.
live-chats-panel-kill = Prekini
processing-updates-panel-loading-u = Učitavanje…
processing-updates-panel-open-the-operation = Otvori operaciju
processing-updates-panel-the-pipeline-has-not-calculated = Pipeline još nije izračunao ova ažuriranja.
processing-updates-panel-calculated-at-in-ms = Izračunato: { $view_checked_at }, za { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatska ažuriranja isključena su u ovoj instalaciji. Pokrenite ažuriranja gumbom.
processing-updates-panel-step = Korak
processing-updates-panel-count = Broj
processing-updates-panel-state = Stanje
processing-updates-panel-last-run = Zadnje pokretanje
processing-updates-panel-runs = Pokretanja: { $step_runs }
processing-updates-panel-a-run-again-would-select = Ponovno pokretanje odabralo bi otprilike ovoliko ({ $step_unit }).
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } pri ponovnom pokretanju
processing-updates-panel-never = Nikad
processing-updates-panel-update-collection = Ažuriraj zbirku
processing-updates-panel-update-processing = Ažuriraj obradu
processing-updates-panel-check-again = Provjeri ponovno
processing-updates-panel-dataset = Skup podataka
processing-updates-panel-processing-updates = Ažuriranja obrade
admin-ai-status-admin-ai-status = Administracija: AI status
admin-ai-status-ai-status = AI status
admin-ai-status-the-configured-service-and-the = Konfigurirana usluga i usluga koja stvarno odgovara. Prelazak na CPU uslugu prikazuje se samo ovdje.
admin-ai-status-loading-u = Učitavanje…
admin-ai-status-config-fingerprint = Otisak konfiguracije
admin-ai-status-website-worker = Web stranica / radnik
admin-ai-status-ai-server = AI poslužitelj
admin-ai-status-match = Podudaranje
admin-ai-status-embeddings-probe = Provjera ugrađivanja
admin-ai-status-dims = { $status_embeddings_serving_model } · dimenzija: { $status_embeddings_serving_dim }
admin-ai-status-llm-configured = LLM konfiguriran
admin-ai-status-capabilities = Mogućnosti
admin-ai-status-capability = Mogućnost
admin-ai-status-configured = Konfigurirano
admin-ai-status-serving = Poslužuje
admin-ai-status-model = Model
admin-ai-status-reachable = Dostupno
admin-ai-status-detail = Detalji
admin-ai-status-no = NE
admin-ai-status-vector-shard-dims-vs-probe = Dimenzije vektorskog sharda prema provjeri
admin-ai-status-no-collections-yet = Još nema zbirki.
admin-ai-status-collection = Zbirka
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Podudara se s provjerom
admin-ai-status-browser-router = Usmjerivač preglednika
admin-ai-status-live-sessions = Aktivne sesije: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Nedavni LLM promet (24 h)
admin-ai-status-no-llm-call-events-yet = Još nema llm_call_events.
admin-ai-status-user = Korisnik
admin-ai-status-calls = Pozivi
admin-ai-status-errors = Pogreške
admin-ai-status-service-use-24-h = Korištenje usluge % (24 h)
admin-ai-status-busy-seconds-in-the-last = Zauzete sekunde u zadnja 24 sata, kao udio dana.
admin-ai-status-no-samples-yet = Još nema uzoraka.
admin-ai-status-service = Usluga
admin-ai-status-busy-s = Zauzeto s
admin-ai-status-use = Korištenje %
admin-collection-detail-admin-collection = Administracija: zbirka { $collection_id }
admin-collection-detail-failed-to-load-collection = Učitavanje zbirke nije uspjelo
admin-collection-detail-loading = Učitavanje...
admin-collection-detail-datasets = Skupovi podataka
admin-collection-detail-dataset = Skup podataka
admin-collection-detail-documents = Dokumenti
admin-collection-detail-size = Veličina
admin-collection-detail-indexed = Indeksirano
admin-collection-detail-errors = Pogreške
admin-collection-detail-state = Stanje
admin-collection-detail-created = Stvoreno
admin-collection-detail-settings = Postavke
admin-collection-detail-the-collection-database-is-not = Baza podataka zbirke još nije spremna.
admin-collection-detail-the-last-storage-provisioning-failed = Zadnje postavljanje pohrane nije uspjelo: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Napredak obrade i procjene
admin-collection-detail-display-name = Prikazni naziv
admin-collection-detail-display-name-2 = prikazni naziv
admin-collection-detail-save = Spremi
admin-collection-detail-access = Pristup
admin-collection-detail-public-every-signed-in-user = Javna. Svaki prijavljeni korisnik može pretraživati i čitati ovu zbirku.
admin-collection-detail-restricted-only-members-of-the = Ograničena. Samo članovi grupa ispod mogu pretraživati i čitati ovu zbirku.
admin-collection-detail-the-collection-is-now-public = Zbirka je sada javna.
admin-collection-detail-the-collection-is-now-restricted = Zbirka je sada ograničena.
admin-collection-detail-make-restricted = Ograniči
admin-collection-detail-make-public = Učini javnom
admin-collection-detail-group-permissions = Dopuštenja grupa
admin-collection-detail-no-group-can-read-this = Nijedna grupa još ne može čitati ovu zbirku.
admin-collection-detail-revoke = Opozovi
admin-collection-detail-grant-group-u = Dodijeli grupi…
admin-collection-detail-grant = Dodijeli
admin-collection-detail-danger-zone = Opasna zona
admin-collection-detail-a-collection-can-only-be = Zbirku je moguće izbrisati samo dok nema skupova podataka.
admin-collection-detail-deleting-the-collection-also-drops = Brisanjem zbirke briše se i njezina baza podataka{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}i sve u njoj. Ovo se ne može poništiti. Upišite naziv zbirke radi potvrde.
admin-collection-detail-collection-name = Naziv zbirke
admin-collection-detail-delete-collection = Izbriši zbirku
admin-collection-detail-features = Značajke
admin-collection-detail-vectors = Vektori
admin-collection-detail-this-installation-runs-no-embedding = Ova instalacija ne pokreće uslugu ugrađivanja, pa nijedna zbirka ne koristi vektore.
admin-collection-detail-vectors-find-passages-by-meaning = Vektori pronalaze odsječke prema značenju. Isključivanje zaustavlja nove vektore i sprječava pretragu da koristi pohranjene, koji ostaju. Uključivanje izračunava vektore koji nedostaju za svaki skup podataka, jedan po jedan.
admin-collection-detail-this-collection-follows-the-installation = Ova zbirka prati instalaciju, koja koristi vektore. Vektori pronalaze odsječke prema značenju. Isključivanje zaustavlja nove vektore i sprječava pretragu da koristi pohranjene, koji ostaju.
admin-collection-processing-could-not-load-this-panel = Nije moguće učitati ovaj panel: { $message }
admin-collection-processing-admin-processing-of = Administracija: obrada zbirke { $collection_id }
admin-collection-processing-u-back-to-collection = ← Natrag na zbirku
admin-collection-processing-processing-stages = Faze obrade
admin-collection-processing-loading-u = Učitavanje…
admin-collection-processing-the-collection-database-is-still = Baza podataka zbirke još se postavlja.
admin-collection-processing-this-collection-has-no-datasets = Ova zbirka još nema skupova podataka.
admin-collection-processing-eta = ETA { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Još nema uzoraka za procjenu. Prikupljaju se dok se skup podataka obrađuje.
admin-collection-processing-estimated-completion = Procijenjeni završetak:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(za { $humanize_seconds_c_eta_seconds }, procjena po najboljem pokušaju, a ne obećanje rasporeda)
admin-collection-processing-no-current-estimate-the-pipeline = Nema trenutne procjene. Pipeline je završen ili ne postiže mjerljiv napredak.
admin-collection-processing-where-processing-time-goes = Kamo odlazi vrijeme obrade
admin-collection-processing-no-task-executions-recorded-yet = Još nema zabilježenih izvršavanja zadataka. Svaka aktivnost koju pipeline pokrene ovdje upisuje jedan redak, pa prazna tablica znači da od uvođenja instrumentacije ništa nije obrađeno.
admin-collection-processing-summed-task-time = Zbroj vremena zadataka
admin-collection-processing-wall-clock = Stvarno vrijeme
admin-collection-processing-achieved-parallelism = Postignuta paralelnost
admin-collection-processing-summed-task-time-divided-by = Zbroj vremena zadataka podijeljen stvarnim vremenom pokazuje koliko je pipeline stvarno postigao paralelno. Vrijednost blizu 1 znači da je prvi zadatak ispod cijeli trošak i da ga vrijedi optimizirati. Vrijednost blizu broja radnih mjesta znači da su mjesta zasićena i da su dodatni radnici jeftinije rješenje. Stvarno vrijeme obuhvaća razdoblje od prvog do zadnjeg izvršavanja, uključujući vrijeme mirovanja.
admin-collection-processing-task = Zadatak
admin-collection-processing-total = Ukupno
admin-collection-processing-share = Udio
admin-collection-processing-executions = Izvršavanja
admin-collection-processing-mean = Prosjek
admin-collection-processing-max = Maks.
admin-collection-processing-failed = Neuspjelo
admin-collection-processing-live-activity = Aktivnost uživo
admin-collection-processing-nothing-running-no-activity-finished = Ništa se ne izvodi. Nijedna aktivnost nije završila u zadnjih { $live_window_seconds } s i nijedan radnik ne prijavljuje ništa u tijeku.
admin-collection-processing-in-flight = U tijeku
admin-collection-processing-average-concurrency = Prosječna istodobnost
admin-collection-processing-task-time-in-window = Vrijeme zadataka u prozoru
admin-collection-processing-share-of-processing-time-over = Udio vremena obrade u zadnjih { $live_window_seconds } s, osvježava se svakih 5 s. Izvršavanje koje prelazi rub prozora računa se samo za dio unutar njega. Redak s izvršavanjima u tijeku, a bez udjela, započeo je prije prozora i nije završio. Provjerite njegovu starost.
admin-collection-processing-share-of-window = Udio u prozoru
admin-collection-processing-task-time = Vrijeme zadataka
admin-collection-processing-completed = Završeno
admin-collection-processing-oldest-running = Najstarije u tijeku
admin-collection-processing-temporal-workflows = Temporal tijekovi rada
admin-collection-processing-workflows-of-this-collection-s = Tijekovi rada skupova podataka ove zbirke, uključujući podređene tijekove rada.
admin-collection-processing-no-workflows-match-this-filter = Nijedan tijek rada ne odgovara ovom filtru.
admin-collection-processing-workflow = Tijek rada
admin-collection-processing-type = Vrsta
admin-collection-processing-status = Status
admin-collection-processing-started = Pokrenuto
admin-collection-processing-closed = Zatvoreno
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = otvori ↗
admin-collection-processing-failed-tasks = Neuspjeli zadaci
admin-collection-processing-no-task-failures-recorded = Nema zabilježenih neuspjeha zadataka.
admin-collection-processing-dataset = Skup podataka
admin-collection-processing-errors = Pogreške
admin-collection-processing-documents = Dokumenti
admin-collection-processing-last-seen = Zadnje viđeno
admin-collection-processing-sample = Uzorak
admin-collection-processing-retry = Pokušaj ponovno
admin-collection-processing-failures-per-document = Neuspjesi po dokumentu
admin-collection-processing-no-document-failures-recorded = Nema zabilježenih neuspjeha dokumenata.
admin-collection-processing-document = Dokument
admin-collections-list-admin-collections = Administracija: zbirke
admin-collections-list-collections = Zbirke
admin-collections-list-loading-collections-u = Učitavanje zbirki…
admin-collections-list-datasets = Skupovi podataka
admin-collections-list-loading-datasets-u = Učitavanje skupova podataka…
admin-collections-list-add-a-collection = Dodaj zbirku
admin-collections-list-name-for-example-enron = Naziv, na primjer enron
admin-collections-list-display-name = Prikazni naziv
admin-collections-list-add-collection = Dodaj zbirku
admin-collections-list-a-name-has-lowercase-letters = Naziv sadrži mala slova, znamenke i podcrte. Velika slova postaju mala,{" "}
admin-collections-list-the-collection-is-saved-as = Zbirka se sprema kao: { $new_name }
admin-collections-list-a-collection-with-the-name = Zbirka s nazivom { $new_name } već postoji.
admin-collections-list-collection = Zbirka
admin-collections-list-documents = Dokumenti
admin-collections-list-size = Veličina
admin-collections-list-errors = Pogreške
admin-collections-list-state = Stanje
admin-collections-list-access = Pristup
admin-collections-list-database-not-ready = Baza podataka nije spremna
admin-collections-list-public = Javna
admin-collections-list-1-group = 1 grupa
admin-collections-list-not-counted-yet = Još nije prebrojano
admin-collections-list-unknown = Nepoznato
admin-collections-list-no-collection-has-a-dataset = Nijedna zbirka nema skup podataka.
admin-collections-list-dataset = Skup podataka
admin-collections-list-indexed = Indeksirano
admin-collections-list-created = Stvoreno
admin-dashboard-admin-dashboard = Administracija: nadzorna ploča
admin-dashboard-administration = Administracija
admin-dashboard-users = Korisnici
admin-dashboard-groups = Grupe
admin-dashboard-collections = Zbirke
admin-dashboard-datasets = Skupovi podataka
admin-dashboard-failed-to-load-counts = Učitavanje brojeva nije uspjelo: { $e }
admin-dataset-detail-admin-dataset = Administracija: skup podataka { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Učitavanje skupa podataka nije uspjelo
admin-dataset-detail-loading = Učitavanje...
admin-dataset-detail-metadata = Metapodaci
admin-dataset-detail-display-name = Prikazni naziv
admin-dataset-detail-name = Naziv
admin-dataset-detail-type = Vrsta
admin-dataset-detail-path = Putanja
admin-dataset-detail-created = Stvoreno
admin-dataset-detail-collection = Zbirka
admin-dataset-detail-save = Spremi
admin-dataset-detail-statistics = Statistika
admin-dataset-detail-state = Stanje
admin-dataset-detail-documents = Dokumenti
admin-dataset-detail-size = Veličina
admin-dataset-detail-indexed = Indeksirano
admin-dataset-detail-errors = Pogreške
admin-dataset-detail-plans-finished = Završeni planovi
admin-dataset-detail-disk = Disk
admin-dataset-detail-rescan-disk-reads-the-dataset = Ponovno skeniraj disk ponovno čita mapu skupa podataka, dodaje nove i promijenjene datoteke i obrađuje ih.
admin-dataset-detail-rescan-disk = Ponovno skeniraj disk
admin-dataset-detail-danger-zone = Opasna zona
admin-dataset-detail-this-deletes-the-dataset-and = Ovo briše skup podataka i sve podatke izdvojene iz njega. Ne možete to poništiti.
admin-dataset-detail-delete-dataset-and-its-data = Izbriši skup podataka i njegove podatke
admin-dataset-detail-accept-uploads = Prihvaćaj prijenose
admin-dataset-detail-the-folder-of-this-dataset = Mapa ovog skupa podataka nije u točki montiranja skupa podataka koja dopušta pisanje, pa ne prima prijenose.
admin-dataset-detail-starting-u = Pokretanje…
admin-failure-detail-admin-failure = Administracija: neuspjeh { $op_id }
admin-failure-detail-loading-tree = Učitavanje stabla…
admin-failure-detail-back-to-errors-and-failures = Natrag na pogreške i neuspjehe
admin-failure-detail-operations = Operacije
admin-failure-detail-scrubbed-copy-written-to-the = Očišćena kopija zapisana je u međuspremnik.
admin-failure-detail-this-tree-is-truncated-at = Ovo stablo je skraćeno. Barem jedno snimanje izostavilo je čvorove.
admin-failure-detail-the-captured-tree-has-expired = Snimljeno stablo je isteklo. Redak operacije i dalje postoji.
admin-failure-detail-no-captured-nodes-for-this = Nema snimljenih čvorova za ovu operaciju.
admin-failure-detail-operation = Operacija
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · korijena: { $root_count } · čvorova: { $tree_nodes_len }
admin-failure-detail-open-in-temporal = Otvori u Temporalu
admin-failure-detail-scrubbed-copy = Očišćena kopija
admin-failure-detail-the-scrubbed-copy-replaces-dataset = Očišćena kopija zamjenjuje putanje skupova podataka hashevima, a duge vrijednosti njihovim duljinama.
admin-failure-detail-copy-scrubbed-record = Kopiraj očišćeni zapis
admin-failure-detail-tree = Stablo
admin-failure-detail-root = Korijen ·{" "}
admin-failure-detail-node-parent-depth-source-stage = čvor { $node_node_index } · roditelj { $node_parent_index } · dubina { $node_depth } · izvor { $node_source } · faza { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = tijek rada { $node_workflow_id } · pokretanje { $node_run_id } · aktivnost { $node_activity_id } · pokušaj { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = Čvorova izostavljeno pri ovom snimanju: { $node_nodes_dropped }
admin-failures-admin-errors-and-failures = Administracija: pogreške i neuspjesi
admin-failures-errors-failures = Pogreške/neuspjesi
admin-failures-loading-failures = Učitavanje neuspjeha…
admin-failures-operational-failures = Operativni neuspjesi
admin-failures-no-operational-failures-at-this = Trenutno nema operativnih neuspjeha.
admin-failures-collection = Zbirka
admin-failures-dataset = Skup podataka
admin-failures-task-name = Naziv zadatka
admin-failures-error-class = Klasa pogreške
admin-failures-operation-kind = Vrsta operacije
admin-failures-from = Od
admin-failures-to = Do
admin-failures-no-captured-failures-match-these = Nijedan snimljeni neuspjeh ne odgovara ovim filtrima.
admin-failures-signature = Potpis
admin-failures-count = Broj
admin-failures-class = Klasa
admin-failures-task = Zadatak
admin-failures-last-seen = Zadnje viđeno
admin-failures-newer = Novije
admin-failures-page = Stranica { $current_page_1 }
admin-failures-older = Starije
admin-failures-per-page = Po stranici
admin-failures-loading-instances = Učitavanje instanci…
admin-failures-no-instances-for-this-signature = Nema instanci za ovaj potpis.
admin-failures-node = {" "}čvor { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Pogreške dokumenata
admin-failures-error-text = Tekst pogreške
admin-failures-loading-document-errors-u = Učitavanje pogrešaka dokumenata…
admin-failures-no-document-errors-match-these = Nijedna pogreška dokumenta ne odgovara ovim filtrima.
admin-failures-errors-by-dataset-and-task = Pogreške po skupu podataka i zadatku
admin-failures-documents = Dokumenti
admin-failures-show-only-this-dataset-and = Prikaži samo ovaj skup podataka i zadatak
admin-failures-total = Ukupno
admin-failures-errors = Pogreške
admin-failures-document = Dokument
admin-failures-runs = Pokretanja
admin-failures-error = Pogreška
admin-failures-dataset-step = Korak skupa podataka
admin-failures-previous-page = Prethodna stranica
admin-failures-page-of-1-error = Stranica { $page } od { $pages }, 1 pogreška
admin-failures-page-of-errors = Stranica { $page } od { $pages }, pogrešaka: { $data_total }
admin-failures-next-page = Sljedeća stranica
admin-feedback-admin-feedback = Administracija: povratne informacije
admin-feedback-feedback = Povratne informacije
admin-feedback-search-titles-descriptions-accounts-and = Pretraži naslove, opise, račune i adrese
admin-feedback-search = Pretraži
admin-feedback-loading-reports-u = Učitavanje izvješća…
admin-feedback-1-report-matches = Odgovara 1 izvješće.
admin-feedback-reports-match = Izvješća koja odgovaraju: { $data_total }.
admin-feedback-received = Primljeno
admin-feedback-type = Vrsta
admin-feedback-title = Naslov
admin-feedback-from = Od
admin-feedback-captures = Snimke
admin-feedback-state = Stanje
admin-feedback-previous-page = Prethodna stranica
admin-feedback-page-of = Stranica { $page } od { $pages }
admin-feedback-next-page = Sljedeća stranica
admin-feedback-image = Slika { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Pročitano
admin-feedback-unread = Nepročitano
admin-feedback-archived = Arhivirano
admin-feedback-mark-unread = Označi kao nepročitano
admin-feedback-mark-read = Označi kao pročitano
admin-feedback-restore = Vrati
admin-feedback-archive = Arhiviraj
admin-feedback-page = Stranica:{" "}
admin-feedback-the-report-has-no-description = Izvješće nema opis.
admin-feedback-open-the-page-image = Otvori sliku stranice
admin-feedback-open-the-dom-copy = Otvori kopiju DOM-a
admin-feedback-page-image-of-the-report = Slika stranice izvješća
admin-feedback-debug-context-and-browser-log = Kontekst za otklanjanje pogrešaka i dnevnik preglednika
admin-feedback-loading-u = Učitavanje…
admin-group-detail-admin-group = Administracija: grupa { $groupname }
admin-group-detail-failed-to-load-group = Učitavanje grupe nije uspjelo
admin-group-detail-loading = Učitavanje...
admin-group-detail-group = Grupa
admin-group-detail-display-name = Prikazni naziv
admin-group-detail-display-name-2 = prikazni naziv
admin-group-detail-save = Spremi
admin-group-detail-members = Članovi
admin-group-detail-saving-membership = Spremanje članstva...
admin-group-detail-username = Korisničko ime
admin-group-detail-origin = Podrijetlo
admin-group-detail-group-admin = Administrator grupe
admin-group-detail-uploader = Prenositelj
admin-group-detail-remove = Ukloni
admin-group-detail-username-to-add = korisničko ime za dodavanje
admin-group-detail-add-member = Dodaj člana
admin-group-detail-collection-access = Pristup zbirkama
admin-group-detail-this-group-has-no-collection = Ova grupa nema dopuštenja za zbirke.
admin-group-detail-revoke = Opozovi
admin-group-detail-grant-collection-u = Dodijeli zbirku…
admin-group-detail-grant = Dodijeli
admin-group-detail-danger-zone = Opasna zona
admin-group-detail-delete-group = Izbriši grupu
admin-groups-list-admin-groups = Administracija: grupe
admin-groups-list-groups = Grupe
admin-groups-list-add-group = Dodaj grupu
admin-groups-list-display-name = prikazni naziv
admin-groups-list-use-lowercase-letters-digits-underscores = U nazivu upotrijebite mala slova, znamenke, podcrte i crtice. Naziv se ne može kasnije promijeniti.
admin-groups-list-add-group-2 = Dodaj grupu +
admin-groups-list-group = Grupa
admin-groups-list-display-name-2 = Prikazni naziv
admin-groups-list-members = Članovi
admin-groups-list-collections = Zbirke
admin-groups-list-loading = Učitavanje...
admin-llm-config-admin-llm = Administracija: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Učitavanje…
admin-llm-config-no-llm-provider-is-configured = Nije konfiguriran nijedan LLM pružatelj. Postavite LLM_BASE_URL / LLM_MODEL u hoover4.ini i ponovno postavite instalaciju.
admin-llm-config-providers = Pružatelji
admin-llm-config-the-refresh-runs-in-the = Osvježavanje se izvodi u pozadini. Trenutni popis ostaje vidljiv.
admin-llm-config-refresh-in-flight-u = {" "}Osvježavanje u tijeku…
admin-llm-config-provider = Pružatelj
admin-llm-config-models = Modeli
admin-llm-config-freshest = Najsvježije
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Osvježi katalog
admin-llm-config-agent-turns-board-assessments-and = Krugovi agenta, procjene ploča i pretvorbe izvješća
admin-llm-config-titles-summaries-and-board-labels = Naslovi, sažeci i oznake ploča
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini postavlja ove modele: quality_model LLM pružatelja za krugove agenta, procjene ploča i pretvorbe izvješća kad je postavljen, a njegov model za ostalo.
admin-llm-config-thinking = Zaključivanje
admin-llm-config-the-model-reasons-before-each = Model zaključuje prije svakog poziva alata i svakog odgovora.
admin-llm-config-catalog = Katalog
admin-llm-config-filter-models-u = Filtriraj modele…
admin-llm-config-model = Model
admin-llm-config-flags = Oznake
admin-llm-config-calls-14d = Pozivi 14 d
admin-llm-config-ai-status = AI status
admin-llm-config-shows-the-serving-health = {" "}prikazuje ispravnost poslužiranja.
admin-llm-reports-reports = Izvješća
admin-llm-reports-each-report-runs-when-you = Svako izvješće pokreće se kad odaberete njegov gumb.
admin-llm-reports-running-u = Izvođenje…
admin-llm-reports-run-report = Pokreni izvješće
admin-llm-reports-read-at = Pročitano: { $read_at }
admin-llm-reports-errors = Pogreške
admin-llm-reports-failed-attempts-by-step-and = Neuspjeli pokušaji po koraku i klasi pogreške te pokretanja agenta koja su neuspjela ili završila prije vremena, po razlogu završetka.
admin-llm-reports-source = Izvor
admin-llm-reports-class = Klasa
admin-llm-reports-no-errors-in-30-days = Nema pogrešaka u 30 dana.
admin-llm-reports-recent-errors = Nedavne pogreške
admin-llm-reports-the-newest-100-failed-attempts = Najnovijih 100 neuspjelih pokušaja u 7 dana. Otvorite redak da biste pročitali njegovu pogrešku.
admin-llm-reports-time = Vrijeme
admin-llm-reports-user = Korisnik
admin-llm-reports-name = Naziv
admin-llm-reports-error = Pogreška
admin-llm-reports-no-errors-in-7-days = Nema pogrešaka u 7 dana.
admin-llm-reports-show = Prikaži
admin-llm-reports-tool-calls = Pozivi alata
admin-llm-reports-one-row-for-each-tool = Jedan redak za svaki alat, po broju poziva u 30 dana. Pogreška je neuspjeli poziv.
admin-llm-reports-tool = Alat
admin-llm-reports-calls-24-h = Pozivi 24 h
admin-llm-reports-error-24-h = Pogreške % 24 h
admin-llm-reports-avg-ms-24-h = Prosj. ms 24 h
admin-llm-reports-calls-7-d = Pozivi 7 d
admin-llm-reports-error-7-d = Pogreške % 7 d
admin-llm-reports-avg-ms-7-d = Prosj. ms 7 d
admin-llm-reports-calls-30-d = Pozivi 30 d
admin-llm-reports-error-30-d = Pogreške % 30 d
admin-llm-reports-avg-ms-30-d = Prosj. ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Nema poziva alata u 30 dana.
admin-llm-reports-top-users = Najaktivniji korisnici
admin-llm-reports-the-30-users-with-the = 30 korisnika s najviše vremena modela u prozoru.
admin-llm-reports-30-days = 30 dana
admin-llm-reports-7-days = 7 dana
admin-llm-reports-24-hours = 24 sata
admin-llm-reports-tool-time = Vrijeme alata
admin-llm-reports-model-calls = Pozivi modela
admin-llm-reports-model-time = Vrijeme modela
admin-llm-reports-tokens-in = Ulazni tokeni
admin-llm-reports-tokens-out = Izlazni tokeni
admin-llm-reports-no-agent-use-in-the = Nema korištenja agenta u prozoru.
admin-llm-reports-system-one-checks = Provjere System one
admin-llm-reports-requests-are-grouped-by-hook = Zahtjevi su grupirani po hooku i pravilu. Latencije su u milisekundama. Udjeli koriste zahtjeve iz zadnjih 30 dana.
admin-llm-reports-counts = Brojevi
admin-llm-reports-recent-failures = Nedavni neuspjesi
admin-llm-reports-select-run-report-to-read = Odaberite Pokreni izvješće da biste pročitali statistiku.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Pravilo
admin-llm-reports-outcome = Ishod
admin-llm-reports-questions = Pitanja
admin-llm-reports-median-ms = Medijan ms
admin-llm-reports-95th-percentile-ms = 95. percentil ms
admin-llm-reports-error-2 = Pogreške %
admin-llm-reports-positive = Pozitivno %
admin-llm-reports-actions = Radnje
admin-metrics-admin-metrics = Administracija: metrike
admin-metrics-metrics = Metrike
admin-metrics-the-last-24-hours = Zadnja 24 sata.
admin-metrics-loading-u = Učitavanje…
admin-metrics-manticore-load-now = Opterećenje Manticorea (sada)
admin-metrics-ram-is-the-memory-of = RAM je memorija tablica. Opterećenje niti odnosi se na zadnjih 1, 5 i 15 minuta.
admin-metrics-manticore-status-could-not-be = Status Manticorea nije moguće pročitati: { $error }
admin-metrics-thread-load-1-5-15 = Opterećenje niti (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Opterećenje primarnih niti (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Opterećenje sekundarnih niti (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Zauzete / ukupne radne niti
admin-metrics-work-queue = Red poslova
admin-metrics-ram-held-by-tables = RAM koji drže tablice
admin-metrics-disk-used-by-tables = Disk koji koriste tablice
admin-metrics-tables-merging = Tablice se spajaju
admin-metrics-tables-read = Pročitane tablice
admin-metrics-read-at = Pročitano
admin-metrics-largest-tables-by-ram = Najveće tablice po RAM-u
admin-metrics-table = Tablica
admin-metrics-ram = RAM
admin-metrics-disk = Disk
admin-metrics-disk-chunks = Dijelovi diska
admin-metrics-merging = Spajanje
admin-metrics-usage-last-24-h = Korištenje (zadnjih 24 h)
admin-metrics-events-by-type = Događaji po vrsti
admin-metrics-event = Događaj
admin-metrics-count = Broj
admin-metrics-events-per-hour = Događaji po satu
admin-metrics-no-events-recorded-yet = Još nema zabilježenih događaja.
admin-metrics-busiest-users = Najaktivniji korisnici
admin-metrics-user = Korisnik
admin-metrics-events = Događaji
admin-metrics-events-2 = { $point_bucket }: događaja: { $point_count }
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API pozivi (zadnjih 24 h)
admin-metrics-no-api-calls-recorded-yet = Još nema zabilježenih API poziva.
admin-metrics-function = Funkcija
admin-metrics-calls = Pozivi
admin-metrics-errors = Pogreške
admin-metrics-error-rate = Stopa pogrešaka
admin-metrics-bytes-in = Primljeni bajtovi
admin-metrics-bytes-out = Poslani bajtovi
admin-operation-detail-admin-operation = Administracija: operacija { $op_id }
admin-operation-detail-loading-operation = Učitavanje operacije…
admin-operation-detail-back-to-operations = Natrag na operacije
admin-operation-detail-operation = Operacija
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · stavljeno u red { $row_started_at }
admin-operation-detail-not-started = nije pokrenuta
admin-operation-detail-re-run-counts-are-not = Brojevi ponovnih pokretanja nisu dostupni.
admin-operation-detail-failed-document-s-task-failure = Neuspjelih dokumenata: { $documents }, neuspjeha zadataka: { $row_failed_tasks_unwrap_or_0 }
admin-operation-detail-failures-were-not-counted = Neuspjesi nisu prebrojani.
admin-operation-detail-open-captured-failure-tree = Otvori snimljeno stablo neuspjeha
admin-operation-detail-open-in-temporal = Otvori u Temporalu
admin-operation-detail-plans = Planovi
admin-operation-detail-plan-s-page = Planova: { $data_plans_total }, stranica { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Za ovu operaciju nije zabilježen nijedan plan.
admin-operation-detail-dataset = Skup podataka
admin-operation-detail-plan-hash = Hash plana
admin-operation-detail-source = Izvor
admin-operation-detail-finished = Završeno
admin-operation-detail-previous = Prethodna
admin-operation-detail-next = Sljedeća
admin-operation-detail-error-events = Događaji pogrešaka
admin-operation-detail-error-event-s-page = Događaja pogrešaka: { $data_events_total }, stranica { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Za ovu operaciju nije zabilježen nijedan događaj pogreške.
admin-operation-detail-time = Vrijeme
admin-operation-detail-hash = Hash
admin-operation-detail-task = Zadatak
admin-operation-detail-event = Događaj
admin-operation-detail-error-excerpt = Isječak pogreške
admin-operations-admin-operations = Administracija: operacije
admin-operations-operations = Operacije
admin-operations-loading-operations = Učitavanje operacija…
admin-operations-filters = Filtri
admin-operations-state = Stanje
admin-operations-any-state = Bilo koje stanje
admin-operations-collection = Zbirka
admin-operations-all-collections = Sve zbirke
admin-operations-choose-a-collection-to-see = Odaberite zbirku da biste vidjeli stope pogrešaka po zadatku.
admin-operations-operations-newest-first = Operacije, najnovije prvo
admin-operations-newer = Novije
admin-operations-page = Stranica { $current_page_1 }
admin-operations-older = Starije
admin-operations-failure-rate-by-task-type = Stopa neuspjeha po vrsti zadatka ({ $collectionname })
admin-operations-one-row-per-activity-execution = Jedan redak po izvršavanju aktivnosti, uključujući ponovne pokušaje. Stopa iznad{" "}
admin-operations-is-marked = {" "}je označena.
admin-operations-no-task-executions-recorded-for = Za ovu zbirku još nema zabilježenih izvršavanja zadataka.
admin-operations-task = Zadatak
admin-operations-error-rate = Stopa pogrešaka
admin-operations-failed-total-executions = Neuspjela / ukupna izvršavanja
admin-operations-documents-affected = Zahvaćeni dokumenti
admin-operations-above-the-line = iznad crte
admin-operations-no-operations-recorded-for-this = Za ovaj filtar nema zabilježenih operacija.
admin-operations-kind = Vrsta
admin-operations-target = Cilj
admin-operations-workflow = Tijek rada
admin-operations-queued-at = Stavljeno u red
admin-operations-started = Pokrenuto
admin-operations-duration = Trajanje
admin-operations-progress = Napredak
admin-operations-eta = ETA
admin-operations-outcome = Ishod
admin-operations-destructive = Destruktivno
admin-operations-repeated-run = Ponovljeno pokretanje
admin-operations-no-estimate-yet = još nema procjene
admin-operations-cancel = Otkaži
admin-operations-type-to-confirm = upišite { $target } radi potvrde
admin-operations-re-run = Pokreni ponovno
admin-operations-waiting-for-a-free-slot = čeka slobodno mjesto ili slobodan cilj
admin-operations-counting-work = brojanje posla…
admin-operations-open-captured-tree = Otvori snimljeno stablo
admin-operations-no-captured-tree = nema snimljenog stabla
admin-operations-no-failed-documents = nema neuspjelih dokumenata
admin-operations-document-s-failed = neuspjelih dokumenata: { $n }
admin-operations-task-failure-s = neuspjeha zadataka: { $t }
admin-operations-failures-not-counted = neuspjesi nisu prebrojani
admin-operations-the-newest-ten-operations-of = Deset najnovijih operacija ove zbirke.{" "}
admin-operations-all-operations = Sve operacije
admin-settings-admin-settings = Administracija: postavke
admin-settings-server-settings = Postavke poslužitelja
admin-settings-key = Ključ
admin-settings-value = Vrijednost
admin-settings-description = Opis
admin-settings-save = Spremi
admin-settings-loading = Učitavanje...
admin-settings-deployment-configuration-read-only = Konfiguracija instalacije (samo za čitanje)
admin-settings-not-set = (nije postavljeno)
admin-user-detail-admin-user = Administracija: korisnik { $username }
admin-user-detail-failed-to-load-user = Učitavanje korisnika nije uspjelo
admin-user-detail-loading = Učitavanje...
admin-user-detail-user = Korisnik
admin-user-detail-the-next-login-replaces-the = Sljedeća prijava zamjenjuje puno ime, e-poštu i status superkorisnika korisnika koji dolazi preko proxyja za prijavu.
admin-user-detail-llm-usage-u = LLM korištenje →
admin-user-detail-full-name = Puno ime
admin-user-detail-full-name-2 = puno ime
admin-user-detail-email = E-pošta
admin-user-detail-superuser = Superkorisnik
admin-user-detail-save = Spremi
admin-user-detail-groups = Grupe
admin-user-detail-saving-membership = Spremanje članstva...
admin-user-detail-group = Grupa
admin-user-detail-origin = Podrijetlo
admin-user-detail-group-admin = Administrator grupe
admin-user-detail-uploader = Prenositelj
admin-user-detail-remove = Ukloni
admin-user-detail-add-to-group-u = Dodaj u grupu…
admin-user-detail-add = Dodaj
admin-user-detail-danger-zone = Opasna zona
admin-user-detail-delete-user = Izbriši korisnika
admin-user-llm-admin-llm-use-by = Administracija: LLM korištenje korisnika { $username }
admin-user-llm-u-back-to-user = ← Natrag na korisnika
admin-user-llm-loading-u = Učitavanje…
admin-user-llm-totals-all-time = Ukupno (cijelo vrijeme)
admin-user-llm-chat-sessions = Sesije razgovora
admin-user-llm-messages = Poruke
admin-user-llm-tool-calls = Pozivi alata
admin-user-llm-model-and-tool-time = Vrijeme modela i alata
admin-user-llm-model-and-tool-time-of = vrijeme modela i alata u koracima agenta ovog korisnika. Paralelni pozivi alata računaju se u cijelosti
admin-user-llm-rate-limit-usage-current-windows = Korištenje ograničenja brzine (trenutni prozori)
admin-user-llm-in-process-counters-of-the = Brojači u procesu pokrenutog spremnika web stranice. Ograničenje razgovora { $metrics_chat_per_minute }/min, ograničenje API-ja { $metrics_api_per_minute }/min, uz postupno opadajuću trajnu stopu preko dužih prozora.
admin-user-llm-chat-messages = Poruke razgovora
admin-user-llm-api-calls = API pozivi
admin-user-llm-window = Prozor
admin-user-llm-used = Iskorišteno
admin-user-llm-budget = Ograničenje
admin-user-llm-no-chat-sessions = Nema sesija razgovora.
admin-user-llm-title = Naslov
admin-user-llm-created = Stvoreno
admin-users-list-admin-users = Administracija: korisnici
admin-users-list-users = Korisnici
admin-users-list-search-users = Pretraži korisnike
admin-users-list-username = Korisničko ime
admin-users-list-full-name = Puno ime
admin-users-list-email-address = Adresa e-pošte
admin-users-list-superuser = Superkorisnik
admin-users-list-groups = Grupe
admin-users-list-created = Stvoreno
admin-users-list-last-login = Zadnja prijava
admin-users-list-loading = Učitavanje...
dataset-create-panel-put-the-documents-in-a = Stavite dokumente u mapu ondje i ponovno učitajte ovu stranicu.
dataset-create-panel-the-name-cannot-start-with = Naziv ne smije počinjati točkom niti sadržavati kosu crtu.
dataset-create-panel-and-a-dash-a-space = a crtica, razmak ili točka postaju podcrta. Naziv se ne može kasnije promijeniti.
live-chats-panel-off = isključeno
processing-updates-panel-the-waiting-steps-change-each = Koraci na čekanju mijenjaju stavke ovako: { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), svaka datoteka broji se jednom, kroz { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = a crtica, razmak ili točka postaju podcrta. Naziv se ne može kasnije promijeniti.
admin-llm-config-fresh = svježe
admin-llm-config-tools = alati{" "}
admin-llm-config-vision = vizija{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (samo za čitanje)
live-chats-panel-on = uključeno
processing-updates-panel-up-to-date-select-it = Ažurno. Odaberite ga za ponovno pokretanje.
admin-ai-status-yes = da
admin-ai-status-no-2 = ne
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = Pogrešaka: { $ds_error_count }
admin-collection-processing-done = gotovo
admin-collection-processing-failed-2 = neuspjelo: { $stage_failed_documents }
admin-collection-processing-left = preostalo
admin-collection-processing-dataset-level = na razini skupa podataka
admin-collections-list-groups = Grupa: { $c_group_count }
admin-failures-operation-s = Operacija: { $group_operation_count }
admin-groups-list-groupname = naziv grupe
admin-llm-config-stale = zastarjelo
admin-llm-config-thinking-is-on = Zaključivanje je uključeno
admin-llm-config-thinking-is-off = Zaključivanje je isključeno
admin-llm-config-shown = Prikazano: { $models_len }
admin-llm-config-reasoning = zaključivanje
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } od { $load_table_count }
admin-metrics-yes = da
admin-metrics-no = ne
admin-metrics-max = maks.
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = pokrenuto { $run_started_at }
admin-operation-detail-yes = da
admin-operation-detail-no = ne
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = e-pošta
admin-user-llm-untitled = (bez naslova)
admin-dataset-ocr-panel-variant-pages = { $source } · stranica: { $pages }
admin-processing-updates-panel-prerequisites-waiting = Zbirci je prvo potrebno ažuriranje: { $steps }. Koraci koji pišu u indeks pretrage čekaju na njega.
admin-operations-no-task-type-failing = Nijedna vrsta zadatka ne zakazuje iznad { $threshold }%.
admin-operations-task-types-failing = Vrsta zadataka koje zakazuju iznad { $threshold }%: { $count }.
processing-updates-panel-collection-updates = Ažuriranja zbirke
admin-collections-list-some-datasets-are-not-counted = Neki skupovi podataka još nisu prebrojani.
admin-failures-hide = Sakrij
admin-failures-show = Prikaži
admin-settings-web-session-lifetime-in-seconds = Trajanje web sesije u sekundama (zadano: 604800 = 1 tjedan)
admin-settings-turns-every-new-chat-turn = Isključuje svaki novi krug razgovora kad je false (zadano: true). Krug u tijeku završava. Stupa na snagu pri sljedećem slanju, bez ponovnog postavljanja.
admin-settings-written-by-main-py-probe = Zapisuje `main.py probe-embeddings`, a to je ono što krajnja točka STVARNO poslužuje. Ručno uređivanje ovoga ne mijenja poslužitelj.
admin-settings-the-folder-whose-subfolders-the = Mapa čije podmape obrazac skupa podataka navodi za ovu točku montiranja. Promjena u hoover4.ini zahtijeva ponovno postavljanje.
admin-settings-from-hoover4-ini-changing-it = Iz hoover4.ini. Promjena zahtijeva ponovno postavljanje.
admin-feedback-bug = Pogreška
admin-operations-state-name = { $state ->
        [pending] na čekanju
        [queued] u redu čekanja
        [running] u tijeku
        [finished] završeno
        [errored] s pogreškom
        [cancelled] otkazano
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Stablo neuspjeha za { $op_id }
admin-failure-detail-showing-of-characters = prikazano znakova: { $node_stack_trace_chars_count } od { $node_stack_trace_original_len }
admin-operations-operation = Operacija: { $state }.
admin-operations-dispatched = Poslano: { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } redaka
admin-operations-plans = { $row_progress_done } / { $row_progress_total } planova
admin-group-detail-group-2 = Grupa { $groupname }
admin-settings-the-setting-was-saved-successfully = Postavka „{ $k }” uspješno je spremljena.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Grupa „{ $g }” uspješno je dodana.
admin-user-detail-user-2 = Korisnik { $username }
admin-dataset-detail-dataset = Skup podataka { $dataset_id }
admin-dataset-detail-collections = Zbirke › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } od { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Postavku prijenosa nije moguće pročitati: { $err }
admin-dataset-detail-operation-started = Operacija je pokrenuta: { $run_id }
admin-collection-detail-collection = Zbirka { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Postavku vektora nije moguće pročitati: { $err }
admin-collection-processing-processing-of = Obrada zbirke { $collection_id }
admin-collection-processing-collections = Zbirke › { $collection_id }
admin-collection-processing-executions-2 = Izvršavanja: { $b_total_executions }
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = stanje na { $at }
admin-collection-processing-over-the-last-s = u zadnjih { $live_window_seconds } s
admin-collection-processing-retry-started-run = Ponovni pokušaj pokrenut (pokretanje { $run }).
admin-collection-processing-document-retry-started-run = Ponovni pokušaj za dokument pokrenut (pokretanje { $run }).
admin-operation-detail-operation-2 = Operacija { $op_id }
admin-user-llm-llm-usage-of = LLM korištenje korisnika { $username }
admin-user-llm-users = Korisnici › { $username }
processing-updates-panel-the-processing-updates-could-not = Ažuriranja obrade nije moguće pročitati: { $e }
processing-updates-panel-update-started = Ažuriranje je pokrenuto: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } od { $operation_progress_total } planova
dataset-ocr-panel-adding = dodavanje: { $added }
dataset-ocr-panel-removing = uklanjanje: { $removed }
dataset-ocr-panel-plan-s-reopened = ponovno otvoreno planova: { $plans }
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] mapa
        [few] mape
       *[other] mapa
    }
    [tables] { $count ->
        [one] tablica
        [few] tablice
       *[other] tablica
    }
   *[files] { $count ->
        [one] datoteka
        [few] datoteke
       *[other] datoteka
    }
}
processing-updates-step-runs = { $count ->
    [one] pokretanje koraka
    [few] pokretanja koraka
   *[other] pokretanja koraka
}
processing-update-search_schema-title = Shema indeksa pretrage
processing-update-search_schema-explanation = { $files ->
    [one] { $count } tablica pretrage zbirke nema stupac koji treba indeksu pretrage.
    [few] { $count } tablice pretrage zbirke nemaju stupac koji treba indeksu pretrage.
   *[other] { $count } tablica pretrage zbirke nema stupac koji treba indeksu pretrage.
} Stupac se dodaje svakoj tablici. Pretraga i dalje radi.
processing-update-search_schema-runs = Tablice indeksa pretrage
processing-update-unfinished-title = Nedovršena obrada
processing-update-unfinished-explanation = { $files ->
    [one] { $count } datoteka nije obrađena do kraja.
    [few] { $count } datoteke nisu obrađene do kraja.
   *[other] { $count } datoteka nije obrađeno do kraja.
} To uključuje datoteke bez plana obrade, na primjer nakon prekinutog unosa. Njihova se obrada dovršava.
processing-update-unfinished-runs = Sve faze obrade za ove datoteke
processing-update-failed_files-title = Neuspjele datoteke
processing-update-failed_files-explanation = { $files ->
    [one] { $count } datoteka ima pogrešku obrade.
    [few] { $count } datoteke imaju pogrešku obrade.
   *[other] { $count } datoteka ima pogrešku obrade.
} Neuspjele faze ponovno se pokreću za njih. Automatsko pokretanje ponavlja datoteku jednom za svaku novu verziju faze koja je zakazala.
processing-update-failed_files-runs = Neuspjele faze, zatim izdvajanje entiteta, ugrađivanje i indeksiranje
processing-update-virus_scan-title = Antivirusno skeniranje
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } datoteka nema antivirusnu presudu.
    [few] { $count } datoteke nemaju antivirusnu presudu.
   *[other] { $count } datoteka nema antivirusnu presudu.
} Skeniraju se. Datoteka za koju skener utvrdi da je zaražena označava se u pretrazi, a preuzimanje njezina izvornika i PDF-a s mogućnošću pretraživanja odbija se.
processing-update-virus_scan-runs = Antivirusno skeniranje, zatim atribut pretrage zaraženih datoteka
processing-update-tables-title = Tablice
processing-update-tables-explanation = { $files ->
    [one] { $count } datoteka ima starije očitanje tablice ili nepotpune ovisne rezultate. Pohranjeni rezultati ažuriraju se.
    [few] Datoteke sa starijim očitanjima tablica ili nepotpunim ovisnim rezultatima: { $count }. Pohranjeni rezultati ažuriraju se.
    *[other] Datoteke sa starijim očitanjima tablica ili nepotpunim ovisnim rezultatima: { $count }. Pohranjeni rezultati ažuriraju se.
    }

processing-update-tables-runs = Čitanje tablica, entiteti, signali, ugrađivanja i oba indeksa
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Datoteke koje trebaju automatski OCR: { $count }. Prethodni OCR tekst na otkrivenom jeziku zadržava se bez novog OCR-a. Ostale stranice dobivaju OCR s instaliranim modelom otkrivenog jezika. Prethodne inačice uklanjaju se kada je zamjena potpuna.
processing-update-ocr-runs = OCR i PDF-ovi s mogućnošću pretraživanja, zatim izdvajanje entiteta, ugrađivanje i indeksiranje novog teksta
processing-update-ocr_detection-title = OCR otkrivanje
processing-update-ocr_detection-explanation = Datoteke bez trenutačnog otkrivanja teksta, pisma ili jezika: { $count }. Svaka prikladna slika i PDF stranica pregledava se u ograničenim skupinama.
processing-update-ocr_detection-runs = Otkrivanje, zatim atributi pretrage ovih datoteka
processing-update-pdf_text-title = Tekst pretraživih PDF-ova
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } datoteka ima pretražive PDF-ove s ranijim slojem teksta.
    [few] { $count } datoteke imaju pretražive PDF-ove s ranijim slojem teksta.
   *[other] { $count } datoteka ima pretražive PDF-ove s ranijim slojem teksta.
} Taj je sloj kopirao svako slovo izvan zapadnoeuropskih abeceda kao crni kvadrat. PDF-ovi jezika sa samo zapadnoeuropskim slovima ostaju nepromijenjeni. Ostali PDF-ovi se čitaju, a dijelovi s crnim kvadratima izrađuju se ponovno. PDF slike koristi spremljene OCR riječi. Stranica PDF-a dobiva novi OCR zahtjev.
processing-update-pdf_text-runs = Dijelovi pretraživih PDF-ova, zatim indeksiranje OCR teksta ponovno izrađenih PDF-ova
processing-update-page_text-title = Indeksirani tekst stranica
processing-update-page_text-explanation = Datoteke s nepotpunim tekstom za pretraživanje: { $count }. Kontrolni znak na stranici prekinuo je njezin indeksirani tekst. Indeksira se cijeli tekst.
processing-update-page_text-runs = Tekst indeksa pretraživanja za ove stranice
processing-update-text_rows-title = Podjela teksta
processing-update-text_rows-explanation = Datoteke s tekstom iz ranije podjele: { $count }. Tekst PDF-a prelazi u jedan redak za svaki dio PDF-a, a dugi tekst dijeli se s kratkim preklapanjem. Ne pokreću se novi OCR ni novo parsiranje.
processing-update-text_rows-runs = Podjela teksta, zatim izdvajanje entiteta, ugrađivanje i indeksiranje novog teksta
processing-update-vectors-title = Vektori
processing-update-vectors-explanation = { $files ->
    [one] { $count } datoteka s tekstom nema vektore modela ugrađivanja koji instalacija poslužuje.
    [few] { $count } datoteke s tekstom nemaju vektore modela ugrađivanja koji instalacija poslužuje.
   *[other] { $count } datoteka s tekstom nema vektore modela ugrađivanja koji instalacija poslužuje.
} Njihovi vektori izračunavaju se i indeksiraju.
processing-update-vectors-runs = Ugrađivanje i indeksiranje vektora
processing-update-folder_counts-title = Brojevi mapa
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } mapa nema broj datoteka ni veličinu ili ima vrijednosti iz ranije verzije.
    [few] { $count } mape nemaju broj datoteka ni veličinu ili imaju vrijednosti iz ranije verzije.
   *[other] { $count } mapa nema broj datoteka ni veličinu ili ima vrijednosti iz ranije verzije.
} Brojevi se ponovno izračunavaju.
processing-update-folder_counts-runs = Stablo mapa
admin-uploads-badge = Prijenosi
admin-uploads-badge-title = Prihvaća prijenose

processing-update-archive_members-title = Članovi arhiva

processing-update-archive_members-explanation = { $files ->
    [one] { $count } podijeljena arhiva treba trenutačan popis članova. Članovi i rezultati pretraživanja ažuriraju se.
    [few] Podijeljene arhive koje trebaju trenutačne popise članova: { $count }. Njihovi članovi i rezultati pretraživanja ažuriraju se.
    *[other] Podijeljene arhive koje trebaju trenutačne popise članova: { $count }. Njihovi članovi i rezultati pretraživanja ažuriraju se.
    }

processing-update-archive_members-runs = Izdvajanje arhiva, usklađivanje članova i ovisna obrada

processing-update-image_previews-title = Pregledi slika

processing-update-image_previews-explanation = { $files ->
    [one] { $count } neuobičajena slika nema pregled. Njezin pregled ponovno se stvara.
    [few] Neuobičajene slike bez pregleda: { $count }. Njihovi pregledi ponovno se stvaraju.
    *[other] Neuobičajene slike bez pregleda: { $count }. Njihovi pregledi ponovno se stvaraju.
    }

processing-update-image_previews-runs = Stvaranje i provjera pregleda slika

processing-update-search_terms-title = Pojmovi pretraživanja

processing-update-search_terms-explanation = { $files ->
    [one] { $count } tablica pretraživanja treba trenutačne pojmove filtara. Pojmovi jezika, OCR-a, pisma i crvenih zastavica postaju pretraživi.
    [few] Tablice pretraživanja koje trebaju trenutačne pojmove filtara: { $count }. Pojmovi jezika, OCR-a, pisma i crvenih zastavica postaju pretraživi.
    *[other] Tablice pretraživanja koje trebaju trenutačne pojmove filtara: { $count }. Pojmovi jezika, OCR-a, pisma i crvenih zastavica postaju pretraživi.
    }

processing-update-search_terms-runs = Indeksiranje i provjera pojmova filtara

automatic-ocr-title = Automatski OCR
automatic-ocr-refresh = Osvježi stanje
automatic-ocr-coverage = Pokrivenost stranica
automatic-ocr-pages = Stranice
automatic-ocr-models = OCR modeli
automatic-ocr-reason = Razlog
automatic-ocr-truncated = Dijagnostički popis nije potpun.
automatic-ocr-presence = Ima objavljen OCR tekst
automatic-ocr-policy = OCR odabire instalirane modele prema otkrivenom pismu i jeziku svake prikladne stranice. Prvo radi Tesseract, a EasyOCR pokriva preostala podržana pisma.
automatic-ocr-unknown = Nema zabilježene trenutačne objave. Nedostatak otkrivanja i neuspjela obrada ne dokazuju odsutnost.
automatic-ocr-retry = Nakon ispravka uzroka upotrijebite ažuriranja obrade za ponavljanje nepotpunog ili neuspjelog rada. Nepodržana pokrivenost zahtijeva kompatibilne instalirane modele.
automatic-ocr-state = { $state ->
    [candidate] Na čekanju
    [planned] Planirano
    [failed] Neuspjelo
    [incomplete] Nepotpuno
    [unsupported] Nepodržano
    [published] Objavljeno
    [applied] Provjereno
    [ready] Otkriven tekst
    [no_text] Tekst nije otkriven
    *[other] { $state }
    }

processing-update-entities-title = Imenovani entiteti
processing-update-entities-explanation = Datoteke koje trebaju trenutačno izdvajanje entiteta ili pretražive rezultate: { $count }. Prethodni uspješni rezultati zamjenjuju se nakon zaključivanja.
processing-update-entities-runs = Izdvajanje imenovanih entiteta, atributi teksta i pretraživi izrazi entiteta

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Pismo nije prepoznato
    [tesseract_capabilities_unavailable] Pokrivenost Tesseracta nije dostupna
    [detected_language] Model odgovara otkrivenom jeziku
    [unknown_language_script_coverage] Nepoznat jezik. Odabran je model pisma.
    [language_script_mismatch_script_coverage] Jezik i pismo razlikuju se. Odabran je model pisma.
    [language_model_unavailable_script_coverage] Jezični model nije dostupan. Odabran je model pisma.
    [easyocr_capabilities_unavailable] Pokrivenost EasyOCR-a nije dostupna
    [tesseract_script_unavailable] Tesseract ne pokriva pismo. Odabran je EasyOCR.
    [script_coverage_unavailable] Nijedan instalirani model ne pokriva ovo pismo.
    *[other] { $reason }
    }

processing-updates-check-requested = Cjevovod izračunava ažuriranja. Brojevi se mijenjaju nakon završetka izračuna.
