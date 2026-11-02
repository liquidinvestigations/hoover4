# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Boten arbejder...
chat-composer-ask-the-bot = Spørg boten...
chat-composer-internet-tools = Internetværktøjer
chat-composer-agent-language-title = Agenten svarer på { $language }. Skift sprog i indstillingerne, i en ny fane.
chat-composer-try-again-in-s = Prøv igen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stop svaret (den delvise svar lagres ikke i samtalen)
chat-composer-starting-the-conversation-u = Starter samtalen…
chat-composer-send = Send
chat-conversation-find-search-in-conversation = Søg i samtalen
chat-conversation-find-previous-match = Forrige match
chat-conversation-find-next-match = Næste match
chat-conversation-find-investigation-board = Undøgelsesboard
doc-ref-card-not-openable = Kan ikke åbnes: { $reason }.
doc-ref-card-the-search-term-was = Søgetermen var{ " " }
doc-ref-card-open = Åbn
doc-ref-card-not-openable-2 = Kan ikke åbnes
chat-markdown-text-show-the-cited-source = Vis den citerede kilde
chat-markdown-text-no-citation-of-this-conversation = Ingen citat fra denne samtale gav dette håndtag, så der står intet dokument bagved.
chat-markdown-text-citations-of-this-conversation-gave = Citater fra denne samtale gav dette håndtag til mere end ét dokument, så den linker til ingen af dem.
cards-browser-card-open-the-archived-page = Åbn den arkiverede side
cards-browser-card-the-page-itself-was-not = Siden i sig selv blev ikke arkiveret (status: { $artifact_status }). Skærmbilledet ovenfor er det, der blev bevaret.
cards-browser-card-click-the-screenshot-to-open = Klik på skærmbilledet for at åbne den arkiverede side.
cards-browser-card-show-less = Vis mindre
cards-browser-card-show-all = Vis alle
cards-browser-card-archived-page = Arkiverede side
cards-browser-card-download = Download
cards-browser-card-archived-copy-of = Arkiverede kopi af { $artifact_url }
cards-browser-card-this-page-was-not-archived = Denne side blev ikke arkiveret (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med et kort
cards-entities-card-the-entity-list-was-cut = Enhedslisten blev afkortet.
cards-entities-card-open-the-card-for-this = Åbn kortet for denne værdi ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Kort: denne samtale har aldrig nævnt datasættet, som disse værdier stammer fra, og seeren tiltales datasæt.
cards-entities-card-more-all-of-them-in = { $rest } mere, alle i dokumentets entitetspanel.{ " " }
cards-entities-card-names-organisations-and-places-above = Navne, organisationer og steder ovenfor er en models tolkning af sproget. Ingen regel har valideret dem, så der er intet at forklare, og de åbner intet.
cards-entities-card-nothing-extracted-from-this-document = Intek udtråget fra dette dokument.
chat-tool-cards-hide = Skjul
chat-tool-cards-expand = Udvid
chat-tool-cards-hide-raw-json = Skjul rå JSON
chat-tool-cards-show-raw-json = Vis rå JSON
cards-result-cards-search-this = Søg her
cards-result-cards-search-every-collection = Søg i alle samlinger
cards-result-cards-form = Skema { $index }: { $form }
cards-result-cards-show-full-text = Vis hele teksten
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Grund: { $why }
cards-result-cards-open-question = Åben spørgsmål: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Udforsningen gav denne svar til sin tavle som { $kind ->
        [sourced] en kildefund
        [inferred] en afledt
        [not_found] en ikke funden
       *[other] en ukendt type
    } fund.
cards-result-cards-it-left-no-open-question = Den efterlod ingen åben spørgsmål.
cards-result-cards-open-questions-for-the-board = Åben spørgsmål for tavlen:
cards-result-cards-arguments = Argumenter
cards-result-cards-list-after-the-call = Liste efter kaldet: { $snapshot_goal }
cards-result-cards-replaces = { " " }· erstatter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listen ved denne version er ikke gemt.
web-search-card-these-sources-returned-nothing-so = Disse kilder returnerede intet, så resultaterne kommer fra færre end tilsigtet
web-search-card-u-degraded = ⚠ { $degraded_len } nedbrudt
web-search-card-form = Skema { $index }: { $form }
web-search-card-no-results-from = Ingen resultater fra: { $degraded_text }
web-search-card-no-results-every-source-answered = Ingen resultater. Alle kilder svarede, og ingen havde noget for denne forespørgsel.
web-search-card-the-lowest-ranked-results-were = De lavest rangerede resultater blev droppet, så dette kald passerer i transskriptet. Assistenten så dem alle.
web-search-card-view-search-details = Vis søgedetaljer.
web-search-card-the-stored-result-could-not = det gemte resultat kunne ikke læses tilbage som JSON
web-search-card-nothing-was-stored-for-this = Der blev ikke gemt noget for dette kald.
web-search-card-forms = Formularer: { $forms }
web-search-card-kind = Type: { $row_kind }
web-search-card-published = Udgivet: { $row_published }
web-search-card-loading-search-detail-u = Indlæser søgningdetalje…
web-search-card-could-not-load-the-search = Søgningdetaljen kunne ikke indlæres: { $e }
web-search-card-malformed-detail = Fejlformet detalje: { $e }
web-search-card-the-tool-returned-selected-results = Værktøyet returnerede udvalgte resultater til modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultater bruger reciprok rangfusion.
web-search-card-returned-nothing = returnerede intet: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidater bruger fusionsorden.
web-search-card-the-cross-encoder-ranks-selected = Cross-encodern rangerer udvalgte resultater.
web-search-card-selected-results-use-fusion-order = Udvalgte resultater bruger fusionsorden.
web-search-card-search-detail = Søgningdetalje
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Søg her
chat-tool-disclosure-search-every-collection = Søg i alle samlinger
chat-tool-disclosure-hide = Skjul
chat-tool-disclosure-expand = Udvid
chat-tool-disclosure-this-step-was-recorded-before = Dette trin blev registreret, før værktøysargumenter og resultater blev gemt. Kun opsummeringen herunder er tilgængelig.
chat-tool-disclosure-arguments = Argumenter
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Skjul rå JSON
chat-tool-disclosure-show-raw-json = Vis rå JSON
chat-tool-disclosure-input-json = Indtjenings-JSON
chat-tool-disclosure-output-json = Udtjenings-JSON
chat-transcript-ask-a-question-about-the = Stil et spørgsmål om dokumenterne i dine samlinger.
chat-transcript-suggested-next = Foreslået næste...
chat-transcript-earlier-answer = Tidligere svar
chat-transcript-tokens-the-conversation-carries-the = Tokens, som samtalen fører, det største enkelt kontekst, der blev faktureret for dette træk, og hvor meget af modellens vindue det brugte
chat-transcript-instruction-to-the-agent = Instruktion til agenten
chat-transcript-the-context-stays-above-the = { " " }Konteksten forbliver over målet for { $target }.
chat-transcript-summary-parts-failed-the-record = { " " }{ $failed } opsummeringsdele fejlede. Optegnelsen indeholder kun listerne.
chat-transcript-show-the-record = Vis optegnelsen
chat-transcript-hide-reasoning = Skjul argumentation
chat-transcript-show-reasoning = Vis argumentation
chat-transcript-from-u-hide = { $count } { $noun } fra { $tool } — skjul
chat-transcript-from-u-show = { $count } { $noun } fra { $tool } — vis
chat-transcript-u-hide = { $summary } — skjul
chat-transcript-u-show = { $summary } — vis
chat-transcript-citations-of-this-conversation-give = Citater fra denne samtale giver { $doc_handle } til mere end ét dokument. Svaret knytter det til intet af dem.
chat-transcript-report = Rapportér { $label }
chat-transcript-open-in-the-workspace = Åbn i arbejdsområdet
chat-transcript-this-version-could-not-be = Denne version kunne ikke læses. Chatteksten fra svaret følger.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Find præcis tekst
chat-web-previous-match = Tidligere match
chat-web-next-match = Næste match
chat-web-close-preview = Luk forhåndsvisning
chat-web-the-captured-page-could-not = Den fangede side kunne ikke indlæses.
chat-web-loading = Indlæser…
chat-workspace-pane-workspace = Arbejdsområde
chat-workspace-pane-close-the-workspace = Luk arbejdsområdet
chat-workspace-pane-close = Luk
chat-workspace-pane-loading-the-files-u = Indlæser filerne…
chat-workspace-pane-the-files-could-not-be = Filerne kunne ikke indlæses: { $error }
chat-workspace-pane-this-conversation-has-no-files = Denne samtale har ingen filer.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Vælg en fil for at læse den.
chat-workspace-pane-loading-the-file-u = Loader filen…
chat-workspace-pane-the-file-could-not-be = Filen kunne ikke indlæses: { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Samlinger
chat-board-create-loading-collections-u = Loader samlinger…
chat-board-create-hoover-search-new-board = Hoover-søgning - Ny tavle
chat-board-create-ai-chat = AI-chat
chat-board-create-new-investigation-board = Ny undersøgelsestavle
chat-board-create-a-board-runs-its-goals = En tavle kører sine mål som en sekvens af agents udforskninger. Hver udforskning er en chat, der ender i ét fund på tavlen. Du gennemgår svaret på hvert mål, og du kan afvise fund og tilføje hints, mens den kører.
chat-board-create-title = Titel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Fjern dette mål
chat-board-create-remove = Fjern
chat-board-create-add-a-goal = Tilføj et mål
chat-board-create-context-optional = Kontekst (valgfrit)
chat-board-create-hints-one-per-line-optional = Tips, ét pr. linje (valgfrit)
chat-board-create-sources = Kilder
chat-board-create-internet-tools = Internetværktøjer
chat-board-create-creating-board = Opretter tavle...
chat-board-create-create-board = Opret tavle
ai-chat-board-hoover-search-board = Hoover-søgning - Tavle
ai-chat-board-loading-the-board-u = Loader tavlen…
ai-chat-board-show-the-board-overview = Vis tavlens oversigt
ai-chat-board-zoom-out = Zoom ud
ai-chat-board-zoom-in = Zoom ind
ai-chat-board-u-ai-chat = ← AI-chat
ai-chat-board-settings = Indstillinger
ai-chat-board-board-settings = Tavleindstillinger
ai-chat-board-internet-tools = Internetværktøjer
ai-chat-board-the-next-explores-of-the = De næste udforskninger på tavlen kan søge på internettet og læse websider. Kørende udforskninger beholder den indstilling, de startede med.
ai-chat-board-collections = Samlinger
ai-chat-board-the-collections-are-fixed-when = Samlingerne er fastlagt, når tavlen oprettes.
ai-chat-board-confirm-drop = Bekræft drop
ai-chat-board-drop-the-board = Drop tavlen
ai-chat-board-close = Luk
ai-chat-board-the-board-used-its-explore = Tavlen har brugt sin explore-grænse
ai-chat-board-the-board-used-explores-the = Tavlen har brugt { $explore_limit } explores, grænsen for én tavl. Den påbegynder ikke mere arbejde. Du kan stadig vælge de foreslåede svar.
ai-chat-board-create-a-new-board-to = Opret en ny tavl for at fortsætte undersøgelsen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Tilføj nyt mål...
ai-chat-board-a-new-goal = Et nyt mål
ai-chat-board-add-goal = Tilføj mål
ai-chat-board-a-board-has-at-most = En tavl har højst { $max_goals } mål. Opret en ny tavl for et andet mål.
ai-chat-board-background-context = Baggrundskontekst
ai-chat-board-continue-with-a-correction = Fortsæt med en rettelse
ai-chat-board-correction-what-is-wrong-or = Rettelse: hvad der er forkert eller mangler. Tavlen fortsætter hermed.
ai-chat-board-the-board-waits-for-your = Tavlen venter på din gennemgang
ai-chat-board-the-board-used-its-budget = Tavlen har brugt sit budget på { $snap_max_explores } explores.
ai-chat-board-the-assessments-gave-no-usable = Vurderingerne gav ingen brugbar retning.
ai-chat-board-accept-or-reject-the-proposed = Accepter eller afvis de foreslåede svar på hvert mål ovenfor. Et afvist svar giver tavlen mulighed for at fortsætte med det samme.
ai-chat-board-no-proposed-answer-waits-for = Der venter ingen foreslået svar på din beslutning.
ai-chat-board-reopen-the-board-to-continue = Genåben tavlen for at fortsætte de åbne mål. Den beholder sine fund og svar.
ai-chat-board-close-the-board-to-accept = Luk tavlen for at acceptere alle foreslåede svar og stoppe den, eller fortsæt den med en rettelse.
ai-chat-board-close-the-board = Luk tavlen
ai-chat-board-or-reopen-the-board-to = Eller genåben tavlen for at fortsætte de åbne mål uden en rettelse.
ai-chat-board-the-board-is-complete = Tavlen er fuldført
ai-chat-board-a-goal-has-no-accepted = Et mål har intet accepteret svar. Genåben tavlen for at fortsætte den. Tavlen beholder sine fund og svar.
ai-chat-board-add-a-hint = Tilføj et hint
ai-chat-board-the-next-assessment-reads-every = Næste vurdering læser hvert hint. Et hint svarer også på et explore, der stillede et spørgsmål.
ai-chat-board-add-hint = Tilføj hint
ai-chat-board-events = Begivenheder
ai-chat-board-newest-first = Nyeste først
ai-chat-board-date = Dato
ai-chat-board-actor = Aktør
ai-chat-board-event = Begivenhed
ai-chat-board-show-details = Vis detaljer
ai-chat-board-open = Åbn
ai-chat-board-show-the-newest-events = Vis de nyeste { $event_rows } begivenheder
ai-chat-board-show-all-events = Vis alle { $snap_events_len } begivenheder
ai-chat-board-statistics = Statistik
ai-chat-board-explores = Undersøgelser
ai-chat-board-model-steps-per-explore = Modeltrin per undersøgelse
ai-chat-board-assessments = Vurderinger
ai-chat-board-intents = Intentioner
ai-chat-board-findings = Fund
ai-chat-board-created = Oprettet
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } afviste dette fund den { $format_utc_ms_fact_rejected_ms }. Tavlen bruger ikke længere det.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } afviste dette fund. Tavlen bruger ikke længere det.
ai-chat-board-no-reason-was-given = Der blev ikke angivet en årsag.
ai-chat-board-reason = Årsag: { $fact_rejected_reason }
ai-chat-board-open-questions = Åbne spørgsmål
ai-chat-board-explored-in = Undersøgt i
ai-chat-board-explore-this-question = Undersøg dette spørgsmål
ai-chat-board-your-questions = Dine spørgsmål
ai-chat-board-ask-about-the-background-context = Spørg om baggrundskonteksten
ai-chat-board-ask-about-this-finding = Spørg om dette fund
ai-chat-board-a-follow-up-question-about = Et opfølgingsspørgsmål om denne node
ai-chat-board-ask = Spørg
ai-chat-board-checks-that-changed-this-finding = Tjek der ændrede dette fund
ai-chat-board-reject-this-correction = Afvis denne rettelse
ai-chat-board-reject-this-finding = Afvis dette fund
ai-chat-board-not-answered-the-board-was = Svaret ikke. Tavlen blev afsluttet uden svar på dette mål. Et hint eller en genåbning åbner den igen.
ai-chat-board-no-answer-yet = Intet svar endnu.
ai-chat-board-the-findings-of-this-answer = Fundene i dette svar er søgninger, der ikke fandt noget. Accepter det for at registrere, at posterne ikke svarer på målet, eller afvis det for at fortsætte undersøgelsen.
ai-chat-board-open-an-assessment-to-read = { "." } Åbn en vurdering for at læse hvorfor.
ai-chat-board-from-the-findings = Fra fundene{ " " }
ai-chat-board-accept-answer = Accepter svar
ai-chat-board-why-the-answer-is-wrong = Hvorfor svaret er forkert eller ufuldstændigt
ai-chat-board-reject-answer = Afvis svar
ai-chat-board-intent = Intention
ai-chat-board-attempts-declared = Forsøg: { $intent_attempts }. Erklæret { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Undersøgelsen spurgte
ai-chat-board-add-a-hint-in-the = Tilføj et hint i tavleoversigten for at svare på den.
ai-chat-board-last-error = Seneste fejl
ai-chat-board-brief = Kort
ai-chat-board-open-the-explore-chat = Åbn undersøgelses chatten
ai-chat-board-loading-the-assessment-u = Indlæser vurderingen…
ai-chat-board-assessment = Vurdering { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Udkom { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Tjek, der ændrede det
ai-chat-board-prompt = Opgave
ai-chat-board-this-assessment-ran-before-the = Denne vurdering kørte før, at opgaverne blev gemt.
ai-chat-board-response = Svar
ai-chat-history-hoover-search-chat-history = Hoover Search - Chat-historik
ai-chat-history-u-back = ← Tilbage
ai-chat-history-conversation-history = Samtalehistorik
ai-chat-history-show-board-chats = Vis tavle-chats
ai-chat-history-loading-u = Indlæser…
ai-chat-history-could-not-load-history = Kunne ikke indlæse historik: { $e }
ai-chat-history-no-conversations-yet = Endnu ingen samtaler.
ai-chat-history-board = Tavle
ai-chat-history-new-chat = Ny chat
ai-chat-history-messages-updated = { $s_message_count } beskeder · opdateret { $s_updated_at }
ai-chat-history-delete-conversation = Slet samtale
ai-chat-history-delete = Slet
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - AI Chat
ai-chat-homepage-what-are-you-researching = Hvad forsker du i?
ai-chat-homepage-view-all-conversations = Vis alle samtaler
ai-chat-homepage-starting-conversation-u = Starter samtale…
ai-chat-homepage-investigation-boards = Undøgelsesbor
ai-chat-homepage-new-board = Ny tavle
ai-chat-homepage-loading-boards-u = Indlæser bor…
ai-chat-homepage-could-not-load-the-boards = Borne kunne ikke indlæses: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har ingen tavle. En tavle kører en lang undøgelse som en række agentundersøgelser, og du gennemgår deres svar.
ai-chat-homepage-updated = Opdateret { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - AI Chat
ai-chat-session-this-conversation-could-not-be = Denne samtale kunne ikke indlæses.
ai-chat-session-loading-u = Indlæser…
ai-chat-session-u-chats = ← Samtaler
ai-chat-session-history = Historik
ai-chat-session-show-the-files-that-the = Vis filerne, som assistenten skrev i denne samtale
ai-chat-session-workspace = Arbejdsområde
ai-chat-session-this-answer-was-interrupted-before = Dette svar blev afbrudt, før det blev fuldført, fordi siden eller serveren stoppede midt i et drej. Spørg igen for at prøve igen.
ai-chat-session-dismiss = Luk
ai-chat-session-board-explore-chats-are-read = Chat i tavleundersøgelser er skrivebeskyttet.{ " " }
ai-chat-session-open-the-board = Åben tavlen
chat-locked-options-on = { $label }: til
chat-locked-options-off = { $label }: fra
chat-tool-cards-running-u = kører…
cards-result-cards-quote-found = Citat fundet
cards-result-cards-quote-not-found = Citat ikke fundet
cards-result-cards-quote-not-checked = Citat ikke kontrolleret
web-search-card-results = { $results_len } resultater
chat-tool-disclosure-running-u = kører…
chat-transcript-call = opkald
chat-transcript-calls = opkald
ai-chat-board-a-board-without-collections-needs = En tavle uden samlinger kræver internetværktøjer.
ai-chat-board-of = { $snap_explores_used } af { $snap_max_explores }
ai-chat-board-assessment-2 = vurdering { $number }
ai-chat-history-messages = { $s_message_count } beskeder
web-search-card-reranked-in = Cross-encodern rangerede resultaterne på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = score { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Turen venter på en fri modelplads.
chat-activity-the-turn-waits-for-a-2 = Turen venter på en fri værktøjsplads.
chat-locked-options-start-a-new-chat-to = Start en ny chat for at ændre denne indstilling.
chat-locked-options-internet-tools = Internetværktøjer
chat-session-card-new-chat = Ny chat
chat-tool-cards-first-frame-of-the-video = Første billede af videoen
chat-tool-cards-screenshot-of = Skærmbillede af
chat-tool-cards-image = Billede
cards-result-cards-the-agent-asked-a-question = Agenten stillede et spørgsmål.
chat-transcript-hide = Skjul
chat-transcript-show = Vis
chat-transcript-unverified-quote-the-quoted-span = Uverificeret citat. Det citerede afsnit er for kort til at blive kontrolleret.
chat-transcript-unverified-quote-the-document-text = Uverificeret citat. Dokumentteksten kunne ikke læses.
chat-transcript-unverified-quote-this-wording-was = Uverificeret citat. Denne formulering blev ikke fundet i dokumentet.
chat-board-create-select-a-collection-or-turn = Vælg en samling eller slå internetværktøjer til.
chat-board-create-select-at-least-one-collection = Vælg mindst en samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = Pauset
ai-chat-board-waits-for-review = Afventer gennemgang
ai-chat-board-completed = Afsluttet
ai-chat-board-dropped = Aftroppet
ai-chat-board-unknown = Ukendt
ai-chat-board-pause-the-board = Pause tavlen
ai-chat-board-resume-the-board = Genoptag tavlen
ai-chat-board-none = Ingen
ai-chat-board-reopen-with-the-remaining-budget = Genåbn med det resterende budget
ai-chat-board-finding = Fund
ai-chat-board-why-the-correction-is-wrong = Hvorfor er rettelserne forkerte
ai-chat-board-reject-correction = Afvis rettelse
ai-chat-board-why-the-finding-is-wrong = Hvorfor er fundet forkert
ai-chat-board-reject-finding = Afvis fund
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Foreslået svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pauset
ai-chat-homepage-waits-for-review = Afventer gennemgang
ai-chat-homepage-completed = Afsluttet
ai-chat-homepage-dropped = Aftroppet
ai-chat-homepage-unknown = Ukendt
cards-result-cards-submitted-by-board =
    Indsendt af tavlen: { $kind ->
        [sourced] en kildefundet
        [inferred] en afledt
        [not_found] en ikke funden
       *[other] en ukendt type
    } fund fra rapporten
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] En kildefundet
        [inferred] En afledt
        [not_found] En ikke funden
       *[other] En ukendt type
    } fund for tavlen
chat-transcript-compacting = Komprimerer konteksten: { $before } tokens til et mål på { $target }.
chat-transcript-compaction-failed = Opsummeringen af de tidligere trin fejlede. Modellen modtog de tidligere trin uændret, { $after } tokens.
chat-transcript-compacted = Kontekst komprimeret: { $steps } trin summeret, { $before } tokens til { $after }.
ai-chat-board-reopen-with-more = Genåbn med { $grant } flere explores
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Fra vurdering { $number } den { $date }.
ai-chat-board-from-assessment = Fra vurdering { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = mistede kontakten til chatten: { $e }
ai-chat-session-could-not-stop-the-answer = kunne ikke stoppe svaret: { $e } — det kører stadig
ai-chat-board-later-assessments-dropped-an-answer = { $n } senere vurderinger faldt fra med et svar for dette mål:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt- og { $a_completion_tokens } complete-token
ai-chat-homepage-completed-goals-not-answered = Fuldført, { $n } mål ikke besvaret
board-graph-intent = formål, { $state }
chat-workspace-pane-characters = { $chars } tegn
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } kører værktøj { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } kører værktøj { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Besvaret efter { $retries_len } mislykket forsøg{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } mislykket forsøg{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] søgte { $n } søgeterm
       *[other] søgte { $n } søgetermer
    }
tool-run-summary-read =
    { $n ->
        [one] læste { $n } dokument
       *[other] læste { $n } dokumenter
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] søgte på internettet for { $n } søgeterm
       *[other] søgte på internettet for { $n } søgetermer
    }
tool-run-summary-read-web =
    { $n ->
        [one] læste { $n } webside
       *[other] læste { $n } websider
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } browserhandling
       *[other] { $n } browserhandlinger
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listede entiteterne fra { $n } dokument
       *[other] listede entiteterne fra { $n } dokumenter
    }
tool-run-summary-cited =
    { $n ->
        [one] citerede { $n } dokument
       *[other] citerede { $n } dokumenter
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citerede { $n } webside
       *[other] citerede { $n } websider
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] læste { $n } færdighed- og værktøjstekst
       *[other] læste { $n } færdigheds- og værktøjtekster
    }
tool-run-summary-saved =
    { $n ->
        [one] gemte { $n } note
       *[other] gemte { $n } noter
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } opgavelisteopkald
       *[other] { $n } opgavelisteopkald
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instruktion til agenten
       *[other] { $n } instruktioner til agenten
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } andet opkald
       *[other] { $n } andre opkald
    }
tool-run-summary-failed = { $failures } mislykket
tool-run-summary-took = tog { $duration_text_ms }
chat-session-card-messages = { $session_message_count } beskeder
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } element
       *[other] { $count } elementer
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } felt
       *[other] { $count } felter
    }
chat-tool-disclosure-searched-collections = gennemgåede samlinger{ $filters }
chat-tool-disclosure-searched-collections-2 = gennemgåede samlinger · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citerede { $n } dokumenter
chat-tool-disclosure-read-document = læste dokument · { $path }
chat-tool-disclosure-searched-the-web = søgte på internettet · { $q }
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
cards-browser-card-pressed = pressede { $key }
cards-browser-card-could-not-press = kunne ikke pressede { $key }
cards-browser-card-chose-an-option-in = valgte et valg i { $element }
cards-browser-card-could-not-choose-an-option = kunne ikke vælge et valg i { $element }
cards-browser-card-hovered = holdt markøren over { $element }
cards-browser-card-could-not-hover = kunne ikke holde markøren over { $element }
cards-browser-card-failed = { $bare } — mislykkedes
cards-entities-card-listed-entities-document = listede enheder · { $count } dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · del { $part } af { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } dokumenter
cards-result-cards-forms = { $tool_name } · { $forms } formularer
cards-result-cards-in = { " " }i { $collections }
cards-result-cards-page = { " " }· side { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokumenter · { $missing } citater ikke fundet
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · uændret
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultater i, { $json_u64_doc_total_after_dedupe } efter deduplikation
