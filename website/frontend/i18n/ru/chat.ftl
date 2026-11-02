# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Бот работает...
chat-composer-ask-the-bot = Спросить у агента...
chat-composer-internet-tools = Интернет-инструменты
chat-composer-agent-language-title = Агент отвечает на языке { $language }. Изменить язык можно в настройках, в новой вкладке.
chat-composer-try-again-in-s = Повторите попытку через { $secs } с
chat-composer-stop-the-answer-the-partial = Остановить ответ (частичный ответ не сохраняется в диалоге)
chat-composer-starting-the-conversation-u = Начало диалога…
chat-composer-send = Отправить
chat-conversation-find-search-in-conversation = Поиск в диалоге
chat-conversation-find-previous-match = Предыдущее совпадение
chat-conversation-find-next-match = Следующее совпадение
chat-conversation-find-investigation-board = Доска расследования
doc-ref-card-not-openable = Не открывается: { $reason }.
doc-ref-card-the-search-term-was = Термин поиска{ " " }
doc-ref-card-open = Открыть
doc-ref-card-not-openable-2 = Не открывается
chat-markdown-text-show-the-cited-source = Показать процитированный источник
chat-markdown-text-no-citation-of-this-conversation = Ни одна цитата этого диалога не даёт данного идентификатора, поэтому за ним не стоит ни одного документа.
chat-markdown-text-citations-of-this-conversation-gave = Цитаты этого диалога присвоили данный идентификатор более чем одному документу, поэтому он не ссылается ни на один из них.
cards-browser-card-open-the-archived-page = Открыть архивную страницу
cards-browser-card-the-page-itself-was-not = Сама страница не была архивирована (состояние: { $artifact_status }). Скриншот выше — то, что удалось сохранить.
cards-browser-card-click-the-screenshot-to-open = Нажмите на скриншот, чтобы открыть архивную страницу.
cards-browser-card-show-less = Показать меньше
cards-browser-card-show-all = Показать все
cards-browser-card-archived-page = Архивная страница
cards-browser-card-download = Скачать
cards-browser-card-archived-copy-of = Архивная копия { $artifact_url }
cards-browser-card-this-page-was-not-archived = Эта страница не была архивирована (состояние: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } с карточкой
cards-entities-card-the-entity-list-was-cut = Список объектов был обрезан.
cards-entities-card-open-the-card-for-this = Открыть карточку для этого значения ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Карточки нет: этот разговор никогда не называл набор данных источником этих значений, и к просмотривающему обращаются по набору данных.
cards-entities-card-more-all-of-them-in = { $rest } больше, все они на панели объектов документа.{ " " }
cards-entities-card-names-organisations-and-places-above = Имена, организации и места выше — это прочтение текста моделью. Никакое правило их не проверило, поэтому объяснять нечего, и они ничего не открывают.
cards-entities-card-nothing-extracted-from-this-document = Из этого документа ничего не извлечено.
chat-tool-cards-hide = Скрыть
chat-tool-cards-expand = Развернуть
chat-tool-cards-hide-raw-json = Скрыть необработанный JSON
chat-tool-cards-show-raw-json = Показать необработанный JSON
cards-result-cards-search-this = Искать это
cards-result-cards-search-every-collection = Искать во всех коллекциях
cards-result-cards-form = Форма { $index }: { $form }
cards-result-cards-show-full-text = Показать полный текст
cards-result-cards-quote = Цитата: { $quote }
cards-result-cards-reason = Причина: { $why }
cards-result-cards-open-question = Открытый вопрос: { $question }
cards-result-cards-the-explore-gave-this-answer =
    Исследование дало этот ответ своей доске как { $kind ->
        [sourced] проверенный
        [inferred] выведенный
        [not_found] не найденный
       *[other] неизвестного вида
    } находку.
cards-result-cards-it-left-no-open-question = Оно не оставило открытого вопроса.
cards-result-cards-open-questions-for-the-board = Открытые вопросы для доски:
cards-result-cards-arguments = Аргументы
cards-result-cards-list-after-the-call = Список после вызова: { $snapshot_goal }
cards-result-cards-replaces = { " " }· заменяет { $replaces_id }
cards-result-cards-the-list-at-this-version = Список в этой версии не сохранён.
web-search-card-these-sources-returned-nothing-so = Эти источники ничего не вернули, поэтому результаты получены из меньшего числа, чем планировалось
web-search-card-u-degraded = ⚠ { $degraded_len } ухудшено
web-search-card-form = Форма { $index }: { $form }
web-search-card-no-results-from = Нет результатов из: { $degraded_text }
web-search-card-no-results-every-source-answered = Результатов нет. Каждый источник ответил, и ни один не нашёл для этого запроса.
web-search-card-the-lowest-ranked-results-were = Самые низко ранжированные результаты отброшены, чтобы этот вызов поместился в транскрипт. Ассистент видел все их.
web-search-card-view-search-details = Просмотреть детали поиска.
web-search-card-the-stored-result-could-not = сохранённый результат не удалось прочитать обратно в формате JSON
web-search-card-nothing-was-stored-for-this = Для этого запроса ничего не сохранено.
web-search-card-forms = Формы: { $forms }
web-search-card-kind = Тип: { $row_kind }
web-search-card-published = Опубликовано: { $row_published }
web-search-card-loading-search-detail-u = Загрузка деталей поиска…
web-search-card-could-not-load-the-search = Не удалось загрузить детали поиска: { $e }
web-search-card-malformed-detail = Некорректные детали: { $e }
web-search-card-the-tool-returned-selected-results = Инструмент вернул отобранные результаты в модель.
web-search-card-results-use-reciprocal-rank-fusion = Результаты отсортированы с помощью слияния по рангам.
web-search-card-returned-nothing = ничего не вернул: { $degraded }
web-search-card-all-candidates-use-fusion-order = Все кандидаты отсортированы с помощью слияния по рангам.
web-search-card-the-cross-encoder-ranks-selected = Кросс-энкодер сортирует отобранные результаты.
web-search-card-selected-results-use-fusion-order = Обранные результаты отсортированы с помощью слияния по рангам.
web-search-card-search-detail = Детали поиска
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Искать здесь
chat-tool-disclosure-search-every-collection = Искать во всех коллекциях
chat-tool-disclosure-hide = Скрыть
chat-tool-disclosure-expand = Развернуть
chat-tool-disclosure-this-step-was-recorded-before = Этот шаг был записан до сохранения аргументов и результатов инструмента. Доступна только приведённая ниже сводка.
chat-tool-disclosure-arguments = Аргументы
chat-tool-disclosure-result = Результат
chat-tool-disclosure-hide-raw-json = Скрыть необработанный JSON
chat-tool-disclosure-show-raw-json = Показать необработанный JSON
chat-tool-disclosure-input-json = Входной JSON
chat-tool-disclosure-output-json = Выходной JSON
chat-transcript-ask-a-question-about-the = Задайте вопрос по документам в ваших коллекциях.
chat-transcript-suggested-next = Предлагаемый следующий…
chat-transcript-earlier-answer = Ранее ответ
chat-transcript-tokens-the-conversation-carries-the = Токены, которые несёт разговор, крупнейший единый контекст, за который был начислен счёт за этот ход, и сколько из окна модели это заняло
chat-transcript-instruction-to-the-agent = Инструкция для агента
chat-transcript-the-context-stays-above-the = Контекст остаётся выше целевого значения { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } частей резюме не удалось. В записи содержатся только списки.
chat-transcript-show-the-record = Показать запись
chat-transcript-hide-reasoning = Скрыть рассуждения
chat-transcript-show-reasoning = Показать рассуждения
chat-transcript-from-u-hide = { $count } { $count ->
        [one] document
       *[other] documents
    } из { $tool } — скрыть
chat-transcript-from-u-show = { $count } { $count ->
        [one] document
       *[other] documents
    } из { $tool } — показать
chat-transcript-u-hide = { $summary } — скрыть
chat-transcript-u-show = { $summary } — показать
chat-transcript-citations-of-this-conversation-give = Ссылки в этом разговоре дают { $doc_handle } более чем к одному документу. Ответ связывает его ни с одним из них.
chat-transcript-report = Пожаловаться на { $label }
chat-transcript-open-in-the-workspace = Открыть в рабочем пространстве
chat-transcript-this-version-could-not-be = Эту версию нельзя прочитать. Ниже следует текст чата с ответом.
chat-transcript-files = Файлы
chat-transcript-version = { $file_name }, версия { $file_version }
chat-web-find-exact-text = Найти точное совпадение
chat-web-previous-match = Предыдущее совпадение
chat-web-next-match = Следующее совпадение
chat-web-close-preview = Закрыть предпросмотр
chat-web-the-captured-page-could-not = Захваченную страницу нельзя загрузить.
chat-web-loading = Загрузка…
chat-workspace-pane-workspace = Рабочее пространство
chat-workspace-pane-close-the-workspace = Закрыть рабочее пространство
chat-workspace-pane-close = Закрыть
chat-workspace-pane-loading-the-files-u = Загрузка файлов…
chat-workspace-pane-the-files-could-not-be = Файлы нельзя загрузить: { $error }
chat-workspace-pane-this-conversation-has-no-files = В этом разговоре нет файлов.
chat-workspace-pane-version = версия { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Выберите файл, чтобы прочитать его.
chat-workspace-pane-loading-the-file-u = Загрузка файла…
chat-workspace-pane-the-file-could-not-be = Не удалось загрузить файл: { $error }
chat-workspace-pane-version-2 = { $found_name }, версия { $found_version }
chat-board-create-collections = Коллекции
chat-board-create-loading-collections-u = Загрузка коллекций…
chat-board-create-hoover-search-new-board = Поиск Hoover — новая доска
chat-board-create-ai-chat = Чат AI
chat-board-create-new-investigation-board = Новая доска расследования
chat-board-create-a-board-runs-its-goals = Доска выполняет свои цели в виде последовательности исследований агента. Каждое исследование — это чат, который завершается одной находкой на доске. Вы просматриваете ответ каждой цели, а во время работы можете отклонять находки и добавлять подсказки.
chat-board-create-title = Заголовок
chat-board-create-goal = Цель
chat-board-create-remove-this-goal = Удалить эту цель
chat-board-create-remove = Удалить
chat-board-create-add-a-goal = Добавить цель
chat-board-create-context-optional = Контекст (необязательно)
chat-board-create-hints-one-per-line-optional = Подсказки, по одной на строку (необязательно)
chat-board-create-sources = Источники
chat-board-create-internet-tools = Интернет-инструменты
chat-board-create-creating-board = Создание доски...
chat-board-create-create-board = Создать доску
ai-chat-board-hoover-search-board = Поиск Hoover — доска
ai-chat-board-loading-the-board-u = Загрузка доски…
ai-chat-board-show-the-board-overview = Показать обзор доски
ai-chat-board-zoom-out = Уменьшить
ai-chat-board-zoom-in = Увеличить
ai-chat-board-u-ai-chat = ← Чат AI
ai-chat-board-settings = Настройки
ai-chat-board-board-settings = Настройки доски
ai-chat-board-internet-tools = Интернет-инструменты
ai-chat-board-the-next-explores-of-the = Следующие исследования доски могут искать в вебе и читать веб-страницы. В работающих исследованиях сохраняется настройка, с которой они начали.
ai-chat-board-collections = Коллекции
ai-chat-board-the-collections-are-fixed-when = Коллекции фиксируются в момент создания доски.
ai-chat-board-confirm-drop = Подтвердить отключение
ai-chat-board-drop-the-board = Отключить доску
ai-chat-board-close = Закрыть
ai-chat-board-the-board-used-its-explore = Доска исчерпала лимит исследований
ai-chat-board-the-board-used-explores-the = Доска использовала { $explore_limit } исследований — лимит одной доски. Новая работа не запускается. Вы по-прежнему можете принять предложенные ответы.
ai-chat-board-create-a-new-board-to = Создайте новую доску, чтобы продолжить расследование
ai-chat-board-goal = Цель
ai-chat-board-goals = Цели
ai-chat-board-add-new-goal = Добавить новую цель...
ai-chat-board-a-new-goal = Новая цель
ai-chat-board-add-goal = Добавить цель
ai-chat-board-a-board-has-at-most = Доска может иметь не более { $max_goals } целей. Создайте новую доску для другой цели.
ai-chat-board-background-context = Контекст
ai-chat-board-continue-with-a-correction = Продолжить с исправлением
ai-chat-board-correction-what-is-wrong-or = Исправление: что не так или упущено. Доска продолжит работу с учётом этого.
ai-chat-board-the-board-waits-for-your = Доска ждёт вашей проверки
ai-chat-board-the-board-used-its-budget = Доска исчерпала бюджет из { $snap_max_explores } исследований.
ai-chat-board-the-assessments-gave-no-usable = Оценки не дали применимого направления.
ai-chat-board-accept-or-reject-the-proposed = Примите или отклоните предложенный ответ каждой цели выше. Отклонённый ответ позволит доске продолжить работу сразу.
ai-chat-board-no-proposed-answer-waits-for = Нет предложенного ответа, ждущего вашего решения.
ai-chat-board-reopen-the-board-to-continue = Откройте доску заново, чтобы продолжить открытые цели. Она сохранит находки и ответы.
ai-chat-board-close-the-board-to-accept = Закройте доску, чтобы принять все предложенные ответы и остановить её, или продолжите работу с исправлением.
ai-chat-board-close-the-board = Закрыть доску
ai-chat-board-or-reopen-the-board-to = Или откройте доску заново, чтобы продолжить открытые цели без исправления.
ai-chat-board-the-board-is-complete = Доска завершена
ai-chat-board-a-goal-has-no-accepted = У цели нет принятого ответа. Откройте доску заново, чтобы продолжить её. Доска сохранит находки и ответы.
ai-chat-board-add-a-hint = Добавить подсказку
ai-chat-board-the-next-assessment-reads-every = Следующая оценка читает каждую подсказку. Подсказка также отвечает на запрос исследования, который задавал вопрос.
ai-chat-board-add-hint = Добавить подсказку
ai-chat-board-events = События
ai-chat-board-newest-first = Сначала новые
ai-chat-board-date = Дата
ai-chat-board-actor = Исполнитель
ai-chat-board-event = Событие
ai-chat-board-show-details = Показать детали
ai-chat-board-open = Открыть
ai-chat-board-show-the-newest-events = Показать самые новые { $event_rows } события
ai-chat-board-show-all-events = Показать все { $snap_events_len } событий
ai-chat-board-statistics = Статистика
ai-chat-board-explores = Исследования
ai-chat-board-model-steps-per-explore = Шаги модели на одно исследование
ai-chat-board-assessments = Оценки
ai-chat-board-intents = Намерения
ai-chat-board-findings = Находки
ai-chat-board-created = Создано
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } отклонил(а) эту находку на { $format_utc_ms_fact_rejected_ms }. Доска больше её не использует.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } отклонил(а) эту находку. Доска больше её не использует.
ai-chat-board-no-reason-was-given = Причина не указана.
ai-chat-board-reason = Причина: { $fact_rejected_reason }
ai-chat-board-open-questions = Открытые вопросы
ai-chat-board-explored-in = Исследовано в
ai-chat-board-explore-this-question = Исследовать этот вопрос
ai-chat-board-your-questions = Ваши вопросы
ai-chat-board-ask-about-the-background-context = Спросить о фоновом контексте
ai-chat-board-ask-about-this-finding = Спросить об этой находке
ai-chat-board-a-follow-up-question-about = Дополнительный вопрос об этом узле
ai-chat-board-ask = Спросить
ai-chat-board-checks-that-changed-this-finding = Проверки, которые изменили эту находку
ai-chat-board-reject-this-correction = Отклонить это исправление
ai-chat-board-reject-this-finding = Отклонить эту находку
ai-chat-board-not-answered-the-board-was = Не отвечено. Доска завершена без ответа на эту цель. Подсказка или повторное открытие снова её открывают.
ai-chat-board-no-answer-yet = Ответа пока нет.
ai-chat-board-the-findings-of-this-answer = Находки этого ответа — это поиски, которые ничего не нашли. Примите, чтобы зафиксировать, что записи не отвечают на цель, или отклоните, чтобы продолжить расследование.
ai-chat-board-open-an-assessment-to-read = { "." } Откройте оценку, чтобы прочитать почему.
ai-chat-board-from-the-findings = Из находок{ " " }
ai-chat-board-accept-answer = Принять ответ
ai-chat-board-why-the-answer-is-wrong = Почему ответ неверен или неполон
ai-chat-board-reject-answer = Отклонить ответ
ai-chat-board-intent = Намерение
ai-chat-board-attempts-declared = Попытки: { $intent_attempts }. Объявлено { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Исследование спросило
ai-chat-board-add-a-hint-in-the = Добавьте подсказку в обзор доски, чтобы ответить на неё.
ai-chat-board-last-error = Последняя ошибка
ai-chat-board-brief = Краткое описание
ai-chat-board-open-the-explore-chat = Открыть чат исследования
ai-chat-board-loading-the-assessment-u = Загрузка оценки…
ai-chat-board-assessment = Оценка { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Модель { $a_model }. Результат { $a_outcome }. { $a_latency_ms } мс, { $tokens }.
ai-chat-board-checks-that-changed-it = Проверки, которые изменили её
ai-chat-board-prompt = Запрос
ai-chat-board-this-assessment-ran-before-the = Эта оценка была до того, как запросы были сохранены.
ai-chat-board-response = Ответ
ai-chat-history-hoover-search-chat-history = Hoover Search — история чата
ai-chat-history-u-back = ← Назад
ai-chat-history-conversation-history = История разговора
ai-chat-history-show-board-chats = Показать чаты доски
ai-chat-history-loading-u = Загрузка…
ai-chat-history-could-not-load-history = Не удалось загрузить историю: { $e }
ai-chat-history-no-conversations-yet = Пока нет ни одного разговора.
ai-chat-history-board = Доска
ai-chat-history-new-chat = Новый чат
ai-chat-history-messages-updated = { $s_message_count } сообщений · обновлено { $s_updated_at }
ai-chat-history-delete-conversation = Удалить разговор
ai-chat-history-delete = Удалить
ai-chat-homepage-hoover-search-ai-chat = Поиск Hoover — AI-чат
ai-chat-homepage-what-are-you-researching = Что вы исследуете?
ai-chat-homepage-view-all-conversations = Показать все разговоры
ai-chat-homepage-starting-conversation-u = Начало разговора…
ai-chat-homepage-investigation-boards = Доски расследований
ai-chat-homepage-new-board = Новая доска
ai-chat-homepage-loading-boards-u = Загрузка досок…
ai-chat-homepage-could-not-load-the-boards = Не удалось загрузить доски: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = У вас нет доски. Доска ведёт длительное расследование как последовательность исследований агента, а вы проверяете его ответы.
ai-chat-homepage-updated = Обновлено { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Поиск Hoover — AI-чат
ai-chat-session-this-conversation-could-not-be = Этот разговор не удалось загрузить.
ai-chat-session-loading-u = Загрузка…
ai-chat-session-u-chats = ← Чаты
ai-chat-session-history = История
ai-chat-session-show-the-files-that-the = Показать файлы, которые ассистент создал в этом разговоре
ai-chat-session-workspace = Рабочая область
ai-chat-session-this-answer-was-interrupted-before = Этот ответ был прерван до завершения, потому что страница или сервер остановились в середине хода. Запросите снова, чтобы повторить.
ai-chat-session-dismiss = Закрыть
ai-chat-session-board-explore-chats-are-read = Чаты исследований доски доступны только для чтения.{ " " }
ai-chat-session-open-the-board = Открыть доску
chat-locked-options-on = { $label }: включено
chat-locked-options-off = { $label }: отключено
chat-tool-cards-running-u = выполняется…
cards-result-cards-quote-found = Цитата найдена
cards-result-cards-quote-not-found = Цитата не найдена
cards-result-cards-quote-not-checked = Цитата не проверена
web-search-card-results = { $results_len } результатов
chat-tool-disclosure-running-u = выполняется…
chat-transcript-call = вызов
chat-transcript-calls = вызовы
ai-chat-board-a-board-without-collections-needs = Доска без коллекций нуждается в интернет-инструментах.
ai-chat-board-of = { $snap_explores_used } из { $snap_max_explores }
ai-chat-board-assessment-2 = оценка { $number }
ai-chat-history-messages = { $s_message_count } сообщений
web-search-card-reranked-in = Кросс-энкодер переранжировал результаты за { $ms } мс.
web-search-card-engine-results = { $name }: { $count } за { $ms } мс
web-search-card-score-was-rank = балл { $score } · было RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Ход ожидает свободного слота модели.
chat-activity-the-turn-waits-for-a-2 = Ход ожидает свободного слота инструмента.
chat-locked-options-start-a-new-chat-to = Начните новый чат, чтобы изменить эту настройку.
chat-locked-options-internet-tools = Интернет-инструменты
chat-session-card-new-chat = Новый чат
chat-tool-cards-first-frame-of-the-video = Первый кадр видео
chat-tool-cards-screenshot-of = Скриншот
chat-tool-cards-image = Изображение
cards-result-cards-the-agent-asked-a-question = Агент задал вопрос.
chat-transcript-hide = Скрыть
chat-transcript-show = Показать
chat-transcript-unverified-quote-the-quoted-span = Не проверенная цитата. Цитируемый фрагмент слишком короткий для проверки.
chat-transcript-unverified-quote-the-document-text = Не проверенная цитата. Текст документа не удалось прочитать.
chat-transcript-unverified-quote-this-wording-was = Не проверенная цитата. Эта формулировка не найдена в документе.
chat-board-create-select-a-collection-or-turn = Выберите коллекцию или включите интернет-инструменты.
chat-board-create-select-at-least-one-collection = Выберите как минимум одну Коллекцию.
ai-chat-board-active = Активная
ai-chat-board-paused = Приостановлена
ai-chat-board-waits-for-review = Ожидает проверки
ai-chat-board-completed = Завершена
ai-chat-board-dropped = Отклонена
ai-chat-board-unknown = Неизвестно
ai-chat-board-pause-the-board = Приостановить доску
ai-chat-board-resume-the-board = Возобновить доску
ai-chat-board-none = Нет
ai-chat-board-reopen-with-the-remaining-budget = Повторно открыть с оставшимся бюджетом
ai-chat-board-finding = Находка
ai-chat-board-why-the-correction-is-wrong = Почему исправление неверно
ai-chat-board-reject-correction = Отклонить исправление
ai-chat-board-why-the-finding-is-wrong = Почему находка неверно
ai-chat-board-reject-finding = Отклонить находку
ai-chat-board-answer = Ответ
ai-chat-board-proposed-answer = Предложенный ответ
ai-chat-homepage-active = Активная
ai-chat-homepage-paused = Приостановлена
ai-chat-homepage-waits-for-review = Ожидает проверки
ai-chat-homepage-completed = Завершена
ai-chat-homepage-dropped = Отклонена
ai-chat-homepage-unknown = Неизвестно
cards-result-cards-submitted-by-board =
    Предложено доской: { $kind ->
        [sourced] с источником
        [inferred] выведено
        [not_found] не найдено
       *[other] неизвестного вида
    } находка из отчёта
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Находка с источником
        [inferred] Находка, выведенная
        [not_found] Находка, не найденная
       *[other] Находка неизвестного вида
    } для доски
chat-transcript-compacting = Сжатие контекста: { $before } токенов до целевого значения { $target }.
chat-transcript-compaction-failed = Резюме предыдущих шагов не удалось. Модель получила предыдущие шаги без изменений, { $after } токенов.
chat-transcript-compacted = Контекст сжат: { $steps } шагов суммировано, { $before } токенов до { $after }.
ai-chat-board-reopen-with-more = Повторно открыть с { $grant } дополнительными исследованиями
ai-chat-board-goal-number = Цель { $number }
ai-chat-board-from-assessment-on = Из оценки { $number } на { $date }.
ai-chat-board-from-assessment = Из оценки { $number }.
chat-board-create-goal-2 = Цель { $index_1 }
ai-chat-session-lost-contact-with-the-chat = потерял связь с чатом: { $e }
ai-chat-session-could-not-stop-the-answer = не удалось остановить ответ: { $e } — он всё ещё выполняется
ai-chat-board-later-assessments-dropped-an-answer = { $n } последующих оценок отменили ответ для этой цели:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } токенов запроса и { $a_completion_tokens } токенов завершения
ai-chat-homepage-completed-goals-not-answered = Завершено, { $n } целей без ответа
board-graph-intent = намерение, { $state }
chat-workspace-pane-characters = { $chars } символов
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } выполняется инструмент { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } выполняется инструмент { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Отвечено после { $retries_len } неудачной попытки{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } неудачных попыток{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, версия { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] выполнен поиск { $n } запроса
        [few] выполнен поиск { $n } запросов
        [many] выполнен поиск { $n } запросов
       *[other] выполнен поиск { $n } запросов
    }
tool-run-summary-read =
    { $n ->
        [one] прочитан { $n } документ
        [few] прочитано { $n } документов
        [many] прочитано { $n } документов
       *[other] прочитано { $n } документов
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] выполнен поиск в интернете по { $n } запросу
        [few] выполнен поиск в интернете по { $n } запросам
        [many] выполнен поиск в интернете по { $n } запросам
       *[other] выполнен поиск в интернете по { $n } запросам
    }
tool-run-summary-read-web =
    { $n ->
        [one] прочитана { $n } веб-страница
        [few] прочитано { $n } веб-страниц
        [many] прочитано { $n } веб-страниц
       *[other] прочитано { $n } веб-страниц
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } действие в браузере
        [few] { $n } действий в браузере
        [many] { $n } действий в браузере
       *[other] { $n } действий в браузере
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] перечислены объекты { $n } документа
        [few] перечислены объекты { $n } документов
        [many] перечислены объекты { $n } документов
       *[other] перечислены объекты { $n } документов
    }
tool-run-summary-cited =
    { $n ->
        [one] приведена цитата из { $n } документа
        [few] приведены цитаты из { $n } документов
        [many] приведены цитаты из { $n } документов
       *[other] приведены цитаты из { $n } документов
    }
tool-run-summary-cited-web =
    { $n ->
        [one] приведена цитата из { $n } веб-страницы
        [few] приведены цитаты из { $n } веб-страниц
        [many] приведены цитаты из { $n } веб-страниц
       *[other] приведены цитаты из { $n } веб-страниц
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] прочитан { $n } текст навыка и инструментов
        [few] прочитано { $n } текстов навыков и инструментов
        [many] прочитано { $n } текстов навыков и инструментов
       *[other] прочитано { $n } текстов навыков и инструментов
    }
tool-run-summary-saved =
    { $n ->
        [one] сохранена { $n } заметка
        [few] сохранено { $n } заметок
        [many] сохранено { $n } заметок
       *[other] сохранено { $n } заметок
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } вызов списка задач
        [few] { $n } вызовов списка задач
        [many] { $n } вызовов списка задач
       *[other] { $n } вызовов списка задач
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } инструкция агенту
        [few] { $n } инструкций агенту
        [many] { $n } инструкций агенту
       *[other] { $n } инструкций агенту
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } другой вызов
        [few] { $n } других вызовов
        [many] { $n } других вызовов
       *[other] { $n } других вызовов
    }
tool-run-summary-failed = { $failures } неудач
tool-run-summary-took = занял { $duration_text_ms }
chat-session-card-messages = { $session_message_count } сообщений
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } элемент
       *[other] { $count } элементов
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } поле
       *[other] { $count } полей
    }
chat-tool-disclosure-searched-collections = искал в коллекциях{ $filters }
chat-tool-disclosure-searched-collections-2 = искал в коллекциях · { $query }{ $filters }
chat-tool-disclosure-cited-documents = процитировал { $n } документов
chat-tool-disclosure-read-document = прочитал документ · { $path }
chat-tool-disclosure-searched-the-web = искал в интернете · { $q }
chat-tool-disclosure-opened-page = открыл страницу · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = вызвал { $other }
chat-tool-disclosure-called-2 = вызвал { $other } · { $short }
cards-browser-card-opened = открыл { $url }
cards-browser-card-could-not-open = не удалось открыть { $url }
cards-browser-card-clicked = нажал на { $element }
cards-browser-card-could-not-click = не удалось нажать на { $element }
cards-browser-card-typed-into = ввёл текст в { $element }
cards-browser-card-could-not-type-into = не удалось ввести текст в { $element }
cards-browser-card-typed = ввёл «{ $text }»
cards-browser-card-could-not-type = не удалось ввести «{ $text }»
cards-browser-card-pressed = нажал { $key }
cards-browser-card-could-not-press = не удалось нажать { $key }
cards-browser-card-chose-an-option-in = выбрал вариант в { $element }
cards-browser-card-could-not-choose-an-option = не удалось выбрать вариант в { $element }
cards-browser-card-hovered = наводил курсор на { $element }
cards-browser-card-could-not-hover = не удалось навести курсор на { $element }
cards-browser-card-failed = { $bare } — сбой
cards-entities-card-listed-entities-document = перечислил объекты · { $count } документ{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · часть { $part } из { $name } #{ $seq }
cards-result-cards-documents = · { $value } документов
cards-result-cards-forms = { $tool_name } · { $forms } форм
cards-result-cards-in = · в { $collections }
cards-result-cards-page = · страница { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } документов · { $missing } цитат не найдено
cards-result-cards-version-unchanged = { $tool_name } · версия { $version } · без изменений
cards-result-cards-version = { $tool_name } · версия { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } результатов, { $json_u64_doc_total_after_dedupe } после дедупликации
