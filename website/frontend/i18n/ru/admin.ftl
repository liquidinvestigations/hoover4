# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = Требуется доступ администратора
admin-guard-signed-in-as = Вы вошли как { $u_username }.
admin-guard-ask-an-administrator-for-access = Запросите у администратора доступ к этому разделу.
admin-shell-dashboard = Панель
admin-shell-collections = Коллекции
admin-shell-operations = Операции
admin-shell-errors-failures = Ошибки/Сбои
admin-shell-feedback = Отзывы
admin-shell-users = Пользователи
admin-shell-groups = Группы
admin-shell-settings = Настройки
admin-shell-llm = LLM
admin-shell-ai-status = Состояние ИИ
admin-shell-metrics = Метрики
admin-shell-administration = Администрирование
dataset-create-panel-add-a-dataset = Добавить набор данных
dataset-create-panel-the-dataset-mounts-could-not = Не удалось прочитать точки монтирования наборов данных, поэтому выбирать не из чего: { $err }
dataset-create-panel-loading-the-dataset-mounts = Загрузка точек монтирования наборов данных.
dataset-create-panel-no-dataset-mount-is-configured = Ни одна точка монтирования наборов данных не настроена.
dataset-create-panel-the-mount-folder-could-not = Не удалось прочитать папку точки монтирования, поэтому выбирать не из чего: { $err }
dataset-create-panel-no-subfolders-were-found-in = В этой точке монтирования не найдено подпапок.{" "}
dataset-create-panel-folder = Папка
dataset-create-panel-select-a-folder = Выберите папку
dataset-create-panel-new-folder = Новая папка
dataset-create-panel-entries-already-a-dataset = { $option_name } (элементов: { $option_entry_count }), уже набор данных
dataset-create-panel-entries = { $option_name } (элементов: { $option_entry_count })
dataset-create-panel-the-server-creates-this-folder = Сервер создаёт эту папку в точке монтирования, когда вы создаёте набор данных.{" "}
dataset-create-panel-the-list-shows-the-direct = Список показывает подпапки первого уровня в точке монтирования.
dataset-create-panel-dataset-name = Имя набора данных
dataset-create-panel-a-name-has-lowercase-letters = Имя состоит из строчных букв, цифр и подчёркиваний. Заглавные буквы становятся строчными,{" "}
dataset-create-panel-the-dataset-is-saved-as = Набор данных сохранится как: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = В этой коллекции уже есть набор данных с именем { $saved_name }.
dataset-create-panel-accept-uploads = Принимать загрузки
dataset-create-panel-tesseract = Tesseract
dataset-create-panel-easyocr = EasyOCR
dataset-create-panel-saved-as-this-collection-s = Сохранено как значения коллекции по умолчанию. Языки ни одного набора данных не меняются.
dataset-create-panel-saving-u = Сохранение…
dataset-create-panel-save-as-collection-defaults = Сохранить как значения коллекции по умолчанию
dataset-create-panel-creating-u = Создание…
dataset-create-panel-create-and-ingest = Создать и запустить приём
dataset-create-panel-mount = Точка монтирования
dataset-ocr-panel-last-operation = Последняя операция: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , начата { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Нет прогресса уже { $current_stale_seconds_60 } мин. Проверьте рабочий процесс Temporal и отмените операцию, если она застряла.
dataset-ocr-panel-filter-languages = Фильтр языков
dataset-ocr-panel-ocr-languages = Языки OCR
dataset-ocr-panel-failed-to-load-the-ocr = Не удалось загрузить настройки OCR этого набора данных
dataset-ocr-panel-loading-u = Загрузка…
dataset-ocr-panel-each-easyocr-script-group-adds = Каждая группа письменностей EasyOCR добавляет один проход OCR по набору данных. Tesseract читает все свои языки за один проход.{" "}
dataset-ocr-panel-tesseract = Tesseract
dataset-ocr-panel-in-force-from = Действует: { $panel_tesseract_languages }, источник: { $source_label_panel_tesseract_source }.
dataset-ocr-panel-use = Использовать значение ({ $source_label_panel_inherited_tesseract_s }): { $panel_inherited_tesseract }
dataset-ocr-panel-the-tesseract-service-did-not = Служба Tesseract не ответила, поэтому установленные языки неизвестны.{" "}
dataset-ocr-panel-the-image-also-has-script = В образе есть также модели письменностей: { $script_models }, например латиница. Форма их не предлагает, потому что настройка входит в ключ хранилища и принимает только коды в нижнем регистре.
dataset-ocr-panel-the-first-language-is-the = Первый язык основной. Выбрано:{" "}
dataset-ocr-panel-easyocr = EasyOCR
dataset-ocr-panel-easyocr-is-off-on-this = В этом развёртывании EasyOCR выключен, поэтому настройка не действует, пока его не включат.
dataset-ocr-panel-in-force-off-from = Действует: выключено, источник: { $source_label_panel_easyocr_source }.
dataset-ocr-panel-in-force-from-2 = Действует: { $panel_easyocr_languages }, источник: { $source_label_panel_easyocr_source }.
dataset-ocr-panel-use-off = Использовать значение ({ $source_label_panel_inherited_easyocr_sou }): выключено
dataset-ocr-panel-use-2 = Использовать значение ({ $source_label_panel_inherited_easyocr_sou }): { $panel_inherited_easyocr }
dataset-ocr-panel-enabled = Включено
dataset-ocr-panel-the-easyocr-service-did-not = Служба EasyOCR не сообщила, какие языки она поддерживает.
dataset-ocr-panel-a-model-download-failed = Не удалось загрузить модель: { $failure }
dataset-ocr-panel-stored-text-variants = Сохранённые варианты текста
dataset-ocr-panel-removing-a-language-deletes-its = Удаление языка удаляет его текст, его строки поиска и его PDF с текстовым слоем.
dataset-ocr-panel-searchable-pdfs = PDF с текстовым слоем
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · файлов: { $variant_pdf_count } · { $variant_total_bytes_1024_1024 } МБ
dataset-ocr-panel-searchable-pdfs-are-off-on = В этом развёртывании PDF с текстовым слоем выключены.
dataset-ocr-panel-saving-u = Сохранение…
dataset-ocr-panel-apply = Применить
dataset-ocr-panel-no-changes-to-apply = Нет изменений для применения.
live-chats-panel-live-llm-chats = Работающие чаты LLM
live-chats-panel-agent-turns-running-right-now = Ходы агента, выполняемые прямо сейчас, сначала самые долгие. Обновляется каждые 2 с. Данные читаются из Temporal, поэтому здесь есть и ход, начавшийся до последнего перезапуска сайта.
live-chats-panel-loading-u = Загрузка…
live-chats-panel-no-chats-running = Работающих чатов нет.
live-chats-panel-user = Пользователь
live-chats-panel-conversation = Беседа
live-chats-panel-question = Вопрос
live-chats-panel-internet = Интернет
live-chats-panel-running = Работает
live-chats-panel-started = Начало
live-chats-panel-cancels-the-workflow-the-turn = Отменяет рабочий процесс. Ход заканчивается отметкой об остановке в стенограмме и не исчезает.
live-chats-panel-kill = Прервать
processing-updates-panel-loading-u = Загрузка…
processing-updates-panel-open-the-operation = Открыть операцию
processing-updates-panel-the-pipeline-has-not-calculated = Конвейер ещё не рассчитал эти обновления.
processing-updates-panel-calculated-at-in-ms = Рассчитано { $view_checked_at } за { $view_check_ms } мс.{" "}
processing-updates-panel-automatic-updates-are-off-on = Автоматические обновления в этой установке выключены. Запустите обновления кнопкой.
processing-updates-panel-step = Шаг
processing-updates-panel-count = Количество
processing-updates-panel-state = Состояние
processing-updates-panel-last-run = Последний запуск
processing-updates-panel-runs = Запусков: { $step_runs }
processing-updates-panel-a-run-again-would-select = Повторный запуск выберет примерно столько ({ $step_unit }).
processing-updates-panel-on-a-run-again = При повторном запуске: { $step_pending } { $unit }
processing-updates-panel-never = Никогда
processing-updates-panel-update-collection = Обновить коллекцию
processing-updates-panel-update-processing = Обновить обработку
processing-updates-panel-check-again = Проверить снова
processing-updates-panel-dataset = Набор данных
processing-updates-panel-processing-updates = Обновления обработки
admin-ai-status-admin-ai-status = Администрирование: состояние ИИ
admin-ai-status-ai-status = Состояние ИИ
admin-ai-status-the-configured-service-and-the = Настроенная служба и служба, которая отвечает на самом деле. Переход на службу CPU виден только здесь.
admin-ai-status-loading-u = Загрузка…
admin-ai-status-config-fingerprint = Отпечаток конфигурации
admin-ai-status-website-worker = Сайт / воркер
admin-ai-status-ai-server = Сервер ИИ
admin-ai-status-match = Совпадает
admin-ai-status-embeddings-probe = Проверка эмбеддингов
admin-ai-status-dims = { $status_embeddings_serving_model } · размерность: { $status_embeddings_serving_dim }
admin-ai-status-llm-configured = LLM настроена
admin-ai-status-capabilities = Возможности
admin-ai-status-capability = Возможность
admin-ai-status-configured = Настроено
admin-ai-status-serving = Обслуживает
admin-ai-status-model = Модель
admin-ai-status-reachable = Доступно
admin-ai-status-detail = Подробности
admin-ai-status-no = НЕТ
admin-ai-status-vector-shard-dims-vs-probe = Размерность векторных шардов и проверка
admin-ai-status-no-collections-yet = Коллекций пока нет.
admin-ai-status-collection = Коллекция
admin-ai-status-shard = Шард
admin-ai-status-matches-probe = Совпадает с проверкой
admin-ai-status-browser-router = Маршрутизатор браузера
admin-ai-status-live-sessions = Активных сеансов: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Недавний трафик LLM (24 ч)
admin-ai-status-no-llm-call-events-yet = В llm_call_events пока нет записей.
admin-ai-status-user = Пользователь
admin-ai-status-calls = Вызовы
admin-ai-status-errors = Ошибки
admin-ai-status-service-use-24-h = Использование служб, % (24 ч)
admin-ai-status-busy-seconds-in-the-last = Секунды занятости за последние 24 часа как доля суток.
admin-ai-status-no-samples-yet = Замеров пока нет.
admin-ai-status-service = Служба
admin-ai-status-busy-s = Занято, с
admin-ai-status-use = Использование, %
admin-collection-detail-admin-collection = Администрирование: коллекция { $collection_id }
admin-collection-detail-failed-to-load-collection = Не удалось загрузить коллекцию
admin-collection-detail-loading = Загрузка...
admin-collection-detail-datasets = Наборы данных
admin-collection-detail-dataset = Набор данных
admin-collection-detail-documents = Документы
admin-collection-detail-size = Размер
admin-collection-detail-indexed = Проиндексировано
admin-collection-detail-errors = Ошибки
admin-collection-detail-state = Состояние
admin-collection-detail-created = Создано
admin-collection-detail-settings = Настройки
admin-collection-detail-the-collection-database-is-not = База данных коллекции ещё не готова.
admin-collection-detail-the-last-storage-provisioning-failed = Последняя подготовка хранилища завершилась сбоем: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Ход обработки и оценки
admin-collection-detail-display-name = Отображаемое имя
admin-collection-detail-display-name-2 = отображаемое имя
admin-collection-detail-save = Сохранить
admin-collection-detail-access = Доступ
admin-collection-detail-public-every-signed-in-user = Публичная. Любой вошедший пользователь может искать в этой коллекции и читать её.
admin-collection-detail-restricted-only-members-of-the = Ограниченная. Искать в этой коллекции и читать её могут только участники перечисленных ниже групп.
admin-collection-detail-the-collection-is-now-public = Коллекция теперь публичная.
admin-collection-detail-the-collection-is-now-restricted = Коллекция теперь ограниченная.
admin-collection-detail-make-restricted = Ограничить доступ
admin-collection-detail-make-public = Сделать публичной
admin-collection-detail-group-permissions = Права групп
admin-collection-detail-no-group-can-read-this = Пока ни одна группа не может читать эту коллекцию.
admin-collection-detail-revoke = Отозвать
admin-collection-detail-grant-group-u = Выдать доступ группе…
admin-collection-detail-grant = Выдать
admin-collection-detail-danger-zone = Опасная зона
admin-collection-detail-a-collection-can-only-be = Коллекцию можно удалить, только если в ней нет наборов данных.
admin-collection-detail-deleting-the-collection-also-drops = Удаление коллекции также удаляет её базу данных{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}и всё, что в ней есть. Отменить это нельзя. Для подтверждения введите имя коллекции.
admin-collection-detail-collection-name = Имя коллекции
admin-collection-detail-delete-collection = Удалить коллекцию
admin-collection-detail-features = Функции
admin-collection-detail-vectors = Векторы
admin-collection-detail-this-installation-runs-no-embedding = В этой установке нет службы эмбеддингов, поэтому ни одна коллекция не использует векторы.
admin-collection-detail-vectors-find-passages-by-meaning = Векторы находят фрагменты по смыслу. Выключение останавливает создание новых векторов и не даёт поиску использовать сохранённые, которые остаются. Включение вычисляет недостающие векторы каждого набора данных, по одному набору за раз.
admin-collection-detail-this-collection-follows-the-installation = Эта коллекция следует установке, которая использует векторы. Векторы находят фрагменты по смыслу. Выключение останавливает создание новых векторов и не даёт поиску использовать сохранённые, которые остаются.
admin-collection-processing-could-not-load-this-panel = Не удалось загрузить эту панель: { $message }
admin-collection-processing-admin-processing-of = Администрирование: обработка { $collection_id }
admin-collection-processing-u-back-to-collection = ← Назад к коллекции
admin-collection-processing-processing-stages = Этапы обработки
admin-collection-processing-loading-u = Загрузка…
admin-collection-processing-the-collection-database-is-still = База данных коллекции ещё подготавливается.
admin-collection-processing-this-collection-has-no-datasets = В этой коллекции пока нет наборов данных.
admin-collection-processing-eta = Осталось: { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Замеров для оценки пока нет. Они собираются, пока набор данных обрабатывается.
admin-collection-processing-estimated-completion = Ожидаемое завершение:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(через { $humanize_seconds_c_eta_seconds }, это приблизительная оценка, а не обещание по срокам)
admin-collection-processing-no-current-estimate-the-pipeline = Текущей оценки нет. Конвейер закончил работу или не делает измеримого прогресса.
admin-collection-processing-where-processing-time-goes = На что уходит время обработки
admin-collection-processing-no-task-executions-recorded-yet = Выполнений задач пока не записано. Каждая активность конвейера записывает здесь одну строку, поэтому пустая таблица означает, что после включения измерений ничего не обрабатывалось.
admin-collection-processing-summed-task-time = Суммарное время задач
admin-collection-processing-wall-clock = Реальное время
admin-collection-processing-achieved-parallelism = Достигнутый параллелизм
admin-collection-processing-summed-task-time-divided-by = Суммарное время задач, делённое на реальное время, показывает, какой параллелизм конвейер реально достиг. Значение около 1 означает, что верхняя задача ниже составляет всю стоимость и её стоит оптимизировать. Значение около числа слотов воркеров означает, что слоты заполнены и дешевле добавить воркеров. Реальное время охватывает период от первого выполнения до последнего, включая простой.
admin-collection-processing-task = Задача
admin-collection-processing-total = Итого
admin-collection-processing-share = Доля
admin-collection-processing-executions = Выполнений
admin-collection-processing-mean = Среднее
admin-collection-processing-max = Макс.
admin-collection-processing-failed = Сбоев
admin-collection-processing-live-activity = Текущая активность
admin-collection-processing-nothing-running-no-activity-finished = Ничего не выполняется. За последние { $live_window_seconds } с не завершилась ни одна активность, и ни один воркер не сообщает о работе в процессе.
admin-collection-processing-in-flight = В работе
admin-collection-processing-average-concurrency = Средняя параллельность
admin-collection-processing-task-time-in-window = Время задач в окне
admin-collection-processing-share-of-processing-time-over = Доля времени обработки за последние { $live_window_seconds } с, обновляется каждые 5 с. Выполнение, которое пересекает границу окна, учитывается только в части внутри окна. Строка с выполнениями в работе, но без доли, относится к тому, что началось до окна и ещё не закончилось. Проверьте его возраст.
admin-collection-processing-share-of-window = Доля окна
admin-collection-processing-task-time = Время задач
admin-collection-processing-completed = Завершено
admin-collection-processing-oldest-running = Самое давнее из выполняющихся
admin-collection-processing-temporal-workflows = Рабочие процессы Temporal
admin-collection-processing-workflows-of-this-collection-s = Рабочие процессы наборов данных этой коллекции, включая дочерние.
admin-collection-processing-no-workflows-match-this-filter = Нет рабочих процессов, подходящих под этот фильтр.
admin-collection-processing-workflow = Рабочий процесс
admin-collection-processing-type = Тип
admin-collection-processing-status = Статус
admin-collection-processing-started = Начало
admin-collection-processing-closed = Закрыт
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = открыть ↗
admin-collection-processing-failed-tasks = Задачи со сбоями
admin-collection-processing-no-task-failures-recorded = Сбоев задач не зарегистрировано.
admin-collection-processing-dataset = Набор данных
admin-collection-processing-errors = Ошибки
admin-collection-processing-documents = Документы
admin-collection-processing-last-seen = Последний раз замечено
admin-collection-processing-sample = Пример
admin-collection-processing-retry = Повторить
admin-collection-processing-failures-per-document = Сбои по документам
admin-collection-processing-no-document-failures-recorded = Сбоев документов не зарегистрировано.
admin-collection-processing-document = Документ
admin-collections-list-admin-collections = Администрирование: коллекции
admin-collections-list-collections = Коллекции
admin-collections-list-loading-collections-u = Загрузка коллекций…
admin-collections-list-datasets = Наборы данных
admin-collections-list-loading-datasets-u = Загрузка наборов данных…
admin-collections-list-add-a-collection = Добавить коллекцию
admin-collections-list-name-for-example-enron = Имя, например enron
admin-collections-list-display-name = Отображаемое имя
admin-collections-list-add-collection = Добавить коллекцию
admin-collections-list-a-name-has-lowercase-letters = Имя состоит из строчных букв, цифр и подчёркиваний. Заглавные буквы становятся строчными,{" "}
admin-collections-list-the-collection-is-saved-as = Коллекция сохранится как: { $new_name }
admin-collections-list-a-collection-with-the-name = Коллекция с именем { $new_name } уже существует.
admin-collections-list-collection = Коллекция
admin-collections-list-documents = Документы
admin-collections-list-size = Размер
admin-collections-list-errors = Ошибки
admin-collections-list-state = Состояние
admin-collections-list-access = Доступ
admin-collections-list-database-not-ready = База данных не готова
admin-collections-list-public = Публичная
admin-collections-list-1-group = 1 группа
admin-collections-list-not-counted-yet = Ещё не подсчитано
admin-collections-list-unknown = Неизвестно
admin-collections-list-no-collection-has-a-dataset = Ни в одной коллекции нет набора данных.
admin-collections-list-dataset = Набор данных
admin-collections-list-indexed = Проиндексировано
admin-collections-list-created = Создано
admin-dashboard-admin-dashboard = Администрирование: панель
admin-dashboard-administration = Администрирование
admin-dashboard-users = Пользователи
admin-dashboard-groups = Группы
admin-dashboard-collections = Коллекции
admin-dashboard-datasets = Наборы данных
admin-dashboard-failed-to-load-counts = Не удалось загрузить счётчики: { $e }
admin-dataset-detail-admin-dataset = Администрирование: набор данных { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Не удалось загрузить набор данных
admin-dataset-detail-loading = Загрузка...
admin-dataset-detail-metadata = Метаданные
admin-dataset-detail-display-name = Отображаемое имя
admin-dataset-detail-name = Имя
admin-dataset-detail-type = Тип
admin-dataset-detail-path = Путь
admin-dataset-detail-created = Создано
admin-dataset-detail-collection = Коллекция
admin-dataset-detail-save = Сохранить
admin-dataset-detail-statistics = Статистика
admin-dataset-detail-state = Состояние
admin-dataset-detail-documents = Документы
admin-dataset-detail-size = Размер
admin-dataset-detail-indexed = Проиндексировано
admin-dataset-detail-errors = Ошибки
admin-dataset-detail-plans-finished = Завершено планов
admin-dataset-detail-disk = Диск
admin-dataset-detail-rescan-disk-reads-the-dataset = Пересканирование диска заново читает папку набора данных, добавляет новые и изменённые файлы и обрабатывает их.
admin-dataset-detail-rescan-disk = Пересканировать диск
admin-dataset-detail-danger-zone = Опасная зона
admin-dataset-detail-this-deletes-the-dataset-and = Это удаляет набор данных и все данные, извлечённые из него. Отменить это нельзя.
admin-dataset-detail-delete-dataset-and-its-data = Удалить набор данных и его данные
admin-dataset-detail-accept-uploads = Принимать загрузки
admin-dataset-detail-the-folder-of-this-dataset = Папка этого набора данных находится не в доступной для записи точке монтирования наборов данных, поэтому он не принимает загрузки.
admin-dataset-detail-starting-u = Запуск…
admin-failure-detail-admin-failure = Администрирование: сбой { $op_id }
admin-failure-detail-loading-tree = Загрузка дерева…
admin-failure-detail-back-to-errors-and-failures = Назад к ошибкам и сбоям
admin-failure-detail-operations = Операции
admin-failure-detail-scrubbed-copy-written-to-the = Очищенная копия записана в буфер обмена.
admin-failure-detail-this-tree-is-truncated-at = Это дерево усечено. По меньшей мере при одном сохранении узлы были отброшены.
admin-failure-detail-the-captured-tree-has-expired = Срок хранения сохранённого дерева истёк. Строка операции по-прежнему на месте.
admin-failure-detail-no-captured-nodes-for-this = Для этой операции нет сохранённых узлов.
admin-failure-detail-operation = Операция
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · корней: { $root_count } · узлов: { $tree_nodes_len }
admin-failure-detail-open-in-temporal = Открыть в Temporal
admin-failure-detail-scrubbed-copy = Очищенная копия
admin-failure-detail-the-scrubbed-copy-replaces-dataset = В очищенной копии пути наборов данных заменены хешами, а длинные значения заменены их длиной.
admin-failure-detail-copy-scrubbed-record = Копировать очищенную запись
admin-failure-detail-tree = Дерево
admin-failure-detail-root = Корень ·{" "}
admin-failure-detail-node-parent-depth-source-stage = узел { $node_node_index } · родитель { $node_parent_index } · глубина { $node_depth } · источник { $node_source } · этап { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = рабочий процесс { $node_workflow_id } · запуск { $node_run_id } · активность { $node_activity_id } · попытка { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = при этом сохранении отброшено узлов: { $node_nodes_dropped }
admin-failures-admin-errors-and-failures = Администрирование: ошибки и сбои
admin-failures-errors-failures = Ошибки/Сбои
admin-failures-loading-failures = Загрузка сбоев…
admin-failures-operational-failures = Сбои операций
admin-failures-no-operational-failures-at-this = Сбоев операций сейчас нет.
admin-failures-collection = Коллекция
admin-failures-dataset = Набор данных
admin-failures-task-name = Имя задачи
admin-failures-error-class = Класс ошибки
admin-failures-operation-kind = Вид операции
admin-failures-from = С
admin-failures-to = По
admin-failures-no-captured-failures-match-these = Нет сохранённых сбоев, подходящих под эти фильтры.
admin-failures-signature = Сигнатура
admin-failures-count = Количество
admin-failures-class = Класс
admin-failures-task = Задача
admin-failures-last-seen = Последний раз замечено
admin-failures-newer = Новее
admin-failures-page = Страница { $current_page_1 }
admin-failures-older = Старее
admin-failures-per-page = На странице
admin-failures-loading-instances = Загрузка экземпляров…
admin-failures-no-instances-for-this-signature = Для этой сигнатуры экземпляров нет.
admin-failures-node = {" "}узел { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Ошибки документов
admin-failures-error-text = Текст ошибки
admin-failures-loading-document-errors-u = Загрузка ошибок документов…
admin-failures-no-document-errors-match-these = Нет ошибок документов, подходящих под эти фильтры.
admin-failures-errors-by-dataset-and-task = Ошибки по наборам данных и задачам
admin-failures-documents = Документы
admin-failures-show-only-this-dataset-and = Показать только этот набор данных и задачу
admin-failures-total = Итого
admin-failures-errors = Ошибки
admin-failures-document = Документ
admin-failures-runs = Запуски
admin-failures-error = Ошибка
admin-failures-dataset-step = Шаг набора данных
admin-failures-previous-page = Предыдущая страница
admin-failures-page-of-1-error = Страница { $page } из { $pages }, 1 ошибка
admin-failures-page-of-errors = Страница { $page } из { $pages }, ошибок: { $data_total }
admin-failures-next-page = Следующая страница
admin-feedback-admin-feedback = Администрирование: отзывы
admin-feedback-feedback = Отзывы
admin-feedback-search-titles-descriptions-accounts-and = Поиск по заголовкам, описаниям, учётным записям и адресам
admin-feedback-search = Найти
admin-feedback-loading-reports-u = Загрузка сообщений…
admin-feedback-1-report-matches = Подходит 1 сообщение.
admin-feedback-reports-match = Подходящих сообщений: { $data_total }.
admin-feedback-received = Получено
admin-feedback-type = Тип
admin-feedback-title = Заголовок
admin-feedback-from = От
admin-feedback-captures = Снимки
admin-feedback-state = Состояние
admin-feedback-previous-page = Предыдущая страница
admin-feedback-page-of = Страница { $page } из { $pages }
admin-feedback-next-page = Следующая страница
admin-feedback-image = Изображение { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Прочитано
admin-feedback-unread = Непрочитано
admin-feedback-archived = В архиве
admin-feedback-mark-unread = Пометить как непрочитанное
admin-feedback-mark-read = Пометить как прочитанное
admin-feedback-restore = Восстановить
admin-feedback-archive = В архив
admin-feedback-page = Страница:{" "}
admin-feedback-the-report-has-no-description = У сообщения нет описания.
admin-feedback-open-the-page-image = Открыть изображение страницы
admin-feedback-open-the-dom-copy = Открыть копию DOM
admin-feedback-page-image-of-the-report = Изображение страницы из сообщения
admin-feedback-debug-context-and-browser-log = Контекст отладки и журнал браузера
admin-feedback-loading-u = Загрузка…
admin-group-detail-admin-group = Администрирование: группа { $groupname }
admin-group-detail-failed-to-load-group = Не удалось загрузить группу
admin-group-detail-loading = Загрузка...
admin-group-detail-group = Группа
admin-group-detail-display-name = Отображаемое имя
admin-group-detail-display-name-2 = отображаемое имя
admin-group-detail-save = Сохранить
admin-group-detail-members = Участники
admin-group-detail-saving-membership = Сохранение членства...
admin-group-detail-username = Имя пользователя
admin-group-detail-origin = Происхождение
admin-group-detail-group-admin = Администратор группы
admin-group-detail-uploader = Загружающий
admin-group-detail-remove = Убрать
admin-group-detail-username-to-add = имя пользователя для добавления
admin-group-detail-add-member = Добавить участника
admin-group-detail-collection-access = Доступ к коллекциям
admin-group-detail-this-group-has-no-collection = У этой группы нет прав на коллекции.
admin-group-detail-revoke = Отозвать
admin-group-detail-grant-collection-u = Выдать доступ к коллекции…
admin-group-detail-grant = Выдать
admin-group-detail-danger-zone = Опасная зона
admin-group-detail-delete-group = Удалить группу
admin-groups-list-admin-groups = Администрирование: группы
admin-groups-list-groups = Группы
admin-groups-list-add-group = Добавить группу
admin-groups-list-display-name = отображаемое имя
admin-groups-list-use-lowercase-letters-digits-underscores = Используйте в имени строчные буквы, цифры, подчёркивания и дефисы. Позже имя изменить нельзя.
admin-groups-list-add-group-2 = Добавить группу +
admin-groups-list-group = Группа
admin-groups-list-display-name-2 = Отображаемое имя
admin-groups-list-members = Участники
admin-groups-list-collections = Коллекции
admin-groups-list-loading = Загрузка...
admin-llm-config-admin-llm = Администрирование: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = Загрузка…
admin-llm-config-no-llm-provider-is-configured = Провайдер LLM не настроен. Задайте LLM_BASE_URL / LLM_MODEL в hoover4.ini и разверните систему заново.
admin-llm-config-providers = Провайдеры
admin-llm-config-the-refresh-runs-in-the = Обновление идёт в фоне. Текущий список остаётся виден.
admin-llm-config-refresh-in-flight-u = {" "}Идёт обновление…
admin-llm-config-provider = Провайдер
admin-llm-config-models = Модели
admin-llm-config-freshest = Самое свежее
admin-llm-config-status = Статус
admin-llm-config-refresh-catalog = Обновить каталог
admin-llm-config-agent-turns-board-assessments-and = Ходы агента, оценки досок и преобразования отчётов
admin-llm-config-titles-summaries-and-board-labels = Заголовки, сводки и подписи досок
admin-llm-config-hoover4-ini-sets-these-models = Эти модели задаёт hoover4.ini: quality_model провайдера LLM для ходов агента, оценок досок и преобразований отчётов, если он задан, а для остального модель провайдера.
admin-llm-config-thinking = Рассуждение
admin-llm-config-the-model-reasons-before-each = Модель рассуждает перед каждым вызовом инструмента и каждым ответом.
admin-llm-config-catalog = Каталог
admin-llm-config-filter-models-u = Фильтр моделей…
admin-llm-config-model = Модель
admin-llm-config-flags = Признаки
admin-llm-config-calls-14d = Вызовов за 14 дн.
admin-llm-config-ai-status = Состояние ИИ
admin-llm-config-shows-the-serving-health = {" "}показывает состояние обслуживания.
admin-llm-reports-reports = Отчёты
admin-llm-reports-each-report-runs-when-you = Каждый отчёт запускается, когда вы нажимаете его кнопку.
admin-llm-reports-running-u = Выполняется…
admin-llm-reports-run-report = Запустить отчёт
admin-llm-reports-read-at = Прочитано: { $read_at }
admin-llm-reports-errors = Ошибки
admin-llm-reports-failed-attempts-by-step-and = Неудачные попытки по шагам и классам ошибок, а также запуски агента, которые завершились сбоем или раньше срока, по причине завершения.
admin-llm-reports-source = Источник
admin-llm-reports-class = Класс
admin-llm-reports-no-errors-in-30-days = За 30 дней ошибок нет.
admin-llm-reports-recent-errors = Недавние ошибки
admin-llm-reports-the-newest-100-failed-attempts = 100 новейших неудачных попыток за 7 дней. Откройте строку, чтобы прочитать ошибку.
admin-llm-reports-time = Время
admin-llm-reports-user = Пользователь
admin-llm-reports-name = Имя
admin-llm-reports-error = Ошибка
admin-llm-reports-no-errors-in-7-days = За 7 дней ошибок нет.
admin-llm-reports-show = Показать
admin-llm-reports-tool-calls = Вызовы инструментов
admin-llm-reports-one-row-for-each-tool = Одна строка на инструмент, по числу вызовов за 30 дней. Ошибка означает неудавшийся вызов.
admin-llm-reports-tool = Инструмент
admin-llm-reports-calls-24-h = Вызовов, 24 ч
admin-llm-reports-error-24-h = Ошибок, %, 24 ч
admin-llm-reports-avg-ms-24-h = Ср. мс, 24 ч
admin-llm-reports-calls-7-d = Вызовов, 7 дн.
admin-llm-reports-error-7-d = Ошибок, %, 7 дн.
admin-llm-reports-avg-ms-7-d = Ср. мс, 7 дн.
admin-llm-reports-calls-30-d = Вызовов, 30 дн.
admin-llm-reports-error-30-d = Ошибок, %, 30 дн.
admin-llm-reports-avg-ms-30-d = Ср. мс, 30 дн.
admin-llm-reports-no-tool-calls-in-30 = За 30 дней вызовов инструментов нет.
admin-llm-reports-top-users = Самые активные пользователи
admin-llm-reports-the-30-users-with-the = 30 пользователей с наибольшим временем работы моделей за период.
admin-llm-reports-30-days = 30 дней
admin-llm-reports-7-days = 7 дней
admin-llm-reports-24-hours = 24 часа
admin-llm-reports-tool-time = Время инструментов
admin-llm-reports-model-calls = Вызовов модели
admin-llm-reports-model-time = Время модели
admin-llm-reports-tokens-in = Токенов на входе
admin-llm-reports-tokens-out = Токенов на выходе
admin-llm-reports-no-agent-use-in-the = За период агент не использовался.
admin-llm-reports-system-one-checks = Проверки System one
admin-llm-reports-requests-are-grouped-by-hook = Запросы сгруппированы по хуку и правилу. Задержки указаны в миллисекундах. Доли считаются по запросам за последние 30 дней.
admin-llm-reports-counts = Количество
admin-llm-reports-recent-failures = Недавние сбои
admin-llm-reports-select-run-report-to-read = Нажмите «Запустить отчёт», чтобы прочитать статистику.
admin-llm-reports-hook = Хук
admin-llm-reports-rule = Правило
admin-llm-reports-outcome = Исход
admin-llm-reports-questions = Вопросы
admin-llm-reports-median-ms = Медиана, мс
admin-llm-reports-95th-percentile-ms = 95-й перцентиль, мс
admin-llm-reports-error-2 = Ошибок, %
admin-llm-reports-positive = Положительных, %
admin-llm-reports-actions = Действия
admin-metrics-admin-metrics = Администрирование: метрики
admin-metrics-metrics = Метрики
admin-metrics-the-last-24-hours = Последние 24 часа.
admin-metrics-loading-u = Загрузка…
admin-metrics-manticore-load-now = Нагрузка Manticore (сейчас)
admin-metrics-ram-is-the-memory-of = RAM означает память таблиц. Нагрузка потоков дана за последние 1, 5 и 15 минут.
admin-metrics-manticore-status-could-not-be = Не удалось прочитать состояние Manticore: { $error }
admin-metrics-thread-load-1-5-15 = Нагрузка потоков (1, 5, 15 мин)
admin-metrics-primary-thread-load-1-5 = Нагрузка основных потоков (1, 5, 15 мин)
admin-metrics-secondary-thread-load-1-5 = Нагрузка вторичных потоков (1, 5, 15 мин)
admin-metrics-worker-threads-busy-total = Рабочих потоков занято / всего
admin-metrics-work-queue = Очередь работ
admin-metrics-ram-held-by-tables = RAM, занятая таблицами
admin-metrics-disk-used-by-tables = Диск, занятый таблицами
admin-metrics-tables-merging = Таблиц в слиянии
admin-metrics-tables-read = Прочитано таблиц
admin-metrics-read-at = Прочитано
admin-metrics-largest-tables-by-ram = Крупнейшие таблицы по RAM
admin-metrics-table = Таблица
admin-metrics-ram = RAM
admin-metrics-disk = Диск
admin-metrics-disk-chunks = Дисковые чанки
admin-metrics-merging = Слияние
admin-metrics-usage-last-24-h = Использование (последние 24 ч)
admin-metrics-events-by-type = События по типам
admin-metrics-event = Событие
admin-metrics-count = Количество
admin-metrics-events-per-hour = События по часам
admin-metrics-no-events-recorded-yet = Событий пока не записано.
admin-metrics-busiest-users = Самые активные пользователи
admin-metrics-user = Пользователь
admin-metrics-events = События
admin-metrics-events-2 = { $point_bucket }: событий: { $point_count }
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = Вызовы API (последние 24 ч)
admin-metrics-no-api-calls-recorded-yet = Вызовов API пока не записано.
admin-metrics-function = Функция
admin-metrics-calls = Вызовы
admin-metrics-errors = Ошибки
admin-metrics-error-rate = Доля ошибок
admin-metrics-bytes-in = Байт на входе
admin-metrics-bytes-out = Байт на выходе
admin-operation-detail-admin-operation = Администрирование: операция { $op_id }
admin-operation-detail-loading-operation = Загрузка операции…
admin-operation-detail-back-to-operations = Назад к операциям
admin-operation-detail-operation = Операция
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · в очереди с { $row_started_at }
admin-operation-detail-not-started = не начата
admin-operation-detail-re-run-counts-are-not = Данные о повторных запусках недоступны.
admin-operation-detail-failed-document-s-task-failure = Документов с ошибкой: { $documents }, сбоев задач: { $row_failed_tasks_unwrap_or_0 }
admin-operation-detail-failures-were-not-counted = Сбои не подсчитывались.
admin-operation-detail-open-captured-failure-tree = Открыть сохранённое дерево сбоев
admin-operation-detail-open-in-temporal = Открыть в Temporal
admin-operation-detail-plans = Планы
admin-operation-detail-plan-s-page = Планов: { $data_plans_total }, страница { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Для этой операции планы не записаны.
admin-operation-detail-dataset = Набор данных
admin-operation-detail-plan-hash = Хеш плана
admin-operation-detail-source = Источник
admin-operation-detail-finished = Завершён
admin-operation-detail-previous = Назад
admin-operation-detail-next = Вперёд
admin-operation-detail-error-events = События ошибок
admin-operation-detail-error-event-s-page = Событий ошибок: { $data_events_total }, страница { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Для этой операции события ошибок не записаны.
admin-operation-detail-time = Время
admin-operation-detail-hash = Хеш
admin-operation-detail-task = Задача
admin-operation-detail-event = Событие
admin-operation-detail-error-excerpt = Фрагмент ошибки
admin-operations-admin-operations = Администрирование: операции
admin-operations-operations = Операции
admin-operations-loading-operations = Загрузка операций…
admin-operations-filters = Фильтры
admin-operations-state = Состояние
admin-operations-any-state = Любое состояние
admin-operations-collection = Коллекция
admin-operations-all-collections = Все коллекции
admin-operations-choose-a-collection-to-see = Выберите коллекцию, чтобы увидеть доли ошибок по задачам.
admin-operations-operations-newest-first = Операции, сначала новые
admin-operations-newer = Новее
admin-operations-page = Страница { $current_page_1 }
admin-operations-older = Старее
admin-operations-failure-rate-by-task-type = Доля сбоев по типам задач ({ $collectionname })
admin-operations-one-row-per-activity-execution = Одна строка на выполнение активности, включая повторы. Доля выше{" "}
admin-operations-is-marked = {" "}отмечена.
admin-operations-no-task-executions-recorded-for = Для этой коллекции выполнений задач пока не записано.
admin-operations-task = Задача
admin-operations-error-rate = Доля ошибок
admin-operations-failed-total-executions = Сбоев / всего выполнений
admin-operations-documents-affected = Затронуто документов
admin-operations-above-the-line = выше линии
admin-operations-no-operations-recorded-for-this = Для этого фильтра операций не записано.
admin-operations-kind = Вид
admin-operations-target = Объект
admin-operations-workflow = Рабочий процесс
admin-operations-queued-at = Поставлена в очередь
admin-operations-started = Начало
admin-operations-duration = Длительность
admin-operations-progress = Ход выполнения
admin-operations-eta = Осталось
admin-operations-outcome = Исход
admin-operations-destructive = Разрушающая
admin-operations-repeated-run = Повторный запуск
admin-operations-no-estimate-yet = оценки пока нет
admin-operations-cancel = Отменить
admin-operations-type-to-confirm = введите { $target } для подтверждения
admin-operations-re-run = Запустить снова
admin-operations-waiting-for-a-free-slot = ждёт свободного слота или свободного объекта
admin-operations-counting-work = подсчёт работы…
admin-operations-open-captured-tree = Открыть сохранённое дерево
admin-operations-no-captured-tree = сохранённого дерева нет
admin-operations-no-failed-documents = документов с ошибкой нет
admin-operations-document-s-failed = документов с ошибкой: { $n }
admin-operations-task-failure-s = сбоев задач: { $t }
admin-operations-failures-not-counted = сбои не подсчитаны
admin-operations-the-newest-ten-operations-of = Десять новейших операций этой коллекции.{" "}
admin-operations-all-operations = Все операции
admin-settings-admin-settings = Администрирование: настройки
admin-settings-server-settings = Настройки сервера
admin-settings-key = Ключ
admin-settings-value = Значение
admin-settings-description = Описание
admin-settings-save = Сохранить
admin-settings-loading = Загрузка...
admin-settings-deployment-configuration-read-only = Конфигурация развёртывания (только чтение)
admin-settings-not-set = (не задано)
admin-user-detail-admin-user = Администрирование: пользователь { $username }
admin-user-detail-failed-to-load-user = Не удалось загрузить пользователя
admin-user-detail-loading = Загрузка...
admin-user-detail-user = Пользователь
admin-user-detail-the-next-login-replaces-the = Следующий вход заменяет полное имя, адрес эл. почты и статус суперпользователя у пользователя, пришедшего через прокси входа.
admin-user-detail-llm-usage-u = Использование LLM →
admin-user-detail-full-name = Полное имя
admin-user-detail-full-name-2 = полное имя
admin-user-detail-email = Эл. почта
admin-user-detail-superuser = Суперпользователь
admin-user-detail-save = Сохранить
admin-user-detail-groups = Группы
admin-user-detail-saving-membership = Сохранение членства...
admin-user-detail-group = Группа
admin-user-detail-origin = Происхождение
admin-user-detail-group-admin = Администратор группы
admin-user-detail-uploader = Загружающий
admin-user-detail-remove = Убрать
admin-user-detail-add-to-group-u = Добавить в группу…
admin-user-detail-add = Добавить
admin-user-detail-danger-zone = Опасная зона
admin-user-detail-delete-user = Удалить пользователя
admin-user-llm-admin-llm-use-by = Администрирование: использование LLM пользователем { $username }
admin-user-llm-u-back-to-user = ← Назад к пользователю
admin-user-llm-loading-u = Загрузка…
admin-user-llm-totals-all-time = Итого (за всё время)
admin-user-llm-chat-sessions = Сеансы чата
admin-user-llm-messages = Сообщения
admin-user-llm-tool-calls = Вызовы инструментов
admin-user-llm-model-and-tool-time = Время модели и инструментов
admin-user-llm-model-and-tool-time-of = время модели и инструментов в шагах агента этого пользователя. Параллельные вызовы инструментов учитываются полностью
admin-user-llm-rate-limit-usage-current-windows = Использование лимитов частоты (текущие окна)
admin-user-llm-in-process-counters-of-the = Счётчики в памяти работающего контейнера сайта. Лимит чата: { $metrics_chat_per_minute }/мин, лимит API: { $metrics_api_per_minute }/мин, с затухающей устойчивой скоростью на более длинных окнах.
admin-user-llm-chat-messages = Сообщения чата
admin-user-llm-api-calls = Вызовы API
admin-user-llm-window = Окно
admin-user-llm-used = Использовано
admin-user-llm-budget = Лимит
admin-user-llm-no-chat-sessions = Сеансов чата нет.
admin-user-llm-title = Название
admin-user-llm-created = Создано
admin-users-list-admin-users = Администрирование: пользователи
admin-users-list-users = Пользователи
admin-users-list-search-users = Поиск пользователей
admin-users-list-username = Имя пользователя
admin-users-list-full-name = Полное имя
admin-users-list-email-address = Адрес эл. почты
admin-users-list-superuser = Суперпользователь
admin-users-list-groups = Группы
admin-users-list-created = Создан
admin-users-list-last-login = Последний вход
admin-users-list-loading = Загрузка...
dataset-create-panel-put-the-documents-in-a = Положите документы в папку там и перезагрузите эту страницу.
dataset-create-panel-the-name-cannot-start-with = Имя не может начинаться с точки или содержать косую черту.
dataset-create-panel-and-a-dash-a-space = а дефис, пробел или точка становятся подчёркиванием. Позже имя изменить нельзя.
dataset-create-panel-the-form-starts-with-the = Форма начинается со значений коллекции по умолчанию. Набор данных, созданный со значениями по умолчанию, следует за их последующими изменениями,{" "}
dataset-ocr-panel-apply-saves-the-languages-and = Кнопка «Применить» сохраняет языки, после чего обновление OCR этого набора данных запускается само.
dataset-ocr-panel-the-list-comes-from-the = Список берётся из работающего образа, а не из конфигурации.
live-chats-panel-off = выкл.
processing-updates-panel-the-waiting-steps-change-each = Ожидающие шаги изменяют: { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), каждый файл учитывается один раз. Выполнить нужно: { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = а дефис, пробел или точка становятся подчёркиванием. Позже имя изменить нельзя.
admin-llm-config-fresh = свежий
admin-llm-config-tools = инструменты{" "}
admin-llm-config-vision = изображения{" "}
admin-metrics-ms = { $f_p50_ms } мс
admin-metrics-ms-2 = { $f_p95_ms } мс
dataset-create-panel-and-a-dataset-created-with = а набор данных, созданный с другими значениями, сохраняет свои. Изменение на странице набора данных запускает OCR заново.
dataset-create-panel-read-only = { $option_name } (только чтение)
live-chats-panel-on = вкл.
processing-updates-panel-up-to-date-select-it = Актуально. Выберите, чтобы запустить снова.
admin-ai-status-yes = да
admin-ai-status-no-2 = нет
admin-ai-status-ms = { $t_median_latency_ms } мс
admin-collection-processing-errors-2 = Ошибок: { $ds_error_count }
admin-collection-processing-done = готово
admin-collection-processing-failed-2 = сбоев: { $stage_failed_documents }
admin-collection-processing-left = осталось
admin-collection-processing-dataset-level = на уровне набора данных
admin-collections-list-groups = Групп: { $c_group_count }
admin-failures-operation-s = Операций: { $group_operation_count }
admin-groups-list-groupname = имя группы
admin-llm-config-stale = устарел
admin-llm-config-thinking-is-on = Рассуждение включено
admin-llm-config-thinking-is-off = Рассуждение выключено
admin-llm-config-shown = Показано: { $models_len }
admin-llm-config-reasoning = рассуждение
admin-llm-config-ms = { $m_median_latency_ms } мс
admin-metrics-of = { $load_table_count_load_unread_tables } из { $load_table_count }
admin-metrics-yes = да
admin-metrics-no = нет
admin-metrics-max = макс.
admin-metrics-ms-3 = { $f_max_ms } мс
admin-operation-detail-started = начато { $run_started_at }
admin-operation-detail-yes = да
admin-operation-detail-no = нет
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = эл. почта
admin-user-llm-untitled = (без названия)
admin-dataset-ocr-panel-models-not-in-image = Моделей для языков { $languages } нет в образе. Служба загружает их при первом использовании, для чего нужен доступ в интернет.
admin-dataset-ocr-panel-variant-pages = { $source } · страниц: { $pages }
admin-processing-updates-panel-prerequisites-waiting = Сначала нужно обновить коллекцию: { $steps }. Шаги, которые пишут в поисковый индекс, ждут этого.
admin-operations-no-task-type-failing = Ни один тип задач не даёт сбоев чаще { $threshold }%.
admin-operations-task-types-failing = Типов задач со сбоями чаще { $threshold }%: { $count }.
processing-updates-panel-collection-updates = Обновления коллекции
admin-collections-list-some-datasets-are-not-counted = Часть наборов данных ещё не подсчитана.
admin-failures-hide = Скрыть
admin-failures-show = Показать
admin-settings-web-session-lifetime-in-seconds = Срок жизни веб-сеанса в секундах (по умолчанию: 604800 = 1 неделя)
admin-settings-turns-every-new-chat-turn = При значении false отключает каждый новый ход чата (по умолчанию: true). Выполняющийся ход завершается. Действует со следующей отправки, без повторного развёртывания.
admin-settings-written-by-main-py-probe = Записывается командой `main.py probe-embeddings` и показывает то, что конечная точка РЕАЛЬНО обслуживает. Ручное изменение не меняет сервер.
admin-settings-the-folder-whose-subfolders-the = Папка, подпапки которой перечисляет форма набора данных. Для изменения нужно повторное развёртывание.
admin-settings-from-hoover4-ini-changing-it = Из hoover4.ini. Для изменения нужно повторное развёртывание.
admin-feedback-bug = Ошибка
admin-operations-state-name = { $state ->
        [pending] ожидает
        [queued] в очереди
        [running] выполняется
        [finished] завершена
        [errored] с ошибкой
        [cancelled] отменена
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Дерево сбоев операции { $op_id }
admin-failure-detail-showing-of-characters = показано символов: { $node_stack_trace_chars_count } из { $node_stack_trace_original_len }
admin-operations-operation = Операция: { $state }.
admin-operations-dispatched = Отправлено: { $new_id }.
admin-operations-rows = строк: { $row_progress_done } / { $row_progress_total }
admin-operations-plans = планов: { $row_progress_done } / { $row_progress_total }
admin-group-detail-group-2 = Группа { $groupname }
admin-settings-the-setting-was-saved-successfully = Настройка «{ $k }» успешно сохранена.
admin-metrics-kib = { $b_as_f64_1024_0 } КиБ
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } МиБ
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } ГиБ
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = Группа «{ $g }» успешно добавлена.
admin-user-detail-user-2 = Пользователь { $username }
admin-dataset-detail-dataset = Набор данных { $dataset_id }
admin-dataset-detail-collections = Коллекции › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } из { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Не удалось прочитать настройку загрузки: { $err }
admin-dataset-detail-operation-started = Операция запущена: { $run_id }
admin-collection-detail-collection = Коллекция { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Не удалось прочитать настройку векторов: { $err }
admin-collection-processing-processing-of = Обработка { $collection_id }
admin-collection-processing-collections = Коллекции › { $collection_id }
admin-collection-processing-executions-2 = Выполнений: { $b_total_executions }
admin-collection-processing-ms = { $row_mean_ms } мс
admin-collection-processing-ms-2 = { $row_p95_ms } мс
admin-collection-processing-ms-2-2 = { $row_max_ms } мс
admin-collection-processing-as-of = по состоянию на { $at }
admin-collection-processing-over-the-last-s = за последние { $live_window_seconds } с
admin-collection-processing-retry-started-run = Повтор запущен (запуск { $run }).
admin-collection-processing-document-retry-started-run = Повтор для документа запущен (запуск { $run }).
admin-operation-detail-operation-2 = Операция { $op_id }
admin-user-llm-llm-usage-of = Использование LLM пользователем { $username }
admin-user-llm-users = Пользователи › { $username }
processing-updates-panel-the-processing-updates-could-not = Не удалось прочитать обновления обработки: { $e }
processing-updates-panel-update-started = Обновление запущено: { $op_id }
dataset-ocr-panel-of-plans = Планов: { $operation_progress_done } из { $operation_progress_total }
dataset-ocr-panel-adding = добавляются: { $added }
dataset-ocr-panel-removing = удаляются: { $removed }
dataset-ocr-panel-plan-s-reopened = Планов открыто заново: { $plans }
dataset-create-panel-saved-as-this-collection-s-2 = Сохранено как значения коллекции по умолчанию. Эти наборы данных наследуют их, а их обновления OCR запускаются по одному: { $changed_join }. Наборы данных со своими языками сохраняют их.
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] папка
        [few] папки
        [many] папок
       *[other] папки
    }
    [tables] { $count ->
        [one] таблица
        [few] таблицы
        [many] таблиц
       *[other] таблицы
    }
   *[files] { $count ->
        [one] файл
        [few] файла
        [many] файлов
       *[other] файла
    }
}
processing-updates-step-runs = { $count ->
    [one] запуск шага
    [few] запуска шага
    [many] запусков шага
   *[other] запуска шага
}
processing-update-search_schema-title = Схема поискового индекса
processing-update-search_schema-explanation = { $files ->
    [one] В { $count } поисковой таблице коллекции нет столбца, который нужен поисковому индексу.
    [few] В { $count } поисковых таблицах коллекции нет столбца, который нужен поисковому индексу.
    [many] В { $count } поисковых таблицах коллекции нет столбца, который нужен поисковому индексу.
   *[other] В { $count } поисковых таблицах коллекции нет столбца, который нужен поисковому индексу.
} Столбец добавляется в каждую таблицу. Поиск продолжает работать.
processing-update-search_schema-runs = Таблицы поискового индекса
processing-update-unfinished-title = Незавершённая обработка
processing-update-unfinished-explanation = { $files ->
    [one] { $count } файл обработан не до конца.
    [few] { $count } файла обработаны не до конца.
    [many] { $count } файлов обработаны не до конца.
   *[other] { $count } файла обработаны не до конца.
} Сюда входят файлы без плана обработки, например после прерванного приёма. Их обработка будет завершена.
processing-update-unfinished-runs = Все этапы обработки этих файлов
processing-update-failed_files-title = Файлы с ошибками
processing-update-failed_files-explanation = { $files ->
    [one] У { $count } файла есть ошибка обработки.
    [few] У { $count } файлов есть ошибка обработки.
    [many] У { $count } файлов есть ошибка обработки.
   *[other] У { $count } файлов есть ошибка обработки.
} Для них заново выполняются неудавшиеся этапы. Автоматический запуск повторяет попытку для файла один раз для каждой новой версии этапа, на котором произошёл сбой.
processing-update-failed_files-runs = Неудавшиеся этапы, затем извлечение сущностей, эмбеддинги и индексация
processing-update-virus_scan-title = Проверка на вирусы
processing-update-virus_scan-explanation = { $files ->
    [one] У { $count } файла нет вердикта антивируса.
    [few] У { $count } файлов нет вердикта антивируса.
    [many] У { $count } файлов нет вердикта антивируса.
   *[other] У { $count } файлов нет вердикта антивируса.
} Эти файлы проверяются. Файл, который сканер признал заражённым, помечается в поиске, а скачивание его оригинала и PDF с текстовым слоем отклоняется.
processing-update-virus_scan-runs = Антивирусная проверка, затем поисковый атрибут заражённых файлов
processing-update-tables-title = Таблицы
processing-update-tables-explanation = { $files ->
    [one] { $count } файл имеет прежнее чтение таблицы или неполные зависимые результаты. Его сохранённые результаты обновляются.
    [few] Файлов с прежним чтением таблиц или неполными зависимыми результатами: { $count }. Их сохранённые результаты обновляются.
    [many] Файлов с прежним чтением таблиц или неполными зависимыми результатами: { $count }. Их сохранённые результаты обновляются.
    *[other] Файлов с прежним чтением таблиц или неполными зависимыми результатами: { $count }. Их сохранённые результаты обновляются.
    }

processing-update-tables-runs = Чтение таблиц, сущности, сигналы, эмбеддинги и оба индекса
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Файлы, требующие автоматического OCR: { $count }. Обнаруженные страницы определяют установленные модели. Полные новые результаты удаляют заменённые варианты.
processing-update-ocr-runs = OCR и PDF с текстовым слоем, затем извлечение сущностей, эмбеддинги и индексация нового текста
processing-update-ocr_detection-title = Определение OCR
processing-update-ocr_detection-explanation = Файлы без текущего обнаружения текста, письменности или языка: { $count }. Каждое подходящее изображение и страница PDF проверяются ограниченными пакетами.
processing-update-ocr_detection-runs = Определение, затем поисковые атрибуты этих файлов
processing-update-pdf_text-title = Текст PDF с поиском
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } файл имеет PDF с поиском с прежним текстовым слоем.
    [few] { $count } файла имеют PDF с поиском с прежним текстовым слоем.
    [many] { $count } файлов имеют PDF с поиском с прежним текстовым слоем.
   *[other] { $count } файла имеют PDF с поиском с прежним текстовым слоем.
} Этот слой копировал каждую букву вне западноевропейских алфавитов как чёрный квадрат. PDF на языках только с западноевропейскими буквами остаются без изменений. Остальные PDF читаются, и части с чёрными квадратами создаются заново. PDF изображения использует сохранённые слова OCR. Страница PDF получает новый запрос OCR.
processing-update-pdf_text-runs = Части PDF с поиском, затем индексация текста OCR пересозданных PDF
processing-update-vectors-title = Векторы
processing-update-vectors-explanation = { $files ->
    [one] У { $count } файла с текстом нет векторов модели эмбеддингов, которую использует установка.
    [few] У { $count } файлов с текстом нет векторов модели эмбеддингов, которую использует установка.
    [many] У { $count } файлов с текстом нет векторов модели эмбеддингов, которую использует установка.
   *[other] У { $count } файлов с текстом нет векторов модели эмбеддингов, которую использует установка.
} Их векторы вычисляются и индексируются.
processing-update-vectors-runs = Эмбеддинги и векторная индексация
processing-update-folder_counts-title = Счётчики папок
processing-update-folder_counts-explanation = { $files ->
    [one] У { $count } папки нет числа файлов или размера либо значения устарели.
    [few] У { $count } папок нет числа файлов или размера либо значения устарели.
    [many] У { $count } папок нет числа файлов или размера либо значения устарели.
   *[other] У { $count } папок нет числа файлов или размера либо значения устарели.
} Счётчики рассчитываются заново.
processing-update-folder_counts-runs = Дерево папок
admin-uploads-badge = Загрузки
admin-uploads-badge-title = Принимает загрузки

processing-update-archive_members-title = Элементы архивов

processing-update-archive_members-explanation = { $files ->
    [one] { $count } разделённый архив требует актуального списка элементов. Его элементы и результаты поиска обновляются.
    [few] Разделённых архивов, которым нужны актуальные списки элементов: { $count }. Их элементы и результаты поиска обновляются.
    [many] Разделённых архивов, которым нужны актуальные списки элементов: { $count }. Их элементы и результаты поиска обновляются.
    *[other] Разделённых архивов, которым нужны актуальные списки элементов: { $count }. Их элементы и результаты поиска обновляются.
    }

processing-update-archive_members-runs = Извлечение архивов, согласование элементов и зависимая обработка

processing-update-image_previews-title = Предпросмотр изображений

processing-update-image_previews-explanation = { $files ->
    [one] { $count } изображение редкого формата не имеет предпросмотра. Его предпросмотр создаётся заново.
    [few] Изображений редких форматов без предпросмотра: { $count }. Их предпросмотр создаётся заново.
    [many] Изображений редких форматов без предпросмотра: { $count }. Их предпросмотр создаётся заново.
    *[other] Изображений редких форматов без предпросмотра: { $count }. Их предпросмотр создаётся заново.
    }

processing-update-image_previews-runs = Создание и проверка предпросмотра изображений

processing-update-search_terms-title = Термины поиска

processing-update-search_terms-explanation = { $files ->
    [one] { $count } таблица поиска требует актуальных терминов фильтров. Термины языка, OCR, письменности и красных флагов станут доступны для поиска.
    [few] Таблиц поиска, которым нужны актуальные термины фильтров: { $count }. Термины языка, OCR, письменности и красных флагов станут доступны для поиска.
    [many] Таблиц поиска, которым нужны актуальные термины фильтров: { $count }. Термины языка, OCR, письменности и красных флагов станут доступны для поиска.
    *[other] Таблиц поиска, которым нужны актуальные термины фильтров: { $count }. Термины языка, OCR, письменности и красных флагов станут доступны для поиска.
    }

processing-update-search_terms-runs = Индексирование и проверка терминов фильтров

automatic-ocr-title = Автоматическое OCR
automatic-ocr-refresh = Обновить состояние
automatic-ocr-coverage = Охват страниц
automatic-ocr-pages = Страницы
automatic-ocr-models = Модели OCR
automatic-ocr-reason = Причина
automatic-ocr-truncated = Список диагностики неполон.
automatic-ocr-presence = Есть опубликованный текст OCR
automatic-ocr-policy = OCR выбирает установленные модели по обнаруженным письменности и языку каждой подходящей страницы. Сначала используется Tesseract, затем EasyOCR для неподдержанных письменностей.
automatic-ocr-unknown = Текущая публикация не записана. Отсутствие обнаружения и ошибка обработки не доказывают отсутствие текста.
automatic-ocr-retry = После устранения причины повторите неполную или неудачную работу через обновления обработки. Неподдерживаемый охват требует совместимых установленных моделей.
automatic-ocr-presence-help = Фильтр находит только проверенный опубликованный текст OCR. Обнаружение и попытки обработки не доказывают наличие опубликованного результата.
automatic-ocr-state = { $state ->
    [candidate] Ожидает
    [planned] Запланировано
    [failed] Ошибка
    [incomplete] Неполное
    [unsupported] Не поддерживается
    [published] Опубликовано
    [applied] Проверено
    [ready] Текст обнаружен
    [no_text] Текст не обнаружен
    *[other] { $state }
    }

processing-update-entities-title = Именованные сущности
processing-update-entities-explanation = Файлы, требующие текущего извлечения сущностей или поисковых результатов: { $count }. Прежние успешные результаты заменяются после завершения инференса.
processing-update-entities-runs = Извлечение именованных сущностей, атрибуты текста и поисковые термины сущностей

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Письменность не определена
    [tesseract_capabilities_unavailable] Охват Tesseract недоступен
    [detected_language] Модель соответствует обнаруженному языку
    [unknown_language_script_coverage] Язык неизвестен. Выбрана модель письменности.
    [language_script_mismatch_script_coverage] Язык и письменность различаются. Выбрана модель письменности.
    [language_model_unavailable_script_coverage] Языковая модель недоступна. Выбрана модель письменности.
    [easyocr_capabilities_unavailable] Охват EasyOCR недоступен
    [tesseract_script_unavailable] Tesseract не охватывает письменность. Выбран EasyOCR.
    [script_coverage_unavailable] Ни одна установленная модель не охватывает эту письменность.
    *[other] { $reason }
    }

processing-updates-check-requested = Конвейер рассчитывает обновления. Счётчики изменятся после завершения расчёта.
