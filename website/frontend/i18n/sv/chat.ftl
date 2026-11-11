# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Boten arbetar...
chat-composer-ask-the-bot = Fråga boten...
chat-composer-internet-tools = Internetverktyg
chat-composer-agent-language-title = Agenten svarar på { $language }. Ändra språket i inställningarna, i en ny flik.
chat-composer-try-again-in-s = Försök igen om { $secs } s
chat-composer-stop-the-answer-the-partial = Stoppa svaret (det ofullständiga svaret sparas inte i konversationen)
chat-composer-starting-the-conversation-u = Startar konversationen…
chat-composer-send = Skicka
chat-conversation-find-search-in-conversation = Sök i konversationen
chat-conversation-find-previous-match = Föregående träff
chat-conversation-find-next-match = Nästa träff
chat-conversation-find-investigation-board = Utredningstavla
doc-ref-card-not-openable = Kan inte öppnas: { $reason }.
doc-ref-card-the-search-term-was = Sökordet var{" "}
doc-ref-card-open = Öppna
doc-ref-card-not-openable-2 = Kan inte öppnas
chat-markdown-text-show-the-cited-source = Visa den citerade källan
chat-markdown-text-no-citation-of-this-conversation = Ingen källhänvisning i den här konversationen gav det här handtaget, så inget dokument ligger bakom det.
chat-markdown-text-citations-of-this-conversation-gave = Källhänvisningar i den här konversationen gav det här handtaget till fler än ett dokument, så det länkar inte till något av dem.
cards-browser-card-open-the-archived-page = Öppna den arkiverade sidan
cards-browser-card-the-page-itself-was-not = Själva sidan arkiverades inte (status: { $artifact_status }). Skärmbilden ovan är det som sparades.
cards-browser-card-click-the-screenshot-to-open = Klicka på skärmbilden för att öppna den arkiverade sidan.
cards-browser-card-show-less = Visa mindre
cards-browser-card-show-all = Visa alla
cards-browser-card-archived-page = Arkiverad sida
cards-browser-card-download = Ladda ned
cards-browser-card-archived-copy-of = Arkiverad kopia av { $artifact_url }
cards-browser-card-this-page-was-not-archived = Den här sidan arkiverades inte (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } med kort
cards-entities-card-the-entity-list-was-cut = Entitetslistan kapades.
cards-entities-card-open-the-card-for-this = Öppna kortet för det här värdet ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Inget kort: den här konversationen nämnde aldrig datamängden som värdena kom från, och visaren adresseras via datamängd.
cards-entities-card-more-all-of-them-in = { $rest } till, alla i dokumentets entitetspanel.{" "}
cards-entities-card-names-organisations-and-places-above = Namn, organisationer och platser ovan är en modells tolkning av prosan. Ingen regel har validerat dem, så det finns inget att förklara och de öppnar ingenting.
cards-entities-card-nothing-extracted-from-this-document = Inget extraherades från det här dokumentet.
chat-tool-cards-hide = Dölj
chat-tool-cards-expand = Fäll ut
chat-tool-cards-hide-raw-json = Dölj rå JSON
chat-tool-cards-show-raw-json = Visa rå JSON
cards-result-cards-search-this = Sök i detta
cards-result-cards-search-every-collection = Sök i alla samlingar
cards-result-cards-form = Form { $index }: { $form }
cards-result-cards-show-full-text = Visa hela texten
cards-result-cards-quote = Citat: { $quote }
cards-result-cards-reason = Skäl: { $why }
cards-result-cards-open-question = Öppen fråga: { $question }
cards-result-cards-the-explore-gave-this-answer = Utforskningen gav det här svaret till sin utredningstavla som { $kind ->
        [sourced] ett belagt
        [inferred] ett härlett
        [not_found] ett negativt
       *[other] ett okänt
    } fynd.
cards-result-cards-it-left-no-open-question = Den lämnade ingen öppen fråga.
cards-result-cards-open-questions-for-the-board = Öppna frågor för utredningstavlan:
cards-result-cards-arguments = Argument
cards-result-cards-list-after-the-call = Lista efter anropet: { $snapshot_goal }
cards-result-cards-replaces = {" "}· ersätter { $replaces_id }
cards-result-cards-the-list-at-this-version = Listan i den här versionen är inte lagrad.
web-search-card-these-sources-returned-nothing-so = De här källorna gav inget, så resultaten kommer från färre källor än avsett
web-search-card-u-degraded = ⚠ { $degraded_len } försämrade
web-search-card-form = Form { $index }: { $form }
web-search-card-no-results-from = Inga resultat från: { $degraded_text }
web-search-card-no-results-every-source-answered = Inga resultat. Alla källor svarade och ingen av dem hade något för den här frågan.
web-search-card-the-lowest-ranked-results-were = De lägst rankade resultaten togs bort så att det här anropet ryms i transkriptet. Assistenten såg alla.
web-search-card-view-search-details = Visa sökdetaljer.
web-search-card-the-stored-result-could-not = det lagrade resultatet kunde inte läsas tillbaka som JSON
web-search-card-nothing-was-stored-for-this = Inget lagrades för det här anropet.
web-search-card-forms = Former: { $forms }
web-search-card-kind = Slag: { $row_kind }
web-search-card-published = Publicerad: { $row_published }
web-search-card-loading-search-detail-u = Läser in sökdetaljer…
web-search-card-could-not-load-the-search = Det gick inte att läsa in sökdetaljerna: { $e }
web-search-card-malformed-detail = Felaktigt formaterade detaljer: { $e }
web-search-card-the-tool-returned-selected-results = Verktyget returnerade utvalda resultat till modellen.
web-search-card-results-use-reciprocal-rank-fusion = Resultaten använder reciprocal rank fusion.
web-search-card-returned-nothing = gav inget: { $degraded }
web-search-card-all-candidates-use-fusion-order = Alla kandidater använder fusionsordningen.
web-search-card-the-cross-encoder-ranks-selected = Cross-encodern rankar utvalda resultat.
web-search-card-selected-results-use-fusion-order = Utvalda resultat använder fusionsordningen.
web-search-card-search-detail = Sökdetaljer
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Sök i detta
chat-tool-disclosure-search-every-collection = Sök i alla samlingar
chat-tool-disclosure-hide = Dölj
chat-tool-disclosure-expand = Fäll ut
chat-tool-disclosure-this-step-was-recorded-before = Det här steget registrerades innan verktygsargument och resultat lagrades. Bara sammanfattningen nedan finns.
chat-tool-disclosure-arguments = Argument
chat-tool-disclosure-result = Resultat
chat-tool-disclosure-hide-raw-json = Dölj rå JSON
chat-tool-disclosure-show-raw-json = Visa rå JSON
chat-tool-disclosure-input-json = Indata (JSON)
chat-tool-disclosure-output-json = Utdata (JSON)
chat-transcript-ask-a-question-about-the = Ställ en fråga om dokumenten i dina samlingar.
chat-transcript-suggested-next = Förslag på nästa steg...
chat-transcript-earlier-answer = Tidigare svar
chat-transcript-tokens-the-conversation-carries-the = Token som konversationen bär, den största enskilda kontexten som det här varvet debiterades för, och hur mycket av modellens fönster den använde
chat-transcript-instruction-to-the-agent = Instruktion till agenten
chat-transcript-the-context-stays-above-the = {" "}Kontexten ligger kvar över målet på { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } delsammanfattningar misslyckades. Journalen innehåller bara listorna.
chat-transcript-show-the-record = Visa journalen
chat-transcript-hide-reasoning = Dölj resonemanget
chat-transcript-show-reasoning = Visa resonemanget
chat-transcript-from-u-hide = { $count } { $count ->
        [one] dokument
       *[other] dokument
    } från { $tool } — dölj
chat-transcript-from-u-show = { $count } { $count ->
        [one] dokument
       *[other] dokument
    } från { $tool } — visa
chat-transcript-u-hide = { $summary } — dölj
chat-transcript-u-show = { $summary } — visa
chat-transcript-citations-of-this-conversation-give = Källhänvisningar i den här konversationen ger { $doc_handle } till fler än ett dokument. Svaret länkar det inte till något av dem.
chat-transcript-report = Rapport { $label }
chat-transcript-open-in-the-workspace = Öppna i arbetsytan
chat-transcript-this-version-could-not-be = Den här versionen kunde inte läsas. Svarets chatttext följer.
chat-transcript-files = Filer
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Hitta exakt text
chat-web-previous-match = Föregående träff
chat-web-next-match = Nästa träff
chat-web-close-preview = Stäng förhandsvisningen
chat-web-the-captured-page-could-not = Den fångade sidan kunde inte läsas in.
chat-web-loading = Läser in…
chat-workspace-pane-workspace = Arbetsyta
chat-workspace-pane-close-the-workspace = Stäng arbetsytan
chat-workspace-pane-close = Stäng
chat-workspace-pane-loading-the-files-u = Läser in filerna…
chat-workspace-pane-the-files-could-not-be = Filerna kunde inte läsas in: { $error }
chat-workspace-pane-this-conversation-has-no-files = Den här konversationen har inga filer.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Välj en fil för att läsa den.
chat-workspace-pane-loading-the-file-u = Läser in filen…
chat-workspace-pane-the-file-could-not-be = Filen kunde inte läsas in: { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Samlingar
chat-board-create-loading-collections-u = Läser in samlingar…
chat-board-create-hoover-search-new-board = Hoover Search - Ny utredningstavla
chat-board-create-ai-chat = AI-chatt
chat-board-create-new-investigation-board = Ny utredningstavla
chat-board-create-a-board-runs-its-goals = En utredningstavla kör sina mål som en följd av agentutforskningar. Varje utforskning är en chatt som slutar i ett fynd på tavlan. Du granskar svaret på varje mål, och du kan avvisa fynd och lägga till ledtrådar medan den körs.
chat-board-create-title = Titel
chat-board-create-goal = Mål
chat-board-create-remove-this-goal = Ta bort målet
chat-board-create-remove = Ta bort
chat-board-create-add-a-goal = Lägg till ett mål
chat-board-create-context-optional = Kontext (valfritt)
chat-board-create-hints-one-per-line-optional = Ledtrådar, en per rad (valfritt)
chat-board-create-sources = Källor
chat-board-create-internet-tools = Internetverktyg
chat-board-create-creating-board = Skapar utredningstavlan...
chat-board-create-create-board = Skapa utredningstavla
chat-board-create-board-language = Utredningstavlans språk
ai-chat-board-hoover-search-board = Hoover Search - Utredningstavla
ai-chat-board-loading-the-board-u = Läser in utredningstavlan…
ai-chat-board-show-the-board-overview = Visa översikten över utredningstavlan
ai-chat-board-zoom-out = Zooma ut
ai-chat-board-zoom-in = Zooma in
ai-chat-board-u-ai-chat = ← AI-chatt
ai-chat-board-settings = Inställningar
ai-chat-board-board-settings = Inställningar för utredningstavlan
ai-chat-board-internet-tools = Internetverktyg
ai-chat-board-the-next-explores-of-the = Utredningstavlans nästa utforskningar kan söka på webben och läsa webbsidor. Utforskningar som pågår behåller den inställning de startade med.
ai-chat-board-collections = Samlingar
ai-chat-board-the-collections-are-fixed-when = Samlingarna fastställs när utredningstavlan skapas.
ai-chat-board-language = Språk
ai-chat-board-the-language-is-fixed-when = Språket fastställs när utredningstavlan skapas.
ai-chat-board-the-agent-language-of-the-owner = Ägarens agentspråk
ai-chat-board-confirm-drop = Bekräfta att tavlan släpps
ai-chat-board-drop-the-board = Släpp utredningstavlan
ai-chat-board-close = Stäng
ai-chat-board-the-board-used-its-explore = Utredningstavlan har nått sin gräns för utforskningar
ai-chat-board-the-board-used-explores-the = Utredningstavlan använde { $explore_limit } utforskningar, vilket är gränsen för en tavla. Den startar inget mer arbete. Du kan fortfarande avgöra de föreslagna svaren.
ai-chat-board-create-a-new-board-to = Skapa en ny utredningstavla för att fortsätta utredningen
ai-chat-board-goal = Mål
ai-chat-board-goals = Mål
ai-chat-board-add-new-goal = Lägg till nytt mål...
ai-chat-board-a-new-goal = Ett nytt mål
ai-chat-board-add-goal = Lägg till mål
ai-chat-board-a-board-has-at-most = En utredningstavla har högst { $max_goals } mål. Skapa en ny utredningstavla för ett annat mål.
ai-chat-board-background-context = Bakgrundskontext
ai-chat-board-continue-with-a-correction = Fortsätt med en korrigering
ai-chat-board-correction-what-is-wrong-or = Korrigering: vad som är fel eller saknas. Utredningstavlan fortsätter med den.
ai-chat-board-the-board-waits-for-your = Utredningstavlan väntar på din granskning
ai-chat-board-the-board-used-its-budget = Utredningstavlan använde hela sin budget på { $snap_max_explores } utforskningar.
ai-chat-board-the-assessments-gave-no-usable = Bedömningarna gav ingen användbar riktning.
ai-chat-board-accept-or-reject-the-proposed = Godkänn eller avvisa det föreslagna svaret på varje mål ovan. Ett avvisat svar gör att utredningstavlan fortsätter direkt.
ai-chat-board-no-proposed-answer-waits-for = Inget föreslaget svar väntar på ditt beslut.
ai-chat-board-reopen-the-board-to-continue = Öppna utredningstavlan igen för att fortsätta med de öppna målen. Den behåller sina fynd och svar.
ai-chat-board-close-the-board-to-accept = Stäng utredningstavlan för att godkänna alla föreslagna svar och stoppa den, eller fortsätt med en korrigering.
ai-chat-board-close-the-board = Stäng utredningstavlan
ai-chat-board-or-reopen-the-board-to = Eller öppna utredningstavlan igen för att fortsätta med de öppna målen utan korrigering.
ai-chat-board-the-board-is-complete = Utredningstavlan är komplett
ai-chat-board-a-goal-has-no-accepted = Ett mål har inget godkänt svar. Öppna utredningstavlan igen för att fortsätta med det. Utredningstavlan behåller sina fynd och svar.
ai-chat-board-add-a-hint = Lägg till en ledtråd
ai-chat-board-the-next-assessment-reads-every = Nästa bedömning läser varje ledtråd. En ledtråd besvarar också en utforskning som ställde en fråga.
ai-chat-board-add-hint = Lägg till ledtråd
ai-chat-board-events = Händelser
ai-chat-board-newest-first = Nyast först
ai-chat-board-date = Datum
ai-chat-board-actor = Aktör
ai-chat-board-event = Händelse
ai-chat-board-show-details = Visa detaljer
ai-chat-board-open = Öppna
ai-chat-board-show-the-newest-events = Visa de { $event_rows } nyaste händelserna
ai-chat-board-show-all-events = Visa alla { $snap_events_len } händelser
ai-chat-board-statistics = Statistik
ai-chat-board-explores = Utforskningar
ai-chat-board-model-steps-per-explore = Modellsteg per utforskning
ai-chat-board-assessments = Bedömningar
ai-chat-board-intents = Avsikter
ai-chat-board-findings = Fynd
ai-chat-board-created = Skapad
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } avvisade det här fyndet den { $format_utc_ms_fact_rejected_ms }. Utredningstavlan använder det inte längre.
ai-chat-board-this-finding-was-replaced-by = Det här fyndet ersattes av { $new } den { $date }. Utredningstavlan använder det inte längre.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } avvisade det här fyndet. Utredningstavlan använder det inte längre.
ai-chat-board-no-reason-was-given = Inget skäl angavs.
ai-chat-board-reason = Skäl: { $fact_rejected_reason }
ai-chat-board-open-questions = Öppna frågor
ai-chat-board-explored-in = Utforskad i{" "}
ai-chat-board-explore-this-question = Utforska den här frågan
ai-chat-board-your-questions = Dina frågor
ai-chat-board-ask-about-the-background-context = Fråga om bakgrundskontexten
ai-chat-board-ask-about-this-finding = Fråga om det här fyndet
ai-chat-board-a-follow-up-question-about = En följdfråga om den här noden
ai-chat-board-ask = Fråga
ai-chat-board-checks-that-changed-this-finding = Kontroller som ändrade det här fyndet
ai-chat-board-reject-this-correction = Avvisa den här korrigeringen
ai-chat-board-reject-this-finding = Avvisa det här fyndet
ai-chat-board-not-answered-the-board-was = Obesvarat. Utredningstavlan avslutades utan svar på det här målet. En ledtråd eller en återöppning öppnar det igen.
ai-chat-board-no-answer-yet = Inget svar ännu.
ai-chat-board-the-findings-of-this-answer = Fynden i det här svaret är sökningar som inte hittade något. Godkänn det för att registrera att posterna inte besvarar målet, eller avvisa det för att fortsätta utredningen.
ai-chat-board-open-an-assessment-to-read = {"."} Öppna en bedömning för att läsa varför.
ai-chat-board-from-the-findings = Från fynden{" "}
ai-chat-board-accept-answer = Godkänn svaret
ai-chat-board-why-the-answer-is-wrong = Varför svaret är fel eller ofullständigt
ai-chat-board-reject-answer = Avvisa svaret
ai-chat-board-intent = Avsikt
ai-chat-board-attempts-declared = Försök: { $intent_attempts }. Deklarerad { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Utforskningen frågade
ai-chat-board-add-a-hint-in-the = Lägg till en ledtråd i översikten över utredningstavlan för att besvara den.
ai-chat-board-last-error = Senaste fel
ai-chat-board-brief = Uppdrag
ai-chat-board-open-the-explore-chat = Öppna utforskningens chatt
ai-chat-board-loading-the-assessment-u = Läser in bedömningen…
ai-chat-board-assessment = Bedömning { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modell { $a_model }. Utfall { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Kontroller som ändrade det
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = Den här bedömningen kördes innan prompterna lagrades.
ai-chat-board-response = Svar
ai-chat-history-hoover-search-chat-history = Hoover Search - Chatthistorik
ai-chat-history-u-back = ← Tillbaka
ai-chat-history-conversation-history = Konversationshistorik
ai-chat-history-show-board-chats = Visa chattar från utredningstavlor
ai-chat-history-loading-u = Läser in…
ai-chat-history-could-not-load-history = Det gick inte att läsa in historiken: { $e }
ai-chat-history-no-conversations-yet = Inga konversationer ännu.
ai-chat-history-board = Utredningstavla
ai-chat-history-new-chat = Ny chatt
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } meddelande · uppdaterad { $s_updated_at }
    *[other] { $s_message_count } meddelanden · uppdaterad { $s_updated_at }
    }

ai-chat-history-delete-conversation = Radera konversationen
ai-chat-history-delete = Radera
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - AI-chatt
ai-chat-homepage-what-are-you-researching = Vad undersöker du?
ai-chat-homepage-view-all-conversations = Visa alla konversationer
ai-chat-homepage-starting-conversation-u = Startar konversationen…
ai-chat-homepage-investigation-boards = Utredningstavlor
ai-chat-homepage-new-board = Ny utredningstavla
ai-chat-homepage-loading-boards-u = Läser in utredningstavlor…
ai-chat-homepage-could-not-load-the-boards = Det gick inte att läsa in utredningstavlorna: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Du har ingen utredningstavla. En utredningstavla kör en lång utredning som en följd av agentutforskningar, och du granskar dess svar.
ai-chat-homepage-updated = Uppdaterad { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - AI-chatt
ai-chat-session-this-conversation-could-not-be = Den här konversationen kunde inte läsas in.
ai-chat-session-loading-u = Läser in…
ai-chat-session-u-chats = ← Chattar
ai-chat-session-history = Historik
ai-chat-session-show-the-files-that-the = Visa de filer som assistenten skrev i den här konversationen
ai-chat-session-workspace = Arbetsyta
ai-chat-session-this-answer-was-interrupted-before = Det här svaret avbröts innan det blev klart, eftersom sidan eller servern stoppades mitt i varvet. Fråga igen för att försöka på nytt.
ai-chat-session-dismiss = Avfärda
ai-chat-session-board-explore-chats-are-read = Chattar för utforskningar av utredningstavlor är skrivskyddade.{" "}
ai-chat-session-open-the-board = Öppna utredningstavlan
chat-locked-options-on = { $label }: på
chat-locked-options-off = { $label }: av
chat-tool-cards-running-u = pågår…
cards-result-cards-quote-found = Citatet hittades
cards-result-cards-quote-not-found = Citatet hittades inte
cards-result-cards-quote-not-checked = Citatet är inte kontrollerat
web-search-card-results = { $results_len } resultat
chat-tool-disclosure-running-u = pågår…
chat-transcript-call = verktygsanrop
chat-transcript-calls = verktygsanrop
ai-chat-board-a-board-without-collections-needs = En utredningstavla utan samlingar behöver internetverktyg.
ai-chat-board-of = { $snap_explores_used } av { $snap_max_explores }
ai-chat-board-assessment-2 = bedömning { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } meddelande
    *[other] { $s_message_count } meddelanden
    }

web-search-card-reranked-in = Cross-encodern rankade om resultaten på { $ms } ms.
web-search-card-engine-results = { $name }: { $count } på { $ms } ms
web-search-card-score-was-rank = poäng { $score } · var RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Varvet väntar på en ledig modellplats.
chat-activity-the-turn-waits-for-a-2 = Varvet väntar på en ledig verktygsplats.
chat-locked-options-start-a-new-chat-to = Starta en ny chatt för att ändra den här inställningen.
chat-locked-options-internet-tools = Internetverktyg
chat-session-card-new-chat = Ny chatt
chat-tool-cards-first-frame-of-the-video = Videons första bildruta
chat-tool-cards-screenshot-of = Skärmbild av
chat-tool-cards-image = Bild
cards-result-cards-the-agent-asked-a-question = Agenten ställde en fråga.
chat-transcript-hide = Dölj
chat-transcript-show = Visa
chat-transcript-unverified-quote-the-quoted-span = Overifierat citat. Det citerade stycket är för kort för att kontrolleras.
chat-transcript-unverified-quote-the-document-text = Overifierat citat. Dokumentets text kunde inte läsas.
chat-transcript-unverified-quote-this-wording-was = Overifierat citat. Den här formuleringen hittades inte i dokumentet.
chat-board-create-select-a-collection-or-turn = Välj en samling eller slå på internetverktyg.
chat-board-create-select-at-least-one-collection = Välj minst en samling.
ai-chat-board-active = Aktiv
ai-chat-board-paused = Pausad
ai-chat-board-waits-for-review = Väntar på granskning
ai-chat-board-completed = Slutförd
ai-chat-board-dropped = Släppt
ai-chat-board-unknown = Okänd
ai-chat-board-pause-the-board = Pausa utredningstavlan
ai-chat-board-resume-the-board = Återuppta utredningstavlan
ai-chat-board-none = Inga
ai-chat-board-reopen-with-the-remaining-budget = Öppna igen med den återstående budgeten
ai-chat-board-finding = Fynd
ai-chat-board-why-the-correction-is-wrong = Varför korrigeringen är fel
ai-chat-board-reject-correction = Avvisa korrigeringen
ai-chat-board-why-the-finding-is-wrong = Varför fyndet är fel
ai-chat-board-reject-finding = Avvisa fyndet
ai-chat-board-answer = Svar
ai-chat-board-proposed-answer = Föreslaget svar
ai-chat-homepage-active = Aktiv
ai-chat-homepage-paused = Pausad
ai-chat-homepage-waits-for-review = Väntar på granskning
ai-chat-homepage-completed = Slutförd
ai-chat-homepage-dropped = Släppt
ai-chat-homepage-unknown = Okänd
cards-result-cards-submitted-by-board = Inskickat av utredningstavlan: { $kind ->
        [sourced] ett belagt
        [inferred] ett härlett
        [not_found] ett negativt
       *[other] ett okänt
    } fynd ur rapporten
cards-result-cards-finding-for-board = { $kind ->
        [sourced] Ett belagt
        [inferred] Ett härlett
        [not_found] Ett negativt
       *[other] Ett okänt
    } fynd för utredningstavlan
chat-transcript-compacting = Komprimerar kontexten: { $before } token till ett mål på { $target }.
chat-transcript-compaction-failed = Sammanfattningen av de tidigare stegen misslyckades. Modellen fick de tidigare stegen oförändrade, { $after } token.
chat-transcript-compacted = Kontexten komprimerad: { $steps } steg sammanfattade, { $before } token till { $after }.
ai-chat-board-reopen-with-more = Öppna igen med { $grant } utforskningar till
ai-chat-board-goal-number = Mål { $number }
ai-chat-board-from-assessment-on = Från bedömning { $number } den { $date }.
ai-chat-board-from-assessment = Från bedömning { $number }.
chat-board-create-goal-2 = Mål { $index_1 }
ai-chat-session-lost-contact-with-the-chat = kontakten med chatten bröts: { $e }
ai-chat-session-could-not-stop-the-answer = det gick inte att stoppa svaret: { $e } — det körs fortfarande
ai-chat-board-later-assessments-dropped-an-answer = { $n } senare bedömningar släppte ett svar på det här målet:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt-token och { $a_completion_tokens } svarstoken
ai-chat-homepage-completed-goals-not-answered = Slutförd, { $n } mål obesvarade
board-graph-intent = avsikt, { $state }
chat-workspace-pane-characters = { $chars } tecken
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } pågående { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } pågående { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Besvarad efter { $retries_len ->
        [one] ett misslyckat försök
       *[other] { $retries_len } misslyckade försök
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len ->
        [one] ett misslyckat försök
       *[other] { $retries_len } misslyckade försök
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched = { $n ->
        [one] sökte efter { $n } term
       *[other] sökte efter { $n } termer
    }
tool-run-summary-read = { $n ->
        [one] läste { $n } dokument
       *[other] läste { $n } dokument
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] sökte på webben efter { $n } term
       *[other] sökte på webben efter { $n } termer
    }
tool-run-summary-read-web = { $n ->
        [one] läste { $n } webbsida
       *[other] läste { $n } webbsidor
    }
tool-run-summary-browser = { $n ->
        [one] { $n } webbläsaråtgärd
       *[other] { $n } webbläsaråtgärder
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] listade entiteterna i { $n } dokument
       *[other] listade entiteterna i { $n } dokument
    }
tool-run-summary-cited = { $n ->
        [one] citerade { $n } dokument
       *[other] citerade { $n } dokument
    }
tool-run-summary-cited-web = { $n ->
        [one] citerade { $n } webbsida
       *[other] citerade { $n } webbsidor
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] läste { $n } färdighet och verktygstexter
       *[other] läste { $n } färdigheter och verktygstexter
    }
tool-run-summary-saved = { $n ->
        [one] sparade { $n } anteckning
       *[other] sparade { $n } anteckningar
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } anrop till att-göra-listan
       *[other] { $n } anrop till att-göra-listan
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instruktion till agenten
       *[other] { $n } instruktioner till agenten
    }
tool-run-summary-other = { $n ->
        [one] { $n } annat anrop
       *[other] { $n } andra anrop
    }
tool-run-summary-failed = { $failures } misslyckades
tool-run-summary-took = tog { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } meddelande
    *[other] { $session_message_count } meddelanden
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } objekt
       *[other] { $count } objekt
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } fält
       *[other] { $count } fält
    }
chat-tool-disclosure-searched-collections = sökte i samlingar{ $filters }
chat-tool-disclosure-searched-collections-2 = sökte i samlingar · { $query }{ $filters }
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
cards-browser-card-could-not-click = kunde inte klicka på { $element }
cards-browser-card-typed-into = skrev i { $element }
cards-browser-card-could-not-type-into = kunde inte skriva i { $element }
cards-browser-card-typed = skrev “{ $text }”
cards-browser-card-could-not-type = kunde inte skriva “{ $text }”
cards-browser-card-pressed = tryckte på { $key }
cards-browser-card-could-not-press = kunde inte trycka på { $key }
cards-browser-card-chose-an-option-in = valde ett alternativ i { $element }
cards-browser-card-could-not-choose-an-option = kunde inte välja ett alternativ i { $element }
cards-browser-card-hovered = höll muspekaren över { $element }
cards-browser-card-could-not-hover = kunde inte hålla muspekaren över { $element }
cards-browser-card-failed = { $bare } — misslyckades
cards-entities-card-listed-entities-document = listade entiteter · { $count } dokument{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · del { $part } av { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } dokument
cards-result-cards-forms = { $tool_name } · { $forms } former
cards-result-cards-in = {" "}i { $collections }
cards-result-cards-page = {" "}· sida { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } dokument · { $missing } citat hittades inte
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · oförändrad
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultat in, { $json_u64_doc_total_after_dedupe } efter borttagning av dubbletter

board-status-on = På

board-status-off = Av

chat-transcript-generic-tool = verktyget
