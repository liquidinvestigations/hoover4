# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Assistenten jobber …
chat-composer-ask-the-bot = Spør assistenten …
chat-composer-internet-tools = Internettverktøy
chat-composer-agent-language-title = Agenten svarer på { $language }. Endre språket i innstillingene, i en ny fane.
chat-composer-try-again-in-s = Prøv igjen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stopp svaret (det delvise svaret lagres ikke i samtalen)
chat-composer-starting-the-conversation-u = Starter samtalen …
chat-composer-send = Send
chat-conversation-find-search-in-conversation = Søk i samtalen
chat-conversation-find-previous-match = Forrige treff
chat-conversation-find-next-match = Neste treff
chat-conversation-find-investigation-board = Undersøkelsestavle
doc-ref-card-not-openable = Kan ikke åpnes: { $reason }.
doc-ref-card-the-search-term-was = Søkeordet var{" "}
doc-ref-card-open = Åpne
doc-ref-card-not-openable-2 = Kan ikke åpnes
chat-markdown-text-show-the-cited-source = Vis kilden det henvises til
chat-markdown-text-no-citation-of-this-conversation = Ingen kildehenvisning i denne samtalen ga dette henvisningsmerket, så ingen dokumenter ligger bak det.
chat-markdown-text-citations-of-this-conversation-gave = Kildehenvisninger i denne samtalen ga dette henvisningsmerket til mer enn ett dokument, så det lenker til ingen av dem.
cards-browser-card-open-the-archived-page = Åpne den arkiverte siden
cards-browser-card-the-page-itself-was-not = Selve siden ble ikke arkivert (status: { $artifact_status }). Skjermbildet over er det som ble beholdt.
cards-browser-card-click-the-screenshot-to-open = Klikk på skjermbildet for å åpne den arkiverte siden.
cards-browser-card-show-less = Vis mindre
cards-browser-card-show-all = Vis alle
cards-browser-card-archived-page = Arkivert side
cards-browser-card-download = Last ned
cards-browser-card-archived-copy-of = Arkivert kopi av { $artifact_url }
cards-browser-card-this-page-was-not-archived = Denne siden ble ikke arkivert (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med kort
cards-entities-card-the-entity-list-was-cut = Entitetslisten ble avkortet.
cards-entities-card-open-the-card-for-this = Åpne kortet for denne verdien ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Ikke noe kort: denne samtalen nevnte aldri datasettet disse verdiene kom fra, og visningen adresseres etter datasett.
cards-entities-card-more-all-of-them-in = { $rest } til, alle i dokumentets entitetspanel.{" "}
cards-entities-card-names-organisations-and-places-above = Navn, organisasjoner og steder over er en models tolkning av teksten. Ingen regel har validert dem, så det er ingenting å forklare, og de åpner ingenting.
cards-entities-card-nothing-extracted-from-this-document = Ingenting er hentet ut fra dette dokumentet.
chat-tool-cards-hide = Skjul
chat-tool-cards-expand = Utvid
chat-tool-cards-hide-raw-json = Skjul rå JSON
chat-tool-cards-show-raw-json = Vis rå JSON
cards-result-cards-search-this = Søk i denne
cards-result-cards-search-every-collection = Søk i alle samlinger
cards-result-cards-form = Form { $index }: { $form }
cards-result-cards-show-full-text = Vis hele teksten
cards-result-cards-quote = Sitat: { $quote }
cards-result-cards-reason = Begrunnelse: { $why }
cards-result-cards-open-question = Åpent spørsmål: { $question }
cards-result-cards-the-explore-gave-this-answer = Utforskningen ga dette svaret til tavlen som { $kind ->
        [sourced] et funn med kilde
        [inferred] et utledet funn
        [not_found] et funn om at noe ikke ble funnet
       *[other] et funn av ukjent type
    }.
cards-result-cards-it-left-no-open-question = Den etterlot ikke noe åpent spørsmål.
cards-result-cards-open-questions-for-the-board = Åpne spørsmål for tavlen:
cards-result-cards-arguments = Argumenter
cards-result-cards-list-after-the-call = Liste etter kallet: { $snapshot_goal }
cards-result-cards-replaces = {" "}· erstatter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listen i denne versjonen er ikke lagret.
web-search-card-these-sources-returned-nothing-so = Disse kildene ga ingenting, så resultatene kommer fra færre kilder enn tiltenkt
web-search-card-u-degraded = ⚠ { $degraded_len } svekket
web-search-card-form = Form { $index }: { $form }
web-search-card-no-results-from = Ingen resultater fra: { $degraded_text }
web-search-card-no-results-every-source-answered = Ingen resultater. Alle kilder svarte, og ingen av dem hadde noe for dette søket.
web-search-card-the-lowest-ranked-results-were = De lavest rangerte resultatene ble utelatt slik at dette kallet får plass i transkripsjonen. Assistenten så alle sammen.
web-search-card-view-search-details = Vis søkedetaljer.
web-search-card-the-stored-result-could-not = det lagrede resultatet kunne ikke leses tilbake som JSON
web-search-card-nothing-was-stored-for-this = Ingenting ble lagret for dette kallet.
web-search-card-forms = Former: { $forms }
web-search-card-kind = Type: { $row_kind }
web-search-card-published = Publisert: { $row_published }
web-search-card-loading-search-detail-u = Laster søkedetaljer …
web-search-card-could-not-load-the-search = Kunne ikke laste søkedetaljene: { $e }
web-search-card-malformed-detail = Ugyldig detalj: { $e }
web-search-card-the-tool-returned-selected-results = Verktøyet ga utvalgte resultater til modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultatene bruker reciprocal rank fusion.
web-search-card-returned-nothing = ga ingenting: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidatene bruker fusjonsrekkefølge.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoderen rangerer utvalgte resultater.
web-search-card-selected-results-use-fusion-order = Utvalgte resultater bruker fusjonsrekkefølge.
web-search-card-search-detail = Søkedetaljer
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Søk i denne
chat-tool-disclosure-search-every-collection = Søk i alle samlinger
chat-tool-disclosure-hide = Skjul
chat-tool-disclosure-expand = Utvid
chat-tool-disclosure-this-step-was-recorded-before = Dette trinnet ble registrert før verktøyargumenter og resultater ble lagret. Bare sammendraget under er tilgjengelig.
chat-tool-disclosure-arguments = Argumenter
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Skjul rå JSON
chat-tool-disclosure-show-raw-json = Vis rå JSON
chat-tool-disclosure-input-json = Inndata-JSON
chat-tool-disclosure-output-json = Utdata-JSON
chat-transcript-ask-a-question-about-the = Still et spørsmål om dokumentene i samlingene dine.
chat-transcript-suggested-next = Foreslått videre …
chat-transcript-earlier-answer = Tidligere svar
chat-transcript-tokens-the-conversation-carries-the = Tokens samtalen bærer, den største enkeltkonteksten denne omgangen ble fakturert for, og hvor mye av modellens vindu det brukte
chat-transcript-instruction-to-the-agent = Instruks til agenten
chat-transcript-the-context-stays-above-the = {" "}Konteksten holder seg over målet på { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } sammendragsdeler mislyktes. Opptegnelsen inneholder bare listene.
chat-transcript-show-the-record = Vis opptegnelsen
chat-transcript-hide-reasoning = Skjul resonnering
chat-transcript-show-reasoning = Vis resonnering
chat-transcript-from-u-hide = { $count } { $count ->
        [one] dokument
       *[other] dokumenter
    } fra { $tool } – skjul
chat-transcript-from-u-show = { $count } { $count ->
        [one] dokument
       *[other] dokumenter
    } fra { $tool } – vis
chat-transcript-u-hide = { $summary } – skjul
chat-transcript-u-show = { $summary } – vis
chat-transcript-citations-of-this-conversation-give = Kildehenvisninger i denne samtalen gir { $doc_handle } til mer enn ett dokument. Svaret lenker det ikke til noen av dem.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Åpne i arbeidsområdet
chat-transcript-this-version-could-not-be = Denne versjonen kunne ikke leses. Chat-teksten i svaret følger.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, versjon { $file_version }
chat-web-find-exact-text = Finn nøyaktig tekst
chat-web-previous-match = Forrige treff
chat-web-next-match = Neste treff
chat-web-close-preview = Lukk forhåndsvisningen
chat-web-the-captured-page-could-not = Den arkiverte siden kunne ikke lastes.
chat-web-loading = Laster …
chat-workspace-pane-workspace = Arbeidsområde
chat-workspace-pane-close-the-workspace = Lukk arbeidsområdet
chat-workspace-pane-close = Lukk
chat-workspace-pane-loading-the-files-u = Laster filene …
chat-workspace-pane-the-files-could-not-be = Filene kunne ikke lastes: { $error }
chat-workspace-pane-this-conversation-has-no-files = Denne samtalen har ingen filer.
chat-workspace-pane-version = versjon { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Velg en fil for å lese den.
chat-workspace-pane-loading-the-file-u = Laster filen …
chat-workspace-pane-the-file-could-not-be = Filen kunne ikke lastes: { $error }
chat-workspace-pane-version-2 = { $found_name }, versjon { $found_version }
chat-board-create-collections = Samlinger
chat-board-create-loading-collections-u = Laster samlinger …
chat-board-create-hoover-search-new-board = Hoover Search – Ny tavle
chat-board-create-ai-chat = AI-chat
chat-board-create-new-investigation-board = Ny undersøkelsestavle
chat-board-create-a-board-runs-its-goals = En tavle kjører målene sine som en rekke agentutforskninger. Hver utforskning er en samtale som ender i ett tavlefunn. Du gjennomgår svaret på hvert mål, og du kan avvise funn og legge til hint mens den kjører.
chat-board-create-title = Tittel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Fjern dette målet
chat-board-create-remove = Fjern
chat-board-create-add-a-goal = Legg til et mål
chat-board-create-context-optional = Kontekst (valgfritt)
chat-board-create-hints-one-per-line-optional = Hint, ett per linje (valgfritt)
chat-board-create-sources = Kilder
chat-board-create-internet-tools = Internettverktøy
chat-board-create-creating-board = Oppretter tavle …
chat-board-create-create-board = Opprett tavle
ai-chat-board-hoover-search-board = Hoover Search – Tavle
ai-chat-board-loading-the-board-u = Laster tavlen …
ai-chat-board-show-the-board-overview = Vis tavleoversikten
ai-chat-board-zoom-out = Zoom ut
ai-chat-board-zoom-in = Zoom inn
ai-chat-board-u-ai-chat = ← AI-chat
ai-chat-board-settings = Innstillinger
ai-chat-board-board-settings = Tavleinnstillinger
ai-chat-board-internet-tools = Internettverktøy
ai-chat-board-the-next-explores-of-the = De neste utforskningene på tavlen kan søke på nettet og lese nettsider. Utforskninger som kjører, beholder innstillingen de startet med.
ai-chat-board-collections = Samlinger
ai-chat-board-the-collections-are-fixed-when = Samlingene låses når tavlen opprettes.
ai-chat-board-confirm-drop = Bekreft forkasting
ai-chat-board-drop-the-board = Forkast tavlen
ai-chat-board-close = Lukk
ai-chat-board-the-board-used-its-explore = Tavlen brukte opp grensen for utforskninger
ai-chat-board-the-board-used-explores-the = Tavlen brukte { $explore_limit } utforskninger, grensen for én tavle. Den starter ikke mer arbeid. Du kan fortsatt avgjøre de foreslåtte svarene.
ai-chat-board-create-a-new-board-to = Opprett en ny tavle for å fortsette undersøkelsen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Legg til nytt mål …
ai-chat-board-a-new-goal = Et nytt mål
ai-chat-board-add-goal = Legg til mål
ai-chat-board-a-board-has-at-most = En tavle har høyst { $max_goals } mål. Opprett en ny tavle for et nytt mål.
ai-chat-board-background-context = Bakgrunnskontekst
ai-chat-board-continue-with-a-correction = Fortsett med en korreksjon
ai-chat-board-correction-what-is-wrong-or = Korreksjon: hva som er feil eller mangler. Tavlen fortsetter med den.
ai-chat-board-the-board-waits-for-your = Tavlen venter på gjennomgangen din
ai-chat-board-the-board-used-its-budget = Tavlen brukte budsjettet sitt på { $snap_max_explores } utforskninger.
ai-chat-board-the-assessments-gave-no-usable = Vurderingene ga ingen brukbar retning.
ai-chat-board-accept-or-reject-the-proposed = Godta eller avvis det foreslåtte svaret for hvert mål over. Et avvist svar lar tavlen fortsette med en gang.
ai-chat-board-no-proposed-answer-waits-for = Ingen foreslåtte svar venter på avgjørelsen din.
ai-chat-board-reopen-the-board-to-continue = Åpne tavlen på nytt for å fortsette med de åpne målene. Den beholder funnene og svarene sine.
ai-chat-board-close-the-board-to-accept = Lukk tavlen for å godta alle foreslåtte svar og stoppe den, eller fortsett den med en korreksjon.
ai-chat-board-close-the-board = Lukk tavlen
ai-chat-board-or-reopen-the-board-to = Eller åpne tavlen på nytt for å fortsette med de åpne målene uten en korreksjon.
ai-chat-board-the-board-is-complete = Tavlen er fullført
ai-chat-board-a-goal-has-no-accepted = Et mål har ikke noe godtatt svar. Åpne tavlen på nytt for å fortsette. Tavlen beholder funnene og svarene sine.
ai-chat-board-add-a-hint = Legg til et hint
ai-chat-board-the-next-assessment-reads-every = Den neste vurderingen leser alle hint. Et hint besvarer også en utforskning som stilte et spørsmål.
ai-chat-board-add-hint = Legg til hint
ai-chat-board-events = Hendelser
ai-chat-board-newest-first = Nyeste først
ai-chat-board-date = Dato
ai-chat-board-actor = Aktør
ai-chat-board-event = Hendelse
ai-chat-board-show-details = Vis detaljer
ai-chat-board-open = Åpne
ai-chat-board-show-the-newest-events = Vis de nyeste { $event_rows } hendelsene
ai-chat-board-show-all-events = Vis alle { $snap_events_len } hendelser
ai-chat-board-statistics = Statistikk
ai-chat-board-explores = Utforskninger
ai-chat-board-model-steps-per-explore = Modelltrinn per utforskning
ai-chat-board-assessments = Vurderinger
ai-chat-board-intents = Hensikter
ai-chat-board-findings = Funn
ai-chat-board-created = Opprettet
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } avviste dette funnet { $format_utc_ms_fact_rejected_ms }. Tavlen bruker det ikke lenger.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } avviste dette funnet. Tavlen bruker det ikke lenger.
ai-chat-board-no-reason-was-given = Ingen begrunnelse ble oppgitt.
ai-chat-board-reason = Begrunnelse: { $fact_rejected_reason }
ai-chat-board-open-questions = Åpne spørsmål
ai-chat-board-explored-in = Utforsket i{" "}
ai-chat-board-explore-this-question = Utforsk dette spørsmålet
ai-chat-board-your-questions = Spørsmålene dine
ai-chat-board-ask-about-the-background-context = Spør om bakgrunnskonteksten
ai-chat-board-ask-about-this-finding = Spør om dette funnet
ai-chat-board-a-follow-up-question-about = Et oppfølgingsspørsmål om denne noden
ai-chat-board-ask = Spør
ai-chat-board-checks-that-changed-this-finding = Kontroller som endret dette funnet
ai-chat-board-reject-this-correction = Avvis denne korreksjonen
ai-chat-board-reject-this-finding = Avvis dette funnet
ai-chat-board-not-answered-the-board-was = Ikke besvart. Tavlen ble ferdigstilt uten svar på dette målet. Et hint eller en gjenåpning åpner det igjen.
ai-chat-board-no-answer-yet = Ikke noe svar ennå.
ai-chat-board-the-findings-of-this-answer = Funnene i dette svaret er søk som ikke fant noe. Godta det for å registrere at dokumentene ikke besvarer målet, eller avvis det for å fortsette undersøkelsen.
ai-chat-board-open-an-assessment-to-read = {"."} Åpne en vurdering for å lese hvorfor.
ai-chat-board-from-the-findings = Fra funnene{" "}
ai-chat-board-accept-answer = Godta svaret
ai-chat-board-why-the-answer-is-wrong = Hvorfor svaret er feil eller ufullstendig
ai-chat-board-reject-answer = Avvis svaret
ai-chat-board-intent = Hensikt
ai-chat-board-attempts-declared = Forsøk: { $intent_attempts }. Erklært { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Utforskningen spurte
ai-chat-board-add-a-hint-in-the = Legg til et hint i tavleoversikten for å besvare det.
ai-chat-board-last-error = Siste feil
ai-chat-board-brief = Oppdrag
ai-chat-board-open-the-explore-chat = Åpne utforskningssamtalen
ai-chat-board-loading-the-assessment-u = Laster vurderingen …
ai-chat-board-assessment = Vurdering { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Utfall { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Kontroller som endret det
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Denne vurderingen kjørte før promptene ble lagret.
ai-chat-board-response = Respons
ai-chat-history-hoover-search-chat-history = Hoover Search – Samtalehistorikk
ai-chat-history-u-back = ← Tilbake
ai-chat-history-conversation-history = Samtalehistorikk
ai-chat-history-show-board-chats = Vis tavlesamtaler
ai-chat-history-loading-u = Laster …
ai-chat-history-could-not-load-history = Kunne ikke laste historikken: { $e }
ai-chat-history-no-conversations-yet = Ingen samtaler ennå.
ai-chat-history-board = Tavle
ai-chat-history-new-chat = Ny samtale
ai-chat-history-messages-updated = { $s_message_count } meldinger · oppdatert { $s_updated_at }
ai-chat-history-delete-conversation = Slett samtalen
ai-chat-history-delete = Slett
ai-chat-homepage-hoover-search-ai-chat = Hoover Search – AI-chat
ai-chat-homepage-what-are-you-researching = Hva undersøker du?
ai-chat-homepage-view-all-conversations = Vis alle samtaler
ai-chat-homepage-starting-conversation-u = Starter samtalen …
ai-chat-homepage-investigation-boards = Undersøkelsestavler
ai-chat-homepage-new-board = Ny tavle
ai-chat-homepage-loading-boards-u = Laster tavler …
ai-chat-homepage-could-not-load-the-boards = Kunne ikke laste tavlene: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har ingen tavle. En tavle kjører en lang undersøkelse som en rekke agentutforskninger, og du gjennomgår svarene.
ai-chat-homepage-updated = Oppdatert { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search – AI-chat
ai-chat-session-this-conversation-could-not-be = Denne samtalen kunne ikke lastes.
ai-chat-session-loading-u = Laster …
ai-chat-session-u-chats = ← Samtaler
ai-chat-session-history = Historikk
ai-chat-session-show-the-files-that-the = Vis filene assistenten skrev i denne samtalen
ai-chat-session-workspace = Arbeidsområde
ai-chat-session-this-answer-was-interrupted-before = Dette svaret ble avbrutt før det var ferdig, fordi siden eller tjeneren stoppet midt i omgangen. Spør på nytt for å prøve igjen.
ai-chat-session-dismiss = Lukk
ai-chat-session-board-explore-chats-are-read = Utforskningssamtaler på tavler er skrivebeskyttet.{" "}
ai-chat-session-open-the-board = Åpne tavlen
chat-locked-options-on = { $label }: på
chat-locked-options-off = { $label }: av
chat-tool-cards-running-u = kjører …
cards-result-cards-quote-found = Sitat funnet
cards-result-cards-quote-not-found = Sitat ikke funnet
cards-result-cards-quote-not-checked = Sitat ikke kontrollert
web-search-card-results = { $results_len } resultater
chat-tool-disclosure-running-u = kjører …
chat-transcript-call = kall
chat-transcript-calls = kall
ai-chat-board-a-board-without-collections-needs = En tavle uten samlinger trenger internettverktøy.
ai-chat-board-of = { $snap_explores_used } av { $snap_max_explores }
ai-chat-board-assessment-2 = vurdering { $number }
ai-chat-history-messages = { $s_message_count } meldinger
web-search-card-reranked-in = Cross-encoderen rangerte resultatene på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = poengsum { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Omgangen venter på en ledig modellplass.
chat-activity-the-turn-waits-for-a-2 = Omgangen venter på en ledig verktøyplass.
chat-locked-options-start-a-new-chat-to = Start en ny samtale for å endre denne innstillingen.
chat-locked-options-internet-tools = Internettverktøy
chat-session-card-new-chat = Ny samtale
chat-tool-cards-first-frame-of-the-video = Første bilde i videoen
chat-tool-cards-screenshot-of = Skjermbilde av
chat-tool-cards-image = Bilde
cards-result-cards-the-agent-asked-a-question = Agenten stilte et spørsmål.
chat-transcript-hide = Skjul
chat-transcript-show = Vis
chat-transcript-unverified-quote-the-quoted-span = Ubekreftet sitat. Det siterte utdraget er for kort til å kontrolleres.
chat-transcript-unverified-quote-the-document-text = Ubekreftet sitat. Dokumentteksten kunne ikke leses.
chat-transcript-unverified-quote-this-wording-was = Ubekreftet sitat. Denne ordlyden ble ikke funnet i dokumentet.
chat-board-create-select-a-collection-or-turn = Velg en samling eller slå på internettverktøy.
chat-board-create-select-at-least-one-collection = Velg minst én samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = På pause
ai-chat-board-waits-for-review = Venter på gjennomgang
ai-chat-board-completed = Fullført
ai-chat-board-dropped = Forkastet
ai-chat-board-unknown = Ukjent
ai-chat-board-pause-the-board = Sett tavlen på pause
ai-chat-board-resume-the-board = Gjenoppta tavlen
ai-chat-board-none = Ingen
ai-chat-board-reopen-with-the-remaining-budget = Åpne på nytt med gjenværende budsjett
ai-chat-board-finding = Funn
ai-chat-board-why-the-correction-is-wrong = Hvorfor korreksjonen er feil
ai-chat-board-reject-correction = Avvis korreksjonen
ai-chat-board-why-the-finding-is-wrong = Hvorfor funnet er feil
ai-chat-board-reject-finding = Avvis funnet
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Foreslått svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = På pause
ai-chat-homepage-waits-for-review = Venter på gjennomgang
ai-chat-homepage-completed = Fullført
ai-chat-homepage-dropped = Forkastet
ai-chat-homepage-unknown = Ukjent
cards-result-cards-submitted-by-board = Sendt inn av tavlen: { $kind ->
        [sourced] et funn med kilde
        [inferred] et utledet funn
        [not_found] et funn om at noe ikke ble funnet
       *[other] et funn av ukjent type
    } fra rapporten
cards-result-cards-finding-for-board = { $kind ->
        [sourced] Et funn med kilde
        [inferred] Et utledet funn
        [not_found] Et funn om at noe ikke ble funnet
       *[other] Et funn av ukjent type
    } for tavlen
chat-transcript-compacting = Komprimerer konteksten: { $before } tokens til et mål på { $target }.
chat-transcript-compaction-failed = Sammendraget av de tidligere trinnene mislyktes. Modellen fikk de tidligere trinnene uendret, { $after } tokens.
chat-transcript-compacted = Konteksten er komprimert: { $steps } trinn oppsummert, { $before } tokens til { $after }.
ai-chat-board-reopen-with-more = Åpne på nytt med { $grant } utforskninger til
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Fra vurdering { $number } den { $date }.
ai-chat-board-from-assessment = Fra vurdering { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = mistet kontakten med samtalen: { $e }
ai-chat-session-could-not-stop-the-answer = kunne ikke stoppe svaret: { $e } – det kjører fortsatt
ai-chat-board-later-assessments-dropped-an-answer = { $n } senere vurderinger forkastet et svar for dette målet:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt- og { $a_completion_tokens } completion-tokens
ai-chat-homepage-completed-goals-not-answered = Fullført, { $n } mål uten svar
board-graph-intent = hensikt, { $state }
chat-workspace-pane-characters = { $chars } tegn
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } pågående verktøy{ $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } pågående verktøy{ $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt =
    Besvart etter { $retries_len ->
        [one] { $retries_len } mislykket forsøk
       *[other] { $retries_len } mislykkede forsøk
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt =
    { $retries_len ->
        [one] { $retries_len } mislykket forsøk
       *[other] { $retries_len } mislykkede forsøk
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, versjon { $report_version }
tool-run-summary-searched = { $n ->
        [one] søkte etter { $n } term
       *[other] søkte etter { $n } termer
    }
tool-run-summary-read = { $n ->
        [one] leste { $n } dokument
       *[other] leste { $n } dokumenter
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] søkte på nettet etter { $n } term
       *[other] søkte på nettet etter { $n } termer
    }
tool-run-summary-read-web = { $n ->
        [one] leste { $n } nettside
       *[other] leste { $n } nettsider
    }
tool-run-summary-browser = { $n ->
        [one] { $n } nettleserhandling
       *[other] { $n } nettleserhandlinger
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] listet opp entitetene i { $n } dokument
       *[other] listet opp entitetene i { $n } dokumenter
    }
tool-run-summary-cited = { $n ->
        [one] henviste til { $n } dokument
       *[other] henviste til { $n } dokumenter
    }
tool-run-summary-cited-web = { $n ->
        [one] henviste til { $n } nettside
       *[other] henviste til { $n } nettsider
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] leste { $n } ferdighet og verktøytekster
       *[other] leste { $n } ferdigheter og verktøytekster
    }
tool-run-summary-saved = { $n ->
        [one] lagret { $n } notat
       *[other] lagret { $n } notater
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } kall til gjøremålslisten
       *[other] { $n } kall til gjøremålslisten
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instruks til agenten
       *[other] { $n } instrukser til agenten
    }
tool-run-summary-other = { $n ->
        [one] { $n } annet kall
       *[other] { $n } andre kall
    }
tool-run-summary-failed = { $failures } mislyktes
tool-run-summary-took = tok { $duration_text_ms }
chat-session-card-messages = { $session_message_count } meldinger
chat-tool-disclosure-item = { $count ->
        [one] { $count } element
       *[other] { $count } elementer
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } felt
       *[other] { $count } felt
    }
chat-tool-disclosure-searched-collections = søkte i samlinger{ $filters }
chat-tool-disclosure-searched-collections-2 = søkte i samlinger · { $query }{ $filters }
chat-tool-disclosure-cited-documents = henviste til { $n } dokumenter
chat-tool-disclosure-read-document = leste dokument · { $path }
chat-tool-disclosure-searched-the-web = søkte på nettet · { $q }
chat-tool-disclosure-opened-page = åpnet side · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = kalte { $other }
chat-tool-disclosure-called-2 = kalte { $other } · { $short }
cards-browser-card-opened = åpnet { $url }
cards-browser-card-could-not-open = kunne ikke åpne { $url }
cards-browser-card-clicked = klikket på { $element }
cards-browser-card-could-not-click = kunne ikke klikke på { $element }
cards-browser-card-typed-into = skrev i { $element }
cards-browser-card-could-not-type-into = kunne ikke skrive i { $element }
cards-browser-card-typed = skrev «{ $text }»
cards-browser-card-could-not-type = kunne ikke skrive «{ $text }»
cards-browser-card-pressed = trykket { $key }
cards-browser-card-could-not-press = kunne ikke trykke { $key }
cards-browser-card-chose-an-option-in = valgte et alternativ i { $element }
cards-browser-card-could-not-choose-an-option = kunne ikke velge et alternativ i { $element }
cards-browser-card-hovered = holdt musepekeren over { $element }
cards-browser-card-could-not-hover = kunne ikke holde musepekeren over { $element }
cards-browser-card-failed = { $bare } – mislyktes
cards-entities-card-listed-entities-document =
    listet opp entiteter · { $count ->
        [one] { $count } dokument
       *[other] { $count } dokumenter
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · del { $part } av { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } dokumenter
cards-result-cards-forms = { $tool_name } · { $forms } former
cards-result-cards-in = {" "}i { $collections }
cards-result-cards-page = {" "}· side { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenter · { $missing } sitater ikke funnet
cards-result-cards-version-unchanged = { $tool_name } · versjon { $version } · uendret
cards-result-cards-version = { $tool_name } · versjon { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultater inn, { $json_u64_doc_total_after_dedupe } etter fjerning av duplikater
