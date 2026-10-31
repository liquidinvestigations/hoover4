# Machine translation of en/chat.ftl. Do not edit by hand: change the English catalog
# and run scripts/i18n/translate_catalogs.py. See translations.json for the producer.

chat-activity-the-bot-is-working = De bot is bezig...
chat-composer-ask-the-bot = Vraag het de bot...
chat-composer-internet-tools = Internettools
chat-composer-agent-language-title = De agent antwoordt in { $language }. Wijzig de taal in de instellingen, in een nieuw tabblad.
chat-composer-try-again-in-s = Opnieuw proberen over { $secs } s
chat-composer-stop-the-answer-the-partial = Stop met het antwoord (het partiële antwoord wordt niet opgeslagen in het gesprek)
chat-composer-starting-the-conversation-u = Gesprek wordt gestart…
chat-composer-send = Versturen
chat-conversation-find-search-in-conversation = Zoeken in gesprek
chat-conversation-find-previous-match = Vorige overeenkomst
chat-conversation-find-next-match = Volgende overeenkomst
chat-conversation-find-investigation-board = Onderzoeksboard
doc-ref-card-not-openable = Niet openbaar: { $reason }.
doc-ref-card-the-search-term-was = De zoekterm was{ " " }
doc-ref-card-open = Openen
doc-ref-card-not-openable-2 = Niet openbaar
chat-markdown-text-show-the-cited-source = De geciteerde bron tonen
chat-markdown-text-no-citation-of-this-conversation = Geen citaat van dit gesprek geeft deze aanduiding, dus er staat geen document achter.
chat-markdown-text-citations-of-this-conversation-gave = Citaaten van dit gesprek geven deze aanduiding aan meer dan één document, dus dit koppelt aan geen enkel.
cards-browser-card-open-the-archived-page = De gearchiveerde pagina openen
cards-browser-card-the-page-itself-was-not = De pagina zelf is niet gearchiveerd (status: { $artifact_status }). De screenshot hierboven is wat er is bewaard.
cards-browser-card-click-the-screenshot-to-open = Klik op de screenshot om de gearchiveerde pagina te openen.
cards-browser-card-show-less = Minder tonen
cards-browser-card-show-all = Alles tonen
cards-browser-card-archived-page = Gearchiveerde pagina
cards-browser-card-download = Downloaden
cards-browser-card-archived-copy-of = Gearchiveerde kopie van { $artifact_url }
cards-browser-card-this-page-was-not-archived = Deze pagina is niet gearchiveerd (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } met een kaart
cards-entities-card-the-entity-list-was-cut = De entiteitenlijst is ingekort.
cards-entities-card-open-the-card-for-this = De kaart voor deze waarde openen ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Geen kaart: dit gesprek heeft de dataset waar deze waarden vandaan komen nooit bij naam genoemd, en de kijker wordt aangesproken bij dataset.
cards-entities-card-more-all-of-them-in = { $rest } meer, allemaal in het entiteitenpaneel van het document.{ " " }
cards-entities-card-names-organisations-and-places-above = Namen, organisaties en pleiten hierboven zijn de interpretatie van de tekst door een model. Er heeft niemand ze gevalideerd, dus er is niets te verklaren en ze openen niets.
cards-entities-card-nothing-extracted-from-this-document = Niets geëxtraheerd uit dit document.
chat-tool-cards-hide = Verbergen
chat-tool-cards-expand = Uitklappen
chat-tool-cards-hide-raw-json = Ruwe JSON verbergen
chat-tool-cards-show-raw-json = Ruwe JSON tonen
cards-result-cards-search-this = Dit doorzoeken
cards-result-cards-search-every-collection = Alle verzamelingen doorzoeken
cards-result-cards-form = Formulier { $index }: { $form }
cards-result-cards-show-full-text = Volledige tekst tonen
cards-result-cards-quote = Citaat: { $quote }
cards-result-cards-reason = Reden: { $why }
cards-result-cards-open-question = Openstaande vraag: { $question }
cards-result-cards-the-explore-gave-this-answer =
    De verkenning gaf dit antwoord aan zijn onderzoeksboard als { $kind ->
        [sourced] een bronhoudende
        [inferred] een afgeleide
        [not_found] een niet gevonden
       *[other] een onbekend type
    } vondst.
cards-result-cards-it-left-no-open-question = Er is geen openstaande vraag over.
cards-result-cards-open-questions-for-the-board = Openstaande vragen voor het onderzoeksboard:
cards-result-cards-arguments = Argumenten
cards-result-cards-list-after-the-call = Lijst na de aanroep: { $snapshot_goal }
cards-result-cards-replaces = { " " }· vervangt { $replaces_id }
cards-result-cards-the-list-at-this-version = De lijst op deze versie wordt niet opgeslagen.
web-search-card-these-sources-returned-nothing-so = Deze bronnen gaven niets terug, dus de resultaten komen van minder bronnen dan bedoeld
web-search-card-u-degraded = ⚠ { $degraded_len } verminderd
web-search-card-form = Formulier { $index }: { $form }
web-search-card-no-results-from = Geen resultaten van: { $degraded_text }
web-search-card-no-results-every-source-answered = Geen resultaten. Elke bron heeft geantwoord en geen van hen had iets voor deze zoekopdracht.
web-search-card-the-lowest-ranked-results-were = De laagst gerankte resultaten zijn verwijderd, zodat deze aanroep in het transcript past. De assistent heeft ze allemaal gezien.
web-search-card-view-search-details = Zoekgegevens bekijken.
web-search-card-the-stored-result-could-not = het opgeslagen resultaat kon niet teruggelezen worden als JSON
web-search-card-nothing-was-stored-for-this = Er is niets opgeslagen voor deze aanroep.
web-search-card-forms = Formulieren: { $forms }
web-search-card-kind = Type: { $row_kind }
web-search-card-published = Gepubliceerd: { $row_published }
web-search-card-loading-search-detail-u = Zoekdetail laden…
web-search-card-could-not-load-the-search = Het zoekdetail kon niet worden geladen: { $e }
web-search-card-malformed-detail = Ongeldige detailgegevens: { $e }
web-search-card-the-tool-returned-selected-results = Het hulpmiddel gaf geselecteerde resultaten aan het model terug.
web-search-card-results-use-reciprocal-rank-fusion = Resultaten gebruiken reciproke rangfusie.
web-search-card-returned-nothing = gaf niets terug: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidaten gebruiken fusievolgorde.
web-search-card-the-cross-encoder-ranks-selected = De cross-encoder rangschikt geselecteerde resultaten.
web-search-card-selected-results-use-fusion-order = Geselecteerde resultaten gebruiken fusievolgorde.
web-search-card-search-detail = Zoekdetail
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Hier zoeken
chat-tool-disclosure-search-every-collection = Alle verzamelingen doorzoeken
chat-tool-disclosure-hide = Verbergen
chat-tool-disclosure-expand = Uitklappen
chat-tool-disclosure-this-step-was-recorded-before = Deze stap is vastgelegd voordat toolargumenten en resultaten werden opgeslagen. Alleen de samenvatting hieronder is beschikbaar.
chat-tool-disclosure-arguments = Argumenten
chat-tool-disclosure-result = Resultaat
chat-tool-disclosure-hide-raw-json = Ruwe JSON verbergen
chat-tool-disclosure-show-raw-json = Ruwe JSON tonen
chat-tool-disclosure-input-json = Invoer-JSON
chat-tool-disclosure-output-json = Uitvoer-JSON
chat-transcript-ask-a-question-about-the = Stel een vraag over de documenten in je verzamelingen.
chat-transcript-suggested-next = Voorgestelde volgende...
chat-transcript-earlier-answer = Eerder antwoord
chat-transcript-tokens-the-conversation-carries-the = Tokens die het gesprek meedraagt, het grootste enkele contextblok dat voor deze beurt in rekening is gebracht, en hoeveel van het modelvenster hier gebruik van maakte
chat-transcript-instruction-to-the-agent = Instructie voor de agent
chat-transcript-the-context-stays-above-the = De context blijft boven het doel van { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } samenvattingsdelen mislukten. De record bevat alleen de lijsten.
chat-transcript-show-the-record = Record tonen
chat-transcript-hide-reasoning = Redenering verbergen
chat-transcript-show-reasoning = Redenering tonen
chat-transcript-from-u-hide = { $count } { $noun } uit { $tool } — verbergen
chat-transcript-from-u-show = { $count } { $noun } uit { $tool } — tonen
chat-transcript-u-hide = { $summary } — verbergen
chat-transcript-u-show = { $summary } — tonen
chat-transcript-citations-of-this-conversation-give = Citaten van dit gesprek geven { $doc_handle } aan meer dan één document. Het antwoord koppelt het aan geen van hen.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Openen in de werkruimte
chat-transcript-this-version-could-not-be = Deze versie kon niet worden gelezen. De chattekst van het antwoord volgt.
chat-transcript-files = Bestanden
chat-transcript-version = { $file_name }, versie { $file_version }
chat-web-find-exact-text = Exacte tekst zoeken
chat-web-previous-match = Vorige overeenkomst
chat-web-next-match = Volgende overeenkomst
chat-web-close-preview = Voorverbeelding sluiten
chat-web-the-captured-page-could-not = De vastgelegde pagina kon niet worden geladen.
chat-web-loading = Laden…
chat-workspace-pane-workspace = Werkruimte
chat-workspace-pane-close-the-workspace = Werkruimte sluiten
chat-workspace-pane-close = Sluiten
chat-workspace-pane-loading-the-files-u = De bestanden worden geladen…
chat-workspace-pane-the-files-could-not-be = De bestanden kon niet worden geladen: { $error }
chat-workspace-pane-this-conversation-has-no-files = Dit gesprek heeft geen bestanden.
chat-workspace-pane-version = versie { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Kies een bestand om het te lezen.
chat-workspace-pane-loading-the-file-u = Bestand laden…
chat-workspace-pane-the-file-could-not-be = Het bestand kon niet worden geladen: { $error }
chat-workspace-pane-version-2 = { $found_name }, versie { $found_version }
chat-board-create-collections = Verzamelingen
chat-board-create-loading-collections-u = Verzamelingen laden…
chat-board-create-hoover-search-new-board = Hoover Zoeken - Nieuw board
chat-board-create-ai-chat = AI Gesprek
chat-board-create-new-investigation-board = Nieuw onderzoeksboard
chat-board-create-a-board-runs-its-goals = Een board voert zijn doelen uit als een reeks agentverkenningen. Elke verkenning is een gesprek dat eindigt met één boardvondst. Je beoordeelt het antwoord van elk doel en kunt vondsten weigeren en hints toevoegen terwijl het draait.
chat-board-create-title = Titel
chat-board-create-goal = Doel
chat-board-create-remove-this-goal = Dit doel verwijderen
chat-board-create-remove = Verwijderen
chat-board-create-add-a-goal = Een doel toevoegen
chat-board-create-context-optional = Context (optioneel)
chat-board-create-hints-one-per-line-optional = Aanwijzingen, één per regel (optioneel)
chat-board-create-sources = Bronnen
chat-board-create-internet-tools = Internettools
chat-board-create-creating-board = Board aanmaken...
chat-board-create-create-board = Board aanmaken
ai-chat-board-hoover-search-board = Hoover Zoeken - Board
ai-chat-board-loading-the-board-u = Board laden…
ai-chat-board-show-the-board-overview = Boardoverzicht tonen
ai-chat-board-zoom-out = Uitzoomen
ai-chat-board-zoom-in = Inzoomen
ai-chat-board-u-ai-chat = ← AI Gesprek
ai-chat-board-settings = Instellingen
ai-chat-board-board-settings = Boardinstellingen
ai-chat-board-internet-tools = Internettools
ai-chat-board-the-next-explores-of-the = De volgende verkenningen van het board kunnen het internet doorzoeken en webpagina's lezen. Draaiende verkenningen behouden de instelling waarmee ze zijn gestart.
ai-chat-board-collections = Verzamelingen
ai-chat-board-the-collections-are-fixed-when = De verzamelingen zijn vastgelegd wanneer het board wordt aangemaakt.
ai-chat-board-confirm-drop = Drop bevestigen
ai-chat-board-drop-the-board = Board droppen
ai-chat-board-close = Sluiten
ai-chat-board-the-board-used-its-explore = Het board heeft zijn explore-limiet gebruikt
ai-chat-board-the-board-used-explores-the = Het board heeft { $explore_limit } explores gebruikt, de limiet voor één board. Er wordt geen nieuw werk gestart. Je kunt nog steeds de voorgestelde antwoorden kiezen.
ai-chat-board-create-a-new-board-to = Maak een nieuw board om het onderzoek voort te zetten
ai-chat-board-goal = Doel
ai-chat-board-goals = Doelen
ai-chat-board-add-new-goal = Nieuw doel toevoegen...
ai-chat-board-a-new-goal = Een nieuw doel
ai-chat-board-add-goal = Doel toevoegen
ai-chat-board-a-board-has-at-most = Een board heeft ten hoogste { $max_goals } doelen. Maak een nieuw board voor een ander doel.
ai-chat-board-background-context = Achtergrondcontext
ai-chat-board-continue-with-a-correction = Doorgaan met een correctie
ai-chat-board-correction-what-is-wrong-or = Correctie: wat er mis of ontbreekt. Het board gaat hiermee door.
ai-chat-board-the-board-waits-for-your = Het board wacht op jouw beoordeling
ai-chat-board-the-board-used-its-budget = Het board heeft zijn budget van { $snap_max_explores } explores gebruikt.
ai-chat-board-the-assessments-gave-no-usable = De beoordelingen gaven geen bruikbare richting.
ai-chat-board-accept-or-reject-the-proposed = Accepteer of weiger het voorgestelde antwoord van elk doel hierboven. Een geweigerd antwoord laat het board meteen doorgaan.
ai-chat-board-no-proposed-answer-waits-for = Er wacht geen voorgesteld antwoord op jouw beslissing.
ai-chat-board-reopen-the-board-to-continue = Open het board opnieuw om de open doelen voort te zetten. Het behoudt zijn vondsten en antwoorden.
ai-chat-board-close-the-board-to-accept = Sluit het board om alle voorgestelde antwoorden te accepteren en te stoppen, of zet het voort met een correctie.
ai-chat-board-close-the-board = Board sluiten
ai-chat-board-or-reopen-the-board-to = Of open het board opnieuw om de open doelen voort te zetten zonder correctie.
ai-chat-board-the-board-is-complete = Het board is voltooid
ai-chat-board-a-goal-has-no-accepted = Een doel heeft geen geaccepteerd antwoord. Open het board opnieuw om het voort te zetten. Het board behoudt zijn vondsten en antwoorden.
ai-chat-board-add-a-hint = Hint toevoegen
ai-chat-board-the-next-assessment-reads-every = De volgende beoordeling leest elke hint. Een hint beantwoordt ook een explore die een vraag stelde.
ai-chat-board-add-hint = Hint toevoegen
ai-chat-board-events = Evenementen
ai-chat-board-newest-first = Nieuwste eerst
ai-chat-board-date = Datum
ai-chat-board-actor = Acteur
ai-chat-board-event = Evenement
ai-chat-board-show-details = Details tonen
ai-chat-board-open = Openen
ai-chat-board-show-the-newest-events = Toon de nieuwste { $event_rows } gebeurtenissen
ai-chat-board-show-all-events = Alle { $snap_events_len } evenementen tonen
ai-chat-board-statistics = Statistieken
ai-chat-board-explores = Verkenningen
ai-chat-board-model-steps-per-explore = Modelstappen per verkenning
ai-chat-board-assessments = Beoordelingen
ai-chat-board-intents = Intenties
ai-chat-board-findings = Vondsten
ai-chat-board-created = Aangemaakt
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } heeft deze vondst op { $format_utc_ms_fact_rejected_ms } afgewezen. Het onderzoeksboard gebruikt deze niet meer.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } heeft deze vondst afgewezen. Het onderzoeksboard gebruikt deze niet meer.
ai-chat-board-no-reason-was-given = Er is geen reden opgegeven.
ai-chat-board-reason = Reden: { $fact_rejected_reason }
ai-chat-board-open-questions = Openstaande vragen
ai-chat-board-explored-in = Verkend in{ " " }
ai-chat-board-explore-this-question = Deze vraag verkennen
ai-chat-board-your-questions = Je vragen
ai-chat-board-ask-about-the-background-context = Vraag naar de achtergrondcontext
ai-chat-board-ask-about-this-finding = Vraag naar deze vondst
ai-chat-board-a-follow-up-question-about = Een navraag over deze knoop
ai-chat-board-ask = Vragen
ai-chat-board-checks-that-changed-this-finding = Checks die deze vondst hebben gewijzigd
ai-chat-board-reject-this-correction = Deze correctie weigeren
ai-chat-board-reject-this-finding = Deze vondst weigeren
ai-chat-board-not-answered-the-board-was = Niet beantwoord. Het onderzoeksboard is voltooid zonder antwoord op dit doel. Een hint of het heropenen opent het opnieuw.
ai-chat-board-no-answer-yet = Nog geen antwoord.
ai-chat-board-the-findings-of-this-answer = De vondsten van dit antwoord zijn zoekopdrachten die niets vonden. Accepteer om te registreren dat de bronnen het doel niet beantwoorden, of weiger om het onderzoek voort te zetten.
ai-chat-board-open-an-assessment-to-read = { "." } Open een beoordeling om te lezen waarom.
ai-chat-board-from-the-findings = Van de vondsten{ " " }
ai-chat-board-accept-answer = Antwoord accepteren
ai-chat-board-why-the-answer-is-wrong = Waarom het antwoord onjuist of onvolledig is
ai-chat-board-reject-answer = Antwoord weigeren
ai-chat-board-intent = Intentie
ai-chat-board-attempts-declared = Pogingen: { $intent_attempts }. Gedeclareerd { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = De verkenning vroeg
ai-chat-board-add-a-hint-in-the = Voeg een hint toe in het boardoverzicht om het te beantwoorden.
ai-chat-board-last-error = Laatste fout
ai-chat-board-brief = Brief
ai-chat-board-open-the-explore-chat = Verkenninggesprek openen
ai-chat-board-loading-the-assessment-u = Beoordeling laden…
ai-chat-board-assessment = Beoordeling { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Uitkomst { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Checks die dit hebben gewijzigd
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Deze beoordeling is uitgevoerd voordat de prompts werden opgeslagen.
ai-chat-board-response = Antwoord
ai-chat-history-hoover-search-chat-history = Hoover Search - Gesprekgeschiedenis
ai-chat-history-u-back = ← Terug
ai-chat-history-conversation-history = Gesprekgeschiedenis
ai-chat-history-show-board-chats = Boardgesprekken tonen
ai-chat-history-loading-u = Laden…
ai-chat-history-could-not-load-history = Geschiedenis kon niet worden geladen: { $e }
ai-chat-history-no-conversations-yet = Nog geen gesprekken.
ai-chat-history-board = Onderzoeksboard
ai-chat-history-new-chat = Nieuw gesprek
ai-chat-history-messages-updated = { $s_message_count } berichten · bijgewerkt op { $s_updated_at }
ai-chat-history-delete-conversation = Gesprek verwijderen
ai-chat-history-delete = Verwijderen
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - AI-gesprek
ai-chat-homepage-what-are-you-researching = Waar ben je mee aan het onderzoeken?
ai-chat-homepage-view-all-conversations = Alle gesprekken bekijken
ai-chat-homepage-starting-conversation-u = Gesprek starten…
ai-chat-homepage-investigation-boards = Onderzoekboards
ai-chat-homepage-new-board = Nieuw board
ai-chat-homepage-loading-boards-u = Boards laden…
ai-chat-homepage-could-not-load-the-boards = De boards konden niet worden geladen: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Je hebt geen board. Een board voert een langdurig onderzoek uit als opeenvolging van agentverkenningen, en jij beoordeelt de antwoorden.
ai-chat-homepage-updated = Bijgewerkt op { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - AI-gesprek
ai-chat-session-this-conversation-could-not-be = Gesprek kon niet worden geladen.
ai-chat-session-loading-u = Laden…
ai-chat-session-u-chats = ← Gesprekken
ai-chat-session-history = Geschiedenis
ai-chat-session-show-the-files-that-the = De bestanden tonen die de assistent in dit gesprek heeft geschreven
ai-chat-session-workspace = Werkruimte
ai-chat-session-this-answer-was-interrupted-before = Dit antwoord is onderbroken voordat het af was, omdat de pagina of de server halverwege een beurt is gestopt. Vraag opnieuw om het opnieuw te proberen.
ai-chat-session-dismiss = Sluiten
ai-chat-session-board-explore-chats-are-read = Board-verkenninggesprekken zijn alleen-lezen.{ " " }
ai-chat-session-open-the-board = Board openen
chat-locked-options-on = { $label }: aan
chat-locked-options-off = { $label }: uit
chat-tool-cards-running-u = bezig…
cards-result-cards-quote-found = Citaat gevonden
cards-result-cards-quote-not-found = Citaat niet gevonden
cards-result-cards-quote-not-checked = Citaat niet gecontroleerd
web-search-card-results = { $results_len } resultaten
chat-tool-disclosure-running-u = bezig…
chat-transcript-call = gesprek
chat-transcript-calls = gesprekken
ai-chat-board-a-board-without-collections-needs = Een onderzoeksboard zonder verzamelingen heeft internettools nodig.
ai-chat-board-of = { $snap_explores_used } van { $snap_max_explores }
ai-chat-board-assessment-2 = beoordeling { $number }
ai-chat-history-messages = { $s_message_count } berichten
web-search-card-reranked-in = De cross-encoder heeft de resultaten gerangschikt in { $ms } ms.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = score { $score } · was RRF #{ $rank }
chat-activity-the-turn-waits-for-a = De beurt wacht op een vrij modelslot.
chat-activity-the-turn-waits-for-a-2 = De beurt wacht op een vrij toolslot.
chat-locked-options-start-a-new-chat-to = Start een nieuw gesprek om deze instelling te wijzigen.
chat-locked-options-internet-tools = Internettools
chat-session-card-new-chat = Nieuw gesprek
chat-tool-cards-first-frame-of-the-video = Eerste frame van de video
chat-tool-cards-screenshot-of = Screenshoot van
chat-tool-cards-image = Afbeelding
cards-result-cards-the-agent-asked-a-question = De agent heeft een vraag gesteld.
chat-transcript-hide = Verbergen
chat-transcript-show = Tonen
chat-transcript-unverified-quote-the-quoted-span = Niet geverifieerd citaat. De geciteerde tekst is te kort om te controleren.
chat-transcript-unverified-quote-the-document-text = Niet geverifieerd citaat. De documenttekst kon niet worden gelezen.
chat-transcript-unverified-quote-this-wording-was = Niet geverifieerd citaat. Deze formulering is niet in het document gevonden.
chat-board-create-select-a-collection-or-turn = Selecteer een verzameling of schakel internettools in.
chat-board-create-select-at-least-one-collection = Selecteer ten minste één verzameling.
ai-chat-board-active = Actief
ai-chat-board-paused = Gepauzeerd
ai-chat-board-waits-for-review = Wacht op beoordeling
ai-chat-board-completed = Voltooid
ai-chat-board-dropped = Verworpen
ai-chat-board-unknown = Onbekend
ai-chat-board-pause-the-board = Board pauzeren
ai-chat-board-resume-the-board = Board hervatten
ai-chat-board-none = Geen
ai-chat-board-reopen-with-the-remaining-budget = Opnieuw openen met resterend budget
ai-chat-board-finding = Vondst
ai-chat-board-why-the-correction-is-wrong = Waarom de correctie onjuist is
ai-chat-board-reject-correction = Correctie verwerpen
ai-chat-board-why-the-finding-is-wrong = Waarom de vondst onjuist is
ai-chat-board-reject-finding = Vondst verwerpen
ai-chat-board-answer = Antwoord
ai-chat-board-proposed-answer = Voorgesteld antwoord
ai-chat-homepage-active = Actief
ai-chat-homepage-paused = Gepauzeerd
ai-chat-homepage-waits-for-review = Wacht op beoordeling
ai-chat-homepage-completed = Voltooid
ai-chat-homepage-dropped = Verworpen
ai-chat-homepage-unknown = Onbekend
cards-result-cards-submitted-by-board =
    Door het board ingediend: { $kind ->
        [sourced] een bronvermelding
        [inferred] een afgeleide
        [not_found] niet gevonden
       *[other] een onbekend type
    } vondst uit het rapport
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Een bronvermelding
        [inferred] Een afgeleide
        [not_found] Niet gevonden
       *[other] Een onbekend type
    } vondst voor het board
chat-transcript-compacting = Context comprimeren: { $before } tokens naar een doel van { $target }.
chat-transcript-compaction-failed = De samenvatting van de eerdere stappen is mislukt. Het model heeft de eerdere stappen ongewijzigd ontvangen, { $after } tokens.
chat-transcript-compacted = Context gecomprimeerd: { $steps } stappen samengevat, van { $before } tokens naar { $after }.
ai-chat-board-reopen-with-more = Opnieuw openen met { $grant } verkenningen meer
ai-chat-board-goal-number = Doel { $number }
ai-chat-board-from-assessment-on = Van beoordeling { $number } op { $date }.
ai-chat-board-from-assessment = Van beoordeling { $number }.
chat-board-create-goal-2 = Doel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = contact met het gesprek verloren: { $e }
ai-chat-session-could-not-stop-the-answer = kon het antwoord niet stoppen: { $e } — het is nog actief
ai-chat-board-later-assessments-dropped-an-answer = { $n } latere beoordelingen hebben een antwoord voor dit doel verwijderd:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt-en { $a_completion_tokens } completion-tokens
ai-chat-homepage-completed-goals-not-answered = Voltooid, { $n } doelen niet beantwoord
board-graph-intent = intent, { $state }
chat-workspace-pane-characters = { $chars } tekens
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } actieve tool { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } actieve tool { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Beantwoord na { $retries_len } mislukte poging{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } mislukte poging{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, versie { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] { $n } zoekopdracht uitgevoerd
       *[other] { $n } zoekopdrachten uitgevoerd
    }
tool-run-summary-read =
    { $n ->
        [one] { $n } document gelezen
       *[other] { $n } documents gelezen
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] { $n } zoekopdracht op het web
       *[other] { $n } zoekopdrachten op het web
    }
tool-run-summary-read-web =
    { $n ->
        [one] { $n } webpagina gelezen
       *[other] { $n } webpagina's gelezen
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } browseractie
       *[other] { $n } browseracties
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] { $n } document verwerkt
       *[other] { $n } documenten verwerkt
    }
tool-run-summary-cited =
    { $n ->
        [one] { $n } document geciteerd
       *[other] { $n } documenten geciteerd
    }
tool-run-summary-cited-web =
    { $n ->
        [one] { $n } webpagina geciteerd
       *[other] { $n } webpagina's geciteerd
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] { $n } skill- en tooltekst gelezen
       *[other] { $n } skill- en toolteksten gelezen
    }
tool-run-summary-saved =
    { $n ->
        [one] { $n } notitie opgeslagen
       *[other] { $n } notities opgeslagen
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } todo-lijst-opdracht
       *[other] { $n } todo-lijst-opdrachten
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instructie aan de agent
       *[other] { $n } instructies aan de agent
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } andere opdracht
       *[other] { $n } andere opdrachten
    }
tool-run-summary-failed = { $failures } mislukt
tool-run-summary-took = { $duration_text_ms } gedurig
chat-session-card-messages = { $session_message_count } berichten
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } item
       *[other] { $count } items
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } veld
       *[other] { $count } velden
    }
chat-tool-disclosure-searched-collections = doorzochte verzamelingen{ $filters }
chat-tool-disclosure-searched-collections-2 = doorzochte verzamelingen · { $query }{ $filters }
chat-tool-disclosure-cited-documents = geciteerde { $n } documenten
chat-tool-disclosure-read-document = document gelezen · { $path }
chat-tool-disclosure-searched-the-web = web doorzocht · { $q }
chat-tool-disclosure-opened-page = pagina geopend · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = aangeroepen { $other }
chat-tool-disclosure-called-2 = aangeroepen { $other } · { $short }
cards-browser-card-opened = geopend { $url }
cards-browser-card-could-not-open = kon niet openen { $url }
cards-browser-card-clicked = geklikt op { $element }
cards-browser-card-could-not-click = kon niet klikken op { $element }
cards-browser-card-typed-into = getypt in { $element }
cards-browser-card-could-not-type-into = kon niet typen in { $element }
cards-browser-card-typed = “{ $text }” getypt
cards-browser-card-could-not-type = “{ $text }” kon niet worden getypt
cards-browser-card-pressed = ingedrukt { $key }
cards-browser-card-could-not-press = kon niet indrukken { $key }
cards-browser-card-chose-an-option-in = optie gekozen in { $element }
cards-browser-card-could-not-choose-an-option = kon niet een optie kiezen in { $element }
cards-browser-card-hovered = over { $element } bewogen
cards-browser-card-could-not-hover = kon niet over { $element } bewegen
cards-browser-card-failed = { $bare } — mislukt
cards-entities-card-listed-entities-document = entiteiten vermeld · { $count } document{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · deel { $part } van { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } documenten
cards-result-cards-forms = { $tool_name } · { $forms } formulieren
cards-result-cards-in = { " " }in { $collections }
cards-result-cards-page = { " " }· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documenten · { $missing } cita(ation|ten) niet gevonden
cards-result-cards-version-unchanged = { $tool_name } · versie { $version } · ongewijzigd
cards-result-cards-version = { $tool_name } · versie { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultaten in, { $json_u64_doc_total_after_dedupe } na deduplicatie
