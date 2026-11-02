# Translation of en/notes.ftl. Change it together with the English catalog.

# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l2 = De två senaste sökningarna hittade ingen ny källa. Läs de bästa resultatsidorna nu: lägg upp till 6 av deras URL:er i ett enda anrop av read_page, i dess lista `urls`. Sök igen först när du har en annan fråga.
note-discovery-l3-web = Du svarade innan du hade läst någon källsida. Anropa read_page en gång med URL:erna till de sidor som stöder dina punkter, upp till 6 i dess lista `urls`. Skriv sedan svaret på nytt med de källor som stöder det.
note-discovery-l3-documents = Du svarade innan du hade läst något dokument. Läs de dokument som stöder dina punkter med read_documents, flera filhashvärden i ett anrop. Skriv sedan svaret på nytt med de källor som stöder det.
note-discovery-l4 = Läs nu de resultatsidor som kan besvara begäran: lägg upp till 6 av deras URL:er i ett enda anrop av read_page, i dess lista `urls`. Ett anrop läser alla samtidigt.

## Page captures

note-capture-empty = Fångsten av { $urls } innehåller ingen artikeltext. Läs en annan källa. Citera inte den här sidan.

## Sources

note-web-tools-absent = Det här varvet har inga webbverktyg, så du kan inte läsa offentliga webbsidor. Använd de valda samlingarna och ange vilken del av begäran de inte besvarar.
note-sources-documents = Sök först i de tillåtna dokumentsamlingarna. Läs deras relevanta dokument.
note-sources-documents-before-web = Sök först i de tillåtna dokumentsamlingarna. Läs deras relevanta dokument. Läs de dokumenten innan du använder webben.

## Named things

note-absent-collection = Ingen tillåten samling heter { $name }. De tillåtna samlingarna är { $collections }.
note-absent-name = De valda samlingarna har ingen indexerad träff för { $name }.
note-absent-close-forms = Indexerade närliggande former: { $forms }. Använd inte en närliggande form som det begärda namnet. När du söker på en sådan, ange i svaret att det är en annan stavning.
note-absent-close-form = { $form } ({ $count } dokument)
note-absent-web = Det här varvets webbverktyg kan söka efter namnet.

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
note-advice-stuck = En chattkontroll bedömer att de senaste sökningarna upprepar sina resultat. Färdigheten no_results beskriver andra former av en sökning.
note-advice-absent = En chattkontroll bedömer att resultaten inte innehåller det som uppgiften efterfrågar. Ange det sökta omfånget innan du rapporterar att något saknas.
note-advice-completion = En chattkontroll bedömer att resultaten kan besvara uppgiften. Jämför varje begärd del med de källor som du har läst innan du svarar.
note-progress-ended = Körningen avslutades efter upprepade sökningar utan framsteg.
note-progress-ended-none = Ingen källa med nyckelordsträff hittades.
note-progress-ended-some = Sökningarna hittade { $count } källor med nyckelordsträff. Agenten slutförde inte sitt svar.
note-progress-ended-searches = Körda sökningar:
