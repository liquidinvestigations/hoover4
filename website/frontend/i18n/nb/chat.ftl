# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Botarbeid pågår…
chat-composer-ask-the-bot = Still spørsmål til boten…
chat-composer-internet-tools = Internettverktøy
chat-composer-agent-language-title = Agenten svarer på { $language }. Endre språket i innstillingene, i en ny fane.
chat-composer-try-again-in-s = Prøv igjen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stopp svaret (delsvaret lagres ikke i samtalen)
chat-composer-starting-the-conversation-u = Starter samtalen…
chat-composer-send = Send
chat-conversation-find-search-in-conversation = Søk i samtalen
chat-conversation-find-previous-match = Forrige treff
chat-conversation-find-next-match = Neste treff
chat-conversation-find-investigation-board = Undersøkelsestavle
doc-ref-card-not-openable = Kan ikke åpnes: { $reason }.
doc-ref-card-the-search-term-was = Søketermen var{ " " }
doc-ref-card-open = Åpne
doc-ref-card-not-openable-2 = Kan ikke åpnes
chat-markdown-text-show-the-cited-source = Vis den siterte kilden
chat-markdown-text-no-citation-of-this-conversation = Ingen sitat i denne samtalen ga denne referansen, så det står inget dokument bak.
chat-markdown-text-citations-of-this-conversation-gave = Sitater i denne samtalen ga denne referansen til mer enn ett dokument, så den lenker til ingen av dem.
cards-browser-card-open-the-archived-page = Åpne den arkiverte siden
cards-browser-card-the-page-itself-was-not = Siden i seg selv ble ikke arkivert (status: { $artifact_status }). Skjermbildet over er det som ble beholdt.
cards-browser-card-click-the-screenshot-to-open = Klikk på skjermbildet for å åpne den arkiverte siden.
cards-browser-card-show-less = Vis mindre
cards-browser-card-show-all = Vis alle
cards-browser-card-archived-page = Arkivert side
cards-browser-card-download = Nedlast
cards-browser-card-archived-copy-of = Arkivert kopi av { $artifact_url }
cards-browser-card-this-page-was-not-archived = Denne siden ble ikke arkivert (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med et kort
cards-entities-card-the-entity-list-was-cut = Entitetslista ble kappet av.
cards-entities-card-open-the-card-for-this = Åpne kortet for denne verdien ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Ingen kort: denne samtalen nevnte aldri hvilket datasett disse verdiene kom fra, og visningen refererer til datasettet.
cards-entities-card-more-all-of-them-in = { $rest } til, alle i dokumentets enhetspanel.
cards-entities-card-names-organisations-and-places-above = Navn, organisasjoner og steder over er modellens tolkning av teksten. Ingen regel validerte dem, så det er ingenting å forklare og de åpner ingenting.
cards-entities-card-nothing-extracted-from-this-document = Ingenting ekstrahert fra dette dokumentet.
chat-tool-cards-hide = Skjul
chat-tool-cards-expand = Utvid
chat-tool-cards-hide-raw-json = Skjul rå JSON
chat-tool-cards-show-raw-json = Vis rå JSON
cards-result-cards-search-this = Søk her
cards-result-cards-search-every-collection = Søk i alle samlinger
cards-result-cards-form = Skjema { $index }: { $form }
cards-result-cards-show-full-text = Vis full tekst
cards-result-cards-quote = Sitat: { $quote }
cards-result-cards-reason = Grunn: { $why }
cards-result-cards-open-question = Åpent spørsmål: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Utforskingen ga denne svaret til tavlen sin som { $kind ->
        [sourced] en kildefinnings
        [inferred] en avlet innings
        [not_found] en ikke-funnet
       *[other] en ukjent type
    } finning.
cards-result-cards-it-left-no-open-question = Den etterlot ingen åpent spørsmål.
cards-result-cards-open-questions-for-the-board = Åpne spørsmål for tavlen:
cards-result-cards-arguments = Argumenter
cards-result-cards-list-after-the-call = Liste etter kall: { $snapshot_goal }
cards-result-cards-replaces = · erstatter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listen ved denne versjonen er ikke lagret.
web-search-card-these-sources-returned-nothing-so = Disse kildene returnerte ingenting, så resultatene kommer fra færre enn tiltalt
web-search-card-u-degraded = ⚠ { $degraded_len } nedbrutt
web-search-card-form = Skjema { $index }: { $form }
web-search-card-no-results-from = Ingen resultater fra: { $degraded_text }
web-search-card-no-results-every-source-answered = Ingen resultater. Alle kilder svarte og ingen av dem hadde noe for denne forespørselen.
web-search-card-the-lowest-ranked-results-were = De lavest rangerte resultatene ble fjernet så dette kall passer i transkriptet. Assistenten så på alle av dem.
web-search-card-view-search-details = Vis søkedetaljer.
web-search-card-the-stored-result-could-not = det lagrede resultatet kunne ikke leses tilbake som JSON
web-search-card-nothing-was-stored-for-this = Det ble ikke lagret noe for denne kall.
web-search-card-forms = Skjema: { $forms }
web-search-card-kind = Type: { $row_kind }
web-search-card-published = Publisert: { $row_published }
web-search-card-loading-search-detail-u = Last inn søkedetaljer…
web-search-card-could-not-load-the-search = Kunne ikke laste søkedetaljene: { $e }
web-search-card-malformed-detail = Feilaktig formatert detalj: { $e }
web-search-card-the-tool-returned-selected-results = Verktøyet returnerte utvalgte resultater til modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultatene bruker gjensidig rangeringsfusjon.
web-search-card-returned-nothing = returnerte ingenting: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidater bruker fusjonsorden.
web-search-card-the-cross-encoder-ranks-selected = Kryss-encoderen rangerer utvalgte resultater.
web-search-card-selected-results-use-fusion-order = Utvalgte resultater bruker fusjonsorden.
web-search-card-search-detail = Søkedetaljer
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Søk her
chat-tool-disclosure-search-every-collection = Søk i alle samlinger
chat-tool-disclosure-hide = Skjul
chat-tool-disclosure-expand = Utvid
chat-tool-disclosure-this-step-was-recorded-before = Dette steget ble registrert før argumenter og resultater fra verktøyet ble lagret. Kun oppsummeringen under er tilgjengelig.
chat-tool-disclosure-arguments = Argumenter
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Skjul rå JSON
chat-tool-disclosure-show-raw-json = Vis rå JSON
chat-tool-disclosure-input-json = Inndata-JSON
chat-tool-disclosure-output-json = Utdata-JSON
chat-transcript-ask-a-question-about-the = Still et spørsmål om dokumentene i samlingene dine.
chat-transcript-suggested-next = Foreslått neste...
chat-transcript-earlier-answer = Tidligere svar
chat-transcript-tokens-the-conversation-carries-the = Tokener samtalen fører, det største enkeltkonteksten denne omgangen ble fakturert for, og hvor mye av modellens vindu som ble brukt
chat-transcript-instruction-to-the-agent = Instruks til agenten
chat-transcript-the-context-stays-above-the = { " " }Konteksten blir over målet for { $target }.
chat-transcript-summary-parts-failed-the-record = { " " }{ $failed } sammendragsdeler feilet. Posten inneholder kun listene.
chat-transcript-show-the-record = Vis posten
chat-transcript-hide-reasoning = Skjul resonnement
chat-transcript-show-reasoning = Vis resonnement
chat-transcript-from-u-hide = { $count } { $noun } fra { $tool } — skjul
chat-transcript-from-u-show = { $count } { $noun } fra { $tool } — vis
chat-transcript-u-hide = { $summary } — skjul
chat-transcript-u-show = { $summary } — vis
chat-transcript-citations-of-this-conversation-give = Sitater fra denne samtalen gir { $doc_handle } til mer enn ett dokument. Svaret knytter det til ingen av dem.
chat-transcript-report = Rapporter { $label }
chat-transcript-open-in-the-workspace = Åpne i arbeidsområdet
chat-transcript-this-version-could-not-be = Denne versjonen kunne ikke leses. Chatteksten til svaret følger.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, versjon { $file_version }
chat-web-find-exact-text = Finn nøyaktig tekst
chat-web-previous-match = Forrige treff
chat-web-next-match = Neste treff
chat-web-close-preview = Lukk forhåndsvisning
chat-web-the-captured-page-could-not = Den fangede siden kunne ikke lastes inn.
chat-web-loading = Lastes inn…
chat-workspace-pane-workspace = Arbeidsområde
chat-workspace-pane-close-the-workspace = Lukk arbeidsområdet
chat-workspace-pane-close = Lukk
chat-workspace-pane-loading-the-files-u = Laster inn filene…
chat-workspace-pane-the-files-could-not-be = Filene kunne ikke lastes inn: { $error }
chat-workspace-pane-this-conversation-has-no-files = Denne samtalen har ingen filer.
chat-workspace-pane-version = versjon { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Velg en fil for å lese den.
chat-workspace-pane-loading-the-file-u = Last inn filen…
chat-workspace-pane-the-file-could-not-be = Filen kunne ikke lastes inn: { $error }
chat-workspace-pane-version-2 = { $found_name }, versjon { $found_version }
chat-board-create-collections = Samlinger
chat-board-create-loading-collections-u = Loader samlinger…
chat-board-create-hoover-search-new-board = Hoover-søk – ny tavle
chat-board-create-ai-chat = AI-samtale
chat-board-create-new-investigation-board = Ny undersøkelsestavle
chat-board-create-a-board-runs-its-goals = En tavle gjennomfører målene som en sekvens av agent-utforskinger. Hver utforsking er en samtale som ender i én tavlefinning. Du gjennomser svaret på hvert mål, og du kan avviste funn og legge til hints mens den kjører.
chat-board-create-title = Tittel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Fjern dette målet
chat-board-create-remove = Fjern
chat-board-create-add-a-goal = Legg til et mål
chat-board-create-context-optional = Kontekst (valgfritt)
chat-board-create-hints-one-per-line-optional = Veiledninger, en per linje (valgfritt)
chat-board-create-sources = Kilder
chat-board-create-internet-tools = Internettverktøy
chat-board-create-creating-board = Oppretter tavle…
chat-board-create-create-board = Opprett tavle
ai-chat-board-hoover-search-board = Hoover-søk – tavle
ai-chat-board-loading-the-board-u = Loader tavle…
ai-chat-board-show-the-board-overview = Vis tavleoversikt
ai-chat-board-zoom-out = Zoom ut
ai-chat-board-zoom-in = Zoom inn
ai-chat-board-u-ai-chat = ← AI-samtale
ai-chat-board-settings = Innstillinger
ai-chat-board-board-settings = Tavleinnstillinger
ai-chat-board-internet-tools = Internettverktøy
ai-chat-board-the-next-explores-of-the = De neste utforskingene til tavlen kan søke på nettet og lese nettsider. Kjørende utforskinger beholder innstillingen de startet med.
ai-chat-board-collections = Samlinger
ai-chat-board-the-collections-are-fixed-when = Samlingene er fastlåst når tavlen opprettes.
ai-chat-board-confirm-drop = Bekreft slipp
ai-chat-board-drop-the-board = Slipp tavlen
ai-chat-board-close = Lukk
ai-chat-board-the-board-used-its-explore = Tavlen brukte utforskningsgrenen sin
ai-chat-board-the-board-used-explores-the = Tavlen brukte { $explore_limit } utforskinger, som er grensen for én tavle. Den starter ingen mer arbeid. Du kan fortsatt bestemme de foreslåte svarene.
ai-chat-board-create-a-new-board-to = Opprett en ny tavle for å fortsette undersøkelsen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Legg til nytt mål...
ai-chat-board-a-new-goal = Et nytt mål
ai-chat-board-add-goal = Legg til mål
ai-chat-board-a-board-has-at-most = En tavle har mest { $max_goals } mål. Opprett en ny tavle for et annet mål.
ai-chat-board-background-context = Bakgrunnskontekst
ai-chat-board-continue-with-a-correction = Fortsett med en korreksjon
ai-chat-board-correction-what-is-wrong-or = Rettelse: hva som er feil eller mangler. Tavlen fortsetter med det.
ai-chat-board-the-board-waits-for-your = Tavla venter på din gjennomgang
ai-chat-board-the-board-used-its-budget = Tavlen brukte budsjettet sitt på { $snap_max_explores } utforskninger.
ai-chat-board-the-assessments-gave-no-usable = Vurderingene ga ingen brukbar retning.
ai-chat-board-accept-or-reject-the-proposed = Godkjenn eller avvis det foreslåte svaret på hvert mål over. Et avvist svar lar tavlen fortsette med en gang.
ai-chat-board-no-proposed-answer-waits-for = Det finnes ingen foreslått svar som venter på din avgjørelse.
ai-chat-board-reopen-the-board-to-continue = Åpne tavlen på nytt for å fortsette de åpne målene. Den beholder funnene og svarene.
ai-chat-board-close-the-board-to-accept = Lukk tavlen for å godta alle foreslåte svare og stoppe den, eller fortsett den med en rettelse.
ai-chat-board-close-the-board = Lukk tavlen
ai-chat-board-or-reopen-the-board-to = Eller åpner tavlen på nytt for å fortsette de åpne målene uten en rettelse.
ai-chat-board-the-board-is-complete = Tavlen er komplett
ai-chat-board-a-goal-has-no-accepted = Et mål har ingen godkjent svar. Åpne tavlen på nytt for å fortsette den. Tavlen beholder funningene og svarene.
ai-chat-board-add-a-hint = Legg til en hint
ai-chat-board-the-next-assessment-reads-every = Vurderingen neste gang leser alle hint. Et hint svarer også på en utforsking som stilte et spørsmål.
ai-chat-board-add-hint = Legg til hint
ai-chat-board-events = Hendelser
ai-chat-board-newest-first = Nyeste først
ai-chat-board-date = Dato
ai-chat-board-actor = Utøver
ai-chat-board-event = Hendelse
ai-chat-board-show-details = Vis detaljer
ai-chat-board-open = Åpne
ai-chat-board-show-the-newest-events = Vis nyeste { $event_rows } hendelser
ai-chat-board-show-all-events = Vis alle { $snap_events_len } hendelser
ai-chat-board-statistics = Statistikk
ai-chat-board-explores = Utforskinger
ai-chat-board-model-steps-per-explore = Modelltrinn per utforsking
ai-chat-board-assessments = Vurderinger
ai-chat-board-intents = Intensjoner
ai-chat-board-findings = Funn
ai-chat-board-created = Opprettet
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } avviste dette funnet på { $format_utc_ms_fact_rejected_ms }. Tavlen bruker det ikke lenger.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } avviste dette funnet. Tavlen bruker det ikke lenger.
ai-chat-board-no-reason-was-given = Ingen grunn ble oppgitt.
ai-chat-board-reason = Grunn: { $fact_rejected_reason }
ai-chat-board-open-questions = Åpne spørsmål
ai-chat-board-explored-in = Utforsket i
ai-chat-board-explore-this-question = Utforsk dette spørsmål
ai-chat-board-your-questions = Dine spørsmål
ai-chat-board-ask-about-the-background-context = Spør om bakgrunnskonteksten
ai-chat-board-ask-about-this-finding = Spør om dette funnet
ai-chat-board-a-follow-up-question-about = Et etterspørsmål om denne noden
ai-chat-board-ask = Spør
ai-chat-board-checks-that-changed-this-finding = Sjekk som endret dette funnet
ai-chat-board-reject-this-correction = Forkast denne korreksjonen
ai-chat-board-reject-this-finding = Forkast denne finningen
ai-chat-board-not-answered-the-board-was = Svarer ikke. Tavlen ble fullført uten svar på dette målet. En hint eller en gjenåpning åpner den igjen.
ai-chat-board-no-answer-yet = Ingen svar ennå.
ai-chat-board-the-findings-of-this-answer = Finningene i dette svaret er søk som ikke fant noe. Godta for å registrere at postene ikke svarer på målet, eller forkast for å fortsette undersøkelsen.
ai-chat-board-open-an-assessment-to-read = { "." } Åpne en vurdering for å lese hvorfor.
ai-chat-board-from-the-findings = Fra finningene{ " " }
ai-chat-board-accept-answer = Godta svar
ai-chat-board-why-the-answer-is-wrong = Hvorfor svaret er feil eller ufullstendig
ai-chat-board-reject-answer = Forkast svar
ai-chat-board-intent = Intensjon
ai-chat-board-attempts-declared = Forsøk: { $intent_attempts }. Erklært { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Utforskingen spurte
ai-chat-board-add-a-hint-in-the = Legg inn en hint i tavleoversikten for å svare på den.
ai-chat-board-last-error = Siste feil
ai-chat-board-brief = Kort
ai-chat-board-open-the-explore-chat = Åpne utføringspratsalen
ai-chat-board-loading-the-assessment-u = Laster vurderingen…
ai-chat-board-assessment = Vurdering { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Utfall { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Sjekkene som endret det
ai-chat-board-prompt = Oppdrag
ai-chat-board-this-assessment-ran-before-the = Denne vurderingen kjørte før oppdragene ble lagret.
ai-chat-board-response = Svar
ai-chat-history-hoover-search-chat-history = Hoover-søk - Samtalehistorikk
ai-chat-history-u-back = ← Tilbake
ai-chat-history-conversation-history = Samtalehistorikk
ai-chat-history-show-board-chats = Vis tavlesamtaler
ai-chat-history-loading-u = Laster…
ai-chat-history-could-not-load-history = Kunne ikke laste historikk: { $e }
ai-chat-history-no-conversations-yet = Ingen samtaler ennå.
ai-chat-history-board = Tavle
ai-chat-history-new-chat = Ny samtale
ai-chat-history-messages-updated = { $s_message_count } meldinger · oppdatert { $s_updated_at }
ai-chat-history-delete-conversation = Slett samtale
ai-chat-history-delete = Slett
ai-chat-homepage-hoover-search-ai-chat = Hoover-søk – AI-samtale
ai-chat-homepage-what-are-you-researching = Hva forsker du på?
ai-chat-homepage-view-all-conversations = Vis alle samtaler
ai-chat-homepage-starting-conversation-u = Starter samtale…
ai-chat-homepage-investigation-boards = Undersøkelsestavler
ai-chat-homepage-new-board = Ny tavle
ai-chat-homepage-loading-boards-u = Lasting av tavler…
ai-chat-homepage-could-not-load-the-boards = Kunne ikke laste tavlene: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har ingen tavle. En tavle fører en lang undersøkelse fram som en sekvens av agentundersøkelser, og du gjennomgår svarene.
ai-chat-homepage-updated = Oppdatert { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover-søk – AI-samtale
ai-chat-session-this-conversation-could-not-be = Denne samtalen kunne ikke lastes.
ai-chat-session-loading-u = Lasting…
ai-chat-session-u-chats = ← Samtaler
ai-chat-session-history = Historikk
ai-chat-session-show-the-files-that-the = Vis filene assistenten skrev i denne samtalen
ai-chat-session-workspace = Arbeidsområde
ai-chat-session-this-answer-was-interrupted-before = Dette svaret ble avbrutt før det var ferdig, fordi siden eller serveren stoppet midt i et tur. Spør igjen for å prøve på nytt.
ai-chat-session-dismiss = Lukk
ai-chat-session-board-explore-chats-are-read = Utkastsamtaler på tavle er skrivebeskyttet.{ " " }
ai-chat-session-open-the-board = Åpne tavla
chat-locked-options-on = { $label }: på
chat-locked-options-off = { $label }: av
chat-tool-cards-running-u = kjører…
cards-result-cards-quote-found = Sitat funnet
cards-result-cards-quote-not-found = Sitat ikke funnet
cards-result-cards-quote-not-checked = Sitat ikke kontrollert
web-search-card-results = { $results_len } resultater
chat-tool-disclosure-running-u = behandler…
chat-transcript-call = samtale
chat-transcript-calls = samtaler
ai-chat-board-a-board-without-collections-needs = En tavle uten samlinger trenger internettverktøy.
ai-chat-board-of = { $snap_explores_used } av { $snap_max_explores }
ai-chat-board-assessment-2 = vurdering { $number }
ai-chat-history-messages = { $s_message_count } meldinger
web-search-card-reranked-in = Kryss-ensatoren rangerte resultater på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = poengsum { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Omdreningen venter på en fri modellplass.
chat-activity-the-turn-waits-for-a-2 = Omdreningen venter på en fri verktøyplass.
chat-locked-options-start-a-new-chat-to = Start en ny samtale for å endre denne innstillingen.
chat-locked-options-internet-tools = Internettverktøy
chat-session-card-new-chat = Ny samtale
chat-tool-cards-first-frame-of-the-video = Første bilde av videoen
chat-tool-cards-screenshot-of = Skjermbilde av
chat-tool-cards-image = Bilde
cards-result-cards-the-agent-asked-a-question = Agenten stilte et spørsmål.
chat-transcript-hide = Skjul
chat-transcript-show = Vis
chat-transcript-unverified-quote-the-quoted-span = Ukontrollert sitat. Det siterte utdraget er for kort til å kontrolleres.
chat-transcript-unverified-quote-the-document-text = Ukontrollert sitat. Dokumentteksten kunne ikke leses.
chat-transcript-unverified-quote-this-wording-was = Ukontrollert sitat. Denne formuleringen ble ikke funnet i dokumentet.
chat-board-create-select-a-collection-or-turn = Velg en samling eller slå på internettverktøy.
chat-board-create-select-at-least-one-collection = Velg minst én samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = Pause
ai-chat-board-waits-for-review = Venter på gjennomgang
ai-chat-board-completed = Fullført
ai-chat-board-dropped = Forkastet
ai-chat-board-unknown = Ukjent
ai-chat-board-pause-the-board = Pause tavla
ai-chat-board-resume-the-board = Gjenoppta tavla
ai-chat-board-none = Ingen
ai-chat-board-reopen-with-the-remaining-budget = Slå open på nytt med gjenstående budsjett
ai-chat-board-finding = Finning
ai-chat-board-why-the-correction-is-wrong = Hvorfor rettingen er feil
ai-chat-board-reject-correction = Forkast retting
ai-chat-board-why-the-finding-is-wrong = Hvorfor finningen er feil
ai-chat-board-reject-finding = Forkast finning
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Foreslått svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pause
ai-chat-homepage-waits-for-review = Venter på gjennomgang
ai-chat-homepage-completed = Fullført
ai-chat-homepage-dropped = Forkastet
ai-chat-homepage-unknown = Ukjent
cards-result-cards-submitted-by-board =
    Innsendt av tavla: { $kind ->
        [sourced] en kildekilde
        [inferred] en utledet
        [not_found] en ikke funnet
       *[other] en ukjent type
    } finning fra rapporten
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] En kildekilde
        [inferred] En utledet
        [not_found] En ikke funnet
       *[other] En ukjent type
    } finning for tavla
chat-transcript-compacting = Komprimerer konteksten: { $before } token mot et mål på { $target }.
chat-transcript-compaction-failed = Oppsummeringen av de tidligere stegene feilet. Modellen mottok de tidligere stegene uendret, { $after } token.
chat-transcript-compacted = Kontekst komprimert: { $steps } steg summert, { $before } token til { $after }.
ai-chat-board-reopen-with-more = Slå open på nytt med { $grant } utforskinger på
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Fra vurdering { $number } på { $date }.
ai-chat-board-from-assessment = Fra vurdering { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = mistet kontakten med samtalen: { $e }
ai-chat-session-could-not-stop-the-answer = kunne ikke stoppe svaret: { $e } — det kjører fortsatt
ai-chat-board-later-assessments-dropped-an-answer = { $n } senere vurderinger droppet et svar for dette målet:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } oppgave- og { $a_completion_tokens } fullførelse-token
ai-chat-homepage-completed-goals-not-answered = Fullført, { $n } mål ikke besvart
board-graph-intent = intensjon, { $state }
chat-workspace-pane-characters = { $chars } tegn
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } kjører verktøy { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } kjører verktøy { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Besvart etter { $retries_len } mislykket forsøk{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } mislykket forsøk{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, versjon { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] søkte etter { $n } søketerm
       *[other] søkte etter { $n } søketermer
    }
tool-run-summary-read =
    { $n ->
        [one] lest { $n } dokument
       *[other] lest { $n } dokumenter
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] søkte på nettet etter { $n } søketerm
       *[other] søkte på nettet etter { $n } søketermer
    }
tool-run-summary-read-web =
    { $n ->
        [one] leste { $n } nettside
       *[other] leste { $n } nettsider
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } nettleserhandling
       *[other] { $n } nettleserhandlinger
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listet opp enhetene i { $n } dokument
       *[other] listet opp enhetene i { $n } dokumenter
    }
tool-run-summary-cited =
    { $n ->
        [one] siterte { $n } dokument
       *[other] siterte { $n } dokumenter
    }
tool-run-summary-cited-web =
    { $n ->
        [one] siterte { $n } nettside
       *[other] siterte { $n } nettsider
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] leste { $n } ferdighets- og verktøytekst
       *[other] leste { $n } ferdighets- og verktøytekster
    }
tool-run-summary-saved =
    { $n ->
        [one] lagret { $n } notat
       *[other] lagret { $n } notater
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } oppgaveliste-kall
       *[other] { $n } oppgaveliste-kall
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instruks til agenten
       *[other] { $n } instruksjoner til agenten
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } annet kall
       *[other] { $n } annerlige kall
    }
tool-run-summary-failed = { $failures } mislykket
tool-run-summary-took = brukte { $duration_text_ms }
chat-session-card-messages = { $session_message_count } meldinger
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } element
       *[other] { $count } elementer
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } felt
       *[other] { $count } felt
    }
chat-tool-disclosure-searched-collections = søkte i samlinger{ $filters }
chat-tool-disclosure-searched-collections-2 = søkte i samlinger · { $query }{ $filters }
chat-tool-disclosure-cited-documents = sitert { $n } dokument
chat-tool-disclosure-read-document = lest dokument · { $path }
chat-tool-disclosure-searched-the-web = søkte på nettet · { $q }
chat-tool-disclosure-opened-page = åpnet side · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = ringte { $other }
chat-tool-disclosure-called-2 = ringte { $other } · { $short }
cards-browser-card-opened = åpnet { $url }
cards-browser-card-could-not-open = kunne ikke åpne { $url }
cards-browser-card-clicked = klikket på { $element }
cards-browser-card-could-not-click = kunne ikke klikket på { $element }
cards-browser-card-typed-into = skrev i { $element }
cards-browser-card-could-not-type-into = kunne ikke skrive i { $element }
cards-browser-card-typed = skrev “{ $text }”
cards-browser-card-could-not-type = kunne ikke skrive “{ $text }”
cards-browser-card-pressed = trykket { $key }
cards-browser-card-could-not-press = kunne ikke trykke { $key }
cards-browser-card-chose-an-option-in = valgte et alternativ i { $element }
cards-browser-card-could-not-choose-an-option = kunne ikke velge et alternativ i { $element }
cards-browser-card-hovered = svevde over { $element }
cards-browser-card-could-not-hover = kunne ikke sveve over { $element }
cards-browser-card-failed = { $bare } — mislyktes
cards-entities-card-listed-entities-document = listet opp enheter · { $count } dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · del { $part } av { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } dokumenter
cards-result-cards-forms = { $tool_name } · { $forms } skjema
cards-result-cards-in = { " " }i { $collections }
cards-result-cards-page = { " " }· side { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenter · { $missing } sitat ikke funnet
cards-result-cards-version-unchanged = { $tool_name } · versjon { $version } · uendret
cards-result-cards-version = { $tool_name } · versjon { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultater i, { $json_u64_doc_total_after_dedupe } etter deduplikasjon
