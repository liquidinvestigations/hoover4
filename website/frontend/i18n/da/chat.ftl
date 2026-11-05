# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Botten arbejder...
chat-composer-ask-the-bot = Spørg botten...
chat-composer-internet-tools = Internetværktøjer
chat-composer-agent-language-title = Agenten svarer på { $language }. Skift sproget i indstillingerne, i en ny fane.
chat-composer-try-again-in-s = Prøv igen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stop svaret (det delvise svar gemmes ikke i samtalen)
chat-composer-starting-the-conversation-u = Starter samtalen…
chat-composer-send = Send
chat-conversation-find-search-in-conversation = Søg i samtalen
chat-conversation-find-previous-match = Forrige træf
chat-conversation-find-next-match = Næste træf
chat-conversation-find-investigation-board = Undersøgelsestavle
doc-ref-card-not-openable = Kan ikke åbnes: { $reason }.
doc-ref-card-the-search-term-was = Søgeordet var{" "}
doc-ref-card-open = Åbn
doc-ref-card-not-openable-2 = Kan ikke åbnes
chat-markdown-text-show-the-cited-source = Vis den citerede kilde
chat-markdown-text-no-citation-of-this-conversation = Ingen kildehenvisning i denne samtale gav dette mærke, så intet dokument ligger bag det.
chat-markdown-text-citations-of-this-conversation-gave = Kildehenvisninger i denne samtale gav dette mærke til mere end ét dokument, så det linker til ingen af dem.
cards-browser-card-open-the-archived-page = Åbn den arkiverede side
cards-browser-card-the-page-itself-was-not = Selve siden blev ikke arkiveret (status: { $artifact_status }). Skærmbilledet ovenfor er det, der blev gemt.
cards-browser-card-click-the-screenshot-to-open = Klik på skærmbilledet for at åbne den arkiverede side.
cards-browser-card-show-less = Vis mindre
cards-browser-card-show-all = Vis alle
cards-browser-card-archived-page = Arkiveret side
cards-browser-card-download = Download
cards-browser-card-archived-copy-of = Arkiveret kopi af { $artifact_url }
cards-browser-card-this-page-was-not-archived = Denne side blev ikke arkiveret (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med et kort
cards-entities-card-the-entity-list-was-cut = Entitetslisten blev afkortet.
cards-entities-card-open-the-card-for-this = Åbn kortet for denne værdi ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Intet kort: denne samtale har aldrig nævnt det datasæt, som disse værdier kommer fra, og fremviseren adresseres via datasættet.
cards-entities-card-more-all-of-them-in = { $rest } flere, alle i dokumentets entitetspanel.{" "}
cards-entities-card-names-organisations-and-places-above = Navne, organisationer og steder ovenfor er en models læsning af teksten. Ingen regel har valideret dem, så der er intet at forklare, og de åbner intet.
cards-entities-card-nothing-extracted-from-this-document = Intet er udtrukket fra dette dokument.
chat-tool-cards-hide = Skjul
chat-tool-cards-expand = Udvid
chat-tool-cards-hide-raw-json = Skjul rå JSON
chat-tool-cards-show-raw-json = Vis rå JSON
cards-result-cards-search-this = Søg i denne
cards-result-cards-search-every-collection = Søg i alle samlinger
cards-result-cards-form = Form { $index }: { $form }
cards-result-cards-show-full-text = Vis hele teksten
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Begrundelse: { $why }
cards-result-cards-open-question = Åbent spørgsmål: { $question }
cards-result-cards-the-explore-gave-this-answer = Udforskningen gav dette svar til sin tavle som { $kind ->
        [sourced] et kildebelagt fund.
        [inferred] et udledt fund.
        [not_found] et fund om, at intet blev fundet.
       *[other] et fund af ukendt type.
    }
cards-result-cards-it-left-no-open-question = Den efterlod intet åbent spørgsmål.
cards-result-cards-open-questions-for-the-board = Åbne spørgsmål til tavlen:
cards-result-cards-arguments = Argumenter
cards-result-cards-list-after-the-call = Liste efter kaldet: { $snapshot_goal }
cards-result-cards-replaces = {" "}· erstatter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listen i denne version er ikke gemt.
web-search-card-these-sources-returned-nothing-so = Disse kilder returnerede intet, så resultaterne kommer fra færre kilder end tilsigtet
web-search-card-u-degraded = ⚠ { $degraded_len } forringede
web-search-card-form = Form { $index }: { $form }
web-search-card-no-results-from = Ingen resultater fra: { $degraded_text }
web-search-card-no-results-every-source-answered = Ingen resultater. Alle kilder svarede, og ingen af dem havde noget til denne forespørgsel.
web-search-card-the-lowest-ranked-results-were = De lavest rangerede resultater blev fjernet, så dette kald kan være i udskriften. Assistenten så dem alle.
web-search-card-view-search-details = Se søgedetaljer.
web-search-card-the-stored-result-could-not = det gemte resultat kunne ikke læses tilbage som JSON
web-search-card-nothing-was-stored-for-this = Der blev ikke gemt noget for dette kald.
web-search-card-forms = Former: { $forms }
web-search-card-kind = Type: { $row_kind }
web-search-card-published = Udgivet: { $row_published }
web-search-card-loading-search-detail-u = Indlæser søgedetaljer…
web-search-card-could-not-load-the-search = Søgedetaljerne kunne ikke indlæses: { $e }
web-search-card-malformed-detail = Ugyldige detaljer: { $e }
web-search-card-the-tool-returned-selected-results = Værktøjet returnerede udvalgte resultater til modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultaterne bruger reciprocal rank fusion.
web-search-card-returned-nothing = returnerede intet: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidater bruger fusionsrækkefølgen.
web-search-card-the-cross-encoder-ranks-selected = Cross-encoderen rangerer udvalgte resultater.
web-search-card-selected-results-use-fusion-order = Udvalgte resultater bruger fusionsrækkefølgen.
web-search-card-search-detail = Søgedetaljer
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Søg i denne
chat-tool-disclosure-search-every-collection = Søg i alle samlinger
chat-tool-disclosure-hide = Skjul
chat-tool-disclosure-expand = Udvid
chat-tool-disclosure-this-step-was-recorded-before = Dette trin blev registreret, før værktøjets argumenter og resultater blev gemt. Kun resuméet nedenfor er tilgængeligt.
chat-tool-disclosure-arguments = Argumenter
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Skjul rå JSON
chat-tool-disclosure-show-raw-json = Vis rå JSON
chat-tool-disclosure-input-json = Input-JSON
chat-tool-disclosure-output-json = Output-JSON
chat-transcript-ask-a-question-about-the = Stil et spørgsmål om dokumenterne i dine samlinger.
chat-transcript-suggested-next = Foreslået næste...
chat-transcript-earlier-answer = Tidligere svar
chat-transcript-tokens-the-conversation-carries-the = Tokens, som samtalen indeholder, den største enkelte kontekst, der blev afregnet for i denne runde, og hvor stor en del af modellens vindue den brugte
chat-transcript-instruction-to-the-agent = Instruktion til agenten
chat-transcript-the-context-stays-above-the = {" "}Konteksten forbliver over målet på { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } dele af resuméet mislykkedes. Optegnelsen indeholder kun listerne.
chat-transcript-show-the-record = Vis optegnelsen
chat-transcript-hide-reasoning = Skjul ræsonnement
chat-transcript-show-reasoning = Vis ræsonnement
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
chat-transcript-citations-of-this-conversation-give = Kildehenvisninger i denne samtale giver { $doc_handle } til mere end ét dokument. Svaret linker det til ingen af dem.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Åbn i arbejdsområdet
chat-transcript-this-version-could-not-be = Denne version kunne ikke læses. Svarets chattekst følger.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Find nøjagtig tekst
chat-web-previous-match = Forrige træf
chat-web-next-match = Næste træf
chat-web-close-preview = Luk forhåndsvisning
chat-web-the-captured-page-could-not = Den indfangede side kunne ikke indlæses.
chat-web-loading = Indlæser…
chat-workspace-pane-workspace = Arbejdsområde
chat-workspace-pane-close-the-workspace = Luk arbejdsområdet
chat-workspace-pane-close = Luk
chat-workspace-pane-loading-the-files-u = Indlæser filerne…
chat-workspace-pane-the-files-could-not-be = Filerne kunne ikke indlæses: { $error }
chat-workspace-pane-this-conversation-has-no-files = Denne samtale har ingen filer.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Vælg en fil for at læse den.
chat-workspace-pane-loading-the-file-u = Indlæser filen…
chat-workspace-pane-the-file-could-not-be = Filen kunne ikke indlæses: { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Samlinger
chat-board-create-loading-collections-u = Indlæser samlinger…
chat-board-create-hoover-search-new-board = Hoover-søgning - Ny tavle
chat-board-create-ai-chat = AI Chat
chat-board-create-new-investigation-board = Ny undersøgelsestavle
chat-board-create-a-board-runs-its-goals = En tavle kører sine mål som en række udforskninger foretaget af agenter. Hver udforskning er en chat, der ender i ét fund på tavlen. Du gennemgår svaret på hvert mål, og du kan afvise fund og tilføje vink, mens tavlen kører.
chat-board-create-title = Titel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Fjern dette mål
chat-board-create-remove = Fjern
chat-board-create-add-a-goal = Tilføj et mål
chat-board-create-context-optional = Kontekst (valgfri)
chat-board-create-hints-one-per-line-optional = Vink, ét pr. linje (valgfrit)
chat-board-create-sources = Kilder
chat-board-create-internet-tools = Internetværktøjer
chat-board-create-creating-board = Opretter tavle...
chat-board-create-create-board = Opret tavle
ai-chat-board-hoover-search-board = Hoover-søgning - Tavle
ai-chat-board-loading-the-board-u = Indlæser tavlen…
ai-chat-board-show-the-board-overview = Vis tavlens oversigt
ai-chat-board-zoom-out = Zoom ud
ai-chat-board-zoom-in = Zoom ind
ai-chat-board-u-ai-chat = ← AI Chat
ai-chat-board-settings = Indstillinger
ai-chat-board-board-settings = Tavleindstillinger
ai-chat-board-internet-tools = Internetværktøjer
ai-chat-board-the-next-explores-of-the = Tavlens næste udforskninger kan søge på nettet og læse websider. Udforskninger, der kører, beholder den indstilling, de startede med.
ai-chat-board-collections = Samlinger
ai-chat-board-the-collections-are-fixed-when = Samlingerne fastlægges, når tavlen oprettes.
ai-chat-board-confirm-drop = Bekræft droppet
ai-chat-board-drop-the-board = Drop tavlen
ai-chat-board-close = Luk
ai-chat-board-the-board-used-its-explore = Tavlen har brugt sin grænse for udforskninger
ai-chat-board-the-board-used-explores-the = Tavlen har brugt { $explore_limit } udforskninger, som er grænsen for én tavle. Den starter ikke mere arbejde. Du kan stadig tage stilling til de foreslåede svar.
ai-chat-board-create-a-new-board-to = Opret en ny tavle for at fortsætte undersøgelsen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Tilføj nyt mål...
ai-chat-board-a-new-goal = Et nyt mål
ai-chat-board-add-goal = Tilføj mål
ai-chat-board-a-board-has-at-most = En tavle har højst { $max_goals } mål. Opret en ny tavle for et yderligere mål.
ai-chat-board-background-context = Baggrundskontekst
ai-chat-board-continue-with-a-correction = Fortsæt med en rettelse
ai-chat-board-correction-what-is-wrong-or = Rettelse: hvad der er forkert eller mangler. Tavlen fortsætter med den.
ai-chat-board-the-board-waits-for-your = Tavlen venter på din gennemgang
ai-chat-board-the-board-used-its-budget = Tavlen har brugt sit budget på { $snap_max_explores } udforskninger.
ai-chat-board-the-assessments-gave-no-usable = Vurderingerne gav ingen brugbar retning.
ai-chat-board-accept-or-reject-the-proposed = Acceptér eller afvis det foreslåede svar på hvert mål ovenfor. Et afvist svar lader tavlen fortsætte med det samme.
ai-chat-board-no-proposed-answer-waits-for = Intet foreslået svar venter på din beslutning.
ai-chat-board-reopen-the-board-to-continue = Genåbn tavlen for at fortsætte de åbne mål. Den beholder sine fund og svar.
ai-chat-board-close-the-board-to-accept = Luk tavlen for at acceptere alle foreslåede svar og stoppe den, eller fortsæt den med en rettelse.
ai-chat-board-close-the-board = Luk tavlen
ai-chat-board-or-reopen-the-board-to = Eller genåbn tavlen for at fortsætte de åbne mål uden en rettelse.
ai-chat-board-the-board-is-complete = Tavlen er komplet
ai-chat-board-a-goal-has-no-accepted = Et mål har intet accepteret svar. Genåbn tavlen for at fortsætte det. Tavlen beholder sine fund og svar.
ai-chat-board-add-a-hint = Tilføj et vink
ai-chat-board-the-next-assessment-reads-every = Den næste vurdering læser alle vink. Et vink besvarer også en udforskning, der stillede et spørgsmål.
ai-chat-board-add-hint = Tilføj vink
ai-chat-board-events = Hændelser
ai-chat-board-newest-first = Nyeste først
ai-chat-board-date = Dato
ai-chat-board-actor = Aktør
ai-chat-board-event = Hændelse
ai-chat-board-show-details = Vis detaljer
ai-chat-board-open = Åbn
ai-chat-board-show-the-newest-events = Vis de { $event_rows } nyeste hændelser
ai-chat-board-show-all-events = Vis alle { $snap_events_len } hændelser
ai-chat-board-statistics = Statistik
ai-chat-board-explores = Udforskninger
ai-chat-board-model-steps-per-explore = Modeltrin pr. udforskning
ai-chat-board-assessments = Vurderinger
ai-chat-board-intents = Hensigter
ai-chat-board-findings = Fund
ai-chat-board-created = Oprettet
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } afviste dette fund den { $format_utc_ms_fact_rejected_ms }. Tavlen bruger det ikke længere.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } afviste dette fund. Tavlen bruger det ikke længere.
ai-chat-board-no-reason-was-given = Der blev ikke angivet nogen begrundelse.
ai-chat-board-reason = Begrundelse: { $fact_rejected_reason }
ai-chat-board-open-questions = Åbne spørgsmål
ai-chat-board-explored-in = Udforsket i{" "}
ai-chat-board-explore-this-question = Udforsk dette spørgsmål
ai-chat-board-your-questions = Dine spørgsmål
ai-chat-board-ask-about-the-background-context = Spørg om baggrundskonteksten
ai-chat-board-ask-about-this-finding = Spørg om dette fund
ai-chat-board-a-follow-up-question-about = Et opfølgende spørgsmål om denne node
ai-chat-board-ask = Spørg
ai-chat-board-checks-that-changed-this-finding = Kontroller, der ændrede dette fund
ai-chat-board-reject-this-correction = Afvis denne rettelse
ai-chat-board-reject-this-finding = Afvis dette fund
ai-chat-board-not-answered-the-board-was = Ikke besvaret. Tavlen blev afsluttet uden et svar på dette mål. Et vink eller en genåbning åbner det igen.
ai-chat-board-no-answer-yet = Intet svar endnu.
ai-chat-board-the-findings-of-this-answer = Fundene i dette svar er søgninger, der intet fandt. Acceptér det for at registrere, at optegnelserne ikke besvarer målet, eller afvis det for at fortsætte undersøgelsen.
ai-chat-board-open-an-assessment-to-read = {"."} Åbn en vurdering for at læse hvorfor.
ai-chat-board-from-the-findings = Fra fundene{" "}
ai-chat-board-accept-answer = Acceptér svar
ai-chat-board-why-the-answer-is-wrong = Hvorfor svaret er forkert eller ufuldstændigt
ai-chat-board-reject-answer = Afvis svar
ai-chat-board-intent = Hensigt
ai-chat-board-attempts-declared = Forsøg: { $intent_attempts }. Erklæret { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Udforskningen spurgte
ai-chat-board-add-a-hint-in-the = Tilføj et vink i tavlens oversigt for at besvare det.
ai-chat-board-last-error = Seneste fejl
ai-chat-board-brief = Opgavebeskrivelse
ai-chat-board-open-the-explore-chat = Åbn udforskningens chat
ai-chat-board-loading-the-assessment-u = Indlæser vurderingen…
ai-chat-board-assessment = Vurdering { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Udfald { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Kontroller, der ændrede det
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Denne vurdering kørte, før prompterne blev gemt.
ai-chat-board-response = Svar
ai-chat-history-hoover-search-chat-history = Hoover-søgning - Chathistorik
ai-chat-history-u-back = ← Tilbage
ai-chat-history-conversation-history = Samtalehistorik
ai-chat-history-show-board-chats = Vis tavlechats
ai-chat-history-loading-u = Indlæser…
ai-chat-history-could-not-load-history = Historikken kunne ikke indlæses: { $e }
ai-chat-history-no-conversations-yet = Ingen samtaler endnu.
ai-chat-history-board = Tavle
ai-chat-history-new-chat = Ny chat
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } besked · opdateret { $s_updated_at }
    *[other] { $s_message_count } beskeder · opdateret { $s_updated_at }
    }

ai-chat-history-delete-conversation = Slet samtale
ai-chat-history-delete = Slet
ai-chat-homepage-hoover-search-ai-chat = Hoover-søgning - AI Chat
ai-chat-homepage-what-are-you-researching = Hvad undersøger du?
ai-chat-homepage-view-all-conversations = Se alle samtaler
ai-chat-homepage-starting-conversation-u = Starter samtalen…
ai-chat-homepage-investigation-boards = Undersøgelsestavler
ai-chat-homepage-new-board = Ny tavle
ai-chat-homepage-loading-boards-u = Indlæser tavler…
ai-chat-homepage-could-not-load-the-boards = Tavlerne kunne ikke indlæses: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har ingen tavle. En tavle kører en lang undersøgelse som en række udforskninger foretaget af agenter, og du gennemgår dens svar.
ai-chat-homepage-updated = Opdateret { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover-søgning - AI Chat
ai-chat-session-this-conversation-could-not-be = Denne samtale kunne ikke indlæses.
ai-chat-session-loading-u = Indlæser…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = Historik
ai-chat-session-show-the-files-that-the = Vis de filer, som assistenten skrev i denne samtale
ai-chat-session-workspace = Arbejdsområde
ai-chat-session-this-answer-was-interrupted-before = Dette svar blev afbrudt, før det var færdigt, fordi siden eller serveren stoppede midt i runden. Spørg igen for at prøve igen.
ai-chat-session-dismiss = Afvis
ai-chat-session-board-explore-chats-are-read = Chats fra tavlens udforskninger er skrivebeskyttede.{" "}
ai-chat-session-open-the-board = Åbn tavlen
chat-locked-options-on = { $label }: til
chat-locked-options-off = { $label }: fra
chat-tool-cards-running-u = kører…
cards-result-cards-quote-found = Citat fundet
cards-result-cards-quote-not-found = Citat ikke fundet
cards-result-cards-quote-not-checked = Citat ikke kontrolleret
web-search-card-results = { $results_len } resultater
chat-tool-disclosure-running-u = kører…
chat-transcript-call = kald
chat-transcript-calls = kald
ai-chat-board-a-board-without-collections-needs = En tavle uden samlinger kræver internetværktøjer.
ai-chat-board-of = { $snap_explores_used } af { $snap_max_explores }
ai-chat-board-assessment-2 = vurdering { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } besked
    *[other] { $s_message_count } beskeder
    }

web-search-card-reranked-in = Cross-encoderen rangerede resultaterne på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = score { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Runden venter på en ledig modelplads.
chat-activity-the-turn-waits-for-a-2 = Runden venter på en ledig værktøjsplads.
chat-locked-options-start-a-new-chat-to = Start en ny chat for at ændre denne indstilling.
chat-locked-options-internet-tools = Internetværktøjer
chat-session-card-new-chat = Ny chat
chat-tool-cards-first-frame-of-the-video = Videoens første billede
chat-tool-cards-screenshot-of = Skærmbillede af
chat-tool-cards-image = Billede
cards-result-cards-the-agent-asked-a-question = Agenten stillede et spørgsmål.
chat-transcript-hide = Skjul
chat-transcript-show = Vis
chat-transcript-unverified-quote-the-quoted-span = Ikke verificeret citat. Det citerede stykke er for kort til at blive kontrolleret.
chat-transcript-unverified-quote-the-document-text = Ikke verificeret citat. Dokumentets tekst kunne ikke læses.
chat-transcript-unverified-quote-this-wording-was = Ikke verificeret citat. Denne ordlyd blev ikke fundet i dokumentet.
chat-board-create-select-a-collection-or-turn = Vælg en samling, eller slå internetværktøjer til.
chat-board-create-select-at-least-one-collection = Vælg mindst én samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = På pause
ai-chat-board-waits-for-review = Venter på gennemgang
ai-chat-board-completed = Afsluttet
ai-chat-board-dropped = Droppet
ai-chat-board-unknown = Ukendt
ai-chat-board-pause-the-board = Sæt tavlen på pause
ai-chat-board-resume-the-board = Genoptag tavlen
ai-chat-board-none = Ingen
ai-chat-board-reopen-with-the-remaining-budget = Genåbn med det resterende budget
ai-chat-board-finding = Fund
ai-chat-board-why-the-correction-is-wrong = Hvorfor rettelsen er forkert
ai-chat-board-reject-correction = Afvis rettelse
ai-chat-board-why-the-finding-is-wrong = Hvorfor fundet er forkert
ai-chat-board-reject-finding = Afvis fund
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Foreslået svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = På pause
ai-chat-homepage-waits-for-review = Venter på gennemgang
ai-chat-homepage-completed = Afsluttet
ai-chat-homepage-dropped = Droppet
ai-chat-homepage-unknown = Ukendt
cards-result-cards-submitted-by-board = Indsendt af tavlen: { $kind ->
        [sourced] et kildebelagt fund
        [inferred] et udledt fund
        [not_found] et fund om, at intet blev fundet
       *[other] et fund af ukendt type
    } fra rapporten
cards-result-cards-finding-for-board = { $kind ->
        [sourced] Et kildebelagt fund
        [inferred] Et udledt fund
        [not_found] Et fund om, at intet blev fundet
       *[other] Et fund af ukendt type
    } til tavlen
chat-transcript-compacting = Komprimerer konteksten: { $before } tokens til et mål på { $target }.
chat-transcript-compaction-failed = Resuméet af de tidligere trin mislykkedes. Modellen fik de tidligere trin uændret, { $after } tokens.
chat-transcript-compacted = Kontekst komprimeret: { $steps } trin opsummeret, { $before } tokens til { $after }.
ai-chat-board-reopen-with-more = Genåbn med { $grant } udforskninger mere
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Fra vurdering { $number } den { $date }.
ai-chat-board-from-assessment = Fra vurdering { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = mistede forbindelsen til chatten: { $e }
ai-chat-session-could-not-stop-the-answer = kunne ikke stoppe svaret: { $e } – det kører stadig
ai-chat-board-later-assessments-dropped-an-answer = { $n } senere vurderinger droppede et svar på dette mål:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt-tokens og { $a_completion_tokens } svar-tokens
ai-chat-homepage-completed-goals-not-answered = Afsluttet, { $n } mål ikke besvaret
board-graph-intent = hensigt, { $state }
chat-workspace-pane-characters = { $chars } tegn
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } kørende værktøjs{ $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } kørende værktøjs{ $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Besvaret efter { $retries_len } mislykkede forsøg{ $if_retries_len_1_else_s ->
        *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len } mislykkede forsøg{ $if_retries_len_1_else_s ->
        *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched = { $n ->
        [one] søgte efter { $n } søgeord
       *[other] søgte efter { $n } søgeord
    }
tool-run-summary-read = { $n ->
        [one] læste { $n } dokument
       *[other] læste { $n } dokumenter
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] søgte på nettet efter { $n } søgeord
       *[other] søgte på nettet efter { $n } søgeord
    }
tool-run-summary-read-web = { $n ->
        [one] læste { $n } webside
       *[other] læste { $n } websider
    }
tool-run-summary-browser = { $n ->
        [one] { $n } browserhandling
       *[other] { $n } browserhandlinger
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] listede entiteterne i { $n } dokument
       *[other] listede entiteterne i { $n } dokumenter
    }
tool-run-summary-cited = { $n ->
        [one] henviste til { $n } dokument
       *[other] henviste til { $n } dokumenter
    }
tool-run-summary-cited-web = { $n ->
        [one] henviste til { $n } webside
       *[other] henviste til { $n } websider
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] læste { $n } færdighed og værktøjstekster
       *[other] læste { $n } færdigheder og værktøjstekster
    }
tool-run-summary-saved = { $n ->
        [one] gemte { $n } note
       *[other] gemte { $n } noter
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } kald til opgavelisten
       *[other] { $n } kald til opgavelisten
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instruktion til agenten
       *[other] { $n } instruktioner til agenten
    }
tool-run-summary-other = { $n ->
        [one] { $n } andet kald
       *[other] { $n } andre kald
    }
tool-run-summary-failed = { $failures } mislykkedes
tool-run-summary-took = tog { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } besked
    *[other] { $session_message_count } beskeder
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } element
       *[other] { $count } elementer
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } felt
       *[other] { $count } felter
    }
chat-tool-disclosure-searched-collections = søgte i samlinger{ $filters }
chat-tool-disclosure-searched-collections-2 = søgte i samlinger · { $query }{ $filters }
chat-tool-disclosure-cited-documents = henviste til { $n } dokumenter
chat-tool-disclosure-read-document = læste dokument · { $path }
chat-tool-disclosure-searched-the-web = søgte på nettet · { $q }
chat-tool-disclosure-opened-page = åbnede side · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = kaldte { $other }
chat-tool-disclosure-called-2 = kaldte { $other } · { $short }
cards-browser-card-opened = åbnede { $url }
cards-browser-card-could-not-open = kunne ikke åbne { $url }
cards-browser-card-clicked = klikkede på { $element }
cards-browser-card-could-not-click = kunne ikke klikke på { $element }
cards-browser-card-typed-into = skrev i { $element }
cards-browser-card-could-not-type-into = kunne ikke skrive i { $element }
cards-browser-card-typed = skrev “{ $text }”
cards-browser-card-could-not-type = kunne ikke skrive “{ $text }”
cards-browser-card-pressed = trykkede på { $key }
cards-browser-card-could-not-press = kunne ikke trykke på { $key }
cards-browser-card-chose-an-option-in = valgte en indstilling i { $element }
cards-browser-card-could-not-choose-an-option = kunne ikke vælge en indstilling i { $element }
cards-browser-card-hovered = holdt musen over { $element }
cards-browser-card-could-not-hover = kunne ikke holde musen over { $element }
cards-browser-card-failed = { $bare } – mislykkedes
cards-entities-card-listed-entities-document = listede entiteter · { $count } dokument{ $if_count_1_else_s ->
        *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · del { $part } af { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } dokumenter
cards-result-cards-forms = { $tool_name } · { $forms } former
cards-result-cards-in = {" "}i { $collections }
cards-result-cards-page = {" "}· side { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenter · { $missing } citater ikke fundet
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · uændret
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultater ind, { $json_u64_doc_total_after_dedupe } efter fjernelse af dubletter

board-status-on = Til

board-status-off = Fra

chat-transcript-generic-tool = værktøjet
