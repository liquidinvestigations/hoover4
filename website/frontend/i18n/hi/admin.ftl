# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = प्रशासन की पहुँच आवश्यक है
admin-guard-signed-in-as = { $u_username } के रूप में साइन इन हैं।
admin-guard-ask-an-administrator-for-access = इस अनुभाग की पहुँच के लिए किसी प्रशासक से कहें।
admin-shell-dashboard = डैशबोर्ड
admin-shell-collections = संग्रह
admin-shell-operations = ऑपरेशन
admin-shell-errors-failures = त्रुटियाँ/विफलताएँ
admin-shell-feedback = फ़ीडबैक
admin-shell-users = उपयोगकर्ता
admin-shell-groups = समूह
admin-shell-settings = सेटिंग
admin-shell-llm = LLM
admin-shell-ai-status = AI स्थिति
admin-shell-metrics = मेट्रिक्स
admin-shell-administration = प्रशासन
dataset-create-panel-add-a-dataset = डेटासेट जोड़ें
dataset-create-panel-the-dataset-mounts-could-not = डेटासेट माउंट पढ़े नहीं जा सके, इसलिए चुनने के लिए कुछ नहीं है: { $err }
dataset-create-panel-loading-the-dataset-mounts = डेटासेट माउंट लोड हो रहे हैं।
dataset-create-panel-no-dataset-mount-is-configured = कोई डेटासेट माउंट कॉन्फ़िगर नहीं है।
dataset-create-panel-the-mount-folder-could-not = माउंट फ़ोल्डर पढ़ा नहीं जा सका, इसलिए चुनने के लिए कुछ नहीं है: { $err }
dataset-create-panel-no-subfolders-were-found-in = इस माउंट में कोई सबफ़ोल्डर नहीं मिला।{" "}
dataset-create-panel-folder = फ़ोल्डर
dataset-create-panel-select-a-folder = फ़ोल्डर चुनें
dataset-create-panel-new-folder = नया फ़ोल्डर
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } प्रविष्टियाँ), पहले से डेटासेट है
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } प्रविष्टियाँ)
dataset-create-panel-the-server-creates-this-folder = डेटासेट बनाने पर सर्वर यह फ़ोल्डर माउंट में बनाता है।{" "}
dataset-create-panel-the-list-shows-the-direct = सूची में माउंट के सीधे सबफ़ोल्डर दिखते हैं।
dataset-create-panel-dataset-name = डेटासेट का नाम
dataset-create-panel-a-name-has-lowercase-letters = नाम में छोटे अक्षर, अंक और अंडरस्कोर होते हैं। बड़े अक्षर छोटे हो जाते हैं,{" "}
dataset-create-panel-the-dataset-is-saved-as = डेटासेट इस नाम से सहेजा जाता है: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = इस संग्रह में { $saved_name } नाम का डेटासेट पहले से है।
dataset-create-panel-accept-uploads = अपलोड स्वीकार करें
dataset-create-panel-creating-u = बनाया जा रहा है…
dataset-create-panel-create-and-ingest = बनाएँ और इन्जेस्ट करें
dataset-create-panel-mount = माउंट
dataset-ocr-panel-last-operation = अंतिम ऑपरेशन: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , शुरू हुआ { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = { $current_stale_seconds_60 } मिनट से कोई प्रगति नहीं। Temporal वर्कफ़्लो जाँचें, और ऑपरेशन अटका हो तो उसे रद्द करें।
dataset-ocr-panel-loading-u = लोड हो रहा है…
dataset-ocr-panel-stored-text-variants = संग्रहीत टेक्स्ट रूपांतर
dataset-ocr-panel-searchable-pdfs = खोजने योग्य PDF
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } फ़ाइलें · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = चालू LLM चैट
live-chats-panel-agent-turns-running-right-now = अभी चल रहे एजेंट टर्न, सबसे लंबे समय से चल रहे पहले। हर 2 सेकंड में रीफ़्रेश होता है। यह Temporal से पढ़ा जाता है, इसलिए वेबसाइट के पिछले रीस्टार्ट से पहले शुरू हुआ टर्न भी यहाँ है।
live-chats-panel-loading-u = लोड हो रहा है…
live-chats-panel-no-chats-running = कोई चैट नहीं चल रही।
live-chats-panel-user = उपयोगकर्ता
live-chats-panel-conversation = बातचीत
live-chats-panel-question = प्रश्न
live-chats-panel-internet = इंटरनेट
live-chats-panel-running = चल रहा है
live-chats-panel-started = शुरू हुआ
live-chats-panel-cancels-the-workflow-the-turn = वर्कफ़्लो रद्द करता है। टर्न गायब होने के बजाय ट्रांसक्रिप्ट में रोके जाने के चिह्न के साथ समाप्त होता है।
live-chats-panel-kill = समाप्त करें
processing-updates-panel-loading-u = लोड हो रहा है…
processing-updates-panel-open-the-operation = ऑपरेशन खोलें
processing-updates-panel-the-pipeline-has-not-calculated = पाइपलाइन ने अभी इन अपडेट की गणना नहीं की है।
processing-updates-panel-calculated-at-in-ms = { $view_checked_at } को { $view_check_ms } ms में गणना की गई।{" "}
processing-updates-panel-automatic-updates-are-off-on = इस इंस्टॉलेशन में स्वचालित अपडेट बंद हैं। अपडेट बटन से शुरू करें।
processing-updates-panel-step = चरण
processing-updates-panel-count = संख्या
processing-updates-panel-state = स्थिति
processing-updates-panel-last-run = अंतिम रन
processing-updates-panel-runs = रन: { $step_runs }
processing-updates-panel-a-run-again-would-select = दोबारा चलाने पर लगभग इतने { $step_unit } चुने जाएँगे।
processing-updates-panel-on-a-run-again = दोबारा चलाने पर { $step_pending } { $unit }
processing-updates-panel-never = कभी नहीं
processing-updates-panel-update-collection = संग्रह अपडेट करें
processing-updates-panel-update-processing = प्रोसेसिंग अपडेट करें
processing-updates-panel-check-again = फिर जाँचें
processing-updates-panel-dataset = डेटासेट
processing-updates-panel-processing-updates = प्रोसेसिंग अपडेट
admin-ai-status-admin-ai-status = प्रशासन: AI स्थिति
admin-ai-status-ai-status = AI स्थिति
admin-ai-status-the-configured-service-and-the = कॉन्फ़िगर की गई सेवा और वह सेवा जो वास्तव में उत्तर देती है। CPU सेवा पर फ़ॉलबैक केवल यहीं दिखता है।
admin-ai-status-loading-u = लोड हो रहा है…
admin-ai-status-config-fingerprint = कॉन्फ़िग फ़िंगरप्रिंट
admin-ai-status-website-worker = वेबसाइट / वर्कर
admin-ai-status-ai-server = AI सर्वर
admin-ai-status-match = मेल
admin-ai-status-embeddings-probe = एम्बेडिंग जाँच
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } आयाम
admin-ai-status-llm-configured = LLM कॉन्फ़िगर है
admin-ai-status-capabilities = क्षमताएँ
admin-ai-status-capability = क्षमता
admin-ai-status-configured = कॉन्फ़िगर
admin-ai-status-serving = सेवा में
admin-ai-status-model = मॉडल
admin-ai-status-reachable = पहुँच योग्य
admin-ai-status-detail = विवरण
admin-ai-status-no = नहीं
admin-ai-status-vector-shard-dims-vs-probe = वेक्टर शार्ड के आयाम बनाम जाँच
admin-ai-status-no-collections-yet = अभी तक कोई संग्रह नहीं।
admin-ai-status-collection = संग्रह
admin-ai-status-shard = शार्ड
admin-ai-status-matches-probe = जाँच से मेल खाता है
admin-ai-status-browser-router = ब्राउज़र राउटर
admin-ai-status-live-sessions = चालू सत्र: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = हाल का LLM ट्रैफ़िक (24 घंटे)
admin-ai-status-no-llm-call-events-yet = अभी तक कोई llm_call_events नहीं।
admin-ai-status-user = उपयोगकर्ता
admin-ai-status-calls = कॉल
admin-ai-status-errors = त्रुटियाँ
admin-ai-status-service-use-24-h = सेवा उपयोग % (24 घंटे)
admin-ai-status-busy-seconds-in-the-last = पिछले 24 घंटों के व्यस्त सेकंड, दिन के अनुपात में।
admin-ai-status-no-samples-yet = अभी तक कोई नमूना नहीं।
admin-ai-status-service = सेवा
admin-ai-status-busy-s = व्यस्त सेकंड
admin-ai-status-use = उपयोग %
admin-collection-detail-admin-collection = प्रशासन: संग्रह { $collection_id }
admin-collection-detail-failed-to-load-collection = संग्रह लोड नहीं हो सका
admin-collection-detail-loading = लोड हो रहा है...
admin-collection-detail-datasets = डेटासेट
admin-collection-detail-dataset = डेटासेट
admin-collection-detail-documents = दस्तावेज़
admin-collection-detail-size = आकार
admin-collection-detail-indexed = इंडेक्स किए गए
admin-collection-detail-errors = त्रुटियाँ
admin-collection-detail-state = स्थिति
admin-collection-detail-created = बनाया गया
admin-collection-detail-settings = सेटिंग
admin-collection-detail-the-collection-database-is-not = संग्रह का डेटाबेस अभी तैयार नहीं है।
admin-collection-detail-the-last-storage-provisioning-failed = अंतिम स्टोरेज प्रोविज़निंग विफल रही: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = प्रोसेसिंग की प्रगति और अनुमान
admin-collection-detail-display-name = प्रदर्शित नाम
admin-collection-detail-display-name-2 = प्रदर्शित नाम
admin-collection-detail-save = सहेजें
admin-collection-detail-access = पहुँच
admin-collection-detail-public-every-signed-in-user = सार्वजनिक। साइन इन किया हुआ हर उपयोगकर्ता इस संग्रह में खोज सकता है और इसे पढ़ सकता है।
admin-collection-detail-restricted-only-members-of-the = प्रतिबंधित। केवल नीचे दिए समूहों के सदस्य इस संग्रह में खोज सकते हैं और इसे पढ़ सकते हैं।
admin-collection-detail-the-collection-is-now-public = संग्रह अब सार्वजनिक है।
admin-collection-detail-the-collection-is-now-restricted = संग्रह अब प्रतिबंधित है।
admin-collection-detail-make-restricted = प्रतिबंधित करें
admin-collection-detail-make-public = सार्वजनिक करें
admin-collection-detail-group-permissions = समूह की अनुमतियाँ
admin-collection-detail-no-group-can-read-this = अभी कोई समूह इस संग्रह को नहीं पढ़ सकता।
admin-collection-detail-revoke = अनुमति हटाएँ
admin-collection-detail-grant-group-u = समूह चुनें…
admin-collection-detail-grant = अनुमति दें
admin-collection-detail-danger-zone = जोखिम क्षेत्र
admin-collection-detail-a-collection-can-only-be = संग्रह तभी हटाया जा सकता है जब उसमें कोई डेटासेट न हो।
admin-collection-detail-deleting-the-collection-also-drops = संग्रह हटाने से उसका डेटाबेस{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}और उसके अंदर का सब कुछ भी मिट जाता है। इसे पूर्ववत नहीं किया जा सकता। पुष्टि के लिए संग्रह का नाम लिखें।
admin-collection-detail-collection-name = संग्रह का नाम
admin-collection-detail-delete-collection = संग्रह हटाएँ
admin-collection-detail-features = सुविधाएँ
admin-collection-detail-vectors = वेक्टर
admin-collection-detail-this-installation-runs-no-embedding = इस इंस्टॉलेशन में कोई एम्बेडिंग सेवा नहीं चलती, इसलिए कोई संग्रह वेक्टर का उपयोग नहीं करता।
admin-collection-detail-vectors-find-passages-by-meaning = वेक्टर अंशों को उनके अर्थ से खोजते हैं। बंद करने पर नए वेक्टर बनना रुक जाता है और खोज संग्रहीत वेक्टर का उपयोग करना बंद कर देती है, जो बने रहते हैं। चालू करने पर हर डेटासेट के छूटे हुए वेक्टर, एक समय में एक डेटासेट, गणना किए जाते हैं।
admin-collection-detail-this-collection-follows-the-installation = यह संग्रह इंस्टॉलेशन का अनुसरण करता है, जो वेक्टर का उपयोग करता है। वेक्टर अंशों को उनके अर्थ से खोजते हैं। बंद करने पर नए वेक्टर बनना रुक जाता है और खोज संग्रहीत वेक्टर का उपयोग करना बंद कर देती है, जो बने रहते हैं।
admin-collection-processing-could-not-load-this-panel = यह पैनल लोड नहीं हो सका: { $message }
admin-collection-processing-admin-processing-of = प्रशासन: { $collection_id } की प्रोसेसिंग
admin-collection-processing-u-back-to-collection = ← संग्रह पर वापस
admin-collection-processing-processing-stages = प्रोसेसिंग चरण
admin-collection-processing-loading-u = लोड हो रहा है…
admin-collection-processing-the-collection-database-is-still = संग्रह का डेटाबेस अभी प्रोविज़न हो रहा है।
admin-collection-processing-this-collection-has-no-datasets = इस संग्रह में अभी कोई डेटासेट नहीं है।
admin-collection-processing-eta = अनुमानित समय { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = अभी तक अनुमान के नमूने नहीं हैं। वे डेटासेट की प्रोसेसिंग के दौरान जमा होते हैं।
admin-collection-processing-estimated-completion = अनुमानित पूर्णता:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}({ $humanize_seconds_c_eta_seconds } में, यह सर्वोत्तम प्रयास का अनुमान है, समय-निर्धारण का वादा नहीं)
admin-collection-processing-no-current-estimate-the-pipeline = अभी कोई अनुमान नहीं है। पाइपलाइन समाप्त हो चुकी है या मापने योग्य प्रगति नहीं कर रही।
admin-collection-processing-where-processing-time-goes = प्रोसेसिंग का समय कहाँ जाता है
admin-collection-processing-no-task-executions-recorded-yet = अभी तक कोई टास्क निष्पादन दर्ज नहीं हुआ। पाइपलाइन जो भी गतिविधि चलाती है वह यहाँ एक पंक्ति लिखती है, इसलिए खाली तालिका का अर्थ है कि इंस्ट्रूमेंटेशन डिप्लॉय होने के बाद कुछ प्रोसेस नहीं हुआ।
admin-collection-processing-summed-task-time = कुल टास्क समय
admin-collection-processing-wall-clock = वास्तविक समय
admin-collection-processing-achieved-parallelism = प्राप्त समानांतरता
admin-collection-processing-summed-task-time-divided-by = कुल टास्क समय को वास्तविक समय से भाग देने पर वह समानांतरता मिलती है जो पाइपलाइन ने वास्तव में हासिल की। 1 के पास होने का अर्थ है कि नीचे का शीर्ष टास्क ही पूरी लागत है और उसे अनुकूलित करना उचित है। वर्कर स्लॉट की संख्या के पास होने का अर्थ है कि स्लॉट भर चुके हैं और अधिक वर्कर जोड़ना सस्ता उपाय है। वास्तविक समय पहले निष्पादन से अंतिम तक फैला है, निष्क्रिय समय सहित।
admin-collection-processing-task = टास्क
admin-collection-processing-total = कुल
admin-collection-processing-share = हिस्सा
admin-collection-processing-executions = निष्पादन
admin-collection-processing-mean = औसत
admin-collection-processing-max = अधिकतम
admin-collection-processing-failed = विफल
admin-collection-processing-live-activity = चालू गतिविधि
admin-collection-processing-nothing-running-no-activity-finished = कुछ नहीं चल रहा। पिछले { $live_window_seconds } सेकंड में कोई गतिविधि पूरी नहीं हुई और कोई वर्कर कुछ प्रगति में नहीं बताता।
admin-collection-processing-in-flight = प्रगति में
admin-collection-processing-average-concurrency = औसत समवर्तिता
admin-collection-processing-task-time-in-window = विंडो में टास्क समय
admin-collection-processing-share-of-processing-time-over = पिछले { $live_window_seconds } सेकंड में प्रोसेसिंग समय का हिस्सा, हर 5 सेकंड में रीफ़्रेश होता है। विंडो के किनारे को पार करने वाला निष्पादन केवल अपने भीतर के भाग के लिए गिना जाता है। जिस पंक्ति में निष्पादन प्रगति में हैं पर कोई हिस्सा नहीं है, वह विंडो से पहले शुरू हुई थी और पूरी नहीं हुई। उसकी आयु जाँचें।
admin-collection-processing-share-of-window = विंडो का हिस्सा
admin-collection-processing-task-time = टास्क समय
admin-collection-processing-completed = पूर्ण
admin-collection-processing-oldest-running = सबसे पुराना चालू
admin-collection-processing-temporal-workflows = Temporal वर्कफ़्लो
admin-collection-processing-workflows-of-this-collection-s = इस संग्रह के डेटासेट के वर्कफ़्लो, चाइल्ड वर्कफ़्लो सहित।
admin-collection-processing-no-workflows-match-this-filter = इस फ़िल्टर से कोई वर्कफ़्लो मेल नहीं खाता।
admin-collection-processing-workflow = वर्कफ़्लो
admin-collection-processing-type = प्रकार
admin-collection-processing-status = स्थिति
admin-collection-processing-started = शुरू हुआ
admin-collection-processing-closed = बंद हुआ
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = खोलें ↗
admin-collection-processing-failed-tasks = विफल टास्क
admin-collection-processing-no-task-failures-recorded = कोई टास्क विफलता दर्ज नहीं हुई।
admin-collection-processing-dataset = डेटासेट
admin-collection-processing-errors = त्रुटियाँ
admin-collection-processing-documents = दस्तावेज़
admin-collection-processing-last-seen = अंतिम बार देखा गया
admin-collection-processing-sample = नमूना
admin-collection-processing-retry = फिर कोशिश करें
admin-collection-processing-failures-per-document = प्रति दस्तावेज़ विफलताएँ
admin-collection-processing-no-document-failures-recorded = कोई दस्तावेज़ विफलता दर्ज नहीं हुई।
admin-collection-processing-document = दस्तावेज़
admin-collections-list-admin-collections = प्रशासन: संग्रह
admin-collections-list-collections = संग्रह
admin-collections-list-loading-collections-u = संग्रह लोड हो रहे हैं…
admin-collections-list-datasets = डेटासेट
admin-collections-list-loading-datasets-u = डेटासेट लोड हो रहे हैं…
admin-collections-list-add-a-collection = संग्रह जोड़ें
admin-collections-list-name-for-example-enron = नाम, जैसे enron
admin-collections-list-display-name = प्रदर्शित नाम
admin-collections-list-add-collection = संग्रह जोड़ें
admin-collections-list-a-name-has-lowercase-letters = नाम में छोटे अक्षर, अंक और अंडरस्कोर होते हैं। बड़े अक्षर छोटे हो जाते हैं,{" "}
admin-collections-list-the-collection-is-saved-as = संग्रह इस नाम से सहेजा जाता है: { $new_name }
admin-collections-list-a-collection-with-the-name = { $new_name } नाम का संग्रह पहले से है।
admin-collections-list-collection = संग्रह
admin-collections-list-documents = दस्तावेज़
admin-collections-list-size = आकार
admin-collections-list-errors = त्रुटियाँ
admin-collections-list-state = स्थिति
admin-collections-list-access = पहुँच
admin-collections-list-database-not-ready = डेटाबेस तैयार नहीं
admin-collections-list-public = सार्वजनिक
admin-collections-list-1-group = 1 समूह
admin-collections-list-not-counted-yet = अभी गिना नहीं गया
admin-collections-list-unknown = अज्ञात
admin-collections-list-no-collection-has-a-dataset = किसी संग्रह में कोई डेटासेट नहीं है।
admin-collections-list-dataset = डेटासेट
admin-collections-list-indexed = इंडेक्स किए गए
admin-collections-list-created = बनाया गया
admin-dashboard-admin-dashboard = प्रशासन: डैशबोर्ड
admin-dashboard-administration = प्रशासन
admin-dashboard-users = उपयोगकर्ता
admin-dashboard-groups = समूह
admin-dashboard-collections = संग्रह
admin-dashboard-datasets = डेटासेट
admin-dashboard-failed-to-load-counts = गिनतियाँ लोड नहीं हो सकीं: { $e }
admin-dataset-detail-admin-dataset = प्रशासन: डेटासेट { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = डेटासेट लोड नहीं हो सका
admin-dataset-detail-loading = लोड हो रहा है...
admin-dataset-detail-metadata = मेटाडेटा
admin-dataset-detail-display-name = प्रदर्शित नाम
admin-dataset-detail-name = नाम
admin-dataset-detail-type = प्रकार
admin-dataset-detail-path = पथ
admin-dataset-detail-created = बनाया गया
admin-dataset-detail-collection = संग्रह
admin-dataset-detail-save = सहेजें
admin-dataset-detail-statistics = आँकड़े
admin-dataset-detail-state = स्थिति
admin-dataset-detail-documents = दस्तावेज़
admin-dataset-detail-size = आकार
admin-dataset-detail-indexed = इंडेक्स किए गए
admin-dataset-detail-errors = त्रुटियाँ
admin-dataset-detail-plans-finished = पूरे हुए प्लान
admin-dataset-detail-disk = डिस्क
admin-dataset-detail-rescan-disk-reads-the-dataset = डिस्क फिर से स्कैन करें डेटासेट फ़ोल्डर को दोबारा पढ़ता है, नई और बदली हुई फ़ाइलें जोड़ता है और उन्हें प्रोसेस करता है।
admin-dataset-detail-rescan-disk = डिस्क फिर से स्कैन करें
admin-dataset-detail-danger-zone = जोखिम क्षेत्र
admin-dataset-detail-this-deletes-the-dataset-and = यह डेटासेट और उससे निकाला गया सारा डेटा हटा देता है। इसे पूर्ववत नहीं किया जा सकता।
admin-dataset-detail-delete-dataset-and-its-data = डेटासेट और उसका डेटा हटाएँ
admin-dataset-detail-accept-uploads = अपलोड स्वीकार करें
admin-dataset-detail-the-folder-of-this-dataset = इस डेटासेट का फ़ोल्डर लिखने योग्य डेटासेट माउंट में नहीं है, इसलिए उसमें अपलोड नहीं आते।
admin-dataset-detail-starting-u = शुरू हो रहा है…
admin-failure-detail-admin-failure = प्रशासन: विफलता { $op_id }
admin-failure-detail-loading-tree = ट्री लोड हो रहा है…
admin-failure-detail-back-to-errors-and-failures = त्रुटियों और विफलताओं पर वापस
admin-failure-detail-operations = ऑपरेशन
admin-failure-detail-scrubbed-copy-written-to-the = स्क्रब की हुई प्रति क्लिपबोर्ड पर लिखी गई।
admin-failure-detail-this-tree-is-truncated-at = यह ट्री छोटा किया गया है। कम से कम एक कैप्चर में नोड छूट गए।
admin-failure-detail-the-captured-tree-has-expired = कैप्चर किए गए ट्री की अवधि समाप्त हो गई। ऑपरेशन की पंक्ति अब भी मौजूद है।
admin-failure-detail-no-captured-nodes-for-this = इस ऑपरेशन के लिए कोई कैप्चर किया गया नोड नहीं है।
admin-failure-detail-operation = ऑपरेशन
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } रूट · { $tree_nodes_len } नोड
admin-failure-detail-open-in-temporal = Temporal में खोलें
admin-failure-detail-scrubbed-copy = स्क्रब की हुई प्रति
admin-failure-detail-the-scrubbed-copy-replaces-dataset = स्क्रब की हुई प्रति डेटासेट पथों को हैश से और लंबे मानों को उनकी लंबाई से बदल देती है।
admin-failure-detail-copy-scrubbed-record = स्क्रब किया रिकॉर्ड कॉपी करें
admin-failure-detail-tree = ट्री
admin-failure-detail-root = रूट ·{" "}
admin-failure-detail-node-parent-depth-source-stage = नोड { $node_node_index } · पैरेंट { $node_parent_index } · गहराई { $node_depth } · स्रोत { $node_source } · चरण { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = वर्कफ़्लो { $node_workflow_id } · रन { $node_run_id } · गतिविधि { $node_activity_id } · प्रयास { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = इस कैप्चर में { $node_nodes_dropped } नोड छूट गए
admin-failures-admin-errors-and-failures = प्रशासन: त्रुटियाँ और विफलताएँ
admin-failures-errors-failures = त्रुटियाँ/विफलताएँ
admin-failures-loading-failures = विफलताएँ लोड हो रही हैं…
admin-failures-operational-failures = संचालन विफलताएँ
admin-failures-no-operational-failures-at-this = इस समय कोई संचालन विफलता नहीं।
admin-failures-collection = संग्रह
admin-failures-dataset = डेटासेट
admin-failures-task-name = टास्क का नाम
admin-failures-error-class = त्रुटि वर्ग
admin-failures-operation-kind = ऑपरेशन का प्रकार
admin-failures-from = से
admin-failures-to = तक
admin-failures-no-captured-failures-match-these = कोई कैप्चर की गई विफलता इन फ़िल्टर से मेल नहीं खाती।
admin-failures-signature = सिग्नेचर
admin-failures-count = संख्या
admin-failures-class = वर्ग
admin-failures-task = टास्क
admin-failures-last-seen = अंतिम बार देखा गया
admin-failures-newer = नए
admin-failures-page = पेज { $current_page_1 }
admin-failures-older = पुराने
admin-failures-per-page = प्रति पेज
admin-failures-loading-instances = घटनाएँ लोड हो रही हैं…
admin-failures-no-instances-for-this-signature = इस सिग्नेचर की कोई घटना नहीं।
admin-failures-node = {" "}नोड { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = दस्तावेज़ त्रुटियाँ
admin-failures-error-text = त्रुटि का टेक्स्ट
admin-failures-loading-document-errors-u = दस्तावेज़ त्रुटियाँ लोड हो रही हैं…
admin-failures-no-document-errors-match-these = कोई दस्तावेज़ त्रुटि इन फ़िल्टर से मेल नहीं खाती।
admin-failures-errors-by-dataset-and-task = डेटासेट और टास्क के अनुसार त्रुटियाँ
admin-failures-documents = दस्तावेज़
admin-failures-show-only-this-dataset-and = केवल यह डेटासेट और टास्क दिखाएँ
admin-failures-total = कुल
admin-failures-errors = त्रुटियाँ
admin-failures-document = दस्तावेज़
admin-failures-runs = रन
admin-failures-error = त्रुटि
admin-failures-dataset-step = डेटासेट चरण
admin-failures-previous-page = पिछला पेज
admin-failures-page-of-1-error = पेज { $page } / { $pages }, 1 त्रुटि
admin-failures-page-of-errors = पेज { $page } / { $pages }, { $data_total } त्रुटियाँ
admin-failures-next-page = अगला पेज
admin-feedback-admin-feedback = प्रशासन: फ़ीडबैक
admin-feedback-feedback = फ़ीडबैक
admin-feedback-search-titles-descriptions-accounts-and = शीर्षक, विवरण, खाते और पते खोजें
admin-feedback-search = खोजें
admin-feedback-loading-reports-u = रिपोर्ट लोड हो रही हैं…
admin-feedback-1-report-matches = 1 रिपोर्ट मेल खाती है।
admin-feedback-reports-match = { $data_total } रिपोर्ट मेल खाती हैं।
admin-feedback-received = प्राप्त
admin-feedback-type = प्रकार
admin-feedback-title = शीर्षक
admin-feedback-from = प्रेषक
admin-feedback-captures = कैप्चर
admin-feedback-state = स्थिति
admin-feedback-previous-page = पिछला पेज
admin-feedback-page-of = पेज { $page } / { $pages }
admin-feedback-next-page = अगला पेज
admin-feedback-image = छवि { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = पढ़ी गई
admin-feedback-unread = अपठित
admin-feedback-archived = आर्काइव की गई
admin-feedback-mark-unread = अपठित चिह्नित करें
admin-feedback-mark-read = पठित चिह्नित करें
admin-feedback-restore = पुनर्स्थापित करें
admin-feedback-archive = आर्काइव करें
admin-feedback-page = पेज:{" "}
admin-feedback-the-report-has-no-description = रिपोर्ट में कोई विवरण नहीं है।
admin-feedback-open-the-page-image = पेज की छवि खोलें
admin-feedback-open-the-dom-copy = DOM की प्रति खोलें
admin-feedback-page-image-of-the-report = रिपोर्ट के पेज की छवि
admin-feedback-debug-context-and-browser-log = डीबग संदर्भ और ब्राउज़र लॉग
admin-feedback-loading-u = लोड हो रहा है…
admin-group-detail-admin-group = प्रशासन: समूह { $groupname }
admin-group-detail-failed-to-load-group = समूह लोड नहीं हो सका
admin-group-detail-loading = लोड हो रहा है...
admin-group-detail-group = समूह
admin-group-detail-display-name = प्रदर्शित नाम
admin-group-detail-display-name-2 = प्रदर्शित नाम
admin-group-detail-save = सहेजें
admin-group-detail-members = सदस्य
admin-group-detail-saving-membership = सदस्यता सहेजी जा रही है...
admin-group-detail-username = उपयोगकर्ता नाम
admin-group-detail-origin = मूल स्रोत
admin-group-detail-group-admin = समूह प्रशासक
admin-group-detail-uploader = अपलोडर
admin-group-detail-remove = हटाएँ
admin-group-detail-username-to-add = जोड़ने के लिए उपयोगकर्ता नाम
admin-group-detail-add-member = सदस्य जोड़ें
admin-group-detail-collection-access = संग्रह की पहुँच
admin-group-detail-this-group-has-no-collection = इस समूह के पास कोई संग्रह अनुमति नहीं है।
admin-group-detail-revoke = अनुमति हटाएँ
admin-group-detail-grant-collection-u = संग्रह चुनें…
admin-group-detail-grant = अनुमति दें
admin-group-detail-danger-zone = जोखिम क्षेत्र
admin-group-detail-delete-group = समूह हटाएँ
admin-groups-list-admin-groups = प्रशासन: समूह
admin-groups-list-groups = समूह
admin-groups-list-add-group = समूह जोड़ें
admin-groups-list-display-name = प्रदर्शित नाम
admin-groups-list-use-lowercase-letters-digits-underscores = नाम में छोटे अक्षर, अंक, अंडरस्कोर और हाइफ़न का उपयोग करें। नाम बाद में बदला नहीं जा सकता।
admin-groups-list-add-group-2 = समूह जोड़ें +
admin-groups-list-group = समूह
admin-groups-list-display-name-2 = प्रदर्शित नाम
admin-groups-list-members = सदस्य
admin-groups-list-collections = संग्रह
admin-groups-list-loading = लोड हो रहा है...
admin-llm-config-admin-llm = प्रशासन: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = लोड हो रहा है…
admin-llm-config-no-llm-provider-is-configured = कोई LLM प्रदाता कॉन्फ़िगर नहीं है। hoover4.ini में LLM_BASE_URL / LLM_MODEL सेट करें और दोबारा डिप्लॉय करें।
admin-llm-config-providers = प्रदाता
admin-llm-config-the-refresh-runs-in-the = रीफ़्रेश बैकग्राउंड में चलता है। तब तक मौजूदा सूची दिखती रहती है।
admin-llm-config-refresh-in-flight-u = {" "}रीफ़्रेश जारी है…
admin-llm-config-provider = प्रदाता
admin-llm-config-models = मॉडल
admin-llm-config-freshest = सबसे ताज़ा
admin-llm-config-status = स्थिति
admin-llm-config-refresh-catalog = कैटलॉग रीफ़्रेश करें
admin-llm-config-every-call = एजेंट टर्न, बोर्ड आकलन, रिपोर्ट रूपांतरण, शीर्षक, सारांश और बोर्ड लेबल
admin-llm-config-hoover4-ini-sets-the-model = hoover4.ini यह मॉडल तय करती है।
admin-llm-config-thinking = थिंकिंग
admin-llm-config-the-model-reasons-before-each = मॉडल हर टूल कॉल और हर उत्तर से पहले तर्क करता है।
admin-llm-config-catalog = कैटलॉग
admin-llm-config-filter-models-u = मॉडल फ़िल्टर करें…
admin-llm-config-model = मॉडल
admin-llm-config-flags = फ़्लैग
admin-llm-config-calls-14d = कॉल 14 दिन
admin-llm-config-ai-status = AI स्थिति
admin-llm-config-shows-the-serving-health = {" "}सेवा की स्थिति दिखाता है।
admin-llm-reports-reports = रिपोर्ट
admin-llm-reports-each-report-runs-when-you = हर रिपोर्ट तब चलती है जब आप उसका बटन चुनते हैं।
admin-llm-reports-running-u = चल रही है…
admin-llm-reports-run-report = रिपोर्ट चलाएँ
admin-llm-reports-read-at = { $read_at } को पढ़ा गया
admin-llm-reports-errors = त्रुटियाँ
admin-llm-reports-failed-attempts-by-step-and = चरण और त्रुटि वर्ग के अनुसार विफल प्रयास, और विफल रहे या जल्दी समाप्त हुए एजेंट रन, उनके समाप्ति कारण के अनुसार।
admin-llm-reports-source = स्रोत
admin-llm-reports-class = वर्ग
admin-llm-reports-no-errors-in-30-days = 30 दिनों में कोई त्रुटि नहीं।
admin-llm-reports-recent-errors = हाल की त्रुटियाँ
admin-llm-reports-the-newest-100-failed-attempts = 7 दिनों के सबसे नए 100 विफल प्रयास। त्रुटि पढ़ने के लिए कोई पंक्ति खोलें।
admin-llm-reports-time = समय
admin-llm-reports-user = उपयोगकर्ता
admin-llm-reports-name = नाम
admin-llm-reports-error = त्रुटि
admin-llm-reports-no-errors-in-7-days = 7 दिनों में कोई त्रुटि नहीं।
admin-llm-reports-show = दिखाएँ
admin-llm-reports-tool-calls = टूल कॉल
admin-llm-reports-one-row-for-each-tool = हर टूल की एक पंक्ति, 30 दिनों की कॉल के अनुसार। त्रुटि का अर्थ है विफल कॉल।
admin-llm-reports-tool = टूल
admin-llm-reports-calls-24-h = कॉल 24 घंटे
admin-llm-reports-error-24-h = त्रुटि % 24 घंटे
admin-llm-reports-avg-ms-24-h = औसत ms 24 घंटे
admin-llm-reports-calls-7-d = कॉल 7 दिन
admin-llm-reports-error-7-d = त्रुटि % 7 दिन
admin-llm-reports-avg-ms-7-d = औसत ms 7 दिन
admin-llm-reports-calls-30-d = कॉल 30 दिन
admin-llm-reports-error-30-d = त्रुटि % 30 दिन
admin-llm-reports-avg-ms-30-d = औसत ms 30 दिन
admin-llm-reports-no-tool-calls-in-30 = 30 दिनों में कोई टूल कॉल नहीं।
admin-llm-reports-top-users = सबसे अधिक उपयोग करने वाले उपयोगकर्ता
admin-llm-reports-the-30-users-with-the = विंडो में सबसे अधिक मॉडल समय वाले 30 उपयोगकर्ता।
admin-llm-reports-30-days = 30 दिन
admin-llm-reports-7-days = 7 दिन
admin-llm-reports-24-hours = 24 घंटे
admin-llm-reports-tool-time = टूल समय
admin-llm-reports-model-calls = मॉडल कॉल
admin-llm-reports-model-time = मॉडल समय
admin-llm-reports-tokens-in = इनपुट टोकन
admin-llm-reports-tokens-out = आउटपुट टोकन
admin-llm-reports-no-agent-use-in-the = विंडो में एजेंट का कोई उपयोग नहीं।
admin-metrics-admin-metrics = प्रशासन: मेट्रिक्स
admin-metrics-metrics = मेट्रिक्स
admin-metrics-the-last-24-hours = पिछले 24 घंटे।
admin-metrics-loading-u = लोड हो रहा है…
admin-metrics-manticore-load-now = Manticore लोड (अभी)
admin-metrics-ram-is-the-memory-of = RAM तालिकाओं की मेमोरी है। थ्रेड लोड पिछले 1, 5 और 15 मिनट का है।
admin-metrics-manticore-status-could-not-be = Manticore की स्थिति पढ़ी नहीं जा सकी: { $error }
admin-metrics-thread-load-1-5-15 = थ्रेड लोड (1, 5, 15 मिनट)
admin-metrics-primary-thread-load-1-5 = प्राथमिक थ्रेड लोड (1, 5, 15 मिनट)
admin-metrics-secondary-thread-load-1-5 = द्वितीयक थ्रेड लोड (1, 5, 15 मिनट)
admin-metrics-worker-threads-busy-total = वर्कर थ्रेड व्यस्त / कुल
admin-metrics-work-queue = कार्य कतार
admin-metrics-ram-held-by-tables = तालिकाओं द्वारा घेरी गई RAM
admin-metrics-disk-used-by-tables = तालिकाओं द्वारा उपयोग की गई डिस्क
admin-metrics-tables-merging = मर्ज हो रही तालिकाएँ
admin-metrics-tables-read = पढ़ी गई तालिकाएँ
admin-metrics-read-at = पढ़ने का समय
admin-metrics-largest-tables-by-ram = RAM के अनुसार सबसे बड़ी तालिकाएँ
admin-metrics-table = तालिका
admin-metrics-ram = RAM
admin-metrics-disk = डिस्क
admin-metrics-disk-chunks = डिस्क खंड
admin-metrics-merging = मर्ज हो रही
admin-metrics-usage-last-24-h = उपयोग (पिछले 24 घंटे)
admin-metrics-events-by-type = प्रकार के अनुसार घटनाएँ
admin-metrics-event = घटना
admin-metrics-count = संख्या
admin-metrics-events-per-hour = प्रति घंटा घटनाएँ
admin-metrics-no-events-recorded-yet = अभी तक कोई घटना दर्ज नहीं हुई।
admin-metrics-busiest-users = सबसे व्यस्त उपयोगकर्ता
admin-metrics-user = उपयोगकर्ता
admin-metrics-events = घटनाएँ
admin-metrics-events-2 = { $point_bucket }: { $point_count } घटनाएँ
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = API कॉल (पिछले 24 घंटे)
admin-metrics-no-api-calls-recorded-yet = अभी तक कोई API कॉल दर्ज नहीं हुई।
admin-metrics-function = फ़ंक्शन
admin-metrics-calls = कॉल
admin-metrics-errors = त्रुटियाँ
admin-metrics-error-rate = त्रुटि दर
admin-metrics-bytes-in = आने वाले बाइट
admin-metrics-bytes-out = जाने वाले बाइट
admin-operation-detail-admin-operation = प्रशासन: ऑपरेशन { $op_id }
admin-operation-detail-loading-operation = ऑपरेशन लोड हो रहा है…
admin-operation-detail-back-to-operations = ऑपरेशन पर वापस
admin-operation-detail-operation = ऑपरेशन
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · कतार में { $row_started_at } को
admin-operation-detail-not-started = शुरू नहीं हुआ
admin-operation-detail-re-run-counts-are-not = दोबारा चलाने की गिनतियाँ उपलब्ध नहीं हैं।
admin-operation-detail-failed-document-s-task-failure = { $documents } दस्तावेज़ विफल, { $row_failed_tasks_unwrap_or_0 } टास्क विफलताएँ
admin-operation-detail-failures-were-not-counted = विफलताएँ गिनी नहीं गईं।
admin-operation-detail-open-captured-failure-tree = कैप्चर किया गया विफलता ट्री खोलें
admin-operation-detail-open-in-temporal = Temporal में खोलें
admin-operation-detail-plans = प्लान
admin-operation-detail-plan-s-page = { $data_plans_total } प्लान, पेज { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = इस ऑपरेशन के लिए कोई प्लान दर्ज नहीं हुआ।
admin-operation-detail-dataset = डेटासेट
admin-operation-detail-plan-hash = प्लान हैश
admin-operation-detail-source = स्रोत
admin-operation-detail-finished = समाप्त
admin-operation-detail-previous = पिछला
admin-operation-detail-next = अगला
admin-operation-detail-error-events = त्रुटि घटनाएँ
admin-operation-detail-error-event-s-page = { $data_events_total } त्रुटि घटनाएँ, पेज { $page_1 }
admin-operation-detail-no-error-events-were-recorded = इस ऑपरेशन के लिए कोई त्रुटि घटना दर्ज नहीं हुई।
admin-operation-detail-time = समय
admin-operation-detail-hash = हैश
admin-operation-detail-task = टास्क
admin-operation-detail-event = घटना
admin-operation-detail-error-excerpt = त्रुटि का अंश
admin-operations-admin-operations = प्रशासन: ऑपरेशन
admin-operations-operations = ऑपरेशन
admin-operations-loading-operations = ऑपरेशन लोड हो रहे हैं…
admin-operations-filters = फ़िल्टर
admin-operations-state = स्थिति
admin-operations-any-state = कोई भी स्थिति
admin-operations-collection = संग्रह
admin-operations-all-collections = सभी संग्रह
admin-operations-choose-a-collection-to-see = प्रति-टास्क त्रुटि दर देखने के लिए कोई संग्रह चुनें।
admin-operations-operations-newest-first = ऑपरेशन, नवीनतम पहले
admin-operations-newer = नए
admin-operations-page = पेज { $current_page_1 }
admin-operations-older = पुराने
admin-operations-failure-rate-by-task-type = टास्क प्रकार के अनुसार विफलता दर ({ $collectionname })
admin-operations-one-row-per-activity-execution = हर गतिविधि निष्पादन की एक पंक्ति, पुनः प्रयास सहित।{" "}
admin-operations-is-marked = {" "}से ऊपर की दर चिह्नित की जाती है।
admin-operations-no-task-executions-recorded-for = इस संग्रह के लिए अभी तक कोई टास्क निष्पादन दर्ज नहीं हुआ।
admin-operations-task = टास्क
admin-operations-error-rate = त्रुटि दर
admin-operations-failed-total-executions = विफल / कुल निष्पादन
admin-operations-documents-affected = प्रभावित दस्तावेज़
admin-operations-above-the-line = सीमा से ऊपर
admin-operations-no-operations-recorded-for-this = इस फ़िल्टर के लिए कोई ऑपरेशन दर्ज नहीं।
admin-operations-kind = प्रकार
admin-operations-target = लक्ष्य
admin-operations-workflow = वर्कफ़्लो
admin-operations-queued-at = कतार में आने का समय
admin-operations-started = शुरू हुआ
admin-operations-duration = अवधि
admin-operations-progress = प्रगति
admin-operations-eta = अनुमानित समय
admin-operations-outcome = परिणाम
admin-operations-destructive = डेटा मिटाने वाला
admin-operations-repeated-run = दोहराया गया रन
admin-operations-no-estimate-yet = अभी कोई अनुमान नहीं
admin-operations-cancel = रद्द करें
admin-operations-type-to-confirm = पुष्टि के लिए { $target } लिखें
admin-operations-re-run = फिर चलाएँ
admin-operations-waiting-for-a-free-slot = खाली स्लॉट या खाली लक्ष्य की प्रतीक्षा में
admin-operations-counting-work = काम गिना जा रहा है…
admin-operations-open-captured-tree = कैप्चर किया गया ट्री खोलें
admin-operations-no-captured-tree = कोई कैप्चर किया गया ट्री नहीं
admin-operations-no-failed-documents = कोई विफल दस्तावेज़ नहीं
admin-operations-document-s-failed = { $n } दस्तावेज़ विफल
admin-operations-task-failure-s = { $t } टास्क विफलताएँ
admin-operations-failures-not-counted = विफलताएँ गिनी नहीं गईं
admin-operations-the-newest-ten-operations-of = इस संग्रह के नवीनतम दस ऑपरेशन।{" "}
admin-operations-all-operations = सभी ऑपरेशन
admin-settings-admin-settings = प्रशासन: सेटिंग
admin-settings-server-settings = सर्वर सेटिंग
admin-settings-key = कुंजी
admin-settings-value = मान
admin-settings-description = विवरण
admin-settings-save = सहेजें
admin-settings-loading = लोड हो रहा है...
admin-settings-deployment-configuration-read-only = डिप्लॉयमेंट कॉन्फ़िगरेशन (केवल पढ़ने योग्य)
admin-settings-not-set = (सेट नहीं)
admin-user-detail-admin-user = प्रशासन: उपयोगकर्ता { $username }
admin-user-detail-failed-to-load-user = उपयोगकर्ता लोड नहीं हो सका
admin-user-detail-loading = लोड हो रहा है...
admin-user-detail-user = उपयोगकर्ता
admin-user-detail-the-next-login-replaces-the = अगला लॉगिन लॉगिन प्रॉक्सी से आए उपयोगकर्ता का पूरा नाम, ईमेल और सुपरयूज़र स्थिति बदल देता है।
admin-user-detail-llm-usage-u = LLM उपयोग →
admin-user-detail-full-name = पूरा नाम
admin-user-detail-full-name-2 = पूरा नाम
admin-user-detail-email = ईमेल
admin-user-detail-superuser = सुपरयूज़र
admin-user-detail-save = सहेजें
admin-user-detail-groups = समूह
admin-user-detail-saving-membership = सदस्यता सहेजी जा रही है...
admin-user-detail-group = समूह
admin-user-detail-origin = मूल स्रोत
admin-user-detail-group-admin = समूह प्रशासक
admin-user-detail-uploader = अपलोडर
admin-user-detail-remove = हटाएँ
admin-user-detail-add-to-group-u = समूह में जोड़ें…
admin-user-detail-add = जोड़ें
admin-user-detail-danger-zone = जोखिम क्षेत्र
admin-user-detail-delete-user = उपयोगकर्ता हटाएँ
admin-user-llm-admin-llm-use-by = प्रशासन: { $username } का LLM उपयोग
admin-user-llm-u-back-to-user = ← उपयोगकर्ता पर वापस
admin-user-llm-loading-u = लोड हो रहा है…
admin-user-llm-totals-all-time = कुल (अब तक)
admin-user-llm-chat-sessions = चैट सत्र
admin-user-llm-messages = संदेश
admin-user-llm-tool-calls = टूल कॉल
admin-user-llm-model-and-tool-time = मॉडल और टूल समय
admin-user-llm-model-and-tool-time-of = इस उपयोगकर्ता के एजेंट चरणों का मॉडल और टूल समय। समानांतर टूल कॉल पूरी गिनी जाती हैं
admin-user-llm-rate-limit-usage-current-windows = दर सीमा का उपयोग (वर्तमान विंडो)
admin-user-llm-in-process-counters-of-the = चल रहे वेबसाइट कंटेनर के इन-प्रोसेस काउंटर। चैट सीमा { $metrics_chat_per_minute }/मिनट, API सीमा { $metrics_api_per_minute }/मिनट, लंबी विंडो पर घटती हुई निरंतर दर के साथ।
admin-user-llm-chat-messages = चैट संदेश
admin-user-llm-api-calls = API कॉल
admin-user-llm-window = विंडो
admin-user-llm-used = उपयोग
admin-user-llm-budget = बजट
admin-user-llm-no-chat-sessions = कोई चैट सत्र नहीं।
admin-user-llm-title = शीर्षक
admin-user-llm-created = बनाया गया
admin-users-list-admin-users = प्रशासन: उपयोगकर्ता
admin-users-list-users = उपयोगकर्ता
admin-users-list-search-users = उपयोगकर्ता खोजें
admin-users-list-username = उपयोगकर्ता नाम
admin-users-list-full-name = पूरा नाम
admin-users-list-email-address = ईमेल पता
admin-users-list-superuser = सुपरयूज़र
admin-users-list-groups = समूह
admin-users-list-created = बनाया गया
admin-users-list-last-login = अंतिम लॉगिन
admin-users-list-loading = लोड हो रहा है...
dataset-create-panel-put-the-documents-in-a = वहाँ किसी फ़ोल्डर में दस्तावेज़ रखें और यह पेज फिर से लोड करें।
dataset-create-panel-the-name-cannot-start-with = नाम पूर्ण विराम से शुरू नहीं हो सकता और उसमें स्लैश नहीं हो सकता।
dataset-create-panel-and-a-dash-a-space = और डैश, स्पेस या पूर्ण विराम अंडरस्कोर बन जाता है। नाम बाद में बदला नहीं जा सकता।
live-chats-panel-off = बंद
processing-updates-panel-the-waiting-steps-change-each = प्रतीक्षा कर रहे चरण { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }) बदलते हैं, हर फ़ाइल एक बार गिनी गई, { $view_executions } { $runs_word } में।
admin-collections-list-and-a-dash-a-space = और डैश, स्पेस या पूर्ण विराम अंडरस्कोर बन जाता है। नाम बाद में बदला नहीं जा सकता।
admin-llm-config-fresh = ताज़ा
admin-llm-config-tools = टूल{" "}
admin-llm-config-vision = विज़न{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (केवल पढ़ने योग्य)
live-chats-panel-on = चालू
processing-updates-panel-up-to-date-select-it = अद्यतन। फिर से चलाने के लिए इसे चुनें।
admin-ai-status-yes = हाँ
admin-ai-status-no-2 = नहीं
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } त्रुटियाँ
admin-collection-processing-done = पूर्ण
admin-collection-processing-failed-2 = { $stage_failed_documents } विफल
admin-collection-processing-left = शेष
admin-collection-processing-dataset-level = डेटासेट स्तर
admin-collections-list-groups = { $c_group_count } समूह
admin-failures-operation-s = { $group_operation_count } ऑपरेशन
admin-groups-list-groupname = समूह का नाम
admin-llm-config-stale = पुराना
admin-llm-config-thinking-is-on = थिंकिंग चालू है
admin-llm-config-thinking-is-off = थिंकिंग बंद है
admin-llm-config-shown = { $models_len } दिखाए गए
admin-llm-config-reasoning = तर्क
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count } में से { $load_table_count_load_unread_tables }
admin-metrics-yes = हाँ
admin-metrics-no = नहीं
admin-metrics-max = अधिकतम
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = शुरू हुआ { $run_started_at }
admin-operation-detail-yes = हाँ
admin-operation-detail-no = नहीं
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = ईमेल
admin-user-llm-untitled = (शीर्षकहीन)
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } पेज
admin-processing-updates-panel-prerequisites-waiting = संग्रह को पहले अपडेट चाहिए: { $steps }। खोज इंडेक्स में लिखने वाले चरण उसकी प्रतीक्षा करते हैं।
admin-operations-no-task-type-failing = कोई टास्क प्रकार { $threshold }% से अधिक विफल नहीं हो रहा।
admin-operations-task-types-failing = { $count } टास्क प्रकार { $threshold }% से अधिक विफल हो रहे हैं।
processing-updates-panel-collection-updates = संग्रह अपडेट
admin-collections-list-some-datasets-are-not-counted = कुछ डेटासेट अभी गिने नहीं गए हैं।
admin-failures-hide = छिपाएँ
admin-failures-show = दिखाएँ
admin-settings-web-session-lifetime-in-seconds = वेब सत्र की अवधि सेकंड में (डिफ़ॉल्ट: 604800 = 1 सप्ताह)
admin-settings-turns-every-new-chat-turn = false होने पर हर नया चैट टर्न बंद कर देता है (डिफ़ॉल्ट: true)। चल रहा टर्न पूरा होता है। अगले भेजने से प्रभावी, डिप्लॉय दोबारा करने की आवश्यकता नहीं।
admin-settings-written-by-main-py-probe = `main.py probe-embeddings` द्वारा लिखा जाता है, और यह वही है जो एंडपॉइंट वास्तव में सेवा में देता है। इसे हाथ से बदलने से सर्वर नहीं बदलता।
admin-settings-the-folder-whose-subfolders-the = वह फ़ोल्डर जिसके सबफ़ोल्डर डेटासेट फ़ॉर्म इस माउंट के लिए सूचीबद्ध करता है। hoover4.ini में इसे बदलने पर दोबारा डिप्लॉय करना पड़ता है।
admin-settings-from-hoover4-ini-changing-it = hoover4.ini से। इसे बदलने पर दोबारा डिप्लॉय करना पड़ता है।
admin-feedback-bug = बग
admin-operations-state-name = { $state ->
        [pending] लंबित
        [queued] कतार में
        [running] चल रहा है
        [finished] पूर्ण
        [errored] त्रुटि के साथ समाप्त
        [cancelled] रद्द
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = { $op_id } का विफलता ट्री
admin-failure-detail-showing-of-characters = { $node_stack_trace_original_len } में से { $node_stack_trace_chars_count } अक्षर दिखाए गए
admin-operations-operation = ऑपरेशन { $state }।
admin-operations-dispatched = { $new_id } भेजा गया।
admin-operations-rows = { $row_progress_done } / { $row_progress_total } पंक्तियाँ
admin-operations-plans = { $row_progress_done } / { $row_progress_total } प्लान
admin-group-detail-group-2 = समूह { $groupname }
admin-settings-the-setting-was-saved-successfully = सेटिंग “{ $k }” सफलतापूर्वक सहेजी गई।
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = समूह “{ $g }” सफलतापूर्वक जोड़ा गया।
admin-user-detail-user-2 = उपयोगकर्ता { $username }
admin-dataset-detail-dataset = डेटासेट { $dataset_id }
admin-dataset-detail-collections = संग्रह › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_total } में से { $detail_stats_plans_finished }
admin-dataset-detail-the-upload-setting-could-not = अपलोड सेटिंग पढ़ी नहीं जा सकी: { $err }
admin-dataset-detail-operation-started = ऑपरेशन शुरू हुआ: { $run_id }
admin-collection-detail-collection = संग्रह { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = वेक्टर सेटिंग पढ़ी नहीं जा सकी: { $err }
admin-collection-processing-processing-of = { $collection_id } की प्रोसेसिंग
admin-collection-processing-collections = संग्रह › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } निष्पादन
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = { $at } तक
admin-collection-processing-over-the-last-s = पिछले { $live_window_seconds } सेकंड में
admin-collection-processing-retry-started-run = फिर कोशिश शुरू हुई (रन { $run })।
admin-collection-processing-document-retry-started-run = दस्तावेज़ की फिर कोशिश शुरू हुई (रन { $run })।
admin-operation-detail-operation-2 = ऑपरेशन { $op_id }
admin-user-llm-llm-usage-of = { $username } का LLM उपयोग
admin-user-llm-users = उपयोगकर्ता › { $username }
processing-updates-panel-the-processing-updates-could-not = प्रोसेसिंग अपडेट पढ़े नहीं जा सके: { $e }
processing-updates-panel-update-started = अपडेट शुरू हुआ: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_total } में से { $operation_progress_done } प्लान
dataset-ocr-panel-adding = जोड़ा जा रहा है: { $added }
dataset-ocr-panel-removing = हटाया जा रहा है: { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } प्लान फिर से खोले गए
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] फ़ोल्डर
       *[other] फ़ोल्डर
    }
    [tables] { $count ->
        [one] तालिका
       *[other] तालिकाएँ
    }
   *[files] { $count ->
        [one] फ़ाइल
       *[other] फ़ाइलें
    }
}
processing-updates-step-runs = { $count ->
    [one] चरण रन
   *[other] चरण रन
}
processing-update-search_schema-title = खोज इंडेक्स स्कीमा
processing-update-search_schema-explanation = { $files ->
    [one] संग्रह की { $count } खोज तालिका में वह कॉलम नहीं है जो खोज इंडेक्स को चाहिए।
   *[other] संग्रह की { $count } खोज तालिकाओं में वह कॉलम नहीं है जो खोज इंडेक्स को चाहिए।
} कॉलम हर तालिका में जोड़ा जाता है। खोज चलती रहती है।
processing-update-search_schema-runs = खोज इंडेक्स तालिकाएँ
processing-update-unfinished-title = अधूरी प्रोसेसिंग
processing-update-unfinished-explanation = { $files ->
    [one] { $count } फ़ाइल अंत तक प्रोसेस नहीं हुई है।
   *[other] { $count } फ़ाइलें अंत तक प्रोसेस नहीं हुई हैं।
} इसमें वे फ़ाइलें शामिल हैं जिनका कोई प्रोसेसिंग प्लान नहीं है, जैसे बाधित इन्जेशन के बाद। उनकी प्रोसेसिंग पूरी की जाती है।
processing-update-unfinished-runs = इन फ़ाइलों के सभी प्रोसेसिंग चरण
processing-update-failed_files-title = विफल फ़ाइलें
processing-update-failed_files-explanation = { $files ->
    [one] { $count } फ़ाइल में प्रोसेसिंग त्रुटि है।
   *[other] { $count } फ़ाइलों में प्रोसेसिंग त्रुटि है।
} उनके लिए विफल चरण फिर से चलाए जाते हैं। स्वचालित रन विफल चरण के हर नए संस्करण पर फ़ाइल को एक बार फिर आज़माता है।
processing-update-failed_files-runs = विफल चरण, फिर इकाई निष्कर्षण, एम्बेडिंग और इंडेक्सिंग
processing-update-virus_scan-title = वायरस स्कैन
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } फ़ाइल का कोई एंटीवायरस निर्णय नहीं है।
   *[other] { $count } फ़ाइलों का कोई एंटीवायरस निर्णय नहीं है।
} उन्हें स्कैन किया जाता है। जिस फ़ाइल को स्कैनर संक्रमित पाता है वह खोज में चिह्नित हो जाती है, और उसकी मूल फ़ाइल और खोजने योग्य PDF के डाउनलोड अस्वीकृत होते हैं।
processing-update-virus_scan-runs = एंटीवायरस स्कैन, फिर संक्रमित फ़ाइलों का खोज गुण
processing-update-tables-title = तालिकाएँ
processing-update-tables-explanation = { $files ->
    [one] { $count } फ़ाइल में पुराना तालिका पठन या अधूरे निर्भर परिणाम हैं। उसके संग्रहीत परिणाम अपडेट किए जाते हैं।
    *[other] पुराने तालिका पठन या अधूरे निर्भर परिणामों वाली फ़ाइलें: { $count }। उनके संग्रहीत परिणाम अपडेट किए जाते हैं।
    }

processing-update-tables-runs = तालिका पठन, इकाइयाँ, संकेत, एम्बेडिंग और दोनों अनुक्रमणिकाएँ
processing-update-ocr-title = OCR
processing-update-ocr-explanation = स्वचालित OCR चाहने वाली फ़ाइलें: { $count }। पहचानी गई भाषा में पहले का OCR पाठ बिना नए OCR के रखा जाता है। बाकी पृष्ठों को पहचानी गई भाषा के स्थापित मॉडल से OCR मिलता है। प्रतिस्थापन पूरा होने पर पुराने संस्करण हटाए जाते हैं।
processing-update-ocr-runs = OCR और खोजने योग्य PDF, फिर नए टेक्स्ट का इकाई निष्कर्षण, एम्बेडिंग और इंडेक्सिंग
processing-update-ocr_detection-title = OCR पहचान
processing-update-ocr_detection-explanation = वर्तमान पाठ, लिपि या भाषा पहचान के बिना फ़ाइलें: { $count }। हर पात्र चित्र और PDF पृष्ठ की सीमित बैच में जाँच होती है।
processing-update-ocr_detection-runs = पहचान, फिर इन फ़ाइलों के खोज गुण
processing-update-pdf_text-title = खोजने योग्य PDF का टेक्स्ट
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } फ़ाइल में पुरानी टेक्स्ट परत वाले खोजने योग्य PDF हैं।
   *[other] { $count } फ़ाइलों में पुरानी टेक्स्ट परत वाले खोजने योग्य PDF हैं।
} वह परत पश्चिमी यूरोपीय वर्णमालाओं से बाहर के हर अक्षर को काले वर्ग के रूप में कॉपी करती थी। केवल पश्चिमी यूरोपीय अक्षरों वाली भाषाओं के PDF वैसे ही रहते हैं। बाकी PDF पढ़े जाते हैं, और काले वर्गों वाले हिस्से फिर से बनाए जाते हैं। इमेज PDF सहेजे गए OCR शब्दों का उपयोग करता है। PDF पेज को नया OCR अनुरोध मिलता है।
processing-update-pdf_text-runs = खोजने योग्य PDF के हिस्से, फिर फिर से बनाए गए PDF के OCR टेक्स्ट की इंडेक्सिंग
processing-update-page_text-title = अनुक्रमित पृष्ठ पाठ
processing-update-page_text-explanation = अधूरे खोज पाठ वाली फ़ाइलें: { $count }। किसी पृष्ठ में एक नियंत्रण वर्ण ने उसका अनुक्रमित पाठ समाप्त कर दिया। पूरा पाठ अनुक्रमित किया जाता है।
processing-update-page_text-runs = इन पृष्ठों का खोज अनुक्रमणिका पाठ
processing-update-text_rows-title = टेक्स्ट विभाजन
processing-update-text_rows-explanation = पिछले विभाजन के टेक्स्ट वाली फ़ाइलें: { $count }। PDF टेक्स्ट हर PDF भाग के लिए एक पंक्ति में जाता है, और लंबा टेक्स्ट छोटे ओवरलैप के साथ काटा जाता है। कोई नया OCR या पार्सिंग नहीं चलती।
processing-update-text_rows-runs = टेक्स्ट विभाजन, फिर नए टेक्स्ट का इकाई निष्कर्षण, एम्बेडिंग और इंडेक्सिंग
processing-update-vectors-title = वेक्टर
processing-update-vectors-explanation = { $files ->
    [one] टेक्स्ट वाली { $count } फ़ाइल के पास उस एम्बेडिंग मॉडल के वेक्टर नहीं हैं जिसे इंस्टॉलेशन चलाता है।
   *[other] टेक्स्ट वाली { $count } फ़ाइलों के पास उस एम्बेडिंग मॉडल के वेक्टर नहीं हैं जिसे इंस्टॉलेशन चलाता है।
} उनके वेक्टर गणना करके इंडेक्स किए जाते हैं।
processing-update-vectors-runs = एम्बेडिंग और वेक्टर इंडेक्सिंग
processing-update-folder_counts-title = फ़ोल्डर गिनतियाँ
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } फ़ोल्डर की न फ़ाइल संख्या है न आकार, या उसके मान पुराने संस्करण के हैं।
   *[other] { $count } फ़ोल्डरों की न फ़ाइल संख्या है न आकार, या उनके मान पुराने संस्करण के हैं।
} गिनतियाँ फिर से निकाली जाती हैं।
processing-update-folder_counts-runs = फ़ोल्डर ट्री
admin-uploads-badge = अपलोड
admin-uploads-badge-title = अपलोड स्वीकार करता है

processing-update-archive_members-title = संग्रह के सदस्य

processing-update-archive_members-explanation = { $files ->
    [one] { $count } विभाजित संग्रह को वर्तमान सदस्य सूची चाहिए। उसके सदस्य और खोज परिणाम अपडेट किए जाते हैं।
    *[other] वर्तमान सदस्य सूचियों की आवश्यकता वाले विभाजित संग्रह: { $count }। उनके सदस्य और खोज परिणाम अपडेट किए जाते हैं।
    }

processing-update-archive_members-runs = संग्रह निष्कर्षण, सदस्यों का मिलान और निर्भर प्रसंस्करण

processing-update-image_previews-title = चित्र पूर्वावलोकन

processing-update-image_previews-explanation = { $files ->
    [one] { $count } असामान्य चित्र का पूर्वावलोकन नहीं है। उसका पूर्वावलोकन फिर से बनाया जाता है।
    *[other] पूर्वावलोकन रहित असामान्य चित्र: { $count }। उनके पूर्वावलोकन फिर से बनाए जाते हैं।
    }

processing-update-image_previews-runs = चित्र पूर्वावलोकन बनाना और सत्यापन

processing-update-search_terms-title = खोज शब्द

processing-update-search_terms-explanation = { $files ->
    [one] { $count } खोज तालिका को वर्तमान फ़िल्टर शब्द चाहिए। भाषा, OCR, लिपि और रेड फ़्लैग के शब्द खोजे जा सकेंगे।
    *[other] वर्तमान फ़िल्टर शब्दों की आवश्यकता वाली खोज तालिकाएँ: { $count }। भाषा, OCR, लिपि और रेड फ़्लैग के शब्द खोजे जा सकेंगे।
    }

processing-update-search_terms-runs = फ़िल्टर शब्दों का अनुक्रमण और सत्यापन

automatic-ocr-title = स्वचालित OCR
automatic-ocr-refresh = स्थिति ताज़ा करें
automatic-ocr-coverage = पृष्ठ कवरेज
automatic-ocr-pages = पृष्ठ
automatic-ocr-models = OCR मॉडल
automatic-ocr-reason = कारण
automatic-ocr-truncated = निदान सूची अधूरी है।
automatic-ocr-presence = प्रकाशित OCR पाठ है
automatic-ocr-policy = OCR हर पात्र पृष्ठ की पहचानी गई लिपि और भाषा से स्थापित मॉडल चुनता है। पहले Tesseract चलता है और शेष समर्थित लिपियों के लिए EasyOCR चलता है।
automatic-ocr-unknown = कोई वर्तमान प्रकाशन दर्ज नहीं है। अनुपस्थित पहचान और विफल प्रसंस्करण से पाठ की अनुपस्थिति सिद्ध नहीं होती।
automatic-ocr-retry = कारण ठीक करने के बाद अधूरे या विफल कार्य को दोहराने के लिए प्रसंस्करण अपडेट उपयोग करें। असमर्थित कवरेज के लिए संगत स्थापित मॉडल चाहिए।
automatic-ocr-state = { $state ->
    [candidate] लंबित
    [planned] नियोजित
    [failed] विफल
    [incomplete] अधूरा
    [unsupported] असमर्थित
    [published] प्रकाशित
    [applied] सत्यापित
    [ready] पाठ मिला
    [no_text] पाठ नहीं मिला
    *[other] { $state }
    }

processing-update-entities-title = नामित इकाइयाँ
processing-update-entities-explanation = वर्तमान इकाई निष्कर्षण या खोज योग्य परिणाम चाहने वाली फ़ाइलें: { $count }। अनुमान पूरा होने के बाद पुराने सफल परिणाम बदले जाते हैं।
processing-update-entities-runs = नामित इकाई निष्कर्षण, पाठ विशेषताएँ और खोज योग्य इकाई शब्द

automatic-ocr-reason-label = { $reason ->
    [unknown_script] लिपि की पहचान नहीं हुई
    [tesseract_capabilities_unavailable] Tesseract कवरेज उपलब्ध नहीं
    [detected_language] मॉडल पहचानी गई भाषा से मेल खाता है
    [unknown_language_script_coverage] भाषा अज्ञात है। लिपि मॉडल चुना गया है।
    [language_script_mismatch_script_coverage] भाषा और लिपि अलग हैं। लिपि मॉडल चुना गया है।
    [language_model_unavailable_script_coverage] भाषा मॉडल उपलब्ध नहीं। लिपि मॉडल चुना गया है।
    [easyocr_capabilities_unavailable] EasyOCR कवरेज उपलब्ध नहीं
    [tesseract_script_unavailable] Tesseract लिपि को कवर नहीं करता। EasyOCR चुना गया है।
    [script_coverage_unavailable] कोई स्थापित मॉडल इस लिपि को कवर नहीं करता।
    *[other] { $reason }
    }

processing-updates-check-requested = पाइपलाइन अपडेट की गणना कर रही है। गणना पूरी होने पर संख्याएँ बदलेंगी।
