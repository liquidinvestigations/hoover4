# Translation of en/notes.ftl. Change it together with the English catalog.

# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l4 = Прочитай сейчас страницы результатов, которые могут ответить на запрос: передай до 6 их URL в одном вызове read_page, в списке `urls`. Один вызов читает их все одновременно.

## Page captures


## Sources


## Named things


## Search progress

note-progress-level = Уровень хода поиска: { $level }.
note-progress-searches = Уже выполненные поиски:
note-progress-search = { $name } { $args }: элементов { $items }, совпадений по ключевым словам { $matches }.
note-progress-available = Ещё доступные шаги поиска:
note-progress-complete = Доступные шаги поиска выполнены.
note-progress-write-now = Напиши ответ или отчёт сейчас. Укажи, чего нет в прочитанных источниках, и назови выполненные поиски.
note-progress-answer-next = Следующим сообщением должен быть ответ. Укажи недостающие факты и поиски, которые ты выполнил.
note-progress-step-quoted = Ищи каждое имя как фразу в кавычках с помощью search_collections.
note-progress-step-variants = Ищи слова без кавычек и варианты имён. Прочитай частоты слов и кандидатов написания.
note-progress-step-filters = Убирай фильтры по одному и выполни поиск без фильтров.
note-progress-step-facets = Проверь значения фильтров с помощью search_facet_values.
note-progress-step-dates = Проверь даты с помощью search_histogram.
note-progress-step-passages = Ищи описание содержания с помощью search_passages.
note-progress-step-folder = Используй { $tool } для запрошенной папки, пути или файла.
note-progress-step-read-hits = Прочитай от 1 до 3 лучших результатов с помощью { $tool }.
note-progress-step-web-search = Ищи в вебе с помощью web_search и прочитай лучшие страницы результатов.
note-progress-step-page-find = Ищи в сохранённом тексте длинной страницы с помощью read_page и find.
note-progress-step-page-retry = Прочитай другой адрес из результатов или архивную копию страницы, которая не открылась.
note-progress-ended = Запуск завершён после повторных поисков без прогресса.
note-progress-ended-none = Не найдено ни одного источника с совпадением по ключевым словам.
note-progress-ended-some = Поиски нашли источников с совпадением по ключевым словам: { $count }. Агент не завершил ответ.
note-progress-ended-searches = Выполненные поиски:
