chat-activity-the-bot-is-working = The bot is working...
chat-composer-ask-the-bot = Ask the bot...
chat-composer-internet-tools = Internet tools
chat-composer-agent-language-title = The agent answers in { $language }. Change the language in the settings, in a new tab.
chat-composer-try-again-in-s = Try again in { $secs } s
chat-composer-stop-the-answer-the-partial = Stop the answer (the partial is not saved to the conversation)
chat-composer-starting-the-conversation-u = Starting the conversation…
chat-composer-send = Send
chat-conversation-find-search-in-conversation = Search in conversation
chat-conversation-find-previous-match = Previous match
chat-conversation-find-next-match = Next match
chat-conversation-find-investigation-board = Investigation Board
doc-ref-card-not-openable = Not openable: { $reason }.
doc-ref-card-the-search-term-was = The search term was{" "}
doc-ref-card-open = Open
doc-ref-card-not-openable-2 = Not openable
chat-markdown-text-show-the-cited-source = Show the cited source
chat-markdown-text-no-citation-of-this-conversation = No citation of this conversation gave this handle, so no document stands behind it.
chat-markdown-text-citations-of-this-conversation-gave = Citations of this conversation gave this handle to more than one document, so it links to none of them.
cards-browser-card-open-the-archived-page = Open the archived page
cards-browser-card-the-page-itself-was-not = The page itself was not archived (status: { $artifact_status }). The screenshot above is what was kept.
cards-browser-card-click-the-screenshot-to-open = Click the screenshot to open the archived page.
cards-browser-card-show-less = Show less
cards-browser-card-show-all = Show all
cards-browser-card-archived-page = Archived page
cards-browser-card-download = Download
cards-browser-card-archived-copy-of = Archived copy of { $artifact_url }
cards-browser-card-this-page-was-not-archived = This page was not archived (status: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } with a card
cards-entities-card-the-entity-list-was-cut = The entity list was cut.
cards-entities-card-open-the-card-for-this = Open the card for this value ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = No card: this conversation never named the dataset these values came from, and the viewer is addressed by dataset.
cards-entities-card-more-all-of-them-in = { $rest } more, all of them in the document's entities panel.{" "}
cards-entities-card-names-organisations-and-places-above = Names, organisations and places above are a model's reading of the prose. No rule validated them, so there is nothing to explain and they open nothing.
cards-entities-card-nothing-extracted-from-this-document = Nothing extracted from this document.
chat-tool-cards-hide = Hide
chat-tool-cards-expand = Expand
chat-tool-cards-hide-raw-json = Hide raw JSON
chat-tool-cards-show-raw-json = Show raw JSON
cards-result-cards-search-this = Search this
cards-result-cards-search-every-collection = Search every collection
cards-result-cards-form = Form { $index }: { $form }
cards-result-cards-show-full-text = Show full text
cards-result-cards-quote = Quote: { $quote }
cards-result-cards-reason = Reason: { $why }
cards-result-cards-open-question = Open question: { $question }
cards-result-cards-the-explore-gave-this-answer = The explore gave this answer to its board as { $kind ->
        [sourced] a sourced
        [inferred] an inferred
        [not_found] a not found
       *[other] an unknown kind
    } finding.
cards-result-cards-it-left-no-open-question = It left no open question.
cards-result-cards-open-questions-for-the-board = Open questions for the board:
cards-result-cards-arguments = Arguments
cards-result-cards-list-after-the-call = List after the call: { $snapshot_goal }
cards-result-cards-replaces = {" "}· replaces { $replaces_id }
cards-result-cards-the-list-at-this-version = The list at this version is not stored.
web-search-card-these-sources-returned-nothing-so = These sources returned nothing, so the results come from fewer than intended
web-search-card-u-degraded = ⚠ { $degraded_len } degraded
web-search-card-form = Form { $index }: { $form }
web-search-card-no-results-from = No results from: { $degraded_text }
web-search-card-no-results-every-source-answered = No results. Every source answered and none of them had anything for this query.
web-search-card-the-lowest-ranked-results-were = The lowest-ranked results were dropped so this call fits in the transcript. The assistant saw all of them.
web-search-card-view-search-details = View search details.
web-search-card-the-stored-result-could-not = the stored result could not be read back as JSON
web-search-card-nothing-was-stored-for-this = Nothing was stored for this call.
web-search-card-forms = Forms: { $forms }
web-search-card-kind = Kind: { $row_kind }
web-search-card-published = Published: { $row_published }
web-search-card-loading-search-detail-u = Loading search detail…
web-search-card-could-not-load-the-search = Could not load the search detail: { $e }
web-search-card-malformed-detail = Malformed detail: { $e }
web-search-card-the-tool-returned-selected-results = The tool returned selected results to the model.
web-search-card-results-use-reciprocal-rank-fusion = Results use reciprocal rank fusion.
web-search-card-returned-nothing = returned nothing: { $degraded }
web-search-card-all-candidates-use-fusion-order = All candidates use fusion order.
web-search-card-the-cross-encoder-ranks-selected = The cross-encoder ranks selected results.
web-search-card-selected-results-use-fusion-order = Selected results use fusion order.
web-search-card-search-detail = Search detail
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Search this
chat-tool-disclosure-search-every-collection = Search every collection
chat-tool-disclosure-hide = Hide
chat-tool-disclosure-expand = Expand
chat-tool-disclosure-this-step-was-recorded-before = This step was recorded before tool arguments and results were stored. Only the summary below is available.
chat-tool-disclosure-arguments = Arguments
chat-tool-disclosure-result = Result
chat-tool-disclosure-hide-raw-json = Hide raw JSON
chat-tool-disclosure-show-raw-json = Show raw JSON
chat-tool-disclosure-input-json = Input JSON
chat-tool-disclosure-output-json = Output JSON
chat-transcript-ask-a-question-about-the = Ask a question about the documents in your collections.
chat-transcript-suggested-next = Suggested next...
chat-transcript-earlier-answer = Earlier answer
chat-transcript-tokens-the-conversation-carries-the = Tokens the conversation carries, the largest single context this turn was billed for, and how much of the model's window that used
chat-transcript-instruction-to-the-agent = Instruction to the agent
chat-transcript-the-context-stays-above-the = {" "}The context stays above the target of { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } summary parts failed. The record holds the lists only.
chat-transcript-show-the-record = Show the record
chat-transcript-hide-reasoning = Hide reasoning
chat-transcript-show-reasoning = Show reasoning
chat-transcript-from-u-hide = { $count } { $count ->
        [one] document
       *[other] documents
    } from { $tool } — hide
chat-transcript-from-u-show = { $count } { $count ->
        [one] document
       *[other] documents
    } from { $tool } — show
chat-transcript-u-hide = { $summary } — hide
chat-transcript-u-show = { $summary } — show
chat-transcript-citations-of-this-conversation-give = Citations of this conversation give { $doc_handle } to more than one document. The answer links it to none of them.
chat-transcript-report = Report { $label }
chat-transcript-open-in-the-workspace = Open in the workspace
chat-transcript-this-version-could-not-be = This version could not be read. The chat text of the answer follows.
chat-transcript-files = Files
chat-transcript-version = { $file_name }, version { $file_version }
chat-web-find-exact-text = Find exact text
chat-web-previous-match = Previous match
chat-web-next-match = Next match
chat-web-close-preview = Close preview
chat-web-the-captured-page-could-not = The captured page could not be loaded.
chat-web-loading = Loading…
chat-workspace-pane-workspace = Workspace
chat-workspace-pane-close-the-workspace = Close the workspace
chat-workspace-pane-close = Close
chat-workspace-pane-loading-the-files-u = Loading the files…
chat-workspace-pane-the-files-could-not-be = The files could not be loaded: { $error }
chat-workspace-pane-this-conversation-has-no-files = This conversation has no files.
chat-workspace-pane-version = version { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Choose a file to read it.
chat-workspace-pane-loading-the-file-u = Loading the file…
chat-workspace-pane-the-file-could-not-be = The file could not be loaded: { $error }
chat-workspace-pane-version-2 = { $found_name }, version { $found_version }
chat-board-create-collections = Collections
chat-board-create-loading-collections-u = Loading collections…
chat-board-create-hoover-search-new-board = Hoover Search - New board
chat-board-create-ai-chat = AI Chat
chat-board-create-new-investigation-board = New investigation board
chat-board-create-a-board-runs-its-goals = A board runs its goals as a sequence of agent explores. Each explore is a chat that ends in one board finding. You review the answer of each goal, and you can reject findings and add hints while it runs.
chat-board-create-title = Title
chat-board-create-goal = Goal
chat-board-create-remove-this-goal = Remove this goal
chat-board-create-remove = Remove
chat-board-create-add-a-goal = Add a goal
chat-board-create-context-optional = Context (optional)
chat-board-create-hints-one-per-line-optional = Hints, one per line (optional)
chat-board-create-sources = Sources
chat-board-create-internet-tools = Internet tools
chat-board-create-creating-board = Creating board...
chat-board-create-create-board = Create board
ai-chat-board-hoover-search-board = Hoover Search - Board
ai-chat-board-loading-the-board-u = Loading the board…
ai-chat-board-show-the-board-overview = Show the board overview
ai-chat-board-zoom-out = Zoom out
ai-chat-board-zoom-in = Zoom in
ai-chat-board-u-ai-chat = ← AI Chat
ai-chat-board-settings = Settings
ai-chat-board-board-settings = Board settings
ai-chat-board-internet-tools = Internet tools
ai-chat-board-the-next-explores-of-the = The next explores of the board can search the web and read web pages. Running explores keep the setting they started with.
ai-chat-board-collections = Collections
ai-chat-board-the-collections-are-fixed-when = The collections are fixed when the board is created.
ai-chat-board-confirm-drop = Confirm drop
ai-chat-board-drop-the-board = Drop the board
ai-chat-board-close = Close
ai-chat-board-the-board-used-its-explore = The board used its explore limit
ai-chat-board-the-board-used-explores-the = The board used { $explore_limit } explores, the limit of one board. It starts no more work. You can still decide the proposed answers.
ai-chat-board-create-a-new-board-to = Create a new board to continue the investigation
ai-chat-board-goal = Goal
ai-chat-board-goals = Goals
ai-chat-board-add-new-goal = Add new goal...
ai-chat-board-a-new-goal = A new goal
ai-chat-board-add-goal = Add goal
ai-chat-board-a-board-has-at-most = A board has at most { $max_goals } goals. Create a new board for another goal.
ai-chat-board-background-context = Background context
ai-chat-board-continue-with-a-correction = Continue with a correction
ai-chat-board-correction-what-is-wrong-or = Correction: what is wrong or missing. The board continues with it.
ai-chat-board-the-board-waits-for-your = The board waits for your review
ai-chat-board-the-board-used-its-budget = The board used its budget of { $snap_max_explores } explores.
ai-chat-board-the-assessments-gave-no-usable = The assessments gave no usable direction.
ai-chat-board-accept-or-reject-the-proposed = Accept or reject the proposed answer of each goal above. A rejected answer lets the board continue at once.
ai-chat-board-no-proposed-answer-waits-for = No proposed answer waits for your decision.
ai-chat-board-reopen-the-board-to-continue = Reopen the board to continue the open goals. It keeps its findings and answers.
ai-chat-board-close-the-board-to-accept = Close the board to accept every proposed answer and stop it, or continue it with a correction.
ai-chat-board-close-the-board = Close the board
ai-chat-board-or-reopen-the-board-to = Or reopen the board to continue the open goals without a correction.
ai-chat-board-the-board-is-complete = The board is complete
ai-chat-board-a-goal-has-no-accepted = A goal has no accepted answer. Reopen the board to continue it. The board keeps its findings and answers.
ai-chat-board-add-a-hint = Add a hint
ai-chat-board-the-next-assessment-reads-every = The next assessment reads every hint. A hint also answers an explore that asked a question.
ai-chat-board-add-hint = Add hint
ai-chat-board-events = Events
ai-chat-board-newest-first = Newest first
ai-chat-board-date = Date
ai-chat-board-actor = Actor
ai-chat-board-event = Event
ai-chat-board-show-details = Show details
ai-chat-board-open = Open
ai-chat-board-show-the-newest-events = Show the newest { $event_rows } events
ai-chat-board-show-all-events = Show all { $snap_events_len } events
ai-chat-board-statistics = Statistics
ai-chat-board-explores = Explores
ai-chat-board-model-steps-per-explore = Model steps per explore
ai-chat-board-assessments = Assessments
ai-chat-board-intents = Intents
ai-chat-board-findings = Findings
ai-chat-board-created = Created
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } rejected this finding on { $format_utc_ms_fact_rejected_ms }. The board no longer uses it.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } rejected this finding. The board no longer uses it.
ai-chat-board-no-reason-was-given = No reason was given.
ai-chat-board-reason = Reason: { $fact_rejected_reason }
ai-chat-board-open-questions = Open questions
ai-chat-board-explored-in = Explored in{" "}
ai-chat-board-explore-this-question = Explore this question
ai-chat-board-your-questions = Your questions
ai-chat-board-ask-about-the-background-context = Ask about the background context
ai-chat-board-ask-about-this-finding = Ask about this finding
ai-chat-board-a-follow-up-question-about = A follow-up question about this node
ai-chat-board-ask = Ask
ai-chat-board-checks-that-changed-this-finding = Checks that changed this finding
ai-chat-board-reject-this-correction = Reject this correction
ai-chat-board-reject-this-finding = Reject this finding
ai-chat-board-not-answered-the-board-was = Not answered. The board was finished without an answer for this goal. A hint or a reopening opens it again.
ai-chat-board-no-answer-yet = No answer yet.
ai-chat-board-the-findings-of-this-answer = The findings of this answer are searches that found nothing. Accept it to record that the records do not answer the goal, or reject it to continue the investigation.
ai-chat-board-open-an-assessment-to-read = {"."} Open an assessment to read why.
ai-chat-board-from-the-findings = From the findings{" "}
ai-chat-board-accept-answer = Accept answer
ai-chat-board-why-the-answer-is-wrong = Why the answer is wrong or incomplete
ai-chat-board-reject-answer = Reject answer
ai-chat-board-intent = Intent
ai-chat-board-attempts-declared = Attempts: { $intent_attempts }. Declared { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = The explore asked
ai-chat-board-add-a-hint-in-the = Add a hint in the board overview to answer it.
ai-chat-board-last-error = Last error
ai-chat-board-brief = Brief
ai-chat-board-open-the-explore-chat = Open the explore chat
ai-chat-board-loading-the-assessment-u = Loading the assessment…
ai-chat-board-assessment = Assessment { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Model { $a_model }. Outcome { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Checks that changed it
ai-chat-board-prompt = Prompt
ai-chat-board-this-assessment-ran-before-the = This assessment ran before the prompts were stored.
ai-chat-board-response = Response
ai-chat-history-hoover-search-chat-history = Hoover Search - Chat history
ai-chat-history-u-back = ← Back
ai-chat-history-conversation-history = Conversation history
ai-chat-history-show-board-chats = Show board chats
ai-chat-history-loading-u = Loading…
ai-chat-history-could-not-load-history = Could not load history: { $e }
ai-chat-history-no-conversations-yet = No conversations yet.
ai-chat-history-board = Board
ai-chat-history-new-chat = New chat
ai-chat-history-messages-updated = { $s_message_count } messages · updated { $s_updated_at }
ai-chat-history-delete-conversation = Delete conversation
ai-chat-history-delete = Delete
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - AI Chat
ai-chat-homepage-what-are-you-researching = What are you researching?
ai-chat-homepage-view-all-conversations = View all conversations
ai-chat-homepage-starting-conversation-u = Starting conversation…
ai-chat-homepage-investigation-boards = Investigation boards
ai-chat-homepage-new-board = New board
ai-chat-homepage-loading-boards-u = Loading boards…
ai-chat-homepage-could-not-load-the-boards = Could not load the boards: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = You have no board. A board runs a long investigation as a sequence of agent explores, and you review its answers.
ai-chat-homepage-updated = Updated { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - AI Chat
ai-chat-session-this-conversation-could-not-be = This conversation could not be loaded.
ai-chat-session-loading-u = Loading…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = History
ai-chat-session-show-the-files-that-the = Show the files that the assistant wrote in this conversation
ai-chat-session-workspace = Workspace
ai-chat-session-this-answer-was-interrupted-before = This answer was interrupted before it finished, because the page or the server stopped mid-turn. Ask again to retry.
ai-chat-session-dismiss = Dismiss
ai-chat-session-board-explore-chats-are-read = Board explore chats are read-only.{" "}
ai-chat-session-open-the-board = Open the board
chat-locked-options-on = { $label }: on
chat-locked-options-off = { $label }: off
chat-tool-cards-running-u = running…
cards-result-cards-quote-found = Quote found
cards-result-cards-quote-not-found = Quote not found
cards-result-cards-quote-not-checked = Quote not checked
web-search-card-results = { $results_len } results
chat-tool-disclosure-running-u = running…
chat-transcript-call = call
chat-transcript-calls = calls
ai-chat-board-a-board-without-collections-needs = A board without collections needs internet tools.
ai-chat-board-of = { $snap_explores_used } of { $snap_max_explores }
ai-chat-board-assessment-2 = assessment { $number }
ai-chat-history-messages = { $s_message_count } messages
web-search-card-reranked-in = The cross-encoder ranked results in { $ms } ms.
web-search-card-engine-results = { $name }: { $count } in { $ms } ms
web-search-card-score-was-rank = score { $score } · was RRF #{ $rank }
chat-activity-the-turn-waits-for-a = The turn waits for a free model slot.
chat-activity-the-turn-waits-for-a-2 = The turn waits for a free tool slot.
chat-locked-options-start-a-new-chat-to = Start a new chat to change this setting.
chat-locked-options-internet-tools = Internet tools
chat-session-card-new-chat = New chat
chat-tool-cards-first-frame-of-the-video = First frame of the video
chat-tool-cards-screenshot-of = Screenshot of
chat-tool-cards-image = Image
cards-result-cards-the-agent-asked-a-question = The agent asked a question.
chat-transcript-hide = Hide
chat-transcript-show = Show
chat-transcript-unverified-quote-the-quoted-span = Unverified quote. The quoted span is too short to check.
chat-transcript-unverified-quote-the-document-text = Unverified quote. The document text could not be read.
chat-transcript-unverified-quote-this-wording-was = Unverified quote. This wording was not found in the document.
chat-board-create-select-a-collection-or-turn = Select a collection or turn on internet tools.
chat-board-create-select-at-least-one-collection = Select at least one collection.
ai-chat-board-active = Active
ai-chat-board-paused = Paused
ai-chat-board-waits-for-review = Waits for review
ai-chat-board-completed = Completed
ai-chat-board-dropped = Dropped
ai-chat-board-unknown = Unknown
ai-chat-board-pause-the-board = Pause the board
ai-chat-board-resume-the-board = Resume the board
ai-chat-board-none = None
ai-chat-board-reopen-with-the-remaining-budget = Reopen with the remaining budget
ai-chat-board-finding = Finding
ai-chat-board-why-the-correction-is-wrong = Why the correction is wrong
ai-chat-board-reject-correction = Reject correction
ai-chat-board-why-the-finding-is-wrong = Why the finding is wrong
ai-chat-board-reject-finding = Reject finding
ai-chat-board-answer = Answer
ai-chat-board-proposed-answer = Proposed answer
ai-chat-homepage-active = Active
ai-chat-homepage-paused = Paused
ai-chat-homepage-waits-for-review = Waits for review
ai-chat-homepage-completed = Completed
ai-chat-homepage-dropped = Dropped
ai-chat-homepage-unknown = Unknown
cards-result-cards-submitted-by-board = Submitted by the board: { $kind ->
        [sourced] a sourced
        [inferred] an inferred
        [not_found] a not found
       *[other] an unknown kind
    } finding from the report
cards-result-cards-finding-for-board = { $kind ->
        [sourced] A sourced
        [inferred] An inferred
        [not_found] A not found
       *[other] An unknown kind
    } finding for the board
chat-transcript-compacting = Compacting the context: { $before } tokens to a target of { $target }.
chat-transcript-compaction-failed = The summary of the earlier steps failed. The model received the earlier steps unchanged, { $after } tokens.
chat-transcript-compacted = Context compacted: { $steps } steps summarised, { $before } tokens to { $after }.
ai-chat-board-reopen-with-more = Reopen with { $grant } more explores
ai-chat-board-goal-number = Goal { $number }
ai-chat-board-from-assessment-on = From assessment { $number } on { $date }.
ai-chat-board-from-assessment = From assessment { $number }.
chat-board-create-goal-2 = Goal { $index_1 }
ai-chat-session-lost-contact-with-the-chat = lost contact with the chat: { $e }
ai-chat-session-could-not-stop-the-answer = could not stop the answer: { $e } — it is still running
ai-chat-board-later-assessments-dropped-an-answer = { $n } later assessments dropped an answer for this goal:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } prompt and { $a_completion_tokens } completion tokens
ai-chat-homepage-completed-goals-not-answered = Completed, { $n } goals not answered
board-graph-intent = intent, { $state }
chat-workspace-pane-characters = { $chars } characters
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } running tool { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } running tool { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Answered after { $retries_len } failed attempt{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } failed attempt{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, version { $report_version }
tool-run-summary-searched = { $n ->
        [one] searched { $n } term
       *[other] searched { $n } terms
    }
tool-run-summary-read = { $n ->
        [one] read { $n } document
       *[other] read { $n } documents
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] searched the web for { $n } term
       *[other] searched the web for { $n } terms
    }
tool-run-summary-read-web = { $n ->
        [one] read { $n } web page
       *[other] read { $n } web pages
    }
tool-run-summary-browser = { $n ->
        [one] { $n } browser action
       *[other] { $n } browser actions
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] listed the entities of { $n } document
       *[other] listed the entities of { $n } documents
    }
tool-run-summary-cited = { $n ->
        [one] cited { $n } document
       *[other] cited { $n } documents
    }
tool-run-summary-cited-web = { $n ->
        [one] cited { $n } web page
       *[other] cited { $n } web pages
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] read { $n } skill and tool texts
       *[other] read { $n } skills and tool texts
    }
tool-run-summary-saved = { $n ->
        [one] saved { $n } note
       *[other] saved { $n } notes
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } todo list call
       *[other] { $n } todo list calls
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instruction to the agent
       *[other] { $n } instructions to the agent
    }
tool-run-summary-other = { $n ->
        [one] { $n } other call
       *[other] { $n } other calls
    }
tool-run-summary-failed = { $failures } failed
tool-run-summary-took = took { $duration_text_ms }
chat-session-card-messages = { $session_message_count } messages
chat-tool-disclosure-item = { $count ->
        [one] { $count } item
       *[other] { $count } items
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } field
       *[other] { $count } fields
    }
chat-tool-disclosure-searched-collections = searched collections{ $filters }
chat-tool-disclosure-searched-collections-2 = searched collections · { $query }{ $filters }
chat-tool-disclosure-cited-documents = cited { $n } documents
chat-tool-disclosure-read-document = read document · { $path }
chat-tool-disclosure-searched-the-web = searched the web · { $q }
chat-tool-disclosure-opened-page = opened page · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = called { $other }
chat-tool-disclosure-called-2 = called { $other } · { $short }
cards-browser-card-opened = opened { $url }
cards-browser-card-could-not-open = could not open { $url }
cards-browser-card-clicked = clicked { $element }
cards-browser-card-could-not-click = could not click { $element }
cards-browser-card-typed-into = typed into { $element }
cards-browser-card-could-not-type-into = could not type into { $element }
cards-browser-card-typed = typed “{ $text }”
cards-browser-card-could-not-type = could not type “{ $text }”
cards-browser-card-pressed = pressed { $key }
cards-browser-card-could-not-press = could not press { $key }
cards-browser-card-chose-an-option-in = chose an option in { $element }
cards-browser-card-could-not-choose-an-option = could not choose an option in { $element }
cards-browser-card-hovered = hovered { $element }
cards-browser-card-could-not-hover = could not hover { $element }
cards-browser-card-failed = { $bare } — failed
cards-entities-card-listed-entities-document = listed entities · { $count } document{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · part { $part } of { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } documents
cards-result-cards-forms = { $tool_name } · { $forms } forms
cards-result-cards-in = {" "}in { $collections }
cards-result-cards-page = {" "}· page { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documents · { $missing } quotes not found
cards-result-cards-version-unchanged = { $tool_name } · version { $version } · unchanged
cards-result-cards-version = { $tool_name } · version { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } results in, { $json_u64_doc_total_after_dedupe } after deduplication
