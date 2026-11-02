# Translation of en/notes.ftl. Change it together with the English catalog.

## Discovery

note-discovery-l2 = لم يجد آخر بحثين أي مصدر جديد. اقرأ الآن أفضل صفحات النتائج: ضع حتى 6 من عناوينها في استدعاء واحد لـ read_page، في قائمة `urls` الخاصة به. ابحث مرة أخرى بسؤال مختلف فقط.
note-discovery-l3-web = أجبت قبل قراءة أي صفحة مصدر. استدعِ read_page مرة واحدة بعناوين الصفحات التي تدعم عناصرك، حتى 6 في قائمة `urls` الخاصة به. ثم اكتب الإجابة من جديد بالمصادر التي تدعمها.
note-discovery-l3-documents = أجبت قبل قراءة أي مستند. اقرأ المستندات التي تدعم عناصرك باستخدام read_documents، مع عدة تجزئات ملفات في استدعاء واحد. ثم اكتب الإجابة من جديد بالمصادر التي تدعمها.
note-discovery-l4 = اقرأ الآن صفحات النتائج التي قد تجيب عن الطلب: ضع حتى 6 من عناوينها في استدعاء واحد لـ read_page، في قائمة `urls` الخاصة به. يقرؤها استدعاء واحد كلها في وقت واحد.

## Page captures

note-capture-empty = لا يحتوي التقاط { $urls } على نص مقال. اقرأ مصدرًا آخر. لا تستشهد بهذه الصفحة.

## Sources

note-web-tools-absent = لا تتوفر في هذا الدور أدوات ويب، لذا لا يمكنه قراءة صفحات الويب العامة. استخدم المجموعات المحددة، وبيّن أي جزء من الطلب لا تجيب عنه.
note-sources-documents = ابحث أولًا في مجموعات المستندات المسموح بها. اقرأ مستنداتها ذات الصلة.
note-sources-documents-before-web = ابحث أولًا في مجموعات المستندات المسموح بها. اقرأ مستنداتها ذات الصلة. اقرأ تلك المستندات قبل استخدام الويب.

## Named things

note-absent-collection = لا توجد مجموعة مسموح بها باسم { $name }. المجموعات المسموح بها هي { $collections }.
note-absent-name = لا توجد في المجموعات المحددة مطابقة مفهرسة لـ { $name }.
note-absent-close-forms = الصيغ القريبة المفهرسة: { $forms }. لا تستخدم صيغة قريبة بوصفها الاسم المطلوب. عندما تبحث عن إحداها، سمِّها في الإجابة تهجئة مختلفة.
note-absent-close-form = { $form } (المستندات: { $count })
note-absent-web = يمكن لأدوات الويب في هذا الدور البحث عن الاسم.

## Search progress

note-progress-level = مستوى تقدم البحث { $level }.
note-progress-searches = عمليات البحث التي أُجريت بالفعل:
note-progress-search = { $name } { $args }: العناصر { $items }، مطابقات الكلمات المفتاحية { $matches }.
note-progress-available = خطوات البحث التي ما زالت متاحة:
note-progress-complete = اكتملت خطوات البحث المتاحة.
note-progress-write-now = اكتب الإجابة أو التقرير الآن. بيّن ما لا تحتويه المصادر التي قرأتها، وسمِّ عمليات البحث.
note-progress-answer-next = يجب أن يكون ردك التالي هو الإجابة. بيّن الوقائع الناقصة وعمليات البحث التي أجريتها.
note-progress-step-quoted = ابحث عن كل اسم كعبارة بين علامتي اقتباس باستخدام search_collections.
note-progress-step-variants = ابحث عن كلمات بلا علامات اقتباس وعن صيغ الاسم المختلفة. اقرأ أعداد الكلمات والتهجئات المرشحة.
note-progress-step-filters = أزل المرشّحات واحدًا تلو الآخر وأجرِ بحثًا بلا مرشّحات.
note-progress-step-facets = تحقق من قيم المرشّحات باستخدام search_facet_values.
note-progress-step-dates = تحقق من التواريخ باستخدام search_histogram.
note-progress-step-passages = ابحث عن وصف للمحتوى باستخدام search_passages.
note-progress-step-folder = استخدم { $tool } للمجلد أو المسار أو الملف المطلوب.
note-progress-step-read-hits = اقرأ أفضل نتيجة إلى ثلاث نتائج باستخدام { $tool }.
note-progress-step-web-search = ابحث في الويب باستخدام web_search واقرأ أفضل صفحات النتائج.
note-progress-step-page-find = ابحث في النص المحفوظ لصفحة طويلة باستخدام read_page وfind.
note-progress-step-page-retry = اقرأ عنوان نتيجة آخر، أو النسخة المؤرشفة لصفحة فشلت.
note-advice-stuck = يقدّر فحص المحادثة أن عمليات البحث الأخيرة تكرر نتائجها. تصف مهارة no_results صيغًا أخرى للبحث.
note-advice-absent = يقدّر فحص المحادثة أن النتائج لا تحتوي على ما تطلبه المهمة. بيّن نطاق البحث قبل أن تبلّغ عن غياب.
note-advice-completion = يقدّر فحص المحادثة أن النتائج يمكن أن تجيب عن المهمة. قارن كل جزء مطلوب بالمصادر التي قرأتها قبل أن تجيب.
note-progress-ended = انتهى التشغيل بعد عمليات بحث متكررة بلا تقدم.
note-progress-ended-none = لم يُعثر على أي مصدر مطابق للكلمات المفتاحية.
note-progress-ended-some = وجدت عمليات البحث مصادر مطابقة للكلمات المفتاحية عددها { $count }. لم يكمل الوكيل إجابته.
note-progress-ended-searches = عمليات البحث التي أُجريت:
