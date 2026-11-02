# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = De laatste twee zoekopdrachten hebben geen nieuwe bron opgeleverd. Lees nu de beste resultaatpagina's: zet maximaal 6 van hun URL's in één aanroep van read_page, in de lijst `urls`. Zoek alleen opnieuw met een andere vraag.
note-discovery-l3-web = Je hebt geantwoord voordat je een bronpagina las. Roep read_page één keer aan met de URL's van de pagina's die je items onderbouwen, maximaal 6 in de lijst `urls`. Schrijf daarna het antwoord opnieuw met de bronnen die het onderbouwen.
note-discovery-l3-documents = Je hebt geantwoord voordat je een document las. Lees de documenten die je items onderbouwen met read_documents, meerdere bestandshashes in één aanroep. Schrijf daarna het antwoord opnieuw met de bronnen die het onderbouwen.
note-discovery-l4 = Lees nu de resultaatpagina's die de vraag mogelijk beantwoorden: zet maximaal 6 van hun URL's in één aanroep van read_page, in de lijst `urls`. Eén aanroep leest ze allemaal tegelijk.

## Page captures

note-capture-empty = De vastlegging van { $urls } bevat geen artikeltekst. Lees een andere bron. Haal deze pagina niet aan.

## Sources

note-web-tools-absent = Deze beurt heeft geen webtools, dus je kunt geen openbare webpagina's lezen. Gebruik de gekozen collecties en vermeld welk deel van de vraag ze niet beantwoorden.
note-sources-documents = Doorzoek eerst de toegestane documentcollecties. Lees de relevante documenten daaruit.
note-sources-documents-before-web = Doorzoek eerst de toegestane documentcollecties. Lees de relevante documenten daaruit. Lees die documenten voordat je het web gebruikt.

## Named things

note-absent-collection = Geen toegestane collectie heet { $name }. De toegestane collecties zijn { $collections }.
note-absent-name = De gekozen collecties hebben geen geïndexeerde treffer voor { $name }.
note-absent-close-forms = Geïndexeerde vergelijkbare vormen: { $forms }. Gebruik een vergelijkbare vorm niet als de gevraagde naam. Als je er een zoekt, noem die in het antwoord als een andere schrijfwijze.
note-absent-close-form = { $form } ({ $count } documenten)
note-absent-web = De webtools van deze beurt kunnen de naam zoeken.

## Search progress

note-progress-level = Voortgangsniveau van het zoeken: { $level }.
note-progress-searches = Zoekopdrachten die al zijn uitgevoerd:
note-progress-search = { $name } { $args }: { $items } items, { $matches } treffers op trefwoorden.
note-progress-available = Zoekstappen die nog beschikbaar zijn:
note-progress-complete = De beschikbare zoekstappen zijn voltooid.
note-progress-write-now = Schrijf nu het antwoord of het rapport. Vermeld wat de gelezen bronnen niet bevatten en noem de zoekopdrachten.
note-progress-answer-next = Je volgende reactie moet het antwoord zijn. Vermeld de ontbrekende feiten en de zoekopdrachten die je hebt uitgevoerd.
note-progress-step-quoted = Zoek elke naam als zin tussen aanhalingstekens met search_collections.
note-progress-step-variants = Zoek woorden zonder aanhalingstekens en naamvarianten. Lees de woordaantallen en de schrijfwijzekandidaten.
note-progress-step-filters = Verwijder filters een voor een en voer een zoekopdracht zonder filters uit.
note-progress-step-facets = Controleer filterwaarden met search_facet_values.
note-progress-step-dates = Controleer datums met search_histogram.
note-progress-step-passages = Zoek met een beschrijving van de inhoud met search_passages.
note-progress-step-folder = Gebruik { $tool } voor de gevraagde map, het gevraagde pad of bestand.
note-progress-step-read-hits = Lees de beste 1 tot 3 treffers met { $tool }.
note-progress-step-web-search = Zoek op het web met web_search en lees de beste resultaatpagina's.
note-progress-step-page-find = Zoek in de bewaarde tekst van een lange pagina met read_page en find.
note-progress-step-page-retry = Lees een ander resultaatadres, of de gearchiveerde kopie van een pagina die mislukte.
note-advice-stuck = Een chatcontrole schat in dat de recente zoekopdrachten hun resultaten herhalen. De vaardigheid no_results beschrijft andere vormen van een zoekopdracht.
note-advice-absent = Een chatcontrole schat in dat de resultaten niet bevatten wat de taak vraagt. Vermeld het doorzochte bereik voordat je een afwezigheid meldt.
note-advice-completion = Een chatcontrole schat in dat de resultaten de taak kunnen beantwoorden. Vergelijk elk gevraagd onderdeel met de bronnen die je las voordat je antwoordt.
note-progress-ended = De run eindigde na herhaalde zoekopdrachten zonder voortgang.
note-progress-ended-none = Er is geen bron met trefwoordtreffers gevonden.
note-progress-ended-some = De zoekopdrachten vonden { $count } bronnen met trefwoordtreffers. De agent heeft zijn antwoord niet voltooid.
note-progress-ended-searches = Uitgevoerde zoekopdrachten:
