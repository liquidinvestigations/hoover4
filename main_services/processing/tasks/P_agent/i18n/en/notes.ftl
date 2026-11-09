# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l4 = Read the result pages that may answer the request now: put up to 6 of their URLs in one read_page call, in its `urls` list. One call reads them all at the same time.

## Page captures


## Sources


## Named things


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
note-progress-ended = The run ended after repeated searches without progress.
note-progress-ended-none = No keyword-matched source was found.
note-progress-ended-some = The searches found { $count } keyword-matched sources. The agent did not complete its answer.
note-progress-ended-searches = Searches run:
