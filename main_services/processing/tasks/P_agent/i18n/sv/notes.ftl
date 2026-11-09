# Translation of en/notes.ftl. Change it together with the English catalog.

# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l4 = Läs nu de resultatsidor som kan besvara begäran: lägg upp till 6 av deras URL:er i ett enda anrop av read_page, i dess lista `urls`. Ett anrop läser alla samtidigt.

## Page captures


## Sources


## Named things


## Search progress

note-progress-level = Sökförloppets nivå { $level }.
note-progress-searches = Sökningar som redan har körts:
note-progress-search = { $name } { $args }: { $items } objekt, { $matches } nyckelordsträffar.
note-progress-available = Söksteg som fortfarande finns:
note-progress-complete = De tillgängliga söksteg är slutförda.
note-progress-write-now = Skriv svaret eller rapporten nu. Ange vad de lästa källorna inte innehåller och namnge sökningarna.
note-progress-answer-next = Nästa svar måste vara slutsvaret. Ange de fakta som saknas och de sökningar som du har kört.
note-progress-step-quoted = Sök efter varje namn som en citerad fras med search_collections.
note-progress-step-variants = Sök efter ord utan citationstecken och namnvarianter. Läs ordantal och stavningskandidater.
note-progress-step-filters = Ta bort filter ett i taget och kör en sökning utan filter.
note-progress-step-facets = Kontrollera filtervärden med search_facet_values.
note-progress-step-dates = Kontrollera datum med search_histogram.
note-progress-step-passages = Sök efter en innehållsbeskrivning med search_passages.
note-progress-step-folder = Använd { $tool } för den begärda mappen, sökvägen eller filen.
note-progress-step-read-hits = Läs de 1 till 3 bästa träffarna med { $tool }.
note-progress-step-web-search = Sök på webben med web_search och läs de bästa resultatsidorna.
note-progress-step-page-find = Sök i den sparade texten på en lång sida med read_page och find.
note-progress-step-page-retry = Läs en annan resultatadress, eller den arkiverade kopian av en sida som misslyckades.
note-progress-ended = Körningen avslutades efter upprepade sökningar utan framsteg.
note-progress-ended-none = Ingen källa med nyckelordsträff hittades.
note-progress-ended-some = Sökningarna hittade { $count } källor med nyckelordsträff. Agenten slutförde inte sitt svar.
note-progress-ended-searches = Körda sökningar:
