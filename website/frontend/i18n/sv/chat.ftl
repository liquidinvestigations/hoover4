# Machine translation of en/chat.ftl. Do not edit by hand: change the English catalog
# and run scripts/i18n/translate_catalogs.py. See translations.json for the producer.

chat-activity-the-bot-is-working = Boten arbetar...
chat-composer-ask-the-bot = Fråga boten...
chat-composer-internet-tools = Internetverktyg
chat-composer-agent-language-title = Agenten svarar på { $language }. Ändra språket i inställningarna, i en ny flik.
chat-composer-try-again-in-s = Försök igen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stoppa svaret (den partiella delen sparas inte i chatten)
chat-composer-starting-the-conversation-u = Startar chatten…
chat-composer-send = Skicka
chat-conversation-find-search-in-conversation = Sök i chatten
chat-conversation-find-previous-match = Förra träffen
chat-conversation-find-next-match = Nästa träff
chat-conversation-find-investigation-board = Utredningstabla
doc-ref-card-not-openable = Kan inte öppnas: { $reason }.
doc-ref-card-the-search-term-was = Söktermen var{ " " }
doc-ref-card-open = Öppna
doc-ref-card-not-openable-2 = Kan inte öppnas
chat-markdown-text-show-the-cited-source = Visa den citerade källan
chat-markdown-text-no-citation-of-this-conversation = Ingen citat i denna chatt gav detta handtag, så inget dokument står bakom det.
chat-markdown-text-citations-of-this-conversation-gave = Citat i denna chatt gav detta handtag till mer än ett dokument, så det länkar till inget av dem.
cards-browser-card-open-the-archived-page = Öppna den arkiverade sidan
cards-browser-card-the-page-itself-was-not = Sidan i sig var inte arkiverad (status: { $artifact_status }). Skärmbilden ovan är vad som behölls.
cards-browser-card-click-the-screenshot-to-open = Klicka på skärmbilden för att öppna den arkiverade sidan.
cards-browser-card-show-less = Visa mindre
cards-browser-card-show-all = Visa alla
cards-browser-card-archived-page = Arkiverad sida
cards-browser-card-download = Ladda ned
cards-browser-card-archived-copy-of = Arkiverad kopia av { $artifact_url }
cards-browser-card-this-page-was-not-archived = Denna sida var inte arkiverad (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med ett kort
cards-entities-card-the-entity-list-was-cut = Entitetslistan blev avklippt.
cards-entities-card-open-the-card-for-this = Öppna kortet för detta värde ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Inget kort: denna konversation har aldrig namngivit datasetet som dessa värden kommer från, och visaren adresseras per dataset.
cards-entities-card-more-all-of-them-in = { $rest } till, alla i dokumentets entitetspanel.{ " " }
cards-entities-card-names-organisations-and-places-above = Namn, organisationer och platser ovan är en modells tolkning av texten. Ingen regel har validerat dem, så det finns inget att förklara och de öppnar inget.
cards-entities-card-nothing-extracted-from-this-document = Inget extraherat från detta dokument.
chat-tool-cards-hide = Dölj
chat-tool-cards-expand = Expandera
chat-tool-cards-hide-raw-json = Dölj rå JSON
chat-tool-cards-show-raw-json = Visa rå JSON
cards-result-cards-search-this = Sök här
cards-result-cards-search-every-collection = Sök i alla samlingar
cards-result-cards-form = Formulär { $index }: { $form }
cards-result-cards-show-full-text = Visa fullständig text
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Skäl: { $why }
cards-result-cards-open-question = Öppen fråga: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Utforskningsuppdraget gav detta svar till sin ärendetabla som { $kind ->
        [sourced] en källsatt
        [inferred] en härledd
        [not_found] en ej hittad
       *[other] ett okänd slag
    } slutsats.
cards-result-cards-it-left-no-open-question = Det lämnade ingen öppen fråga.
cards-result-cards-open-questions-for-the-board = Öppna frågor för ärendetablan:
cards-result-cards-arguments = Argument
cards-result-cards-list-after-the-call = Lista efter anropet: { $snapshot_goal }
cards-result-cards-replaces = { " " }· ersätter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listan vid denna version lagras inte.
web-search-card-these-sources-returned-nothing-so = Dessa källor returnerade inget, så resultaten kommer från färre än avsett
web-search-card-u-degraded = ⚠ { $degraded_len } nedgraderade
web-search-card-form = Formulär { $index }: { $form }
web-search-card-no-results-from = Inga resultat från: { $degraded_text }
web-search-card-no-results-every-source-answered = Inga resultat. Varje källa svarade och ingen av dem hade något för denna fråga.
web-search-card-the-lowest-ranked-results-were = De lägst rankade resultaten drogs bort så att detta anpassar sig till transkriptet. Assistenten såg alla dem.
web-search-card-view-search-details = Visa sökdetaljer.
web-search-card-the-stored-result-could-not = det lagrade resultatet kunde inte läsas tillbaka som JSON
web-search-card-nothing-was-stored-for-this = Inget lagrades för detta anrop.
web-search-card-forms = Formulär: { $forms }
web-search-card-kind = Typ: { $row_kind }
web-search-card-published = Publicerad: { $row_published }
web-search-card-loading-search-detail-u = Läser sökdetaljer…
web-search-card-could-not-load-the-search = Det gick inte att lätta sökdetaljerna: { $e }
web-search-card-malformed-detail = Felaktigt formad detalj: { $e }
web-search-card-the-tool-returned-selected-results = Verktyget returnerade utvalda resultat till modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultaten använder reciprokkaksfusionsordning.
web-search-card-returned-nothing = returnerade ingenting: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alla kandidater använder fusionsordning.
web-search-card-the-cross-encoder-ranks-selected = Korsencodern rangordnar utvalda resultat.
web-search-card-selected-results-use-fusion-order = Utvalda resultat använder fusionsordning.
web-search-card-search-detail = Sökdetaljer
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Sök här
chat-tool-disclosure-search-every-collection = Sök i alla samlingar
chat-tool-disclosure-hide = Dölj
chat-tool-disclosure-expand = Expandera
chat-tool-disclosure-this-step-was-recorded-before = Detta steg registrerades innan verktygsargument och resultat lagrades. Endast sammanfattningen nedan är tillgänglig.
chat-tool-disclosure-arguments = Argument
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Dölj rå JSON
chat-tool-disclosure-show-raw-json = Visa rå JSON
chat-tool-disclosure-input-json = Inmatnings-JSON
chat-tool-disclosure-output-json = Utdata-JSON
chat-transcript-ask-a-question-about-the = Ställ en fråga om dokumenten i dina samlingar.
chat-transcript-suggested-next = Föreslaget nästa...
chat-transcript-earlier-answer = Tidigare svar
chat-transcript-tokens-the-conversation-carries-the = Tokens som konversationen för, den största enskilda kontexten som debiterades den här gången och hur mycket av modellens fönster som användes
chat-transcript-instruction-to-the-agent = Instruktion till agenten
chat-transcript-the-context-stays-above-the = Kontexten håller över målet på { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } sammanfattningsdelar misslyckades. Posten innehåller endast listorna.
chat-transcript-show-the-record = Visa posten
chat-transcript-hide-reasoning = Dölj resonemang
chat-transcript-show-reasoning = Visa resonemang
chat-transcript-from-u-hide = { $count } { $noun } från { $tool } — dölj
chat-transcript-from-u-show = { $count } { $noun } från { $tool } — visa
chat-transcript-u-hide = { $summary } — dölj
chat-transcript-u-show = { $summary } — visa
chat-transcript-citations-of-this-conversation-give = Citat för den här konversationen ger { $doc_handle } till flera dokument. Svaret länkar till inget av dem.
chat-transcript-report = Rapportera { $label }
chat-transcript-open-in-the-workspace = Öppna i arbetsytan
chat-transcript-this-version-could-not-be = Den här versionen kunde inte läsas. Chatttexten för svaret följer.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Hitta exakt text
chat-web-previous-match = Tidigare träff
chat-web-next-match = Nästa träff
chat-web-close-preview = Stäng förhandsgranskning
chat-web-the-captured-page-could-not = Den fångna sidan kunde inte laddas.
chat-web-loading = Laddar…
chat-workspace-pane-workspace = Arbetsyta
chat-workspace-pane-close-the-workspace = Stäng arbetsytan
chat-workspace-pane-close = Stäng
chat-workspace-pane-loading-the-files-u = Laddar filerna…
chat-workspace-pane-the-files-could-not-be = Filerna kunde inte laddas: { $error }
chat-workspace-pane-this-conversation-has-no-files = Den här konversationen har inga filer.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Välj ett dokument för att läsa det.
chat-workspace-pane-loading-the-file-u = Laddar dokumentet…
chat-workspace-pane-the-file-could-not-be = Filen kunde inte laddas: { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Samlingar
chat-board-create-loading-collections-u = Laddar samlingar…
chat-board-create-hoover-search-new-board = Hoover Sök - Nytt ärendetabla
chat-board-create-ai-chat = AI-Chatt
chat-board-create-new-investigation-board = Nytt ärendetabla för utredning
chat-board-create-a-board-runs-its-goals = En ärendetabla kör sina mål som en sekvens av agent-utforskningar. Varje utforskning är en chatt som slutar med en enda slutsats på ärendetablan. Du granskar svaret på varje mål och kan avvisa slutsatser och lägga till ledtrådar medan den kör.
chat-board-create-title = Titel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Ta bort detta mål
chat-board-create-remove = Ta bort
chat-board-create-add-a-goal = Lägg till ett mål
chat-board-create-context-optional = Kontext (valfritt)
chat-board-create-hints-one-per-line-optional = Tips, ett per rad (valfritt)
chat-board-create-sources = Källor
chat-board-create-internet-tools = Internetverktyg
chat-board-create-creating-board = Skapar ärendetabla...
chat-board-create-create-board = Skapa ärendetabla
ai-chat-board-hoover-search-board = Hoover-sökning – Ärendetabla
ai-chat-board-loading-the-board-u = Laddar ärendetablan…
ai-chat-board-show-the-board-overview = Visa ärendetablans översikt
ai-chat-board-zoom-out = Zooma ut
ai-chat-board-zoom-in = Zooma in
ai-chat-board-u-ai-chat = ← AI-Chatt
ai-chat-board-settings = Inställningar
ai-chat-board-board-settings = Ärendetablas inställningar
ai-chat-board-internet-tools = Internetverktyg
ai-chat-board-the-next-explores-of-the = Nästa undersökningar i ärendetablan kan söka på webben och läsa webbplatser. Pågående undersökningar behåller den inställning de startade med.
ai-chat-board-collections = Samlingar
ai-chat-board-the-collections-are-fixed-when = Samlingarna är fasta när ärendetablan skapas.
ai-chat-board-confirm-drop = Bekräfta borttagning
ai-chat-board-drop-the-board = Ta bort ärendetablan
ai-chat-board-close = Stäng
ai-chat-board-the-board-used-its-explore = Ärendetablan har använt sin undersökningsgräns
ai-chat-board-the-board-used-explores-the = Ärendetablan har använt { $explore_limit } undersökningar, gränsen för en ärendetabla. Den startar inget mer arbete. Du kan fortfarande bestämma de föreslagna svaren.
ai-chat-board-create-a-new-board-to = Skapa en ny ärendetabla för att fortsätta utredningen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Lägg till nytt mål...
ai-chat-board-a-new-goal = Ett nytt mål
ai-chat-board-add-goal = Lägg till mål
ai-chat-board-a-board-has-at-most = En ärendetabla har högst { $max_goals } mål. Skapa en ny ärendetabla för ett annat mål.
ai-chat-board-background-context = Bakgrundskontext
ai-chat-board-continue-with-a-correction = Fortsätt med en rättelse
ai-chat-board-correction-what-is-wrong-or = Rättelse: vad som är fel eller saknas. Ärendetablan fortsätter med det.
ai-chat-board-the-board-waits-for-your = Ärendetablan väntar på din granskning
ai-chat-board-the-board-used-its-budget = Ärendetablan har använt sin budget på { $snap_max_explores } undersökningar.
ai-chat-board-the-assessments-gave-no-usable = Utvärderingarna gav ingen användbar riktning.
ai-chat-board-accept-or-reject-the-proposed = Acceptera eller avvisa de föreslagna svaren för varje mål ovan. Ett avvistat mål låter ärendetablan fortsätta omedelbart.
ai-chat-board-no-proposed-answer-waits-for = Inget föreslaget väntar på ditt beslut.
ai-chat-board-reopen-the-board-to-continue = Öffna ärendetablan igen för att fortsätta de öppna målen. Den behåller sina slutsatser och svar.
ai-chat-board-close-the-board-to-accept = Stäng ärendetablan för att acceptera alla föreslagna svar och stoppa den, eller fortsätt den med en rättelse.
ai-chat-board-close-the-board = Stäng ärendetablan
ai-chat-board-or-reopen-the-board-to = Eller öppna ärendetablan igen för att fortsätta de öppna målen utan en rättelse.
ai-chat-board-the-board-is-complete = Ärendetablan är komplett
ai-chat-board-a-goal-has-no-accepted = Ett mål har inget accepterat svar. Öffna ärendetablan igen för att fortsätta den. Ärendetablan behåller sina slutsatser och svar.
ai-chat-board-add-a-hint = Lägg till en ledtråd
ai-chat-board-the-next-assessment-reads-every = Nästa utvärdering läser varje ledtråd. En ledtråd besvarar också en utforskning som ställde en fråga.
ai-chat-board-add-hint = Lägg till ledtråd
ai-chat-board-events = Händelser
ai-chat-board-newest-first = Nyaste först
ai-chat-board-date = Datum
ai-chat-board-actor = Aktör
ai-chat-board-event = Händelse
ai-chat-board-show-details = Visa detaljer
ai-chat-board-open = Öppna
ai-chat-board-show-the-newest-events = Visa de nyaste { $event_rows } händelser
ai-chat-board-show-all-events = Visa alla { $snap_events_len } händelser
ai-chat-board-statistics = Statistik
ai-chat-board-explores = Utforskningar
ai-chat-board-model-steps-per-explore = Modellskepp per utforskning
ai-chat-board-assessments = Utvärderingar
ai-chat-board-intents = Intentioner
ai-chat-board-findings = Slutsatser
ai-chat-board-created = Skapad
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } avvisade denna slutsats på { $format_utc_ms_fact_rejected_ms }. Tabellen använder den inte längre.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } avvisade denna slutsats. Tabellen använder den inte längre.
ai-chat-board-no-reason-was-given = Ingen anledning angavs.
ai-chat-board-reason = Anledning: { $fact_rejected_reason }
ai-chat-board-open-questions = Öppna frågor
ai-chat-board-explored-in = Utforskad i
ai-chat-board-explore-this-question = Utforska denna fråga
ai-chat-board-your-questions = Dina frågor
ai-chat-board-ask-about-the-background-context = Fråga om bakgrundskontexten
ai-chat-board-ask-about-this-finding = Fråga om denna slutsats
ai-chat-board-a-follow-up-question-about = En uppföljningsfråga om denna nod
ai-chat-board-ask = Fråga
ai-chat-board-checks-that-changed-this-finding = Kontroller som ändrade denna slutsats
ai-chat-board-reject-this-correction = Neka denna korrektion
ai-chat-board-reject-this-finding = Neka denna slutsats
ai-chat-board-not-answered-the-board-was = Svarat ej. Ärendetablan avslutades utan svar för detta mål. En ledtråd eller en öppning öppnar den igen.
ai-chat-board-no-answer-yet = Inget svar än.
ai-chat-board-the-findings-of-this-answer = Slutsatserna för detta svar är sökningar som inte hittade något. Acceptera för att registrera att posterna inte svarar på målet, eller neka för att fortsätta utredningen.
ai-chat-board-open-an-assessment-to-read = { "." } Öppna en utvärdering för att läsa varför.
ai-chat-board-from-the-findings = Från slutsatserna{ " " }
ai-chat-board-accept-answer = Acceptera svar
ai-chat-board-why-the-answer-is-wrong = Varför svaret är felaktigt eller ofullständigt
ai-chat-board-reject-answer = Neka svar
ai-chat-board-intent = Intention
ai-chat-board-attempts-declared = Försök: { $intent_attempts }. Deklarerat { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Utforskningsmodulen frågade
ai-chat-board-add-a-hint-in-the = Lägg till en ledtråd i översikten över ärendetablan för att svara på den.
ai-chat-board-last-error = Senaste fel
ai-chat-board-brief = Sammanfattning
ai-chat-board-open-the-explore-chat = Öppna utforskningschatten
ai-chat-board-loading-the-assessment-u = Laddar utvärderingen…
ai-chat-board-assessment = Utvärdering { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Utfall { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Kontroller som ändrade den
ai-chat-board-prompt = Uppmaning
ai-chat-board-this-assessment-ran-before-the = Denna utvärdering kördes innan uppmänningarna lagrades.
ai-chat-board-response = Svar
ai-chat-history-hoover-search-chat-history = Hoover Sök - Chatthistorik
ai-chat-history-u-back = ← Tillbaka
ai-chat-history-conversation-history = Konversationshistorik
ai-chat-history-show-board-chats = Visa ärendetablan chattar
ai-chat-history-loading-u = Laddar…
ai-chat-history-could-not-load-history = Kunde inte ladda historiken: { $e }
ai-chat-history-no-conversations-yet = Inga samtal än.
ai-chat-history-board = Ärendetabla
ai-chat-history-new-chat = Ny chatt
ai-chat-history-messages-updated = { $s_message_count } meddelanden · uppdaterat { $s_updated_at }
ai-chat-history-delete-conversation = Ta bort samtalet
ai-chat-history-delete = Ta bort
ai-chat-homepage-hoover-search-ai-chat = Hoover Sök - AI Chatt
ai-chat-homepage-what-are-you-researching = Vad undersöker du?
ai-chat-homepage-view-all-conversations = Visa alla samtal
ai-chat-homepage-starting-conversation-u = Startar samtal…
ai-chat-homepage-investigation-boards = Undersökningsbord
ai-chat-homepage-new-board = Nytt bord
ai-chat-homepage-loading-boards-u = Laddar bord…
ai-chat-homepage-could-not-load-the-boards = Kunde inte ladda boarden: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har inget bord. Ett bord kör en lång undersökning som en sekvens av agentundersökningar, och du granskar dess svar.
ai-chat-homepage-updated = Uppdaterat { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Sök - AI Chatt
ai-chat-session-this-conversation-could-not-be = Detta samtal kunde inte laddas.
ai-chat-session-loading-u = Laddar…
ai-chat-session-u-chats = ← Chattar
ai-chat-session-history = Historik
ai-chat-session-show-the-files-that-the = Visa filerna som assistenten skrev i detta samtal
ai-chat-session-workspace = Arbetsyta
ai-chat-session-this-answer-was-interrupted-before = Detta svar avbröts innan det var klart, eftersom sidan eller servern stoppade mitt i svaret. Be igen för att försöka igen.
ai-chat-session-dismiss = Stäng
ai-chat-session-board-explore-chats-are-read = Board-undersökningschattar är skrivskyddade.{ " " }
ai-chat-session-open-the-board = Öppna bordet
chat-locked-options-on = { $label }: på
chat-locked-options-off = { $label }: av
chat-tool-cards-running-u = kör…
cards-result-cards-quote-found = Citat hittats
cards-result-cards-quote-not-found = Citat hittades inte
cards-result-cards-quote-not-checked = Citat inte kontrollerat
web-search-card-results = { $results_len } resultat
chat-tool-disclosure-running-u = kör…
chat-transcript-call = samtal
chat-transcript-calls = samtal
ai-chat-board-a-board-without-collections-needs = En ärendetabla utan samlingar behöver internetverktyg.
ai-chat-board-of = { $snap_explores_used } av { $snap_max_explores }
ai-chat-board-assessment-2 = utvärdering { $number }
ai-chat-history-messages = { $s_message_count } meddelanden
web-search-card-reranked-in = Cross-encodern rangordnade resultaten på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = poäng { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Vändningen väntar på en ledig modellplats.
chat-activity-the-turn-waits-for-a-2 = Vändningen väntar på en ledig verktygsplats.
chat-locked-options-start-a-new-chat-to = Starta en ny chatt för att ändra den här inställningen.
chat-locked-options-internet-tools = Internetverktyg
chat-session-card-new-chat = Ny chatt
chat-tool-cards-first-frame-of-the-video = Första bildramen i videon
chat-tool-cards-screenshot-of = Skärmdump av
chat-tool-cards-image = Bild
cards-result-cards-the-agent-asked-a-question = Agenten ställde en fråga.
chat-transcript-hide = Dölj
chat-transcript-show = Visa
chat-transcript-unverified-quote-the-quoted-span = Okontrollerat citat. Det citerade avsnittet är för kort för att kontrolleras.
chat-transcript-unverified-quote-the-document-text = Okontrollerat citat. Dokumenttexten kunde inte läsas.
chat-transcript-unverified-quote-this-wording-was = Okontrollerat citat. Den här formuleringen hittades inte i dokumentet.
chat-board-create-select-a-collection-or-turn = Välj en samling eller slå på internetverktyg.
chat-board-create-select-at-least-one-collection = Välj minst en samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = Pausad
ai-chat-board-waits-for-review = Väntar på granskning
ai-chat-board-completed = Slutförd
ai-chat-board-dropped = Nedlagd
ai-chat-board-unknown = Okänd
ai-chat-board-pause-the-board = Pausa ärendetablan
ai-chat-board-resume-the-board = Återuppta ärendetablan
ai-chat-board-none = Ingen
ai-chat-board-reopen-with-the-remaining-budget = Öppna igen med återstående budget
ai-chat-board-finding = Slutsats
ai-chat-board-why-the-correction-is-wrong = Varför korrektionen är fel
ai-chat-board-reject-correction = Avvisa korrektionen
ai-chat-board-why-the-finding-is-wrong = Varför slutsätten är fel
ai-chat-board-reject-finding = Avvisa slutsätten
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Föreslaget svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pausad
ai-chat-homepage-waits-for-review = Väntar på granskning
ai-chat-homepage-completed = Slutförd
ai-chat-homepage-dropped = Nedlagd
ai-chat-homepage-unknown = Okänd
cards-result-cards-submitted-by-board =
    Inlämnat av ärendetablan: { $kind ->
        [sourced] en källad
        [inferred] en härledd
        [not_found] en ej funnen
       *[other] en okänd typ
    } slutsats från rapporten
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] En källad
        [inferred] En härledd
        [not_found] En ej funnen
       *[other] En okänd typ
    } slutsats för ärendetablan
chat-transcript-compacting = Komprimerar kontexten: { $before } token till ett mål på { $target }.
chat-transcript-compaction-failed = Sammanfattningen av de tidigare stegen misslyckades. Modellen fick de tidigare stegen oförändrade, { $after } token.
chat-transcript-compacted = Kontext komprimerad: { $steps } stegransammanfattningar, { $before } token till { $after }.
ai-chat-board-reopen-with-more = Öppna igen med { $grant } fler undersökningar
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Från bedömning { $number } på { $date }.
ai-chat-board-from-assessment = Från bedömning { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = förlorade kontakt med chatten: { $e }
ai-chat-session-could-not-stop-the-answer = kunde inte stoppa svaret: { $e } — det kör fortfarande
ai-chat-board-later-assessments-dropped-an-answer = { $n } senare bedömningar lämnade ett svar för detta mål:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt- och { $a_completion_tokens } completion-token
ai-chat-homepage-completed-goals-not-answered = Slutförda, { $n } mål som inte besvarats
board-graph-intent = avsikt, { $state }
chat-workspace-pane-characters = { $chars } tecken
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } kör verktyg { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } kör verktyg { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Besvarat efter { $retries_len } misslyckat försök{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } misslyckat försök{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] sökte { $n } term
       *[other] sökte { $n } termer
    }
tool-run-summary-read =
    { $n ->
        [one] läste { $n } dokument
       *[other] läste { $n } dokument
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] sökte på webben efter { $n } term
       *[other] sökte på webben efter { $n } termer
    }
tool-run-summary-read-web =
    { $n ->
        [one] läste { $n } webbsida
       *[other] läste { $n } webbsidor
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } webbläddringsåtgärd
       *[other] { $n } webbläddringsåtgärder
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listade entiteterna i { $n } dokument
       *[other] listade entiteterna i { $n } dokument
    }
tool-run-summary-cited =
    { $n ->
        [one] citerade { $n } dokument
       *[other] citerade { $n } dokument
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citerade { $n } webbsida
       *[other] citerade { $n } webbsidor
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] läste { $n } färdighet- och verktygstext
       *[other] läste { $n } färdigheter- och verktygstexter
    }
tool-run-summary-saved =
    { $n ->
        [one] sparade { $n } anteckning
       *[other] sparade { $n } anteckningar
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } anrop mot todo-listan
       *[other] { $n } anmot mot todo-listan
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instruktion till agenten
       *[other] { $n } instruktioner till agenten
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } annat anrop
       *[other] { $n } andra anrop
    }
tool-run-summary-failed = { $failures } misslyckade
tool-run-summary-took = tog { $duration_text_ms }
chat-session-card-messages = { $session_message_count } meddelanden
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } objekt
       *[other] { $count } objekt
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } fält
       *[other] { $count } fält
    }
chat-tool-disclosure-searched-collections = sökte samlingar{ $filters }
chat-tool-disclosure-searched-collections-2 = sökte samlingar · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citerade { $n } dokument
chat-tool-disclosure-read-document = läste dokument · { $path }
chat-tool-disclosure-searched-the-web = sökte på webben · { $q }
chat-tool-disclosure-opened-page = öppnade sida · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = anropade { $other }
chat-tool-disclosure-called-2 = anropade { $other } · { $short }
cards-browser-card-opened = öppnade { $url }
cards-browser-card-could-not-open = kunde inte öppna { $url }
cards-browser-card-clicked = klickade på { $element }
cards-browser-card-could-not-click = kunde inte klickade på { $element }
cards-browser-card-typed-into = skrev i { $element }
cards-browser-card-could-not-type-into = kunde inte skriva i { $element }
cards-browser-card-typed = skrev “{ $text }”
cards-browser-card-could-not-type = kunde inte skriva “{ $text }”
cards-browser-card-pressed = tryckte på { $key }
cards-browser-card-could-not-press = kunde inte trycka på { $key }
cards-browser-card-chose-an-option-in = valde ett alternativ i { $element }
cards-browser-card-could-not-choose-an-option = kunde inte välja ett alternativ i { $element }
cards-browser-card-hovered = hovrade över { $element }
cards-browser-card-could-not-hover = kunde inte hovra över { $element }
cards-browser-card-failed = { $bare } — misslyckades
cards-entities-card-listed-entities-document = listade enheter · { $count } dokument{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · del { $part } av { $name } #{ $seq }
cards-result-cards-documents = · { $value } dokument
cards-result-cards-forms = { $tool_name } · { $forms } formulär
cards-result-cards-in = · i { $collections }
cards-result-cards-page = · sida { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokument · { $missing } citat hittades inte
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · oförändrad
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultat i, { $json_u64_doc_total_after_dedupe } efter deduplikation
