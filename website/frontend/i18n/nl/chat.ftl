# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = De bot is aan het werk...
chat-composer-ask-the-bot = Vraag het aan de bot...
chat-composer-internet-tools = Internettools
chat-composer-agent-language-title = De agent antwoordt in het { $language }. Wijzig de taal in de instellingen, in een nieuw tabblad.
chat-composer-try-again-in-s = Probeer het opnieuw over { $secs } s
chat-composer-stop-the-answer-the-partial = Het antwoord stoppen (het deelantwoord wordt niet in het gesprek opgeslagen)
chat-composer-starting-the-conversation-u = Het gesprek starten…
chat-composer-send = Verzenden
chat-conversation-find-search-in-conversation = Zoeken in gesprek
chat-conversation-find-previous-match = Vorige treffer
chat-conversation-find-next-match = Volgende treffer
chat-conversation-find-investigation-board = Onderzoeksbord
doc-ref-card-not-openable = Niet te openen: { $reason }.
doc-ref-card-the-search-term-was = De zoekterm was{" "}
doc-ref-card-open = Openen
doc-ref-card-not-openable-2 = Niet te openen
chat-markdown-text-show-the-cited-source = Toon de aangehaalde bron
chat-markdown-text-no-citation-of-this-conversation = Geen bronverwijzing in dit gesprek heeft deze verwijzing gegeven, dus er staat geen document achter.
chat-markdown-text-citations-of-this-conversation-gave = Bronverwijzingen in dit gesprek hebben deze verwijzing aan meer dan één document gegeven, dus ze linkt naar geen ervan.
cards-browser-card-open-the-archived-page = Open de gearchiveerde pagina
cards-browser-card-the-page-itself-was-not = De pagina zelf is niet gearchiveerd (status: { $artifact_status }). De schermafbeelding hierboven is wat is bewaard.
cards-browser-card-click-the-screenshot-to-open = Klik op de schermafbeelding om de gearchiveerde pagina te openen.
cards-browser-card-show-less = Minder tonen
cards-browser-card-show-all = Alles tonen
cards-browser-card-archived-page = Gearchiveerde pagina
cards-browser-card-download = Downloaden
cards-browser-card-archived-copy-of = Gearchiveerde kopie van { $artifact_url }
cards-browser-card-this-page-was-not-archived = Deze pagina is niet gearchiveerd (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } met een kaart
cards-entities-card-the-entity-list-was-cut = De entiteitenlijst is afgekapt.
cards-entities-card-open-the-card-for-this = Open de kaart voor deze waarde ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Geen kaart: dit gesprek heeft de dataset waar deze waarden vandaan komen nooit genoemd, en de viewer wordt via de dataset aangesproken.
cards-entities-card-more-all-of-them-in = nog { $rest }, allemaal in het entiteitenpaneel van het document.{" "}
cards-entities-card-names-organisations-and-places-above = Namen, organisaties en plaatsen hierboven zijn de lezing van een model van de lopende tekst. Geen regel heeft ze gevalideerd, dus er valt niets uit te leggen en ze openen niets.
cards-entities-card-nothing-extracted-from-this-document = Niets uit dit document gehaald.
chat-tool-cards-hide = Verbergen
chat-tool-cards-expand = Uitklappen
chat-tool-cards-hide-raw-json = Ruwe JSON verbergen
chat-tool-cards-show-raw-json = Ruwe JSON tonen
cards-result-cards-search-this = Hierop zoeken
cards-result-cards-search-every-collection = In alle collecties zoeken
cards-result-cards-form = Variant { $index }: { $form }
cards-result-cards-show-full-text = Volledige tekst tonen
cards-result-cards-quote = Citaat: { $quote }
cards-result-cards-reason = Reden: { $why }
cards-result-cards-open-question = Open vraag: { $question }
cards-result-cards-the-explore-gave-this-answer = De verkenning gaf dit antwoord aan haar bord als bevinding ({ $kind ->
        [sourced] met bronnen
        [inferred] afgeleid
        [not_found] niet gevonden
       *[other] van onbekend soort
    }).
cards-result-cards-it-left-no-open-question = Ze liet geen open vraag achter.
cards-result-cards-open-questions-for-the-board = Open vragen voor het bord:
cards-result-cards-arguments = Argumenten
cards-result-cards-list-after-the-call = Lijst na de aanroep: { $snapshot_goal }
cards-result-cards-replaces = {" "}· vervangt { $replaces_id }
cards-result-cards-the-list-at-this-version = De lijst in deze versie is niet opgeslagen.
web-search-card-these-sources-returned-nothing-so = Deze bronnen leverden niets op, dus de resultaten komen van minder bronnen dan bedoeld
web-search-card-u-degraded = ⚠ { $degraded_len } verminderd
web-search-card-form = Variant { $index }: { $form }
web-search-card-no-results-from = Geen resultaten van: { $degraded_text }
web-search-card-no-results-every-source-answered = Geen resultaten. Elke bron heeft geantwoord en geen enkele had iets voor deze zoekopdracht.
web-search-card-the-lowest-ranked-results-were = De laagst gerangschikte resultaten zijn weggelaten zodat deze aanroep in het transcript past. De assistent heeft ze allemaal gezien.
web-search-card-view-search-details = Zoekdetails bekijken.
web-search-card-the-stored-result-could-not = het opgeslagen resultaat kon niet als JSON worden teruggelezen
web-search-card-nothing-was-stored-for-this = Voor deze aanroep is niets opgeslagen.
web-search-card-forms = Varianten: { $forms }
web-search-card-kind = Soort: { $row_kind }
web-search-card-published = Gepubliceerd: { $row_published }
web-search-card-loading-search-detail-u = Zoekdetails laden…
web-search-card-could-not-load-the-search = De zoekdetails konden niet worden geladen: { $e }
web-search-card-malformed-detail = Ongeldige details: { $e }
web-search-card-the-tool-returned-selected-results = De tool gaf geselecteerde resultaten terug aan het model.
web-search-card-results-use-reciprocal-rank-fusion = De resultaten gebruiken reciprocal rank fusion.
web-search-card-returned-nothing = leverde niets op: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alle kandidaten gebruiken de fusievolgorde.
web-search-card-the-cross-encoder-ranks-selected = De cross-encoder rangschikt de geselecteerde resultaten.
web-search-card-selected-results-use-fusion-order = De geselecteerde resultaten gebruiken de fusievolgorde.
web-search-card-search-detail = Zoekdetails
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Hierop zoeken
chat-tool-disclosure-search-every-collection = In alle collecties zoeken
chat-tool-disclosure-hide = Verbergen
chat-tool-disclosure-expand = Uitklappen
chat-tool-disclosure-this-step-was-recorded-before = Deze stap is vastgelegd voordat toolargumenten en -resultaten werden opgeslagen. Alleen de samenvatting hieronder is beschikbaar.
chat-tool-disclosure-arguments = Argumenten
chat-tool-disclosure-result = Resultaat
chat-tool-disclosure-hide-raw-json = Ruwe JSON verbergen
chat-tool-disclosure-show-raw-json = Ruwe JSON tonen
chat-tool-disclosure-input-json = Invoer-JSON
chat-tool-disclosure-output-json = Uitvoer-JSON
chat-transcript-ask-a-question-about-the = Stel een vraag over de documenten in je collecties.
chat-transcript-suggested-next = Voorgestelde vervolgstappen...
chat-transcript-earlier-answer = Eerder antwoord
chat-transcript-tokens-the-conversation-carries-the = Tokens in het gesprek, de grootste afzonderlijke context waarvoor deze beurt is gefactureerd, en hoeveel van het venster van het model daarmee is gebruikt
chat-transcript-instruction-to-the-agent = Instructie aan de agent
chat-transcript-the-context-stays-above-the = {" "}De context blijft boven de streefwaarde van { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } samenvattingsdelen zijn mislukt. Het overzicht bevat alleen de lijsten.
chat-transcript-show-the-record = Het overzicht tonen
chat-transcript-hide-reasoning = Redenering verbergen
chat-transcript-show-reasoning = Redenering tonen
chat-transcript-from-u-hide = { $count } { $count ->
        [one] document
       *[other] documenten
    } van { $tool } — verbergen
chat-transcript-from-u-show = { $count } { $count ->
        [one] document
       *[other] documenten
    } van { $tool } — tonen
chat-transcript-u-hide = { $summary } — verbergen
chat-transcript-u-show = { $summary } — tonen
chat-transcript-citations-of-this-conversation-give = Bronverwijzingen in dit gesprek geven { $doc_handle } aan meer dan één document. Het antwoord linkt het naar geen ervan.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Openen in de werkruimte
chat-transcript-this-version-could-not-be = Deze versie kon niet worden gelezen. Hieronder volgt de chattekst van het antwoord.
chat-transcript-files = Bestanden
chat-transcript-version = { $file_name }, versie { $file_version }
chat-web-find-exact-text = Exacte tekst zoeken
chat-web-previous-match = Vorige treffer
chat-web-next-match = Volgende treffer
chat-web-close-preview = Voorvertoning sluiten
chat-web-the-captured-page-could-not = De vastgelegde pagina kon niet worden geladen.
chat-web-loading = Laden…
chat-workspace-pane-workspace = Werkruimte
chat-workspace-pane-close-the-workspace = De werkruimte sluiten
chat-workspace-pane-close = Sluiten
chat-workspace-pane-loading-the-files-u = De bestanden laden…
chat-workspace-pane-the-files-could-not-be = De bestanden konden niet worden geladen: { $error }
chat-workspace-pane-this-conversation-has-no-files = Dit gesprek heeft geen bestanden.
chat-workspace-pane-version = versie { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Kies een bestand om het te lezen.
chat-workspace-pane-loading-the-file-u = Het bestand laden…
chat-workspace-pane-the-file-could-not-be = Het bestand kon niet worden geladen: { $error }
chat-workspace-pane-version-2 = { $found_name }, versie { $found_version }
chat-board-create-collections = Collecties
chat-board-create-loading-collections-u = Collecties laden…
chat-board-create-hoover-search-new-board = Hoover Zoeken - Nieuw bord
chat-board-create-ai-chat = AI-chat
chat-board-create-new-investigation-board = Nieuw onderzoeksbord
chat-board-create-a-board-runs-its-goals = Een bord werkt zijn doelen af als een reeks verkenningen door agents. Elke verkenning is een chat die eindigt in één bevinding op het bord. Jij beoordeelt het antwoord op elk doel, en je kunt tijdens de uitvoering bevindingen afwijzen en hints toevoegen.
chat-board-create-title = Titel
chat-board-create-goal = Doel
chat-board-create-remove-this-goal = Dit doel verwijderen
chat-board-create-remove = Verwijderen
chat-board-create-add-a-goal = Een doel toevoegen
chat-board-create-context-optional = Context (optioneel)
chat-board-create-hints-one-per-line-optional = Hints, één per regel (optioneel)
chat-board-create-sources = Bronnen
chat-board-create-internet-tools = Internettools
chat-board-create-creating-board = Bord aanmaken...
chat-board-create-create-board = Bord aanmaken
ai-chat-board-hoover-search-board = Hoover Zoeken - Bord
ai-chat-board-loading-the-board-u = Het bord laden…
ai-chat-board-show-the-board-overview = Het overzicht van het bord tonen
ai-chat-board-zoom-out = Uitzoomen
ai-chat-board-zoom-in = Inzoomen
ai-chat-board-u-ai-chat = ← AI-chat
ai-chat-board-settings = Instellingen
ai-chat-board-board-settings = Instellingen van het bord
ai-chat-board-internet-tools = Internettools
ai-chat-board-the-next-explores-of-the = De volgende verkenningen van het bord kunnen het web doorzoeken en webpagina's lezen. Lopende verkenningen houden de instelling waarmee ze zijn gestart.
ai-chat-board-collections = Collecties
ai-chat-board-the-collections-are-fixed-when = De collecties liggen vast wanneer het bord wordt aangemaakt.
ai-chat-board-confirm-drop = Verwijderen bevestigen
ai-chat-board-drop-the-board = Het bord verwijderen
ai-chat-board-close = Sluiten
ai-chat-board-the-board-used-its-explore = Het bord heeft zijn verkenningslimiet bereikt
ai-chat-board-the-board-used-explores-the = Het bord heeft { $explore_limit } verkenningen gebruikt, de limiet van één bord. Het start geen nieuw werk meer. Je kunt nog wel over de voorgestelde antwoorden beslissen.
ai-chat-board-create-a-new-board-to = Maak een nieuw bord aan om het onderzoek voort te zetten
ai-chat-board-goal = Doel
ai-chat-board-goals = Doelen
ai-chat-board-add-new-goal = Nieuw doel toevoegen...
ai-chat-board-a-new-goal = Een nieuw doel
ai-chat-board-add-goal = Doel toevoegen
ai-chat-board-a-board-has-at-most = Een bord heeft maximaal { $max_goals } doelen. Maak een nieuw bord aan voor een ander doel.
ai-chat-board-background-context = Achtergrondcontext
ai-chat-board-continue-with-a-correction = Voortzetten met een correctie
ai-chat-board-correction-what-is-wrong-or = Correctie: wat er niet klopt of ontbreekt. Het bord gaat hiermee verder.
ai-chat-board-the-board-waits-for-your = Het bord wacht op jouw beoordeling
ai-chat-board-the-board-used-its-budget = Het bord heeft zijn budget van { $snap_max_explores } verkenningen gebruikt.
ai-chat-board-the-assessments-gave-no-usable = De evaluaties gaven geen bruikbare richting.
ai-chat-board-accept-or-reject-the-proposed = Accepteer of wijs het voorgestelde antwoord van elk doel hierboven af. Bij een afgewezen antwoord gaat het bord meteen verder.
ai-chat-board-no-proposed-answer-waits-for = Er wacht geen voorgesteld antwoord op jouw beslissing.
ai-chat-board-reopen-the-board-to-continue = Heropen het bord om de open doelen voort te zetten. Het behoudt zijn bevindingen en antwoorden.
ai-chat-board-close-the-board-to-accept = Sluit het bord om alle voorgestelde antwoorden te accepteren en het te stoppen, of zet het voort met een correctie.
ai-chat-board-close-the-board = Het bord sluiten
ai-chat-board-or-reopen-the-board-to = Of heropen het bord om de open doelen zonder correctie voort te zetten.
ai-chat-board-the-board-is-complete = Het bord is volledig
ai-chat-board-a-goal-has-no-accepted = Een doel heeft geen geaccepteerd antwoord. Heropen het bord om het voort te zetten. Het bord behoudt zijn bevindingen en antwoorden.
ai-chat-board-add-a-hint = Een hint toevoegen
ai-chat-board-the-next-assessment-reads-every = De volgende evaluatie leest elke hint. Een hint beantwoordt ook een verkenning die een vraag stelde.
ai-chat-board-add-hint = Hint toevoegen
ai-chat-board-events = Gebeurtenissen
ai-chat-board-newest-first = Nieuwste eerst
ai-chat-board-date = Datum
ai-chat-board-actor = Actor
ai-chat-board-event = Gebeurtenis
ai-chat-board-show-details = Details tonen
ai-chat-board-open = Openen
ai-chat-board-show-the-newest-events = Toon de nieuwste { $event_rows } gebeurtenissen
ai-chat-board-show-all-events = Toon alle { $snap_events_len } gebeurtenissen
ai-chat-board-statistics = Statistieken
ai-chat-board-explores = Verkenningen
ai-chat-board-model-steps-per-explore = Modelstappen per verkenning
ai-chat-board-assessments = Evaluaties
ai-chat-board-intents = Intenties
ai-chat-board-findings = Bevindingen
ai-chat-board-created = Aangemaakt
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } heeft deze bevinding afgewezen op { $format_utc_ms_fact_rejected_ms }. Het bord gebruikt haar niet meer.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } heeft deze bevinding afgewezen. Het bord gebruikt haar niet meer.
ai-chat-board-no-reason-was-given = Er is geen reden opgegeven.
ai-chat-board-reason = Reden: { $fact_rejected_reason }
ai-chat-board-open-questions = Open vragen
ai-chat-board-explored-in = Verkend in{" "}
ai-chat-board-explore-this-question = Deze vraag verkennen
ai-chat-board-your-questions = Jouw vragen
ai-chat-board-ask-about-the-background-context = Vraag naar de achtergrondcontext
ai-chat-board-ask-about-this-finding = Vraag naar deze bevinding
ai-chat-board-a-follow-up-question-about = Een vervolgvraag over dit knooppunt
ai-chat-board-ask = Vragen
ai-chat-board-checks-that-changed-this-finding = Controles die deze bevinding hebben gewijzigd
ai-chat-board-reject-this-correction = Deze correctie afwijzen
ai-chat-board-reject-this-finding = Deze bevinding afwijzen
ai-chat-board-not-answered-the-board-was = Niet beantwoord. Het bord is afgerond zonder antwoord op dit doel. Een hint of een heropening opent het opnieuw.
ai-chat-board-no-answer-yet = Nog geen antwoord.
ai-chat-board-the-findings-of-this-answer = De bevindingen van dit antwoord zijn zoekopdrachten die niets opleverden. Accepteer het om vast te leggen dat de gegevens het doel niet beantwoorden, of wijs het af om het onderzoek voort te zetten.
ai-chat-board-open-an-assessment-to-read = {"."} Open een evaluatie om te lezen waarom.
ai-chat-board-from-the-findings = Uit de bevindingen{" "}
ai-chat-board-accept-answer = Antwoord accepteren
ai-chat-board-why-the-answer-is-wrong = Waarom het antwoord onjuist of onvolledig is
ai-chat-board-reject-answer = Antwoord afwijzen
ai-chat-board-intent = Intentie
ai-chat-board-attempts-declared = Pogingen: { $intent_attempts }. Gedeclareerd { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = De verkenning vroeg
ai-chat-board-add-a-hint-in-the = Voeg een hint toe in het overzicht van het bord om te antwoorden.
ai-chat-board-last-error = Laatste fout
ai-chat-board-brief = Opdracht
ai-chat-board-open-the-explore-chat = De chat van de verkenning openen
ai-chat-board-loading-the-assessment-u = De evaluatie laden…
ai-chat-board-assessment = Evaluatie { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Uitkomst { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Controles die het hebben gewijzigd
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Deze evaluatie draaide voordat de prompts werden opgeslagen.
ai-chat-board-response = Antwoord
ai-chat-history-hoover-search-chat-history = Hoover Zoeken - Chatgeschiedenis
ai-chat-history-u-back = ← Terug
ai-chat-history-conversation-history = Gespreksgeschiedenis
ai-chat-history-show-board-chats = Chats van borden tonen
ai-chat-history-loading-u = Laden…
ai-chat-history-could-not-load-history = De geschiedenis kon niet worden geladen: { $e }
ai-chat-history-no-conversations-yet = Nog geen gesprekken.
ai-chat-history-board = Bord
ai-chat-history-new-chat = Nieuwe chat
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } bericht · bijgewerkt { $s_updated_at }
    *[other] { $s_message_count } berichten · bijgewerkt { $s_updated_at }
    }

ai-chat-history-delete-conversation = Gesprek verwijderen
ai-chat-history-delete = Verwijderen
ai-chat-homepage-hoover-search-ai-chat = Hoover Zoeken - AI-chat
ai-chat-homepage-what-are-you-researching = Wat onderzoek je?
ai-chat-homepage-view-all-conversations = Alle gesprekken bekijken
ai-chat-homepage-starting-conversation-u = Gesprek starten…
ai-chat-homepage-investigation-boards = Onderzoeksborden
ai-chat-homepage-new-board = Nieuw bord
ai-chat-homepage-loading-boards-u = Borden laden…
ai-chat-homepage-could-not-load-the-boards = De borden konden niet worden geladen: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Je hebt geen bord. Een bord voert een langer onderzoek uit als een reeks verkenningen door agents, en jij beoordeelt de antwoorden.
ai-chat-homepage-updated = Bijgewerkt { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Zoeken - AI-chat
ai-chat-session-this-conversation-could-not-be = Dit gesprek kon niet worden geladen.
ai-chat-session-loading-u = Laden…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = Geschiedenis
ai-chat-session-show-the-files-that-the = Toon de bestanden die de assistent in dit gesprek heeft geschreven
ai-chat-session-workspace = Werkruimte
ai-chat-session-this-answer-was-interrupted-before = Dit antwoord is onderbroken voordat het klaar was, omdat de pagina of de server midden in de beurt stopte. Vraag het opnieuw om het nogmaals te proberen.
ai-chat-session-dismiss = Sluiten
ai-chat-session-board-explore-chats-are-read = Chats van bordverkenningen zijn alleen-lezen.{" "}
ai-chat-session-open-the-board = Het bord openen
chat-locked-options-on = { $label }: aan
chat-locked-options-off = { $label }: uit
chat-tool-cards-running-u = bezig…
cards-result-cards-quote-found = Citaat gevonden
cards-result-cards-quote-not-found = Citaat niet gevonden
cards-result-cards-quote-not-checked = Citaat niet gecontroleerd
web-search-card-results = { $results_len } resultaten
chat-tool-disclosure-running-u = bezig…
chat-transcript-call = aanroep
chat-transcript-calls = aanroepen
ai-chat-board-a-board-without-collections-needs = Een bord zonder collecties heeft internettools nodig.
ai-chat-board-of = { $snap_explores_used } van { $snap_max_explores }
ai-chat-board-assessment-2 = evaluatie { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } bericht
    *[other] { $s_message_count } berichten
    }

web-search-card-reranked-in = De cross-encoder heeft de resultaten in { $ms } ms herrangschikt.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = score { $score } · was RRF #{ $rank }
chat-activity-the-turn-waits-for-a = De beurt wacht op een vrij modelslot.
chat-activity-the-turn-waits-for-a-2 = De beurt wacht op een vrij toolslot.
chat-locked-options-start-a-new-chat-to = Begin een nieuwe chat om deze instelling te wijzigen.
chat-locked-options-internet-tools = Internettools
chat-session-card-new-chat = Nieuwe chat
chat-tool-cards-first-frame-of-the-video = Eerste beeld van de video
chat-tool-cards-screenshot-of = Schermafbeelding van
chat-tool-cards-image = Afbeelding
cards-result-cards-the-agent-asked-a-question = De agent stelde een vraag.
chat-transcript-hide = Verbergen
chat-transcript-show = Tonen
chat-transcript-unverified-quote-the-quoted-span = Niet geverifieerd citaat. Het aangehaalde stuk is te kort om te controleren.
chat-transcript-unverified-quote-the-document-text = Niet geverifieerd citaat. De documenttekst kon niet worden gelezen.
chat-transcript-unverified-quote-this-wording-was = Niet geverifieerd citaat. Deze formulering is niet in het document gevonden.
chat-board-create-select-a-collection-or-turn = Kies een collectie of schakel internettools in.
chat-board-create-select-at-least-one-collection = Kies minstens één collectie.
ai-chat-board-active = Actief
ai-chat-board-paused = Gepauzeerd
ai-chat-board-waits-for-review = Wacht op beoordeling
ai-chat-board-completed = Voltooid
ai-chat-board-dropped = Verwijderd
ai-chat-board-unknown = Onbekend
ai-chat-board-pause-the-board = Het bord pauzeren
ai-chat-board-resume-the-board = Het bord hervatten
ai-chat-board-none = Geen
ai-chat-board-reopen-with-the-remaining-budget = Heropenen met het resterende budget
ai-chat-board-finding = Bevinding
ai-chat-board-why-the-correction-is-wrong = Waarom de correctie onjuist is
ai-chat-board-reject-correction = Correctie afwijzen
ai-chat-board-why-the-finding-is-wrong = Waarom de bevinding onjuist is
ai-chat-board-reject-finding = Bevinding afwijzen
ai-chat-board-answer = Antwoord
ai-chat-board-proposed-answer = Voorgesteld antwoord
ai-chat-homepage-active = Actief
ai-chat-homepage-paused = Gepauzeerd
ai-chat-homepage-waits-for-review = Wacht op beoordeling
ai-chat-homepage-completed = Voltooid
ai-chat-homepage-dropped = Verwijderd
ai-chat-homepage-unknown = Onbekend
cards-result-cards-submitted-by-board = Ingediend door het bord: bevinding ({ $kind ->
        [sourced] met bronnen
        [inferred] afgeleid
        [not_found] niet gevonden
       *[other] van onbekend soort
    }) uit het rapport
cards-result-cards-finding-for-board = Bevinding voor het bord ({ $kind ->
        [sourced] met bronnen
        [inferred] afgeleid
        [not_found] niet gevonden
       *[other] van onbekend soort
    })
chat-transcript-compacting = De context wordt samengevat: { $before } tokens naar een streefwaarde van { $target }.
chat-transcript-compaction-failed = De samenvatting van de eerdere stappen is mislukt. Het model kreeg de eerdere stappen ongewijzigd, { $after } tokens.
chat-transcript-compacted = Context samengevat: { $steps } stappen samengevat, { $before } tokens naar { $after }.
ai-chat-board-reopen-with-more = Heropenen met { $grant } extra verkenningen
ai-chat-board-goal-number = Doel { $number }
ai-chat-board-from-assessment-on = Uit evaluatie { $number } van { $date }.
ai-chat-board-from-assessment = Uit evaluatie { $number }.
chat-board-create-goal-2 = Doel { $index_1 }
ai-chat-session-lost-contact-with-the-chat = contact met de chat verloren: { $e }
ai-chat-session-could-not-stop-the-answer = het antwoord kon niet worden gestopt: { $e } — het loopt nog
ai-chat-board-later-assessments-dropped-an-answer = { $n } latere evaluaties lieten een antwoord op dit doel vervallen:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt- en { $a_completion_tokens } completion-tokens
ai-chat-homepage-completed-goals-not-answered = Voltooid, { $n } doelen niet beantwoord
board-graph-intent = intentie, { $state }
chat-workspace-pane-characters = { $chars } tekens
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } lopende tool-{ $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } lopende tool-{ $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Beantwoord na { $retries_len } mislukte {
        $retries_len ->
            [one] poging
           *[other] pogingen
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len } mislukte {
        $retries_len ->
            [one] poging
           *[other] pogingen
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, versie { $report_version }
tool-run-summary-searched = { $n ->
        [one] naar { $n } term gezocht
       *[other] naar { $n } termen gezocht
    }
tool-run-summary-read = { $n ->
        [one] { $n } document gelezen
       *[other] { $n } documenten gelezen
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] op het web naar { $n } term gezocht
       *[other] op het web naar { $n } termen gezocht
    }
tool-run-summary-read-web = { $n ->
        [one] { $n } webpagina gelezen
       *[other] { $n } webpagina's gelezen
    }
tool-run-summary-browser = { $n ->
        [one] { $n } browseractie
       *[other] { $n } browseracties
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] de entiteiten van { $n } document opgesomd
       *[other] de entiteiten van { $n } documenten opgesomd
    }
tool-run-summary-cited = { $n ->
        [one] { $n } document aangehaald
       *[other] { $n } documenten aangehaald
    }
tool-run-summary-cited-web = { $n ->
        [one] { $n } webpagina aangehaald
       *[other] { $n } webpagina's aangehaald
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] { $n } vaardigheid en tooltekst gelezen
       *[other] { $n } vaardigheden en toolteksten gelezen
    }
tool-run-summary-saved = { $n ->
        [one] { $n } notitie opgeslagen
       *[other] { $n } notities opgeslagen
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } aanroep van de takenlijst
       *[other] { $n } aanroepen van de takenlijst
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instructie aan de agent
       *[other] { $n } instructies aan de agent
    }
tool-run-summary-other = { $n ->
        [one] { $n } andere aanroep
       *[other] { $n } andere aanroepen
    }
tool-run-summary-failed = { $failures } mislukt
tool-run-summary-took = duurde { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } bericht
    *[other] { $session_message_count } berichten
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } item
       *[other] { $count } items
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } veld
       *[other] { $count } velden
    }
chat-tool-disclosure-searched-collections = collecties doorzocht{ $filters }
chat-tool-disclosure-searched-collections-2 = collecties doorzocht · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } documenten aangehaald
chat-tool-disclosure-read-document = document gelezen · { $path }
chat-tool-disclosure-searched-the-web = het web doorzocht · { $q }
chat-tool-disclosure-opened-page = pagina geopend · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = { $other } aangeroepen
chat-tool-disclosure-called-2 = { $other } aangeroepen · { $short }
cards-browser-card-opened = { $url } geopend
cards-browser-card-could-not-open = { $url } kon niet worden geopend
cards-browser-card-clicked = op { $element } geklikt
cards-browser-card-could-not-click = kon niet op { $element } klikken
cards-browser-card-typed-into = in { $element } getypt
cards-browser-card-could-not-type-into = kon niet in { $element } typen
cards-browser-card-typed = “{ $text }” getypt
cards-browser-card-could-not-type = kon “{ $text }” niet typen
cards-browser-card-pressed = { $key } ingedrukt
cards-browser-card-could-not-press = kon { $key } niet indrukken
cards-browser-card-chose-an-option-in = een optie gekozen in { $element }
cards-browser-card-could-not-choose-an-option = kon geen optie kiezen in { $element }
cards-browser-card-hovered = de muisaanwijzer boven { $element } gehouden
cards-browser-card-could-not-hover = kon de muisaanwijzer niet boven { $element } houden
cards-browser-card-failed = { $bare } — mislukt
cards-entities-card-listed-entities-document = entiteiten opgesomd · { $count } { $count ->
        [one] document
       *[other] documenten
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · deel { $part } van { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } documenten
cards-result-cards-forms = { $tool_name } · { $forms } varianten
cards-result-cards-in = {" "}in { $collections }
cards-result-cards-page = {" "}· pagina { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documenten · { $missing } citaten niet gevonden
cards-result-cards-version-unchanged = { $tool_name } · versie { $version } · ongewijzigd
cards-result-cards-version = { $tool_name } · versie { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultaten binnen, { $json_u64_doc_total_after_dedupe } na ontdubbeling

board-status-on = Aan

board-status-off = Uit

chat-transcript-generic-tool = het hulpmiddel
