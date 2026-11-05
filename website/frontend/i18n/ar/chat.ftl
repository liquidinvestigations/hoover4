# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = المساعد يعمل...
chat-composer-ask-the-bot = اسأل المساعد...
chat-composer-internet-tools = أدوات الإنترنت
chat-composer-agent-language-title = يجيب الوكيل بـ{ $language }. غيّر اللغة من الإعدادات في علامة تبويب جديدة.
chat-composer-try-again-in-s = أعد المحاولة بعد { $secs } ث
chat-composer-stop-the-answer-the-partial = إيقاف الإجابة (لا يُحفظ الجزء المكتوب منها في المحادثة)
chat-composer-starting-the-conversation-u = جارٍ بدء المحادثة…
chat-composer-send = إرسال
chat-conversation-find-search-in-conversation = بحث في المحادثة
chat-conversation-find-previous-match = المطابقة السابقة
chat-conversation-find-next-match = المطابقة التالية
chat-conversation-find-investigation-board = لوحة التحقيق
doc-ref-card-not-openable = لا يمكن فتحه: { $reason }.
doc-ref-card-the-search-term-was = كانت كلمة البحث{" "}
doc-ref-card-open = فتح
doc-ref-card-not-openable-2 = لا يمكن فتحه
chat-markdown-text-show-the-cited-source = عرض المصدر المستشهد به
chat-markdown-text-no-citation-of-this-conversation = لم يمنح أي استشهاد في هذه المحادثة هذا المعرّف، لذا لا يوجد مستند يقف خلفه.
chat-markdown-text-citations-of-this-conversation-gave = منحت استشهادات هذه المحادثة هذا المعرّف لأكثر من مستند، لذا لا يرتبط بأي منها.
cards-browser-card-open-the-archived-page = فتح الصفحة المؤرشفة
cards-browser-card-the-page-itself-was-not = لم تُؤرشف الصفحة نفسها (الحالة: { $artifact_status }). لقطة الشاشة أعلاه هي ما حُفظ.
cards-browser-card-click-the-screenshot-to-open = انقر على لقطة الشاشة لفتح الصفحة المؤرشفة.
cards-browser-card-show-less = عرض أقل
cards-browser-card-show-all = عرض الكل
cards-browser-card-archived-page = صفحة مؤرشفة
cards-browser-card-download = تنزيل
cards-browser-card-archived-copy-of = نسخة مؤرشفة من { $artifact_url }
cards-browser-card-this-page-was-not-archived = لم تُؤرشف هذه الصفحة (الحالة: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } مع بطاقة
cards-entities-card-the-entity-list-was-cut = قُطعت قائمة الكيانات.
cards-entities-card-open-the-card-for-this = فتح بطاقة هذه القيمة ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = لا توجد بطاقة: لم تذكر هذه المحادثة قط مجموعة البيانات التي جاءت منها هذه القيم، والعارض يُخاطَب بمجموعة البيانات.
cards-entities-card-more-all-of-them-in = { $rest } أخرى، وكلها في لوحة كيانات المستند.{" "}
cards-entities-card-names-organisations-and-places-above = الأسماء والمنظمات والأماكن أعلاه هي قراءة نموذج للنص. لم تتحقق منها أي قاعدة، لذا لا يوجد ما يُشرح ولا تفتح شيئًا.
cards-entities-card-nothing-extracted-from-this-document = لم يُستخرج شيء من هذا المستند.
chat-tool-cards-hide = إخفاء
chat-tool-cards-expand = توسيع
chat-tool-cards-hide-raw-json = إخفاء JSON الخام
chat-tool-cards-show-raw-json = عرض JSON الخام
cards-result-cards-search-this = ابحث عن هذا
cards-result-cards-search-every-collection = ابحث في كل مجموعة
cards-result-cards-form = الصيغة { $index }: { $form }
cards-result-cards-show-full-text = عرض النص كاملًا
cards-result-cards-quote = الاقتباس: { $quote }
cards-result-cards-reason = السبب: { $why }
cards-result-cards-open-question = سؤال مفتوح: { $question }
cards-result-cards-the-explore-gave-this-answer = قدّم الاستكشاف هذه الإجابة إلى لوحته بوصفها استنتاجًا { $kind ->
        [sourced] موثّقًا بمصادر
        [inferred] مستنتَجًا
        [not_found] بعدم العثور على ما يلزم
       *[other] من نوع غير معروف
    }.
cards-result-cards-it-left-no-open-question = ولم يترك أي سؤال مفتوح.
cards-result-cards-open-questions-for-the-board = أسئلة مفتوحة للوحة:
cards-result-cards-arguments = المعاملات
cards-result-cards-list-after-the-call = القائمة بعد الاستدعاء: { $snapshot_goal }
cards-result-cards-replaces = {" "}· يحل محل { $replaces_id }
cards-result-cards-the-list-at-this-version = القائمة في هذا الإصدار غير مخزَّنة.
web-search-card-these-sources-returned-nothing-so = لم تعد هذه المصادر شيئًا، لذا جاءت النتائج من مصادر أقل من المقصود
web-search-card-u-degraded = ⚠ { $degraded_len } متعثرة
web-search-card-form = الصيغة { $index }: { $form }
web-search-card-no-results-from = لا توجد نتائج من: { $degraded_text }
web-search-card-no-results-every-source-answered = لا توجد نتائج. استجاب كل مصدر ولم يكن لدى أي منها شيء لهذا الاستعلام.
web-search-card-the-lowest-ranked-results-were = حُذفت النتائج الأدنى ترتيبًا ليتسع هذا الاستدعاء في السجل. وقد رأى المساعد كلها.
web-search-card-view-search-details = عرض تفاصيل البحث.
web-search-card-the-stored-result-could-not = تعذّرت قراءة النتيجة المخزَّنة بصيغة JSON
web-search-card-nothing-was-stored-for-this = لم يُخزَّن شيء لهذا الاستدعاء.
web-search-card-forms = الصيغ: { $forms }
web-search-card-kind = النوع: { $row_kind }
web-search-card-published = تاريخ النشر: { $row_published }
web-search-card-loading-search-detail-u = جارٍ تحميل تفاصيل البحث…
web-search-card-could-not-load-the-search = تعذّر تحميل تفاصيل البحث: { $e }
web-search-card-malformed-detail = تفاصيل غير صالحة: { $e }
web-search-card-the-tool-returned-selected-results = أعادت الأداة نتائج مختارة إلى النموذج.
web-search-card-results-use-reciprocal-rank-fusion = تستخدم النتائج دمج الرتب التبادلي.
web-search-card-returned-nothing = لم تعد شيئًا: { $degraded }
web-search-card-all-candidates-use-fusion-order = تستخدم كل النتائج المرشحة ترتيب الدمج.
web-search-card-the-cross-encoder-ranks-selected = يرتّب المرمّز المتقاطع النتائج المختارة.
web-search-card-selected-results-use-fusion-order = تستخدم النتائج المختارة ترتيب الدمج.
web-search-card-search-detail = تفاصيل البحث
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = ابحث عن هذا
chat-tool-disclosure-search-every-collection = ابحث في كل مجموعة
chat-tool-disclosure-hide = إخفاء
chat-tool-disclosure-expand = توسيع
chat-tool-disclosure-this-step-was-recorded-before = سُجلت هذه الخطوة قبل تخزين معاملات الأداة ونتائجها. لا يتوفر سوى الملخص أدناه.
chat-tool-disclosure-arguments = المعاملات
chat-tool-disclosure-result = النتيجة
chat-tool-disclosure-hide-raw-json = إخفاء JSON الخام
chat-tool-disclosure-show-raw-json = عرض JSON الخام
chat-tool-disclosure-input-json = JSON المُدخَل
chat-tool-disclosure-output-json = JSON المُخرَج
chat-transcript-ask-a-question-about-the = اطرح سؤالًا عن المستندات الموجودة في مجموعاتك.
chat-transcript-suggested-next = المقترح التالي...
chat-transcript-earlier-answer = إجابة سابقة
chat-transcript-tokens-the-conversation-carries-the = الرموز (tokens) التي تحملها المحادثة، وأكبر سياق منفرد حوسب عليه هذا الدور، ومقدار ما استهلكه ذلك من نافذة النموذج
chat-transcript-instruction-to-the-agent = تعليمة إلى الوكيل
chat-transcript-the-context-stays-above-the = {" "}يبقى السياق دون الهدف البالغ { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}فشلت أجزاء الملخص: { $failed }. لا يحتوي السجل إلا على القوائم.
chat-transcript-show-the-record = عرض السجل
chat-transcript-hide-reasoning = إخفاء الاستدلال
chat-transcript-show-reasoning = عرض الاستدلال
chat-transcript-from-u-hide = { $count ->
        [zero] لا مستندات
        [one] مستند واحد
        [two] مستندان
        [few] { $count } مستندات
        [many] { $count } مستندًا
       *[other] { $count } مستند
    } من { $tool } — إخفاء
chat-transcript-from-u-show = { $count ->
        [zero] لا مستندات
        [one] مستند واحد
        [two] مستندان
        [few] { $count } مستندات
        [many] { $count } مستندًا
       *[other] { $count } مستند
    } من { $tool } — عرض
chat-transcript-u-hide = { $summary } — إخفاء
chat-transcript-u-show = { $summary } — عرض
chat-transcript-citations-of-this-conversation-give = تمنح استشهادات هذه المحادثة المعرّف { $doc_handle } لأكثر من مستند. لا تربطه الإجابة بأي منها.
chat-transcript-report = التقرير { $label }
chat-transcript-open-in-the-workspace = فتح في مساحة العمل
chat-transcript-this-version-could-not-be = تعذّرت قراءة هذا الإصدار. يلي ذلك نص الإجابة في المحادثة.
chat-transcript-files = الملفات
chat-transcript-version = { $file_name }، الإصدار { $file_version }
chat-web-find-exact-text = البحث عن نص مطابق
chat-web-previous-match = المطابقة السابقة
chat-web-next-match = المطابقة التالية
chat-web-close-preview = إغلاق المعاينة
chat-web-the-captured-page-could-not = تعذّر تحميل الصفحة الملتقطة.
chat-web-loading = جارٍ التحميل…
chat-workspace-pane-workspace = مساحة العمل
chat-workspace-pane-close-the-workspace = إغلاق مساحة العمل
chat-workspace-pane-close = إغلاق
chat-workspace-pane-loading-the-files-u = جارٍ تحميل الملفات…
chat-workspace-pane-the-files-could-not-be = تعذّر تحميل الملفات: { $error }
chat-workspace-pane-this-conversation-has-no-files = لا تحتوي هذه المحادثة على ملفات.
chat-workspace-pane-version = الإصدار { $entry_version }، { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = اختر ملفًا لقراءته.
chat-workspace-pane-loading-the-file-u = جارٍ تحميل الملف…
chat-workspace-pane-the-file-could-not-be = تعذّر تحميل الملف: { $error }
chat-workspace-pane-version-2 = { $found_name }، الإصدار { $found_version }
chat-board-create-collections = المجموعات
chat-board-create-loading-collections-u = جارٍ تحميل المجموعات…
chat-board-create-hoover-search-new-board = بحث Hoover - لوحة جديدة
chat-board-create-ai-chat = محادثة AI
chat-board-create-new-investigation-board = لوحة تحقيق جديدة
chat-board-create-a-board-runs-its-goals = تنفّذ اللوحة أهدافها في سلسلة من استكشافات الوكيل. كل استكشاف محادثة تنتهي باستنتاج واحد في اللوحة. تراجع إجابة كل هدف، ويمكنك رفض الاستنتاجات وإضافة تلميحات أثناء التشغيل.
chat-board-create-title = العنوان
chat-board-create-goal = الهدف
chat-board-create-remove-this-goal = إزالة هذا الهدف
chat-board-create-remove = إزالة
chat-board-create-add-a-goal = إضافة هدف
chat-board-create-context-optional = السياق (اختياري)
chat-board-create-hints-one-per-line-optional = التلميحات، تلميح في كل سطر (اختياري)
chat-board-create-sources = المصادر
chat-board-create-internet-tools = أدوات الإنترنت
chat-board-create-creating-board = جارٍ إنشاء اللوحة...
chat-board-create-create-board = إنشاء لوحة
ai-chat-board-hoover-search-board = بحث Hoover - اللوحة
ai-chat-board-loading-the-board-u = جارٍ تحميل اللوحة…
ai-chat-board-show-the-board-overview = عرض نظرة عامة على اللوحة
ai-chat-board-zoom-out = تصغير
ai-chat-board-zoom-in = تكبير
ai-chat-board-u-ai-chat = ← محادثة AI
ai-chat-board-settings = الإعدادات
ai-chat-board-board-settings = إعدادات اللوحة
ai-chat-board-internet-tools = أدوات الإنترنت
ai-chat-board-the-next-explores-of-the = يمكن لاستكشافات اللوحة التالية البحث في الويب وقراءة صفحات الويب. تحتفظ الاستكشافات الجارية بالإعداد الذي بدأت به.
ai-chat-board-collections = المجموعات
ai-chat-board-the-collections-are-fixed-when = تُثبَّت المجموعات عند إنشاء اللوحة.
ai-chat-board-confirm-drop = تأكيد الإسقاط
ai-chat-board-drop-the-board = إسقاط اللوحة
ai-chat-board-close = إغلاق
ai-chat-board-the-board-used-its-explore = استنفدت اللوحة حد الاستكشافات
ai-chat-board-the-board-used-explores-the = استنفدت اللوحة حد الاستكشافات البالغ { $explore_limit }، وهو حد اللوحة الواحدة. لن تبدأ عملًا آخر. يمكنك مع ذلك البتّ في الإجابات المقترحة.
ai-chat-board-create-a-new-board-to = أنشئ لوحة جديدة لمواصلة التحقيق
ai-chat-board-goal = الهدف
ai-chat-board-goals = الأهداف
ai-chat-board-add-new-goal = إضافة هدف جديد...
ai-chat-board-a-new-goal = هدف جديد
ai-chat-board-add-goal = إضافة هدف
ai-chat-board-a-board-has-at-most = الحد الأقصى للأهداف في اللوحة هو { $max_goals }. أنشئ لوحة جديدة لهدف آخر.
ai-chat-board-background-context = السياق الخلفي
ai-chat-board-continue-with-a-correction = المتابعة مع تصحيح
ai-chat-board-correction-what-is-wrong-or = التصحيح: ما الخطأ أو الناقص. تتابع اللوحة به.
ai-chat-board-the-board-waits-for-your = اللوحة تنتظر مراجعتك
ai-chat-board-the-board-used-its-budget = استنفدت اللوحة ميزانيتها البالغة { $snap_max_explores } استكشافًا.
ai-chat-board-the-assessments-gave-no-usable = لم تعطِ التقييمات أي اتجاه صالح للاستخدام.
ai-chat-board-accept-or-reject-the-proposed = اقبل الإجابة المقترحة لكل هدف أعلاه أو ارفضها. تتيح الإجابة المرفوضة للوحة المتابعة فورًا.
ai-chat-board-no-proposed-answer-waits-for = لا توجد إجابة مقترحة تنتظر قرارك.
ai-chat-board-reopen-the-board-to-continue = أعد فتح اللوحة لمتابعة الأهداف المفتوحة. تحتفظ باستنتاجاتها وإجاباتها.
ai-chat-board-close-the-board-to-accept = أغلق اللوحة لقبول كل إجابة مقترحة وإيقافها، أو تابعها مع تصحيح.
ai-chat-board-close-the-board = إغلاق اللوحة
ai-chat-board-or-reopen-the-board-to = أو أعد فتح اللوحة لمتابعة الأهداف المفتوحة بلا تصحيح.
ai-chat-board-the-board-is-complete = اللوحة مكتملة
ai-chat-board-a-goal-has-no-accepted = لا توجد إجابة مقبولة لأحد الأهداف. أعد فتح اللوحة لمتابعته. تحتفظ اللوحة باستنتاجاتها وإجاباتها.
ai-chat-board-add-a-hint = إضافة تلميح
ai-chat-board-the-next-assessment-reads-every = يقرأ التقييم التالي كل تلميح. ويجيب التلميح أيضًا عن استكشاف طرح سؤالًا.
ai-chat-board-add-hint = إضافة تلميح
ai-chat-board-events = الأحداث
ai-chat-board-newest-first = الأحدث أولًا
ai-chat-board-date = التاريخ
ai-chat-board-actor = الجهة
ai-chat-board-event = الحدث
ai-chat-board-show-details = عرض التفاصيل
ai-chat-board-open = فتح
ai-chat-board-show-the-newest-events = عرض أحدث { $event_rows } من الأحداث
ai-chat-board-show-all-events = عرض كل الأحداث ({ $snap_events_len })
ai-chat-board-statistics = الإحصاءات
ai-chat-board-explores = الاستكشافات
ai-chat-board-model-steps-per-explore = خطوات النموذج لكل استكشاف
ai-chat-board-assessments = التقييمات
ai-chat-board-intents = المقاصد
ai-chat-board-findings = الاستنتاجات
ai-chat-board-created = تاريخ الإنشاء
ai-chat-board-rejected-this-finding-on-the = رفض { $rejected_by } هذا الاستنتاج في { $format_utc_ms_fact_rejected_ms }. ولم تعد اللوحة تستخدمه.
ai-chat-board-rejected-this-finding-the-board = رفض { $rejected_by } هذا الاستنتاج. ولم تعد اللوحة تستخدمه.
ai-chat-board-no-reason-was-given = لم يُذكر سبب.
ai-chat-board-reason = السبب: { $fact_rejected_reason }
ai-chat-board-open-questions = أسئلة مفتوحة
ai-chat-board-explored-in = استُكشف في{" "}
ai-chat-board-explore-this-question = استكشاف هذا السؤال
ai-chat-board-your-questions = أسئلتك
ai-chat-board-ask-about-the-background-context = اسأل عن السياق الخلفي
ai-chat-board-ask-about-this-finding = اسأل عن هذا الاستنتاج
ai-chat-board-a-follow-up-question-about = سؤال متابعة عن هذه العقدة
ai-chat-board-ask = اسأل
ai-chat-board-checks-that-changed-this-finding = الفحوص التي غيّرت هذا الاستنتاج
ai-chat-board-reject-this-correction = رفض هذا التصحيح
ai-chat-board-reject-this-finding = رفض هذا الاستنتاج
ai-chat-board-not-answered-the-board-was = بلا إجابة. أُنهيت اللوحة دون إجابة عن هذا الهدف. يعيد تلميح أو إعادة فتح اللوحة فتحه.
ai-chat-board-no-answer-yet = لا توجد إجابة بعد.
ai-chat-board-the-findings-of-this-answer = استنتاجات هذه الإجابة هي عمليات بحث لم تجد شيئًا. اقبلها لتسجيل أن السجلات لا تجيب عن الهدف، أو ارفضها لمواصلة التحقيق.
ai-chat-board-open-an-assessment-to-read = {"."} افتح تقييمًا لقراءة السبب.
ai-chat-board-from-the-findings = من الاستنتاجات{" "}
ai-chat-board-accept-answer = قبول الإجابة
ai-chat-board-why-the-answer-is-wrong = لماذا الإجابة خاطئة أو ناقصة
ai-chat-board-reject-answer = رفض الإجابة
ai-chat-board-intent = المقصد
ai-chat-board-attempts-declared = المحاولات: { $intent_attempts }. أُعلن في { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = سأل الاستكشاف
ai-chat-board-add-a-hint-in-the = أضف تلميحًا في النظرة العامة على اللوحة للإجابة عنه.
ai-chat-board-last-error = آخر خطأ
ai-chat-board-brief = الموجز
ai-chat-board-open-the-explore-chat = فتح محادثة الاستكشاف
ai-chat-board-loading-the-assessment-u = جارٍ تحميل التقييم…
ai-chat-board-assessment = التقييم { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. النموذج { $a_model }. النتيجة { $a_outcome }. { $a_latency_ms } ms، { $tokens }.
ai-chat-board-checks-that-changed-it = الفحوص التي غيّرته
ai-chat-board-prompt = الموجّه
ai-chat-board-this-assessment-ran-before-the = جرى هذا التقييم قبل تخزين الموجّهات.
ai-chat-board-response = الاستجابة
ai-chat-history-hoover-search-chat-history = بحث Hoover - سجل المحادثات
ai-chat-history-u-back = ← رجوع
ai-chat-history-conversation-history = سجل المحادثات
ai-chat-history-show-board-chats = عرض محادثات اللوحات
ai-chat-history-loading-u = جارٍ التحميل…
ai-chat-history-could-not-load-history = تعذّر تحميل السجل: { $e }
ai-chat-history-no-conversations-yet = لا توجد محادثات بعد.
ai-chat-history-board = لوحة
ai-chat-history-new-chat = محادثة جديدة
ai-chat-history-messages-updated = { $s_message_count ->
        [zero] لا رسائل
        [one] رسالة واحدة
        [two] رسالتان
        [few] { $s_message_count } رسائل
        [many] { $s_message_count } رسالة
       *[other] { $s_message_count } رسالة
    } · آخر تحديث { $s_updated_at }

ai-chat-history-delete-conversation = حذف المحادثة
ai-chat-history-delete = حذف
ai-chat-homepage-hoover-search-ai-chat = بحث Hoover - محادثة AI
ai-chat-homepage-what-are-you-researching = ما الذي تبحث فيه؟
ai-chat-homepage-view-all-conversations = عرض كل المحادثات
ai-chat-homepage-starting-conversation-u = جارٍ بدء المحادثة…
ai-chat-homepage-investigation-boards = لوحات التحقيق
ai-chat-homepage-new-board = لوحة جديدة
ai-chat-homepage-loading-boards-u = جارٍ تحميل اللوحات…
ai-chat-homepage-could-not-load-the-boards = تعذّر تحميل اللوحات: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = ليست لديك لوحة. تنفّذ اللوحة تحقيقًا طويلًا في سلسلة من استكشافات الوكيل، وتراجع أنت إجاباتها.
ai-chat-homepage-updated = آخر تحديث { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = بحث Hoover - محادثة AI
ai-chat-session-this-conversation-could-not-be = تعذّر تحميل هذه المحادثة.
ai-chat-session-loading-u = جارٍ التحميل…
ai-chat-session-u-chats = ← المحادثات
ai-chat-session-history = السجل
ai-chat-session-show-the-files-that-the = عرض الملفات التي كتبها المساعد في هذه المحادثة
ai-chat-session-workspace = مساحة العمل
ai-chat-session-this-answer-was-interrupted-before = انقطعت هذه الإجابة قبل اكتمالها لأن الصفحة أو الخادم توقفا في منتصف الدور. اسأل مرة أخرى لإعادة المحاولة.
ai-chat-session-dismiss = تجاهل
ai-chat-session-board-explore-chats-are-read = محادثات استكشاف اللوحات للقراءة فقط.{" "}
ai-chat-session-open-the-board = فتح اللوحة
chat-locked-options-on = { $label }: مفعّل
chat-locked-options-off = { $label }: معطّل
chat-tool-cards-running-u = قيد التشغيل…
cards-result-cards-quote-found = عُثر على الاقتباس
cards-result-cards-quote-not-found = لم يُعثر على الاقتباس
cards-result-cards-quote-not-checked = لم يُفحص الاقتباس
web-search-card-results = { $results_len ->
        [zero] لا نتائج
        [one] نتيجة واحدة
        [two] نتيجتان
        [few] { $results_len } نتائج
        [many] { $results_len } نتيجة
       *[other] { $results_len } نتيجة
    }
chat-tool-disclosure-running-u = قيد التشغيل…
chat-transcript-call = استدعاء
chat-transcript-calls = استدعاءات
ai-chat-board-a-board-without-collections-needs = تحتاج اللوحة التي بلا مجموعات إلى أدوات الإنترنت.
ai-chat-board-of = { $snap_explores_used } من { $snap_max_explores }
ai-chat-board-assessment-2 = التقييم { $number }
ai-chat-history-messages = { $s_message_count ->
        [zero] لا رسائل
        [one] رسالة واحدة
        [two] رسالتان
        [few] { $s_message_count } رسائل
        [many] { $s_message_count } رسالة
       *[other] { $s_message_count } رسالة
    }

web-search-card-reranked-in = أعاد المرمّز المتقاطع ترتيب النتائج في { $ms } ms.
web-search-card-engine-results = { $name }: { $count } في { $ms } ms
web-search-card-score-was-rank = الدرجة { $score } · كان RRF #{ $rank }
chat-activity-the-turn-waits-for-a = ينتظر الدور توفر خانة نموذج شاغرة.
chat-activity-the-turn-waits-for-a-2 = ينتظر الدور توفر خانة أداة شاغرة.
chat-locked-options-start-a-new-chat-to = ابدأ محادثة جديدة لتغيير هذا الإعداد.
chat-locked-options-internet-tools = أدوات الإنترنت
chat-session-card-new-chat = محادثة جديدة
chat-tool-cards-first-frame-of-the-video = الإطار الأول من الفيديو
chat-tool-cards-screenshot-of = لقطة شاشة لـ
chat-tool-cards-image = صورة
cards-result-cards-the-agent-asked-a-question = طرح الوكيل سؤالًا.
chat-transcript-hide = إخفاء
chat-transcript-show = عرض
chat-transcript-unverified-quote-the-quoted-span = اقتباس غير متحقق منه. المقطع المقتبس أقصر من أن يُفحص.
chat-transcript-unverified-quote-the-document-text = اقتباس غير متحقق منه. تعذّرت قراءة نص المستند.
chat-transcript-unverified-quote-this-wording-was = اقتباس غير متحقق منه. لم يُعثر على هذه الصياغة في المستند.
chat-board-create-select-a-collection-or-turn = اختر مجموعة أو فعّل أدوات الإنترنت.
chat-board-create-select-at-least-one-collection = اختر مجموعة واحدة على الأقل.
ai-chat-board-active = نشطة
ai-chat-board-paused = متوقفة مؤقتًا
ai-chat-board-waits-for-review = تنتظر المراجعة
ai-chat-board-completed = مكتملة
ai-chat-board-dropped = مُسقطة
ai-chat-board-unknown = غير معروفة
ai-chat-board-pause-the-board = إيقاف اللوحة مؤقتًا
ai-chat-board-resume-the-board = استئناف اللوحة
ai-chat-board-none = لا شيء
ai-chat-board-reopen-with-the-remaining-budget = إعادة الفتح بالميزانية المتبقية
ai-chat-board-finding = استنتاج
ai-chat-board-why-the-correction-is-wrong = لماذا التصحيح خاطئ
ai-chat-board-reject-correction = رفض التصحيح
ai-chat-board-why-the-finding-is-wrong = لماذا الاستنتاج خاطئ
ai-chat-board-reject-finding = رفض الاستنتاج
ai-chat-board-answer = الإجابة
ai-chat-board-proposed-answer = الإجابة المقترحة
ai-chat-homepage-active = نشطة
ai-chat-homepage-paused = متوقفة مؤقتًا
ai-chat-homepage-waits-for-review = تنتظر المراجعة
ai-chat-homepage-completed = مكتملة
ai-chat-homepage-dropped = مُسقطة
ai-chat-homepage-unknown = غير معروفة
cards-result-cards-submitted-by-board = أرسلتها اللوحة: استنتاج { $kind ->
        [sourced] موثّق بمصادر
        [inferred] مستنتَج
        [not_found] بعدم العثور على ما يلزم
       *[other] من نوع غير معروف
    } من التقرير
cards-result-cards-finding-for-board = استنتاج { $kind ->
        [sourced] موثّق بمصادر
        [inferred] مستنتَج
        [not_found] بعدم العثور على ما يلزم
       *[other] من نوع غير معروف
    } للوحة
chat-transcript-compacting = جارٍ ضغط السياق: { $before } رمزًا إلى هدف قدره { $target }.
chat-transcript-compaction-failed = فشل تلخيص الخطوات السابقة. تلقى النموذج الخطوات السابقة دون تغيير، بعدد رموز { $after }.
chat-transcript-compacted = ضُغط السياق: لُخّصت { $steps } من الخطوات، وانخفضت الرموز من { $before } إلى { $after }.
ai-chat-board-reopen-with-more = إعادة الفتح مع { $grant } استكشافات إضافية
ai-chat-board-goal-number = الهدف { $number }
ai-chat-board-from-assessment-on = من التقييم { $number } بتاريخ { $date }.
ai-chat-board-from-assessment = من التقييم { $number }.
chat-board-create-goal-2 = الهدف { $index_1 }
ai-chat-session-lost-contact-with-the-chat = انقطع الاتصال بالمحادثة: { $e }
ai-chat-session-could-not-stop-the-answer = تعذّر إيقاف الإجابة: { $e } — ما زالت قيد التشغيل
ai-chat-board-later-assessments-dropped-an-answer = التقييمات اللاحقة التي أسقطت إجابة عن هذا الهدف: { $n }
ai-chat-board-prompt-and-completion-tokens = رموز الموجّه { $a_prompt_tokens } ورموز الإكمال { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = مكتملة، أهداف بلا إجابة: { $n }
board-graph-intent = مقصد، { $state }
chat-workspace-pane-characters = الأحرف: { $chars }
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } { $if_joined_live_end_1_tr_chat_transcript_ } أداة قيد التشغيل
chat-transcript-running-tool-2 = { $turn_tool_rows_len } { $if_turn_tool_rows_len_1_tr_chat_transcri } أداة قيد التشغيل
chat-transcript-answered-after-failed-attempt = { $retries_len ->
        [zero] أُجيب بعد محاولات فاشلة: { $retries_len }
        [one] أُجيب بعد محاولة فاشلة واحدة
        [two] أُجيب بعد محاولتين فاشلتين
        [few] أُجيب بعد { $retries_len } محاولات فاشلة
        [many] أُجيب بعد { $retries_len } محاولة فاشلة
       *[other] أُجيب بعد { $retries_len } محاولة فاشلة
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len ->
        [zero] لا محاولات فاشلة
        [one] محاولة فاشلة واحدة
        [two] محاولتان فاشلتان
        [few] { $retries_len } محاولات فاشلة
        [many] { $retries_len } محاولة فاشلة
       *[other] { $retries_len } محاولة فاشلة
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }، الإصدار { $report_version }
tool-run-summary-searched = { $n ->
        [zero] لا بحث عن مصطلحات
        [one] بحث عن مصطلح واحد
        [two] بحث عن مصطلحين
        [few] بحث عن { $n } مصطلحات
        [many] بحث عن { $n } مصطلحًا
       *[other] بحث عن { $n } مصطلح
    }
tool-run-summary-read = { $n ->
        [zero] لا قراءة لمستندات
        [one] قراءة مستند واحد
        [two] قراءة مستندين
        [few] قراءة { $n } مستندات
        [many] قراءة { $n } مستندًا
       *[other] قراءة { $n } مستند
    }
tool-run-summary-searched-the-web-for = { $n ->
        [zero] لا بحث في الويب عن مصطلحات
        [one] بحث في الويب عن مصطلح واحد
        [two] بحث في الويب عن مصطلحين
        [few] بحث في الويب عن { $n } مصطلحات
        [many] بحث في الويب عن { $n } مصطلحًا
       *[other] بحث في الويب عن { $n } مصطلح
    }
tool-run-summary-read-web = { $n ->
        [zero] لا قراءة لصفحات ويب
        [one] قراءة صفحة ويب واحدة
        [two] قراءة صفحتي ويب
        [few] قراءة { $n } صفحات ويب
        [many] قراءة { $n } صفحة ويب
       *[other] قراءة { $n } صفحة ويب
    }
tool-run-summary-browser = { $n ->
        [zero] لا إجراءات في المتصفح
        [one] إجراء واحد في المتصفح
        [two] إجراءان في المتصفح
        [few] { $n } إجراءات في المتصفح
        [many] { $n } إجراءً في المتصفح
       *[other] { $n } إجراء في المتصفح
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [zero] لا سرد لكيانات مستندات
        [one] سرد كيانات مستند واحد
        [two] سرد كيانات مستندين
        [few] سرد كيانات { $n } مستندات
        [many] سرد كيانات { $n } مستندًا
       *[other] سرد كيانات { $n } مستند
    }
tool-run-summary-cited = { $n ->
        [zero] لا استشهاد بمستندات
        [one] استشهاد بمستند واحد
        [two] استشهاد بمستندين
        [few] استشهاد بـ{ $n } مستندات
        [many] استشهاد بـ{ $n } مستندًا
       *[other] استشهاد بـ{ $n } مستند
    }
tool-run-summary-cited-web = { $n ->
        [zero] لا استشهاد بصفحات ويب
        [one] استشهاد بصفحة ويب واحدة
        [two] استشهاد بصفحتي ويب
        [few] استشهاد بـ{ $n } صفحات ويب
        [many] استشهاد بـ{ $n } صفحة ويب
       *[other] استشهاد بـ{ $n } صفحة ويب
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [zero] لا قراءة لمهارات ونصوص أدوات
        [one] قراءة مهارة واحدة ونصوص الأدوات
        [two] قراءة مهارتين ونصوص الأدوات
        [few] قراءة { $n } مهارات ونصوص الأدوات
        [many] قراءة { $n } مهارة ونصوص الأدوات
       *[other] قراءة { $n } مهارة ونصوص الأدوات
    }
tool-run-summary-saved = { $n ->
        [zero] لا حفظ لملاحظات
        [one] حفظ ملاحظة واحدة
        [two] حفظ ملاحظتين
        [few] حفظ { $n } ملاحظات
        [many] حفظ { $n } ملاحظة
       *[other] حفظ { $n } ملاحظة
    }
tool-run-summary-todo-list = { $n ->
        [zero] لا استدعاءات لقائمة المهام
        [one] استدعاء واحد لقائمة المهام
        [two] استدعاءان لقائمة المهام
        [few] { $n } استدعاءات لقائمة المهام
        [many] { $n } استدعاءً لقائمة المهام
       *[other] { $n } استدعاء لقائمة المهام
    }
tool-run-summary-to-the-agent = { $n ->
        [zero] لا تعليمات إلى الوكيل
        [one] تعليمة واحدة إلى الوكيل
        [two] تعليمتان إلى الوكيل
        [few] { $n } تعليمات إلى الوكيل
        [many] { $n } تعليمة إلى الوكيل
       *[other] { $n } تعليمة إلى الوكيل
    }
tool-run-summary-other = { $n ->
        [zero] لا استدعاءات أخرى
        [one] استدعاء آخر واحد
        [two] استدعاءان آخران
        [few] { $n } استدعاءات أخرى
        [many] { $n } استدعاءً آخر
       *[other] { $n } استدعاء آخر
    }
tool-run-summary-failed = فشل { $failures }
tool-run-summary-took = استغرق { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
        [zero] لا رسائل
        [one] رسالة واحدة
        [two] رسالتان
        [few] { $session_message_count } رسائل
        [many] { $session_message_count } رسالة
       *[other] { $session_message_count } رسالة
    }

chat-tool-disclosure-item = { $count ->
        [zero] لا عناصر
        [one] عنصر واحد
        [two] عنصران
        [few] { $count } عناصر
        [many] { $count } عنصرًا
       *[other] { $count } عنصر
    }
chat-tool-disclosure-field = { $count ->
        [zero] لا حقول
        [one] حقل واحد
        [two] حقلان
        [few] { $count } حقول
        [many] { $count } حقلًا
       *[other] { $count } حقل
    }
chat-tool-disclosure-searched-collections = بحث في المجموعات{ $filters }
chat-tool-disclosure-searched-collections-2 = بحث في المجموعات · { $query }{ $filters }
chat-tool-disclosure-cited-documents = استشهاد بمستندات: { $n }
chat-tool-disclosure-read-document = قراءة مستند · { $path }
chat-tool-disclosure-searched-the-web = بحث في الويب · { $q }
chat-tool-disclosure-opened-page = فتح صفحة · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = استدعاء { $other }
chat-tool-disclosure-called-2 = استدعاء { $other } · { $short }
cards-browser-card-opened = فتح { $url }
cards-browser-card-could-not-open = تعذّر فتح { $url }
cards-browser-card-clicked = نقر على { $element }
cards-browser-card-could-not-click = تعذّر النقر على { $element }
cards-browser-card-typed-into = كتابة في { $element }
cards-browser-card-could-not-type-into = تعذّرت الكتابة في { $element }
cards-browser-card-typed = كتابة “{ $text }”
cards-browser-card-could-not-type = تعذّرت كتابة “{ $text }”
cards-browser-card-pressed = ضغط على { $key }
cards-browser-card-could-not-press = تعذّر الضغط على { $key }
cards-browser-card-chose-an-option-in = اختيار خيار في { $element }
cards-browser-card-could-not-choose-an-option = تعذّر اختيار خيار في { $element }
cards-browser-card-hovered = تمرير المؤشر فوق { $element }
cards-browser-card-could-not-hover = تعذّر تمرير المؤشر فوق { $element }
cards-browser-card-failed = { $bare } — فشل
cards-entities-card-listed-entities-document = سرد الكيانات · { $count ->
        [zero] لا مستندات
        [one] مستند واحد
        [two] مستندان
        [few] { $count } مستندات
        [many] { $count } مستندًا
       *[other] { $count } مستند
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · الجزء { $part } من { $name } #{ $seq }
cards-result-cards-documents = {" "}· المستندات: { $value }
cards-result-cards-forms = { $tool_name } · الصيغ: { $forms }
cards-result-cards-in = {" "}في { $collections }
cards-result-cards-page = {" "}· الصفحة { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · المستندات: { $citations_len } · اقتباسات لم يُعثر عليها: { $missing }
cards-result-cards-version-unchanged = { $tool_name } · الإصدار { $version } · دون تغيير
cards-result-cards-version = { $tool_name } · الإصدار { $version }
web-search-card-results-in-after-deduplication = الواردة { $json_u64_doc_total_before_dedupe } نتيجة، وبعد إزالة التكرار { $json_u64_doc_total_after_dedupe }

board-status-on = مفعّل

board-status-off = معطّل

chat-transcript-generic-tool = الأداة
