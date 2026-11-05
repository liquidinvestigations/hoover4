# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = Бот работает...
chat-composer-ask-the-bot = Спросите бота...
chat-composer-internet-tools = Интернет-инструменты
chat-composer-agent-language-title = Агент отвечает на языке: { $language }. Язык меняется в настройках, в новой вкладке.
chat-composer-try-again-in-s = Повторите через { $secs } с
chat-composer-stop-the-answer-the-partial = Остановить ответ (неполный ответ не сохраняется в беседе)
chat-composer-starting-the-conversation-u = Начало беседы…
chat-composer-send = Отправить
chat-conversation-find-search-in-conversation = Поиск в беседе
chat-conversation-find-previous-match = Предыдущее совпадение
chat-conversation-find-next-match = Следующее совпадение
chat-conversation-find-investigation-board = Доска расследования
doc-ref-card-not-openable = Не открывается: { $reason }.
doc-ref-card-the-search-term-was = Искомый термин:{" "}
doc-ref-card-open = Открыть
doc-ref-card-not-openable-2 = Не открывается
chat-markdown-text-show-the-cited-source = Показать цитируемый источник
chat-markdown-text-no-citation-of-this-conversation = Ни одна ссылка этой беседы не присвоила эту метку, поэтому за ней не стоит ни один документ.
chat-markdown-text-citations-of-this-conversation-gave = Ссылки этой беседы присвоили эту метку нескольким документам, поэтому она не ведёт ни к одному из них.
cards-browser-card-open-the-archived-page = Открыть архивную страницу
cards-browser-card-the-page-itself-was-not = Сама страница не заархивирована (состояние: { $artifact_status }). Сохранён только снимок экрана выше.
cards-browser-card-click-the-screenshot-to-open = Нажмите на снимок экрана, чтобы открыть архивную страницу.
cards-browser-card-show-less = Показать меньше
cards-browser-card-show-all = Показать всё
cards-browser-card-archived-page = Архивная страница
cards-browser-card-download = Скачать
cards-browser-card-archived-copy-of = Архивная копия { $artifact_url }
cards-browser-card-this-page-was-not-archived = Эта страница не заархивирована (состояние: { $artifact_status }).
cards-entities-card-with-a-card = С карточкой: { $openable }
cards-entities-card-the-entity-list-was-cut = Список сущностей обрезан.
cards-entities-card-open-the-card-for-this = Открыть карточку этого значения ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Карточки нет: эта беседа ни разу не назвала набор данных, из которого взяты значения, а просмотр открывается по набору данных.
cards-entities-card-more-all-of-them-in = Ещё { $rest }, все они в панели сущностей документа.{" "}
cards-entities-card-names-organisations-and-places-above = Имена, организации и места выше получены чтением текста моделью. Ни одно правило их не проверяло, поэтому объяснять нечего, и они ничего не открывают.
cards-entities-card-nothing-extracted-from-this-document = Из этого документа ничего не извлечено.
chat-tool-cards-hide = Свернуть
chat-tool-cards-expand = Развернуть
chat-tool-cards-hide-raw-json = Скрыть исходный JSON
chat-tool-cards-show-raw-json = Показать исходный JSON
cards-result-cards-search-this = Искать это
cards-result-cards-search-every-collection = Искать во всех коллекциях
cards-result-cards-form = Вариант запроса { $index }: { $form }
cards-result-cards-show-full-text = Показать весь текст
cards-result-cards-quote = Цитата: { $quote }
cards-result-cards-reason = Причина: { $why }
cards-result-cards-open-question = Открытый вопрос: { $question }
cards-result-cards-the-explore-gave-this-answer = Исследование передало этот ответ доске как { $kind ->
        [sourced] подтверждённую источниками
        [inferred] предположительную
        [not_found] отрицательную
       *[other] неопознанную
    } находку.
cards-result-cards-it-left-no-open-question = Открытых вопросов оно не оставило.
cards-result-cards-open-questions-for-the-board = Открытые вопросы для доски:
cards-result-cards-arguments = Аргументы
cards-result-cards-list-after-the-call = Список после вызова: { $snapshot_goal }
cards-result-cards-replaces = {" "}· заменяет { $replaces_id }
cards-result-cards-the-list-at-this-version = Список этой версии не сохранён.
web-search-card-these-sources-returned-nothing-so = Эти источники ничего не вернули, поэтому результаты получены из меньшего числа источников, чем задумано
web-search-card-u-degraded = ⚠ Ограничено: { $degraded_len }
web-search-card-form = Вариант запроса { $index }: { $form }
web-search-card-no-results-from = Нет результатов от: { $degraded_text }
web-search-card-no-results-every-source-answered = Результатов нет. Все источники ответили, но ни у одного не нашлось ничего по этому запросу.
web-search-card-the-lowest-ranked-results-were = Результаты с самым низким рангом убраны, чтобы вызов поместился в стенограмму. Ассистент видел их все.
web-search-card-view-search-details = Показать сведения о поиске.
web-search-card-the-stored-result-could-not = сохранённый результат не удалось прочитать как JSON
web-search-card-nothing-was-stored-for-this = Для этого вызова ничего не сохранено.
web-search-card-forms = Варианты запроса: { $forms }
web-search-card-kind = Тип: { $row_kind }
web-search-card-published = Опубликовано: { $row_published }
web-search-card-loading-search-detail-u = Загрузка сведений о поиске…
web-search-card-could-not-load-the-search = Не удалось загрузить сведения о поиске: { $e }
web-search-card-malformed-detail = Некорректные сведения: { $e }
web-search-card-the-tool-returned-selected-results = Инструмент вернул модели отобранные результаты.
web-search-card-results-use-reciprocal-rank-fusion = Результаты упорядочены методом взаимного слияния рангов (RRF).
web-search-card-returned-nothing = ничего не вернули: { $degraded }
web-search-card-all-candidates-use-fusion-order = Все кандидаты идут в порядке слияния.
web-search-card-the-cross-encoder-ranks-selected = Кросс-энкодер ранжирует отобранные результаты.
web-search-card-selected-results-use-fusion-order = Отобранные результаты идут в порядке слияния.
web-search-card-search-detail = Сведения о поиске
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Искать это
chat-tool-disclosure-search-every-collection = Искать во всех коллекциях
chat-tool-disclosure-hide = Свернуть
chat-tool-disclosure-expand = Развернуть
chat-tool-disclosure-this-step-was-recorded-before = Этот шаг записан до того, как начали сохранять аргументы и результаты инструментов. Доступна только краткая сводка ниже.
chat-tool-disclosure-arguments = Аргументы
chat-tool-disclosure-result = Результат
chat-tool-disclosure-hide-raw-json = Скрыть исходный JSON
chat-tool-disclosure-show-raw-json = Показать исходный JSON
chat-tool-disclosure-input-json = Входной JSON
chat-tool-disclosure-output-json = Выходной JSON
chat-transcript-ask-a-question-about-the = Задайте вопрос о документах ваших коллекций.
chat-transcript-suggested-next = Предлагаемые следующие шаги...
chat-transcript-earlier-answer = Предыдущий ответ
chat-transcript-tokens-the-conversation-carries-the = Токены, которые несёт беседа, самый большой отдельный контекст, за который выставлен счёт в этом ходе, и какую часть окна модели он занял
chat-transcript-instruction-to-the-agent = Указание агенту
chat-transcript-the-context-stays-above-the = {" "}Контекст остаётся выше целевого значения: { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}Не удалось составить частей сводки: { $failed }. В записи остались только списки.
chat-transcript-show-the-record = Показать запись
chat-transcript-hide-reasoning = Скрыть рассуждения
chat-transcript-show-reasoning = Показать рассуждения
chat-transcript-from-u-hide = { $count } { $count ->
        [one] документ
        [few] документа
        [many] документов
       *[other] документа
    } из { $tool } — скрыть
chat-transcript-from-u-show = { $count } { $count ->
        [one] документ
        [few] документа
        [many] документов
       *[other] документа
    } из { $tool } — показать
chat-transcript-u-hide = { $summary } — скрыть
chat-transcript-u-show = { $summary } — показать
chat-transcript-citations-of-this-conversation-give = Ссылки этой беседы присваивают метку { $doc_handle } нескольким документам. Ответ не связывает её ни с одним из них.
chat-transcript-report = Отчёт { $label }
chat-transcript-open-in-the-workspace = Открыть в рабочей области
chat-transcript-this-version-could-not-be = Эту версию не удалось прочитать. Ниже идёт текст ответа из чата.
chat-transcript-files = Файлы
chat-transcript-version = { $file_name }, версия { $file_version }
chat-web-find-exact-text = Найти точный текст
chat-web-previous-match = Предыдущее совпадение
chat-web-next-match = Следующее совпадение
chat-web-close-preview = Закрыть предпросмотр
chat-web-the-captured-page-could-not = Не удалось загрузить сохранённую страницу.
chat-web-loading = Загрузка…
chat-workspace-pane-workspace = Рабочая область
chat-workspace-pane-close-the-workspace = Закрыть рабочую область
chat-workspace-pane-close = Закрыть
chat-workspace-pane-loading-the-files-u = Загрузка файлов…
chat-workspace-pane-the-files-could-not-be = Не удалось загрузить файлы: { $error }
chat-workspace-pane-this-conversation-has-no-files = В этой беседе нет файлов.
chat-workspace-pane-version = версия { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Выберите файл, чтобы прочитать его.
chat-workspace-pane-loading-the-file-u = Загрузка файла…
chat-workspace-pane-the-file-could-not-be = Не удалось загрузить файл: { $error }
chat-workspace-pane-version-2 = { $found_name }, версия { $found_version }
chat-board-create-collections = Коллекции
chat-board-create-loading-collections-u = Загрузка коллекций…
chat-board-create-hoover-search-new-board = Hoover Search - Новая доска
chat-board-create-ai-chat = ИИ-чат
chat-board-create-new-investigation-board = Новая доска расследования
chat-board-create-a-board-runs-its-goals = Доска выполняет свои цели как последовательность исследований агента. Каждое исследование — это чат, который заканчивается одной находкой доски. Вы проверяете ответ на каждую цель, а пока доска работает, можете отклонять находки и добавлять подсказки.
chat-board-create-title = Название
chat-board-create-goal = Цель
chat-board-create-remove-this-goal = Удалить эту цель
chat-board-create-remove = Удалить
chat-board-create-add-a-goal = Добавить цель
chat-board-create-context-optional = Контекст (необязательно)
chat-board-create-hints-one-per-line-optional = Подсказки, по одной в строке (необязательно)
chat-board-create-sources = Источники
chat-board-create-internet-tools = Интернет-инструменты
chat-board-create-creating-board = Создание доски...
chat-board-create-create-board = Создать доску
ai-chat-board-hoover-search-board = Hoover Search - Доска
ai-chat-board-loading-the-board-u = Загрузка доски…
ai-chat-board-show-the-board-overview = Показать обзор доски
ai-chat-board-zoom-out = Уменьшить
ai-chat-board-zoom-in = Увеличить
ai-chat-board-u-ai-chat = ← ИИ-чат
ai-chat-board-settings = Настройки
ai-chat-board-board-settings = Настройки доски
ai-chat-board-internet-tools = Интернет-инструменты
ai-chat-board-the-next-explores-of-the = Следующие исследования доски смогут искать в вебе и читать веб-страницы. Уже выполняющиеся исследования сохраняют настройку, с которой начались.
ai-chat-board-collections = Коллекции
ai-chat-board-the-collections-are-fixed-when = Коллекции задаются при создании доски и не меняются.
ai-chat-board-confirm-drop = Подтвердить удаление
ai-chat-board-drop-the-board = Удалить доску
ai-chat-board-close = Закрыть
ai-chat-board-the-board-used-its-explore = Доска исчерпала предел исследований
ai-chat-board-the-board-used-explores-the = Доска использовала исследований: { $explore_limit }. Это предел одной доски. Новая работа не запускается. Предложенные ответы по-прежнему можно принять или отклонить.
ai-chat-board-create-a-new-board-to = Создайте новую доску, чтобы продолжить расследование
ai-chat-board-goal = Цель
ai-chat-board-goals = Цели
ai-chat-board-add-new-goal = Добавить новую цель...
ai-chat-board-a-new-goal = Новая цель
ai-chat-board-add-goal = Добавить цель
ai-chat-board-a-board-has-at-most = На доске не больше { $max_goals } целей. Для другой цели создайте новую доску.
ai-chat-board-background-context = Фоновый контекст
ai-chat-board-continue-with-a-correction = Продолжить с поправкой
ai-chat-board-correction-what-is-wrong-or = Поправка: что неверно или чего не хватает. Доска продолжит работу с её учётом.
ai-chat-board-the-board-waits-for-your = Доска ждёт вашей проверки
ai-chat-board-the-board-used-its-budget = Доска израсходовала бюджет исследований: { $snap_max_explores }.
ai-chat-board-the-assessments-gave-no-usable = Оценки не дали пригодного направления.
ai-chat-board-accept-or-reject-the-proposed = Примите или отклоните предложенный ответ на каждую цель выше. Отклонённый ответ позволяет доске сразу продолжить работу.
ai-chat-board-no-proposed-answer-waits-for = Предложенных ответов, которые ждут вашего решения, нет.
ai-chat-board-reopen-the-board-to-continue = Откройте доску заново, чтобы продолжить работу над открытыми целями. Находки и ответы сохраняются.
ai-chat-board-close-the-board-to-accept = Завершите доску, чтобы принять все предложенные ответы и остановить её, или продолжите работу с поправкой.
ai-chat-board-close-the-board = Завершить доску
ai-chat-board-or-reopen-the-board-to = Или откройте доску заново и продолжите работу над открытыми целями без поправки.
ai-chat-board-the-board-is-complete = Работа над доской закончена
ai-chat-board-a-goal-has-no-accepted = У одной из целей нет принятого ответа. Откройте доску заново, чтобы продолжить работу над ней. Находки и ответы сохраняются.
ai-chat-board-add-a-hint = Добавить подсказку
ai-chat-board-the-next-assessment-reads-every = Следующая оценка читает все подсказки. Подсказка также отвечает на исследование, которое задало вопрос.
ai-chat-board-add-hint = Добавить подсказку
ai-chat-board-events = События
ai-chat-board-newest-first = Сначала новые
ai-chat-board-date = Дата
ai-chat-board-actor = Исполнитель
ai-chat-board-event = Событие
ai-chat-board-show-details = Показать подробности
ai-chat-board-open = Открыть
ai-chat-board-show-the-newest-events = Показать последние события: { $event_rows }
ai-chat-board-show-all-events = Показать все события: { $snap_events_len }
ai-chat-board-statistics = Статистика
ai-chat-board-explores = Исследования
ai-chat-board-model-steps-per-explore = Шагов модели на исследование
ai-chat-board-assessments = Оценки
ai-chat-board-intents = Намерения
ai-chat-board-findings = Находки
ai-chat-board-created = Создано
ai-chat-board-rejected-this-finding-on-the = Отклонено пользователем { $rejected_by }, { $format_utc_ms_fact_rejected_ms }. Доска больше не использует эту находку.
ai-chat-board-rejected-this-finding-the-board = Отклонено пользователем { $rejected_by }. Доска больше не использует эту находку.
ai-chat-board-no-reason-was-given = Причина не указана.
ai-chat-board-reason = Причина: { $fact_rejected_reason }
ai-chat-board-open-questions = Открытые вопросы
ai-chat-board-explored-in = Исследовано в{" "}
ai-chat-board-explore-this-question = Исследовать этот вопрос
ai-chat-board-your-questions = Ваши вопросы
ai-chat-board-ask-about-the-background-context = Спросить о фоновом контексте
ai-chat-board-ask-about-this-finding = Спросить об этой находке
ai-chat-board-a-follow-up-question-about = Дополнительный вопрос об этом узле
ai-chat-board-ask = Спросить
ai-chat-board-checks-that-changed-this-finding = Проверки, изменившие эту находку
ai-chat-board-reject-this-correction = Отклонить эту поправку
ai-chat-board-reject-this-finding = Отклонить эту находку
ai-chat-board-not-answered-the-board-was = Ответа нет. Доска завершена без ответа на эту цель. Подсказка или повторное открытие доски возобновит работу над ней.
ai-chat-board-no-answer-yet = Ответа пока нет.
ai-chat-board-the-findings-of-this-answer = Находки этого ответа — поиски, которые ничего не нашли. Примите ответ, чтобы записать, что записи не отвечают на цель, или отклоните его, чтобы продолжить расследование.
ai-chat-board-open-an-assessment-to-read = {"."} Откройте оценку, чтобы узнать причину.
ai-chat-board-from-the-findings = Из находок{" "}
ai-chat-board-accept-answer = Принять ответ
ai-chat-board-why-the-answer-is-wrong = Почему ответ неверен или неполон
ai-chat-board-reject-answer = Отклонить ответ
ai-chat-board-intent = Намерение
ai-chat-board-attempts-declared = Попыток: { $intent_attempts }. Объявлено: { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = Исследование задало вопрос
ai-chat-board-add-a-hint-in-the = Чтобы ответить на него, добавьте подсказку в обзоре доски.
ai-chat-board-last-error = Последняя ошибка
ai-chat-board-brief = Задание
ai-chat-board-open-the-explore-chat = Открыть чат исследования
ai-chat-board-loading-the-assessment-u = Загрузка оценки…
ai-chat-board-assessment = Оценка { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Модель: { $a_model }. Результат: { $a_outcome }. { $a_latency_ms } мс, { $tokens }.
ai-chat-board-checks-that-changed-it = Проверки, изменившие её
ai-chat-board-prompt = Промпт
ai-chat-board-this-assessment-ran-before-the = Эта оценка выполнялась до того, как начали сохранять промпты.
ai-chat-board-response = Ответ
ai-chat-history-hoover-search-chat-history = Hoover Search - История чатов
ai-chat-history-u-back = ← Назад
ai-chat-history-conversation-history = История бесед
ai-chat-history-show-board-chats = Показать чаты досок
ai-chat-history-loading-u = Загрузка…
ai-chat-history-could-not-load-history = Не удалось загрузить историю: { $e }
ai-chat-history-no-conversations-yet = Бесед пока нет.
ai-chat-history-board = Доска
ai-chat-history-new-chat = Новый чат
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } сообщение · обновлено { $s_updated_at }
    [few] { $s_message_count } сообщения · обновлено { $s_updated_at }
    [many] { $s_message_count } сообщений · обновлено { $s_updated_at }
    *[other] { $s_message_count } сообщения · обновлено { $s_updated_at }
    }

ai-chat-history-delete-conversation = Удалить беседу
ai-chat-history-delete = Удалить
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - ИИ-чат
ai-chat-homepage-what-are-you-researching = Что вы исследуете?
ai-chat-homepage-view-all-conversations = Все беседы
ai-chat-homepage-starting-conversation-u = Начало беседы…
ai-chat-homepage-investigation-boards = Доски расследований
ai-chat-homepage-new-board = Новая доска
ai-chat-homepage-loading-boards-u = Загрузка досок…
ai-chat-homepage-could-not-load-the-boards = Не удалось загрузить доски: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = У вас нет досок. Доска ведёт долгое расследование как последовательность исследований агента, а вы проверяете её ответы.
ai-chat-homepage-updated = Обновлено: { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - ИИ-чат
ai-chat-session-this-conversation-could-not-be = Не удалось загрузить эту беседу.
ai-chat-session-loading-u = Загрузка…
ai-chat-session-u-chats = ← Чаты
ai-chat-session-history = История
ai-chat-session-show-the-files-that-the = Показать файлы, которые ассистент записал в этой беседе
ai-chat-session-workspace = Рабочая область
ai-chat-session-this-answer-was-interrupted-before = Ответ прерван до завершения, потому что страница или сервер остановились посреди хода. Задайте вопрос ещё раз, чтобы повторить.
ai-chat-session-dismiss = Скрыть
ai-chat-session-board-explore-chats-are-read = Чаты исследований доски доступны только для чтения.{" "}
ai-chat-session-open-the-board = Открыть доску
chat-locked-options-on = { $label }: вкл.
chat-locked-options-off = { $label }: выкл.
chat-tool-cards-running-u = выполняется…
cards-result-cards-quote-found = Цитата найдена
cards-result-cards-quote-not-found = Цитата не найдена
cards-result-cards-quote-not-checked = Цитата не проверена
web-search-card-results = Результатов: { $results_len }
chat-tool-disclosure-running-u = выполняется…
chat-transcript-call = вызов инструмента
chat-transcript-calls = вызовы инструментов
ai-chat-board-a-board-without-collections-needs = Доске без коллекций нужны интернет-инструменты.
ai-chat-board-of = { $snap_explores_used } из { $snap_max_explores }
ai-chat-board-assessment-2 = оценка { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } сообщение
    [few] { $s_message_count } сообщения
    [many] { $s_message_count } сообщений
    *[other] { $s_message_count } сообщения
    }

web-search-card-reranked-in = Кросс-энкодер ранжировал результаты за { $ms } мс.
web-search-card-engine-results = { $name }: { $count } за { $ms } мс
web-search-card-score-was-rank = оценка { $score } · было RRF #{ $rank }
chat-activity-the-turn-waits-for-a = Ход ждёт свободный слот модели.
chat-activity-the-turn-waits-for-a-2 = Ход ждёт свободный слот инструмента.
chat-locked-options-start-a-new-chat-to = Начните новый чат, чтобы изменить эту настройку.
chat-locked-options-internet-tools = Интернет-инструменты
chat-session-card-new-chat = Новый чат
chat-tool-cards-first-frame-of-the-video = Первый кадр видео
chat-tool-cards-screenshot-of = Снимок экрана:
chat-tool-cards-image = Изображение
cards-result-cards-the-agent-asked-a-question = Агент задал вопрос.
chat-transcript-hide = Скрыть
chat-transcript-show = Показать
chat-transcript-unverified-quote-the-quoted-span = Цитата не проверена. Цитируемый фрагмент слишком короткий для проверки.
chat-transcript-unverified-quote-the-document-text = Цитата не проверена. Текст документа не удалось прочитать.
chat-transcript-unverified-quote-this-wording-was = Цитата не проверена. Эта формулировка в документе не найдена.
chat-board-create-select-a-collection-or-turn = Выберите коллекцию или включите интернет-инструменты.
chat-board-create-select-at-least-one-collection = Выберите хотя бы одну коллекцию.
ai-chat-board-active = Активна
ai-chat-board-paused = Приостановлена
ai-chat-board-waits-for-review = Ждёт проверки
ai-chat-board-completed = Завершена
ai-chat-board-dropped = Удалена
ai-chat-board-unknown = Неизвестно
ai-chat-board-pause-the-board = Приостановить доску
ai-chat-board-resume-the-board = Возобновить доску
ai-chat-board-none = Нет
ai-chat-board-reopen-with-the-remaining-budget = Открыть заново с оставшимся бюджетом
ai-chat-board-finding = Находка
ai-chat-board-why-the-correction-is-wrong = Почему поправка неверна
ai-chat-board-reject-correction = Отклонить поправку
ai-chat-board-why-the-finding-is-wrong = Почему находка неверна
ai-chat-board-reject-finding = Отклонить находку
ai-chat-board-answer = Ответ
ai-chat-board-proposed-answer = Предложенный ответ
ai-chat-homepage-active = Активна
ai-chat-homepage-paused = Приостановлена
ai-chat-homepage-waits-for-review = Ждёт проверки
ai-chat-homepage-completed = Завершена
ai-chat-homepage-dropped = Удалена
ai-chat-homepage-unknown = Неизвестно
cards-result-cards-submitted-by-board = Передано доской: { $kind ->
        [sourced] подтверждённая источниками
        [inferred] предположительная
        [not_found] отрицательная
       *[other] неопознанная
    } находка из отчёта
cards-result-cards-finding-for-board = { $kind ->
        [sourced] Подтверждённая источниками
        [inferred] Предположительная
        [not_found] Отрицательная
       *[other] Неопознанная
    } находка для доски
chat-transcript-compacting = Сжатие контекста: токенов { $before }, целевое значение { $target }.
chat-transcript-compaction-failed = Сводку предыдущих шагов составить не удалось. Модель получила предыдущие шаги без изменений, токенов: { $after }.
chat-transcript-compacted = Контекст сжат: шагов в сводке: { $steps }, токенов было { $before }, стало { $after }.
ai-chat-board-reopen-with-more = Открыть заново с дополнительными исследованиями: { $grant }
ai-chat-board-goal-number = Цель { $number }
ai-chat-board-from-assessment-on = Из оценки { $number } от { $date }.
ai-chat-board-from-assessment = Из оценки { $number }.
chat-board-create-goal-2 = Цель { $index_1 }
ai-chat-session-lost-contact-with-the-chat = потеряна связь с чатом: { $e }
ai-chat-session-could-not-stop-the-answer = не удалось остановить ответ: { $e } — он ещё выполняется
ai-chat-board-later-assessments-dropped-an-answer = Более поздние оценки отбросили ответ на эту цель ({ $n }):
ai-chat-board-prompt-and-completion-tokens = токенов запроса: { $a_prompt_tokens }, токенов ответа: { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = Завершена, целей без ответа: { $n }
board-graph-intent = намерение, { $state }
chat-workspace-pane-characters = Символов: { $chars }
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + в работе ({ $if_joined_live_end_1_tr_chat_transcript_ }): { $joined_live_end }
chat-transcript-running-tool-2 = В работе ({ $if_turn_tool_rows_len_1_tr_chat_transcri }): { $turn_tool_rows_len }
chat-transcript-answered-after-failed-attempt = Ответ получен после неудачных попыток: { $retries_len }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = Неудачных попыток: { $retries_len }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, версия { $report_version }
tool-run-summary-searched = { $n ->
        [one] поиск по { $n } термину
        [few] поиск по { $n } терминам
        [many] поиск по { $n } терминам
       *[other] поиск по { $n } терминам
    }
tool-run-summary-read = { $n ->
        [one] прочитан { $n } документ
        [few] прочитано { $n } документа
        [many] прочитано { $n } документов
       *[other] прочитано { $n } документа
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] поиск в вебе по { $n } термину
        [few] поиск в вебе по { $n } терминам
        [many] поиск в вебе по { $n } терминам
       *[other] поиск в вебе по { $n } терминам
    }
tool-run-summary-read-web = { $n ->
        [one] прочитана { $n } веб-страница
        [few] прочитано { $n } веб-страницы
        [many] прочитано { $n } веб-страниц
       *[other] прочитано { $n } веб-страницы
    }
tool-run-summary-browser = { $n ->
        [one] { $n } действие в браузере
        [few] { $n } действия в браузере
        [many] { $n } действий в браузере
       *[other] { $n } действия в браузере
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] перечислены сущности { $n } документа
        [few] перечислены сущности { $n } документов
        [many] перечислены сущности { $n } документов
       *[other] перечислены сущности { $n } документов
    }
tool-run-summary-cited = { $n ->
        [one] ссылка на { $n } документ
        [few] ссылки на { $n } документа
        [many] ссылки на { $n } документов
       *[other] ссылки на { $n } документа
    }
tool-run-summary-cited-web = { $n ->
        [one] ссылка на { $n } веб-страницу
        [few] ссылки на { $n } веб-страницы
        [many] ссылки на { $n } веб-страниц
       *[other] ссылки на { $n } веб-страницы
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] прочитан { $n } навык и тексты инструментов
        [few] прочитано { $n } навыка и тексты инструментов
        [many] прочитано { $n } навыков и тексты инструментов
       *[other] прочитано { $n } навыка и тексты инструментов
    }
tool-run-summary-saved = { $n ->
        [one] сохранена { $n } заметка
        [few] сохранено { $n } заметки
        [many] сохранено { $n } заметок
       *[other] сохранено { $n } заметки
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } вызов плана
        [few] { $n } вызова плана
        [many] { $n } вызовов плана
       *[other] { $n } вызова плана
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } указание агенту
        [few] { $n } указания агенту
        [many] { $n } указаний агенту
       *[other] { $n } указания агенту
    }
tool-run-summary-other = { $n ->
        [one] { $n } другой вызов
        [few] { $n } других вызова
        [many] { $n } других вызовов
       *[other] { $n } других вызова
    }
tool-run-summary-failed = сбоев: { $failures }
tool-run-summary-took = заняло { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } сообщение
    [few] { $session_message_count } сообщения
    [many] { $session_message_count } сообщений
    *[other] { $session_message_count } сообщения
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } элемент
        [few] { $count } элемента
        [many] { $count } элементов
       *[other] { $count } элемента
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } поле
        [few] { $count } поля
        [many] { $count } полей
       *[other] { $count } поля
    }
chat-tool-disclosure-searched-collections = поиск по коллекциям{ $filters }
chat-tool-disclosure-searched-collections-2 = поиск по коллекциям · { $query }{ $filters }
chat-tool-disclosure-cited-documents = ссылки на документы: { $n }
chat-tool-disclosure-read-document = чтение документа · { $path }
chat-tool-disclosure-searched-the-web = поиск в вебе · { $q }
chat-tool-disclosure-opened-page = открыта страница · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = вызван { $other }
chat-tool-disclosure-called-2 = вызван { $other } · { $short }
cards-browser-card-opened = открыто: { $url }
cards-browser-card-could-not-open = не удалось открыть: { $url }
cards-browser-card-clicked = нажато: { $element }
cards-browser-card-could-not-click = не удалось нажать: { $element }
cards-browser-card-typed-into = введён текст в: { $element }
cards-browser-card-could-not-type-into = не удалось ввести текст в: { $element }
cards-browser-card-typed = введено «{ $text }»
cards-browser-card-could-not-type = не удалось ввести «{ $text }»
cards-browser-card-pressed = нажата клавиша { $key }
cards-browser-card-could-not-press = не удалось нажать клавишу { $key }
cards-browser-card-chose-an-option-in = выбран вариант в: { $element }
cards-browser-card-could-not-choose-an-option = не удалось выбрать вариант в: { $element }
cards-browser-card-hovered = наведено на: { $element }
cards-browser-card-could-not-hover = не удалось навести на: { $element }
cards-browser-card-failed = { $bare } — сбой
cards-entities-card-listed-entities-document = перечислены сущности · документов: { $count }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · часть { $part } из { $name } #{ $seq }
cards-result-cards-documents = {" "}· документов: { $value }
cards-result-cards-forms = { $tool_name } · вариантов запроса: { $forms }
cards-result-cards-in = {" "}в { $collections }
cards-result-cards-page = {" "}· страница { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · документов: { $citations_len } · цитат не найдено: { $missing }
cards-result-cards-version-unchanged = { $tool_name } · версия { $version } · без изменений
cards-result-cards-version = { $tool_name } · версия { $version }
web-search-card-results-in-after-deduplication = Получено результатов: { $json_u64_doc_total_before_dedupe }, после удаления дубликатов: { $json_u64_doc_total_after_dedupe }

board-status-on = Включено

board-status-off = Выключено

chat-transcript-generic-tool = инструмент
