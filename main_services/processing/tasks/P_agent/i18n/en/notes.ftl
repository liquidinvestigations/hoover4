# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l2 = The last two searches found no new source. Read the best result pages now: put up to 6 of their URLs in one read_page call, in its `urls` list. Search again only with a different question.
note-discovery-l3-web = You answered before reading any source page. Call read_page once with the URLs of the pages that support your items, up to 6 in its `urls` list. Then write the answer again with the sources that support it.
note-discovery-l3-documents = You answered before reading any document. Read the documents that support your items with read_documents, several file hashes in one call. Then write the answer again with the sources that support it.
note-discovery-l4 = Read the result pages that may answer the request now: put up to 6 of their URLs in one read_page call, in its `urls` list. One call reads them all at the same time.

## Page captures

note-capture-empty = The capture of { $urls } holds no article text. Read another source. Do not cite this page.

## Sources

note-web-tools-absent = This turn has no web tools, so it cannot read public web pages. Use the selected collections, and state which part of the request they do not answer.
note-sources-documents = Search the permitted document collections first. Read their relevant documents.
note-sources-documents-before-web = Search the permitted document collections first. Read their relevant documents. Read those documents before using the web.

## Named things

note-absent-collection = No permitted collection is named { $name }. The permitted collections are { $collections }.
note-absent-name = The selected collections have no indexed match for { $name }.
note-absent-close-forms = Indexed close forms: { $forms }. Do not use a close form as the requested name. When you search one, name it in the answer as a different spelling.
note-absent-close-form = { $form } ({ $count } documents)
note-absent-web = The web tools of this turn can search the name.

## Search progress

note-progress-level = Search progress level { $level }.
note-progress-searches = Searches already run:
note-progress-search = { $name } { $args }: { $items } items, { $matches } keyword matches.
note-progress-available = Search steps still available:
note-progress-complete = The available search steps are complete.
note-progress-write-now = Write the answer or the report now. State what the sources read do not hold and name the searches.
note-progress-answer-next = The next reply must be the answer. State the missing facts and the searches that you ran.
note-progress-step-quoted = Search each name as a quoted phrase with search_collections.
note-progress-step-variants = Search unquoted words and name variants. Read word counts and spelling candidates.
note-progress-step-filters = Remove filters one at a time and run a search without filters.
note-progress-step-facets = Verify filter values with search_facet_values.
note-progress-step-dates = Verify dates with search_histogram.
note-progress-step-passages = Search a content description with search_passages.
note-progress-step-folder = Use { $tool } for the requested folder, path or file.
note-progress-step-read-hits = Read the best 1 to 3 hits with { $tool }.
note-progress-step-web-search = Search the web with web_search and read the best result pages.
note-progress-step-page-find = Search the kept text of a long page with read_page and find.
note-progress-step-page-retry = Read another result address, or the archived copy of a failed page.
note-advice-stuck = A chat check estimates that the recent searches repeat their results. The no_results skill describes other forms of a search.
note-advice-absent = A chat check estimates that the results do not hold what the task asks for. State the searched scope before you report an absence.
note-advice-completion = A chat check estimates that the results can answer the task. Compare each requested part with the sources that you read before you answer.
note-progress-ended = The run ended after repeated searches without progress.
note-progress-ended-none = No keyword-matched source was found.
note-progress-ended-some = The searches found { $count } keyword-matched sources. The agent did not complete its answer.
note-progress-ended-searches = Searches run:
