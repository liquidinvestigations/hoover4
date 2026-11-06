admin-guard-administration-access-required = Administration access required
admin-guard-signed-in-as = Signed in as { $u_username }.
admin-guard-ask-an-administrator-for-access = Ask an administrator for access to this section.
admin-shell-dashboard = Dashboard
admin-shell-collections = Collections
admin-shell-operations = Operations
admin-shell-errors-failures = Errors/Failures
admin-shell-feedback = Feedback
admin-shell-users = Users
admin-shell-groups = Groups
admin-shell-settings = Settings
admin-shell-llm = LLM
admin-shell-ai-status = AI status
admin-shell-metrics = Metrics
admin-shell-administration = Administration
dataset-create-panel-add-a-dataset = Add a dataset
dataset-create-panel-the-dataset-mounts-could-not = The dataset mounts could not be read, so there is nothing to pick from: { $err }
dataset-create-panel-loading-the-dataset-mounts = Loading the dataset mounts.
dataset-create-panel-no-dataset-mount-is-configured = No dataset mount is configured.
dataset-create-panel-the-mount-folder-could-not = The mount folder could not be read, so there is nothing to pick from: { $err }
dataset-create-panel-no-subfolders-were-found-in = No subfolders were found in this mount.{" "}
dataset-create-panel-folder = Folder
dataset-create-panel-select-a-folder = Select a folder
dataset-create-panel-new-folder = New folder
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } entries), already a dataset
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } entries)
dataset-create-panel-the-server-creates-this-folder = The server creates this folder in the mount when you create the dataset.{" "}
dataset-create-panel-the-list-shows-the-direct = The list shows the direct subfolders of the mount.
dataset-create-panel-dataset-name = Dataset name
dataset-create-panel-a-name-has-lowercase-letters = A name has lowercase letters, digits and underscores. Capital letters become lowercase,{" "}
dataset-create-panel-the-dataset-is-saved-as = The dataset is saved as: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = This collection has a dataset with the name { $saved_name }.
dataset-create-panel-accept-uploads = Accept uploads
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Saved as this collection's defaults. No dataset changes its languages.
dataset-create-panel-saving-u = Saving…
dataset-create-panel-save-as-collection-defaults = Save as collection defaults
dataset-create-panel-creating-u = Creating…
dataset-create-panel-create-and-ingest = Create and ingest
dataset-create-panel-mount = Mount
dataset-ocr-panel-last-operation = Last operation: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , started { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = No progress for { $current_stale_seconds_60 } minutes. Check the Temporal workflow, and cancel the operation if it is stuck.
dataset-ocr-panel-filter-languages = Filter languages
dataset-ocr-panel-ocr-languages = OCR languages
dataset-ocr-panel-failed-to-load-the-ocr = Failed to load the OCR settings for this dataset
dataset-ocr-panel-loading-u = Loading…
dataset-ocr-panel-each-easyocr-script-group-adds = Each EasyOCR script group adds one OCR pass over the dataset. Tesseract reads all its languages in one pass.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = In force: { $panel_tesseract_languages }, from { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = Use { $source_label_panel_inherited_tesseract_s }: { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = The Tesseract service did not answer, so the installed languages are unknown.{" "}
dataset-ocr-panel-the-image-also-has-script = The image also has { $script_models } script models, for example Latin. The form does not offer them, because the setting becomes part of a storage key and accepts lowercase codes only.
dataset-ocr-panel-the-first-language-is-the = The first language is the primary one. Selected:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = EasyOCR is off on this deployment, so this setting has no effect until it is on.
dataset-ocr-panel-in-force-off-from = In force: off, from { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = In force: { $panel_easyocr_languages }, from { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = Use { $source_label_panel_inherited_easyocr_sou }: off
dataset-ocr-panel-use-2 = Use { $source_label_panel_inherited_easyocr_sou }: { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Enabled
dataset-ocr-panel-the-easyocr-service-did-not = The EasyOCR service did not report the languages that it supports.
dataset-ocr-panel-a-model-download-failed = A model download failed: { $failure }
dataset-ocr-panel-stored-text-variants = Stored text variants
dataset-ocr-panel-removing-a-language-deletes-its = Removing a language deletes its text, its search rows and its searchable PDF.
dataset-ocr-panel-searchable-pdfs = Searchable PDFs
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } files · { $variant_total_bytes_1024_1024 } MB
dataset-ocr-panel-searchable-pdfs-are-off-on = Searchable PDFs are off on this deployment.
dataset-ocr-panel-saving-u = Saving…
dataset-ocr-panel-apply = Apply
dataset-ocr-panel-no-changes-to-apply = No changes to apply.
live-chats-panel-live-llm-chats = Live LLM chats
live-chats-panel-agent-turns-running-right-now = Agent turns running right now, longest-running first. Refreshes every 2 s. Read from Temporal, so a turn that started before the last website restart is here too.
live-chats-panel-loading-u = Loading…
live-chats-panel-no-chats-running = No chats running.
live-chats-panel-user = User
live-chats-panel-conversation = Conversation
live-chats-panel-question = Question
live-chats-panel-internet = Internet
live-chats-panel-running = Running
live-chats-panel-started = Started
live-chats-panel-cancels-the-workflow-the-turn = Cancels the workflow. The turn ends with a stopped marker in the transcript rather than vanishing.
live-chats-panel-kill = Kill
processing-updates-panel-loading-u = Loading…
processing-updates-panel-open-the-operation = Open the operation
processing-updates-panel-the-pipeline-has-not-calculated = The pipeline has not calculated these updates yet.
processing-updates-panel-calculated-at-in-ms = Calculated at { $view_checked_at } in { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = Automatic updates are off on this installation. Start the updates with the button.
processing-updates-panel-step = Step
processing-updates-panel-count = Count
processing-updates-panel-state = State
processing-updates-panel-last-run = Last run
processing-updates-panel-runs = Runs: { $step_runs }
processing-updates-panel-a-run-again-would-select = A run again would select about this many { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } on a run again
processing-updates-panel-never = Never
processing-updates-panel-update-collection = Update collection
processing-updates-panel-update-processing = Update processing
processing-updates-panel-check-again = Check again
processing-updates-panel-dataset = Dataset
processing-updates-panel-processing-updates = Processing updates
admin-ai-status-admin-ai-status = Admin: AI status
admin-ai-status-ai-status = AI status
admin-ai-status-the-configured-service-and-the = The configured service and the service that actually answers. A fallback to the CPU service shows here only.
admin-ai-status-loading-u = Loading…
admin-ai-status-config-fingerprint = Config fingerprint
admin-ai-status-website-worker = Website / worker
admin-ai-status-ai-server = AI server
admin-ai-status-match = Match
admin-ai-status-embeddings-probe = Embeddings probe
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dims
admin-ai-status-llm-configured = LLM configured
admin-ai-status-capabilities = Capabilities
admin-ai-status-capability = Capability
admin-ai-status-configured = Configured
admin-ai-status-serving = Serving
admin-ai-status-model = Model
admin-ai-status-reachable = Reachable
admin-ai-status-detail = Detail
admin-ai-status-no = NO
admin-ai-status-vector-shard-dims-vs-probe = Vector shard dims vs probe
admin-ai-status-no-collections-yet = No collections yet.
admin-ai-status-collection = Collection
admin-ai-status-shard = Shard
admin-ai-status-matches-probe = Matches probe
admin-ai-status-browser-router = Browser router
admin-ai-status-live-sessions = Live sessions: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Recent LLM traffic (24 h)
admin-ai-status-no-llm-call-events-yet = No llm_call_events yet.
admin-ai-status-user = User
admin-ai-status-calls = Calls
admin-ai-status-errors = Errors
admin-ai-status-service-use-24-h = Service use% (24 h)
admin-ai-status-busy-seconds-in-the-last = Busy seconds in the last 24 hours, as a share of the day.
admin-ai-status-no-samples-yet = No samples yet.
admin-ai-status-service = Service
admin-ai-status-busy-s = Busy s
admin-ai-status-use = Use %
admin-collection-detail-admin-collection = Admin: collection { $collection_id }
admin-collection-detail-failed-to-load-collection = Failed to load collection
admin-collection-detail-loading = Loading...
admin-collection-detail-datasets = Datasets
admin-collection-detail-dataset = Dataset
admin-collection-detail-documents = Documents
admin-collection-detail-size = Size
admin-collection-detail-indexed = Indexed
admin-collection-detail-errors = Errors
admin-collection-detail-state = State
admin-collection-detail-created = Created
admin-collection-detail-settings = Settings
admin-collection-detail-the-collection-database-is-not = The collection database is not ready yet.
admin-collection-detail-the-last-storage-provisioning-failed = The last storage provisioning failed: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Processing progress and estimates
admin-collection-detail-display-name = Display name
admin-collection-detail-display-name-2 = display name
admin-collection-detail-save = Save
admin-collection-detail-access = Access
admin-collection-detail-public-every-signed-in-user = Public. Every signed-in user can search and read this collection.
admin-collection-detail-restricted-only-members-of-the = Restricted. Only members of the groups below can search and read this collection.
admin-collection-detail-the-collection-is-now-public = The collection is now public.
admin-collection-detail-the-collection-is-now-restricted = The collection is now restricted.
admin-collection-detail-make-restricted = Make restricted
admin-collection-detail-make-public = Make public
admin-collection-detail-group-permissions = Group permissions
admin-collection-detail-no-group-can-read-this = No group can read this collection yet.
admin-collection-detail-revoke = Revoke
admin-collection-detail-grant-group-u = Grant group…
admin-collection-detail-grant = Grant
admin-collection-detail-danger-zone = Danger zone
admin-collection-detail-a-collection-can-only-be = A collection can only be deleted while it has no datasets.
admin-collection-detail-deleting-the-collection-also-drops = Deleting the collection also drops its database{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}and everything in it. This cannot be undone. Type the collection name to confirm.
admin-collection-detail-collection-name = Collection name
admin-collection-detail-delete-collection = Delete collection
admin-collection-detail-features = Features
admin-collection-detail-vectors = Vectors
admin-collection-detail-this-installation-runs-no-embedding = This installation runs no embedding service, so no collection uses vectors.
admin-collection-detail-vectors-find-passages-by-meaning = Vectors find passages by meaning. Off stops new vectors and stops search from using the stored ones, which stay. On computes the missing vectors of every dataset, one dataset at a time.
admin-collection-detail-this-collection-follows-the-installation = This collection follows the installation, which uses vectors. Vectors find passages by meaning. Off stops new vectors and stops search from using the stored ones, which stay.
admin-collection-processing-could-not-load-this-panel = Could not load this panel: { $message }
admin-collection-processing-admin-processing-of = Admin: processing of { $collection_id }
admin-collection-processing-u-back-to-collection = ← Back to collection
admin-collection-processing-processing-stages = Processing stages
admin-collection-processing-loading-u = Loading…
admin-collection-processing-the-collection-database-is-still = The collection database is still being provisioned.
admin-collection-processing-this-collection-has-no-datasets = This collection has no datasets yet.
admin-collection-processing-eta = ETA { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = No estimate samples yet. They are collected while the dataset is processing.
admin-collection-processing-estimated-completion = Estimated completion:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(in { $humanize_seconds_c_eta_seconds }, a best-effort estimate rather than a scheduling promise)
admin-collection-processing-no-current-estimate-the-pipeline = No current estimate. The pipeline is finished or not making measurable progress.
admin-collection-processing-where-processing-time-goes = Where processing time goes
admin-collection-processing-no-task-executions-recorded-yet = No task executions recorded yet. Every activity the pipeline runs writes one row here, so an empty table means nothing has been processed since the instrumentation was deployed.
admin-collection-processing-summed-task-time = Summed task time
admin-collection-processing-wall-clock = Wall clock
admin-collection-processing-achieved-parallelism = Achieved parallelism
admin-collection-processing-summed-task-time-divided-by = Summed task time divided by wall clock is what the pipeline actually achieved in parallel. Close to 1 means the top task below is the whole cost and worth optimising; close to the worker slot count means the slots are saturated and more workers is the cheaper fix. Wall clock spans the first execution to the last, idle time included.
admin-collection-processing-task = Task
admin-collection-processing-total = Total
admin-collection-processing-share = Share
admin-collection-processing-executions = Executions
admin-collection-processing-mean = Mean
admin-collection-processing-max = Max
admin-collection-processing-failed = Failed
admin-collection-processing-live-activity = Live activity
admin-collection-processing-nothing-running-no-activity-finished = Nothing running. No activity finished in the last { $live_window_seconds } s and no worker reports anything in flight.
admin-collection-processing-in-flight = In flight
admin-collection-processing-average-concurrency = Average concurrency
admin-collection-processing-task-time-in-window = Task time in window
admin-collection-processing-share-of-processing-time-over = Share of processing time over the last { $live_window_seconds } s, refreshed every 5 s. An execution that straddles the window edge counts only for the part inside it. A row with executions in flight but no share is one that started before the window and has not finished. Check its age.
admin-collection-processing-share-of-window = Share of window
admin-collection-processing-task-time = Task time
admin-collection-processing-completed = Completed
admin-collection-processing-oldest-running = Oldest running
admin-collection-processing-temporal-workflows = Temporal workflows
admin-collection-processing-workflows-of-this-collection-s = Workflows of this collection's datasets, child workflows included.
admin-collection-processing-no-workflows-match-this-filter = No workflows match this filter.
admin-collection-processing-workflow = Workflow
admin-collection-processing-type = Type
admin-collection-processing-status = Status
admin-collection-processing-started = Started
admin-collection-processing-closed = Closed
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = open ↗
admin-collection-processing-failed-tasks = Failed tasks
admin-collection-processing-no-task-failures-recorded = No task failures recorded.
admin-collection-processing-dataset = Dataset
admin-collection-processing-errors = Errors
admin-collection-processing-documents = Documents
admin-collection-processing-last-seen = Last seen
admin-collection-processing-sample = Sample
admin-collection-processing-retry = Retry
admin-collection-processing-failures-per-document = Failures per document
admin-collection-processing-no-document-failures-recorded = No document failures recorded.
admin-collection-processing-document = Document
admin-collections-list-admin-collections = Admin: collections
admin-collections-list-collections = Collections
admin-collections-list-loading-collections-u = Loading collections…
admin-collections-list-datasets = Datasets
admin-collections-list-loading-datasets-u = Loading datasets…
admin-collections-list-add-a-collection = Add a collection
admin-collections-list-name-for-example-enron = Name, for example enron
admin-collections-list-display-name = Display name
admin-collections-list-add-collection = Add collection
admin-collections-list-a-name-has-lowercase-letters = A name has lowercase letters, digits and underscores. Capital letters become lowercase,{" "}
admin-collections-list-the-collection-is-saved-as = The collection is saved as: { $new_name }
admin-collections-list-a-collection-with-the-name = A collection with the name { $new_name } exists.
admin-collections-list-collection = Collection
admin-collections-list-documents = Documents
admin-collections-list-size = Size
admin-collections-list-errors = Errors
admin-collections-list-state = State
admin-collections-list-access = Access
admin-collections-list-database-not-ready = Database not ready
admin-collections-list-public = Public
admin-collections-list-1-group = 1 group
admin-collections-list-not-counted-yet = Not counted yet
admin-collections-list-unknown = Unknown
admin-collections-list-no-collection-has-a-dataset = No collection has a dataset.
admin-collections-list-dataset = Dataset
admin-collections-list-indexed = Indexed
admin-collections-list-created = Created
admin-dashboard-admin-dashboard = Admin: dashboard
admin-dashboard-administration = Administration
admin-dashboard-users = Users
admin-dashboard-groups = Groups
admin-dashboard-collections = Collections
admin-dashboard-datasets = Datasets
admin-dashboard-failed-to-load-counts = Failed to load counts: { $e }
admin-dataset-detail-admin-dataset = Admin: dataset { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Failed to load dataset
admin-dataset-detail-loading = Loading...
admin-dataset-detail-metadata = Metadata
admin-dataset-detail-display-name = Display name
admin-dataset-detail-name = Name
admin-dataset-detail-type = Type
admin-dataset-detail-path = Path
admin-dataset-detail-created = Created
admin-dataset-detail-collection = Collection
admin-dataset-detail-save = Save
admin-dataset-detail-statistics = Statistics
admin-dataset-detail-state = State
admin-dataset-detail-documents = Documents
admin-dataset-detail-size = Size
admin-dataset-detail-indexed = Indexed
admin-dataset-detail-errors = Errors
admin-dataset-detail-plans-finished = Plans finished
admin-dataset-detail-disk = Disk
admin-dataset-detail-rescan-disk-reads-the-dataset = Rescan disk reads the dataset folder again, adds new and changed files, and processes them.
admin-dataset-detail-rescan-disk = Rescan disk
admin-dataset-detail-danger-zone = Danger zone
admin-dataset-detail-this-deletes-the-dataset-and = This deletes the dataset and all data extracted from it. You cannot undo it.
admin-dataset-detail-delete-dataset-and-its-data = Delete dataset and its data
admin-dataset-detail-accept-uploads = Accept uploads
admin-dataset-detail-the-folder-of-this-dataset = The folder of this dataset is not in a writable dataset mount, so it receives no uploads.
admin-dataset-detail-starting-u = Starting…
admin-failure-detail-admin-failure = Admin: failure { $op_id }
admin-failure-detail-loading-tree = Loading tree…
admin-failure-detail-back-to-errors-and-failures = Back to errors and failures
admin-failure-detail-operations = Operations
admin-failure-detail-scrubbed-copy-written-to-the = Scrubbed copy written to the clipboard.
admin-failure-detail-this-tree-is-truncated-at = This tree is truncated. At least one capture dropped nodes.
admin-failure-detail-the-captured-tree-has-expired = The captured tree has expired. The operations row is still present.
admin-failure-detail-no-captured-nodes-for-this = No captured nodes for this operation.
admin-failure-detail-operation = Operation
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } root(s) · { $tree_nodes_len } node(s)
admin-failure-detail-open-in-temporal = Open in Temporal
admin-failure-detail-scrubbed-copy = Scrubbed copy
admin-failure-detail-the-scrubbed-copy-replaces-dataset = The scrubbed copy replaces dataset paths with hashes and long values with their lengths.
admin-failure-detail-copy-scrubbed-record = Copy scrubbed record
admin-failure-detail-tree = Tree
admin-failure-detail-root = Root ·{" "}
admin-failure-detail-node-parent-depth-source-stage = node { $node_node_index } · parent { $node_parent_index } · depth { $node_depth } · source { $node_source } · stage { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = workflow { $node_workflow_id } · run { $node_run_id } · activity { $node_activity_id } · attempt { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } node(s) dropped at this capture
admin-failures-admin-errors-and-failures = Admin: errors and failures
admin-failures-errors-failures = Errors/Failures
admin-failures-loading-failures = Loading failures…
admin-failures-operational-failures = Operational failures
admin-failures-no-operational-failures-at-this = No operational failures at this time.
admin-failures-collection = Collection
admin-failures-dataset = Dataset
admin-failures-task-name = Task name
admin-failures-error-class = Error class
admin-failures-operation-kind = Operation kind
admin-failures-from = From
admin-failures-to = To
admin-failures-no-captured-failures-match-these = No captured failures match these filters.
admin-failures-signature = Signature
admin-failures-count = Count
admin-failures-class = Class
admin-failures-task = Task
admin-failures-last-seen = Last seen
admin-failures-newer = Newer
admin-failures-page = Page { $current_page_1 }
admin-failures-older = Older
admin-failures-per-page = Per page
admin-failures-loading-instances = Loading instances…
admin-failures-no-instances-for-this-signature = No instances for this signature.
admin-failures-node = {" "}node { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Document errors
admin-failures-error-text = Error text
admin-failures-loading-document-errors-u = Loading document errors…
admin-failures-no-document-errors-match-these = No document errors match these filters.
admin-failures-errors-by-dataset-and-task = Errors by dataset and task
admin-failures-documents = Documents
admin-failures-show-only-this-dataset-and = Show only this dataset and task
admin-failures-total = Total
admin-failures-errors = Errors
admin-failures-document = Document
admin-failures-runs = Runs
admin-failures-error = Error
admin-failures-dataset-step = Dataset step
admin-failures-previous-page = Previous page
admin-failures-page-of-1-error = Page { $page } of { $pages }, 1 error
admin-failures-page-of-errors = Page { $page } of { $pages }, { $data_total } errors
admin-failures-next-page = Next page
admin-feedback-admin-feedback = Admin: feedback
admin-feedback-feedback = Feedback
admin-feedback-search-titles-descriptions-accounts-and = Search titles, descriptions, accounts and addresses
admin-feedback-search = Search
admin-feedback-loading-reports-u = Loading reports…
admin-feedback-1-report-matches = 1 report matches.
admin-feedback-reports-match = { $data_total } reports match.
admin-feedback-received = Received
admin-feedback-type = Type
admin-feedback-title = Title
admin-feedback-from = From
admin-feedback-captures = Captures
admin-feedback-state = State
admin-feedback-previous-page = Previous page
admin-feedback-page-of = Page { $page } of { $pages }
admin-feedback-next-page = Next page
admin-feedback-image = Image { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Read
admin-feedback-unread = Unread
admin-feedback-archived = Archived
admin-feedback-mark-unread = Mark unread
admin-feedback-mark-read = Mark read
admin-feedback-restore = Restore
admin-feedback-archive = Archive
admin-feedback-page = Page:{" "}
admin-feedback-the-report-has-no-description = The report has no description.
admin-feedback-open-the-page-image = Open the page image
admin-feedback-open-the-dom-copy = Open the DOM copy
admin-feedback-page-image-of-the-report = Page image of the report
admin-feedback-debug-context-and-browser-log = Debug context and browser log
admin-feedback-loading-u = Loading…
admin-group-detail-admin-group = Admin: group { $groupname }
admin-group-detail-failed-to-load-group = Failed to load group
admin-group-detail-loading = Loading...
admin-group-detail-group = Group
admin-group-detail-display-name = Display name
admin-group-detail-display-name-2 = display name
admin-group-detail-save = Save
admin-group-detail-members = Members
admin-group-detail-saving-membership = Saving membership...
admin-group-detail-username = Username
admin-group-detail-origin = Origin
admin-group-detail-group-admin = Group admin
admin-group-detail-uploader = Uploader
admin-group-detail-remove = Remove
admin-group-detail-username-to-add = username to add
admin-group-detail-add-member = Add member
admin-group-detail-collection-access = Collection access
admin-group-detail-this-group-has-no-collection = This group has no collection permissions.
admin-group-detail-revoke = Revoke
admin-group-detail-grant-collection-u = Grant collection…
admin-group-detail-grant = Grant
admin-group-detail-danger-zone = Danger zone
admin-group-detail-delete-group = Delete group
admin-groups-list-admin-groups = Admin: groups
admin-groups-list-groups = Groups
admin-groups-list-add-group = Add group
admin-groups-list-display-name = display name
admin-groups-list-use-lowercase-letters-digits-underscores = Use lowercase letters, digits, underscores and hyphens in the name. The name cannot change later.
admin-groups-list-add-group-2 = Add group +
admin-groups-list-group = Group
admin-groups-list-display-name-2 = Display name
admin-groups-list-members = Members
admin-groups-list-collections = Collections
admin-groups-list-loading = Loading...
admin-llm-config-admin-llm = Admin: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Loading…
admin-llm-config-no-llm-provider-is-configured = No LLM provider is configured. Set LLM_BASE_URL / LLM_MODEL in hoover4.ini and redeploy.
admin-llm-config-providers = Providers
admin-llm-config-the-refresh-runs-in-the = The refresh runs in the background. The current list stays visible meanwhile.
admin-llm-config-refresh-in-flight-u = {" "}Refresh in flight…
admin-llm-config-provider = Provider
admin-llm-config-models = Models
admin-llm-config-freshest = Freshest
admin-llm-config-status = Status
admin-llm-config-refresh-catalog = Refresh catalog
admin-llm-config-agent-turns-board-assessments-and = Agent turns, board assessments and report conversions
admin-llm-config-titles-summaries-and-board-labels = Titles, summaries and board labels
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini sets these models: quality_model of the LLM provider for agent turns, board assessments and report conversions when it is set, and its model for the rest.
admin-llm-config-thinking = Thinking
admin-llm-config-the-model-reasons-before-each = The model reasons before each tool call and each answer.
admin-llm-config-catalog = Catalog
admin-llm-config-filter-models-u = Filter models…
admin-llm-config-model = Model
admin-llm-config-flags = Flags
admin-llm-config-calls-14d = Calls 14d
admin-llm-config-ai-status = AI status
admin-llm-config-shows-the-serving-health = {" "}shows the serving health.
admin-llm-reports-reports = Reports
admin-llm-reports-each-report-runs-when-you = Each report runs when you select its button.
admin-llm-reports-running-u = Running…
admin-llm-reports-run-report = Run report
admin-llm-reports-read-at = Read at { $read_at }
admin-llm-reports-errors = Errors
admin-llm-reports-failed-attempts-by-step-and = Failed attempts by step and error class, and agent runs that failed or ended early by their end reason.
admin-llm-reports-source = Source
admin-llm-reports-class = Class
admin-llm-reports-no-errors-in-30-days = No errors in 30 days.
admin-llm-reports-recent-errors = Recent errors
admin-llm-reports-the-newest-100-failed-attempts = The newest 100 failed attempts of 7 days. Open a row to read its error.
admin-llm-reports-time = Time
admin-llm-reports-user = User
admin-llm-reports-name = Name
admin-llm-reports-error = Error
admin-llm-reports-no-errors-in-7-days = No errors in 7 days.
admin-llm-reports-show = Show
admin-llm-reports-tool-calls = Tool calls
admin-llm-reports-one-row-for-each-tool = One row for each tool, by calls in 30 days. An error is a failed call.
admin-llm-reports-tool = Tool
admin-llm-reports-calls-24-h = Calls 24 h
admin-llm-reports-error-24-h = Error % 24 h
admin-llm-reports-avg-ms-24-h = Avg ms 24 h
admin-llm-reports-calls-7-d = Calls 7 d
admin-llm-reports-error-7-d = Error % 7 d
admin-llm-reports-avg-ms-7-d = Avg ms 7 d
admin-llm-reports-calls-30-d = Calls 30 d
admin-llm-reports-error-30-d = Error % 30 d
admin-llm-reports-avg-ms-30-d = Avg ms 30 d
admin-llm-reports-no-tool-calls-in-30 = No tool calls in 30 days.
admin-llm-reports-top-users = Top users
admin-llm-reports-the-30-users-with-the = The 30 users with the most model time in the window.
admin-llm-reports-30-days = 30 days
admin-llm-reports-7-days = 7 days
admin-llm-reports-24-hours = 24 hours
admin-llm-reports-tool-time = Tool time
admin-llm-reports-model-calls = Model calls
admin-llm-reports-model-time = Model time
admin-llm-reports-tokens-in = Tokens in
admin-llm-reports-tokens-out = Tokens out
admin-llm-reports-no-agent-use-in-the = No agent use in the window.
admin-llm-reports-system-one-checks = System one checks
admin-llm-reports-requests-are-grouped-by-hook = Requests are grouped by hook and rule. Latencies are in milliseconds. Shares use requests from the last 30 days.
admin-llm-reports-counts = Counts
admin-llm-reports-recent-failures = Recent failures
admin-llm-reports-select-run-report-to-read = Select Run report to read the statistics.
admin-llm-reports-hook = Hook
admin-llm-reports-rule = Rule
admin-llm-reports-outcome = Outcome
admin-llm-reports-questions = Questions
admin-llm-reports-median-ms = Median ms
admin-llm-reports-95th-percentile-ms = 95th percentile ms
admin-llm-reports-error-2 = Error %
admin-llm-reports-positive = Positive %
admin-llm-reports-actions = Actions
admin-metrics-admin-metrics = Admin: metrics
admin-metrics-metrics = Metrics
admin-metrics-the-last-24-hours = The last 24 hours.
admin-metrics-loading-u = Loading…
admin-metrics-manticore-load-now = Manticore load (now)
admin-metrics-ram-is-the-memory-of = RAM is the memory of the tables. Thread load is for the last 1, 5 and 15 minutes.
admin-metrics-manticore-status-could-not-be = Manticore status could not be read: { $error }
admin-metrics-thread-load-1-5-15 = Thread load (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Primary thread load (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Secondary thread load (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Worker threads busy / total
admin-metrics-work-queue = Work queue
admin-metrics-ram-held-by-tables = RAM held by tables
admin-metrics-disk-used-by-tables = Disk used by tables
admin-metrics-tables-merging = Tables merging
admin-metrics-tables-read = Tables read
admin-metrics-read-at = Read at
admin-metrics-largest-tables-by-ram = Largest tables by RAM
admin-metrics-table = Table
admin-metrics-ram = RAM
admin-metrics-disk = Disk
admin-metrics-disk-chunks = Disk chunks
admin-metrics-merging = Merging
admin-metrics-usage-last-24-h = Usage (last 24 h)
admin-metrics-events-by-type = Events by type
admin-metrics-event = Event
admin-metrics-count = Count
admin-metrics-events-per-hour = Events per hour
admin-metrics-no-events-recorded-yet = No events recorded yet.
admin-metrics-busiest-users = Busiest users
admin-metrics-user = User
admin-metrics-events = Events
admin-metrics-events-2 = { $point_bucket }: { $point_count } events
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API calls (last 24 h)
admin-metrics-no-api-calls-recorded-yet = No API calls recorded yet.
admin-metrics-function = Function
admin-metrics-calls = Calls
admin-metrics-errors = Errors
admin-metrics-error-rate = Error rate
admin-metrics-bytes-in = Bytes in
admin-metrics-bytes-out = Bytes out
admin-operation-detail-admin-operation = Admin: operation { $op_id }
admin-operation-detail-loading-operation = Loading operation…
admin-operation-detail-back-to-operations = Back to operations
admin-operation-detail-operation = Operation
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · queued at { $row_started_at }
admin-operation-detail-not-started = not started
admin-operation-detail-re-run-counts-are-not = Re-run counts are not available.
admin-operation-detail-failed-document-s-task-failure = { $documents } failed document(s), { $row_failed_tasks_unwrap_or_0 } task failure(s)
admin-operation-detail-failures-were-not-counted = Failures were not counted.
admin-operation-detail-open-captured-failure-tree = Open captured Failure tree
admin-operation-detail-open-in-temporal = Open in Temporal
admin-operation-detail-plans = Plans
admin-operation-detail-plan-s-page = { $data_plans_total } plan(s), page { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = No plans were recorded for this operation.
admin-operation-detail-dataset = Dataset
admin-operation-detail-plan-hash = Plan hash
admin-operation-detail-source = Source
admin-operation-detail-finished = Finished
admin-operation-detail-previous = Previous
admin-operation-detail-next = Next
admin-operation-detail-error-events = Error events
admin-operation-detail-error-event-s-page = { $data_events_total } Error event(s), page { $page_1 }
admin-operation-detail-no-error-events-were-recorded = No Error events were recorded for this operation.
admin-operation-detail-time = Time
admin-operation-detail-hash = Hash
admin-operation-detail-task = Task
admin-operation-detail-event = Event
admin-operation-detail-error-excerpt = Error excerpt
admin-operations-admin-operations = Admin: operations
admin-operations-operations = Operations
admin-operations-loading-operations = Loading operations…
admin-operations-filters = Filters
admin-operations-state = State
admin-operations-any-state = Any state
admin-operations-collection = Collection
admin-operations-all-collections = All collections
admin-operations-choose-a-collection-to-see = Choose a collection to see its per-task error rates.
admin-operations-operations-newest-first = Operations, newest first
admin-operations-newer = Newer
admin-operations-page = Page { $current_page_1 }
admin-operations-older = Older
admin-operations-failure-rate-by-task-type = Failure rate by task type ({ $collectionname })
admin-operations-one-row-per-activity-execution = One row per activity execution, retries included. A rate over{" "}
admin-operations-is-marked = {" "}is marked.
admin-operations-no-task-executions-recorded-for = No task executions recorded for this collection yet.
admin-operations-task = Task
admin-operations-error-rate = Error rate
admin-operations-failed-total-executions = Failed / total executions
admin-operations-documents-affected = Documents affected
admin-operations-above-the-line = above the line
admin-operations-no-operations-recorded-for-this = No operations recorded for this filter.
admin-operations-kind = Kind
admin-operations-target = Target
admin-operations-workflow = Workflow
admin-operations-queued-at = Queued at
admin-operations-started = Started
admin-operations-duration = Duration
admin-operations-progress = Progress
admin-operations-eta = ETA
admin-operations-outcome = Outcome
admin-operations-destructive = Destructive
admin-operations-repeated-run = Repeated run
admin-operations-no-estimate-yet = no estimate yet
admin-operations-cancel = Cancel
admin-operations-type-to-confirm = type { $target } to confirm
admin-operations-re-run = Re-run
admin-operations-waiting-for-a-free-slot = waiting for a free slot or a free target
admin-operations-counting-work = counting work…
admin-operations-open-captured-tree = Open captured tree
admin-operations-no-captured-tree = no captured tree
admin-operations-no-failed-documents = no failed documents
admin-operations-document-s-failed = { $n } document(s) failed
admin-operations-task-failure-s = { $t } task failure(s)
admin-operations-failures-not-counted = failures not counted
admin-operations-the-newest-ten-operations-of = The newest ten operations of this collection.{" "}
admin-operations-all-operations = All operations
admin-settings-admin-settings = Admin: settings
admin-settings-server-settings = Server settings
admin-settings-key = Key
admin-settings-value = Value
admin-settings-description = Description
admin-settings-save = Save
admin-settings-loading = Loading...
admin-settings-deployment-configuration-read-only = Deployment configuration (read-only)
admin-settings-not-set = (not set)
admin-user-detail-admin-user = Admin: user { $username }
admin-user-detail-failed-to-load-user = Failed to load user
admin-user-detail-loading = Loading...
admin-user-detail-user = User
admin-user-detail-the-next-login-replaces-the = The next login replaces the full name, email and superuser status of a user from the login proxy.
admin-user-detail-llm-usage-u = LLM usage →
admin-user-detail-full-name = Full name
admin-user-detail-full-name-2 = full name
admin-user-detail-email = Email
admin-user-detail-superuser = Superuser
admin-user-detail-save = Save
admin-user-detail-groups = Groups
admin-user-detail-saving-membership = Saving membership...
admin-user-detail-group = Group
admin-user-detail-origin = Origin
admin-user-detail-group-admin = Group admin
admin-user-detail-uploader = Uploader
admin-user-detail-remove = Remove
admin-user-detail-add-to-group-u = Add to group…
admin-user-detail-add = Add
admin-user-detail-danger-zone = Danger zone
admin-user-detail-delete-user = Delete user
admin-user-llm-admin-llm-use-by = Admin: LLM use by { $username }
admin-user-llm-u-back-to-user = ← Back to user
admin-user-llm-loading-u = Loading…
admin-user-llm-totals-all-time = Totals (all time)
admin-user-llm-chat-sessions = Chat sessions
admin-user-llm-messages = Messages
admin-user-llm-tool-calls = Tool calls
admin-user-llm-model-and-tool-time = Model and tool time
admin-user-llm-model-and-tool-time-of = model and tool time of this user's agent steps. Parallel tool calls count in full
admin-user-llm-rate-limit-usage-current-windows = Rate-limit usage (current windows)
admin-user-llm-in-process-counters-of-the = In-process counters of the running website container. Chat limit { $metrics_chat_per_minute }/min, API limit { $metrics_api_per_minute }/min, with a decaying sustained rate over the longer windows.
admin-user-llm-chat-messages = Chat messages
admin-user-llm-api-calls = API calls
admin-user-llm-window = Window
admin-user-llm-used = Used
admin-user-llm-budget = Budget
admin-user-llm-no-chat-sessions = No chat sessions.
admin-user-llm-title = Title
admin-user-llm-created = Created
admin-users-list-admin-users = Admin: users
admin-users-list-users = Users
admin-users-list-search-users = Search users
admin-users-list-username = Username
admin-users-list-full-name = Full name
admin-users-list-email-address = Email address
admin-users-list-superuser = Superuser
admin-users-list-groups = Groups
admin-users-list-created = Created
admin-users-list-last-login = Last login
admin-users-list-loading = Loading...
dataset-create-panel-put-the-documents-in-a = Put the documents in a folder there and reload this page.
dataset-create-panel-the-name-cannot-start-with = The name cannot start with a full stop or contain a slash.
dataset-create-panel-and-a-dash-a-space = and a dash, a space or a full stop becomes an underscore. The name cannot change later.
dataset-create-panel-the-form-starts-with-the = The form starts with the collection defaults. A dataset created with the defaults follows later changes of them,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Apply saves the languages, and the OCR update of this dataset then starts by itself.
dataset-ocr-panel-the-list-comes-from-the = The list comes from the running image, not from configuration.
live-chats-panel-off = off
processing-updates-panel-the-waiting-steps-change-each = The waiting steps change { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), each file counted once, in { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = and a dash, a space or a full stop becomes an underscore. The name cannot change later.
admin-llm-config-fresh = fresh
admin-llm-config-tools = tools{" "}
admin-llm-config-vision = vision{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-and-a-dataset-created-with = and a dataset created with other values keeps its own. A change on the dataset page runs OCR again.
dataset-create-panel-read-only = { $option_name } (read-only)
live-chats-panel-on = on
processing-updates-panel-up-to-date-select-it = Up to date. Select it to run it again.
admin-ai-status-yes = yes
admin-ai-status-no-2 = no
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } errors
admin-collection-processing-done = done
admin-collection-processing-failed-2 = { $stage_failed_documents } failed
admin-collection-processing-left = left
admin-collection-processing-dataset-level = dataset-level
admin-collections-list-groups = { $c_group_count } groups
admin-failures-operation-s = { $group_operation_count } operation(s)
admin-groups-list-groupname = groupname
admin-llm-config-stale = stale
admin-llm-config-thinking-is-on = Thinking is on
admin-llm-config-thinking-is-off = Thinking is off
admin-llm-config-shown = { $models_len } shown
admin-llm-config-reasoning = reasoning
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } of { $load_table_count }
admin-metrics-yes = yes
admin-metrics-no = no
admin-metrics-max = max
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = started { $run_started_at }
admin-operation-detail-yes = yes
admin-operation-detail-no = no
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = email
admin-user-llm-untitled = (untitled)
admin-dataset-ocr-panel-models-not-in-image = The models of { $languages } are not in the image. The service downloads them on first use, which needs internet access.
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } pages
admin-processing-updates-panel-prerequisites-waiting = The collection needs an update first: { $steps }. Steps that write to the search index wait for it.
admin-operations-no-task-type-failing = No task type is failing above { $threshold }%.
admin-operations-task-types-failing = { $count } task type(s) failing above { $threshold }%.
processing-updates-panel-collection-updates = Collection updates
admin-collections-list-some-datasets-are-not-counted = Some datasets are not counted yet.
admin-failures-hide = Hide
admin-failures-show = Show
admin-settings-web-session-lifetime-in-seconds = Web session lifetime in seconds (default: 604800 = 1 week)
admin-settings-turns-every-new-chat-turn = Turns every new chat turn off when false (default: true). An in-flight turn finishes. Takes effect on the next send, with no redeploy.
admin-settings-written-by-main-py-probe = Written by `main.py probe-embeddings`, and it is what the endpoint ACTUALLY serves. Editing this by hand does not change the server.
admin-settings-the-folder-whose-subfolders-the = The folder whose subfolders the dataset form lists. Changing it needs a redeploy.
admin-settings-from-hoover4-ini-changing-it = From hoover4.ini. Changing it needs a redeploy.
admin-feedback-bug = Bug
admin-operations-state-name = { $state ->
        [pending] pending
        [queued] queued
        [running] running
        [finished] finished
        [errored] errored
        [cancelled] cancelled
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Failure tree of { $op_id }
admin-failure-detail-showing-of-characters = showing { $node_stack_trace_chars_count } of { $node_stack_trace_original_len } characters
admin-operations-operation = Operation { $state }.
admin-operations-dispatched = Dispatched { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } rows
admin-operations-plans = { $row_progress_done } / { $row_progress_total } plans
admin-group-detail-group-2 = Group { $groupname }
admin-settings-the-setting-was-saved-successfully = The setting “{ $k }” was saved successfully.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = The group “{ $g }” was added successfully.
admin-user-detail-user-2 = User { $username }
admin-dataset-detail-dataset = Dataset { $dataset_id }
admin-dataset-detail-collections = Collections › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } of { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = The upload setting could not be read: { $err }
admin-dataset-detail-operation-started = Operation started: { $run_id }
admin-collection-detail-collection = Collection { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = The vectors setting could not be read: { $err }
admin-collection-processing-processing-of = Processing of { $collection_id }
admin-collection-processing-collections = Collections › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } executions
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = as of { $at }
admin-collection-processing-over-the-last-s = over the last { $live_window_seconds } s
admin-collection-processing-retry-started-run = Retry started (run { $run }).
admin-collection-processing-document-retry-started-run = Document retry started (run { $run }).
admin-operation-detail-operation-2 = Operation { $op_id }
admin-user-llm-llm-usage-of = LLM usage of { $username }
admin-user-llm-users = Users › { $username }
processing-updates-panel-the-processing-updates-could-not = The processing updates could not be read: { $e }
processing-updates-panel-update-started = Update started: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } of { $operation_progress_total } plans
dataset-ocr-panel-adding = adding { $added }
dataset-ocr-panel-removing = removing { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } plan(s) reopened
dataset-create-panel-saved-as-this-collection-s-2 = Saved as this collection's defaults. These datasets inherit them, and their OCR updates start one at a time: { $changed_join }. Datasets with their own languages keep them.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] folder
       *[other] folders
    }
    [tables] { $count ->
        [one] table
       *[other] tables
    }
   *[files] { $count ->
        [one] file
       *[other] files
    }
}
processing-updates-step-runs = { $count ->
    [one] step run
   *[other] step runs
}
processing-update-search_schema-title = Search index schema
processing-update-search_schema-explanation = { $files ->
    [one] { $count } search table of the collection misses a column that the search index needs.
   *[other] { $count } search tables of the collection miss a column that the search index needs.
} The column is added to each table. Search keeps working.
processing-update-search_schema-runs = Search index tables
processing-update-unfinished-title = Unfinished processing
processing-update-unfinished-explanation = { $files ->
    [one] { $count } file is not processed to the end.
   *[other] { $count } files are not processed to the end.
} This includes files without a processing plan, for example after an interrupted ingestion. Their processing completes.
processing-update-unfinished-runs = All processing stages for these files
processing-update-failed_files-title = Failed files
processing-update-failed_files-explanation = { $files ->
    [one] { $count } file has a processing error.
   *[other] { $count } files have a processing error.
} The failed stages run again for them. The automatic run retries a file once for each new version of the stage that failed.
processing-update-failed_files-runs = The failed stages, then entity extraction, embedding and indexing
processing-update-virus_scan-title = Virus scan
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } file has no antivirus verdict.
   *[other] { $count } files have no antivirus verdict.
} They are scanned. A file that the scanner finds infected is marked in search, and its original and searchable PDF downloads are refused.
processing-update-virus_scan-runs = Antivirus scan, then the search attribute of infected files
processing-update-tables-title = Tables
processing-update-tables-explanation = { $files ->
    [one] { $count } file has an earlier table reading or incomplete dependent output. Its stored results are updated.
    *[other] { $count } files have earlier table readings or incomplete dependent output. Update their stored results.
    }

processing-update-tables-runs = Table reading, entities, signals, embedding, and both indexes
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Files needing automatic OCR: { $count }. Detected pages select installed models. Complete replacement output removes superseded variants.
processing-update-ocr-runs = OCR and searchable PDFs, then entity extraction, embedding and indexing of the new text
processing-update-ocr_detection-title = OCR detection
processing-update-ocr_detection-explanation = Files without current text, script, or language detection: { $count }. Every eligible image and PDF page is examined in bounded batches.
processing-update-ocr_detection-runs = Detection, then the search attributes of these files
processing-update-pdf_text-title = Searchable PDF text
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } file has searchable PDFs with an earlier text layer.
   *[other] { $count } files have searchable PDFs with an earlier text layer.
} That layer copied each letter outside the Western European alphabets as a black square. PDFs of languages with only Western European letters are kept. The other PDFs are read, and the parts with black squares are built again. An image PDF uses the stored OCR words. A PDF page gets a new OCR request.
processing-update-pdf_text-runs = Searchable PDF parts, then OCR text indexing of the rebuilt PDFs
processing-update-vectors-title = Vectors
processing-update-vectors-explanation = { $files ->
    [one] { $count } file with text has no vectors of the embedding model that the installation serves.
   *[other] { $count } files with text have no vectors of the embedding model that the installation serves.
} Their vectors are computed and indexed.
processing-update-vectors-runs = Embedding and vector indexing
processing-update-folder_counts-title = Folder counts
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } folder has no file count or size, or has values of an earlier version.
   *[other] { $count } folders have no file count or size, or have values of an earlier version.
} The counts are calculated again.
processing-update-folder_counts-runs = Folder tree
admin-uploads-badge = Uploads
admin-uploads-badge-title = Accepts uploads

processing-update-archive_members-title = Archive members

processing-update-archive_members-explanation = { $files ->
    [one] { $count } split archive needs a current member list. Its members and search output are updated.
    *[other] { $count } split archives need current member lists. Update their members and search output.
    }

processing-update-archive_members-runs = Archive extraction, member reconciliation, and dependent processing

processing-update-image_previews-title = Image previews

processing-update-image_previews-explanation = { $files ->
    [one] { $count } uncommon image has no preview. Its preview is created again.
    *[other] { $count } uncommon images have no preview. Create their previews again.
    }

processing-update-image_previews-runs = Image preview creation and verification

processing-update-search_terms-title = Search terms

processing-update-search_terms-explanation = { $files ->
    [one] { $count } search table needs current filter terms. Language, OCR, script, and red flag terms become searchable.
    *[other] Search tables that need current filter terms: { $count }. Language, OCR, script, and red flag terms become searchable.
    }

processing-update-search_terms-runs = Filter term indexing and verification

automatic-ocr-title = Automatic OCR
automatic-ocr-refresh = Refresh status
automatic-ocr-coverage = Page coverage
automatic-ocr-pages = Pages
automatic-ocr-models = OCR models
automatic-ocr-reason = Reason
automatic-ocr-truncated = The diagnostic list is incomplete.
automatic-ocr-presence = Has published OCR text
automatic-ocr-policy = OCR selects installed models from each eligible page’s detected script and language. Tesseract runs first, with EasyOCR for scripts it cannot cover.
automatic-ocr-unknown = No current publication is recorded. Missing detection and failed processing do not establish absence.
automatic-ocr-retry = Use processing updates to retry incomplete or failed work after its cause is corrected. Unsupported coverage requires compatible installed models.
automatic-ocr-state = { $state ->
    [candidate] Pending
    [planned] Planned
    [failed] Failed
    [incomplete] Incomplete
    [unsupported] Unsupported
    [published] Published
    [applied] Verified
    [ready] Detected text
    [no_text] No detected text
    *[other] { $state }
    }


processing-update-entities-title = Named entities
processing-update-entities-explanation = Files needing current entity extraction or searchable output: { $count }. Earlier successful results are replaced after inference completes.
processing-update-entities-runs = Named entity extraction, text attributes, and searchable entity terms

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Script not identified
    [tesseract_capabilities_unavailable] Tesseract coverage unavailable
    [detected_language] Model matches detected language
    [unknown_language_script_coverage] Unknown language. A script model is selected.
    [language_script_mismatch_script_coverage] Language and script differ. A script model is selected.
    [language_model_unavailable_script_coverage] Language model unavailable. A script model is selected.
    [easyocr_capabilities_unavailable] EasyOCR coverage unavailable
    [tesseract_script_unavailable] Tesseract lacks script coverage. EasyOCR is selected.
    [script_coverage_unavailable] No installed model covers this script.
    *[other] { $reason }
    }

processing-updates-check-requested = The pipeline is calculating the updates. Counts change when calculation finishes.
