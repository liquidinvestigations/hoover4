# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = El bot está trabajando...
chat-composer-ask-the-bot = Pregunta al bot...
chat-composer-internet-tools = Herramientas de Internet
chat-composer-agent-language-title = El agente responde en { $language }. Cambia el idioma en la configuración, en una pestaña nueva.
chat-composer-try-again-in-s = Vuelve a intentarlo en { $secs } s
chat-composer-stop-the-answer-the-partial = Detener la respuesta (la parcial no se guarda en la conversación)
chat-composer-starting-the-conversation-u = Iniciando la conversación…
chat-composer-send = Enviar
chat-conversation-find-search-in-conversation = Buscar en la conversación
chat-conversation-find-previous-match = Coincidencia anterior
chat-conversation-find-next-match = Coincidencia siguiente
chat-conversation-find-investigation-board = Cuadro de investigación
doc-ref-card-not-openable = No se puede abrir: { $reason }.
doc-ref-card-the-search-term-was = El término de búsqueda{ " " }
doc-ref-card-open = Abrir
doc-ref-card-not-openable-2 = No se puede abrir
chat-markdown-text-show-the-cited-source = Mostrar la fuente citada
chat-markdown-text-no-citation-of-this-conversation = Ninguna citación de esta conversación dio este identificador, por lo que ningún documento lo respalda.
chat-markdown-text-citations-of-this-conversation-gave = Las citaciones de esta conversación dieron este identificador a más de un documento, por lo que no enlaza a ninguno de ellos.
cards-browser-card-open-the-archived-page = Abrir la página archivada
cards-browser-card-the-page-itself-was-not = La página en sí no fue archivada (estado: { $artifact_status }). La captura de pantalla de arriba es lo que se conservó.
cards-browser-card-click-the-screenshot-to-open = Haz clic en la captura de pantalla para abrir la página archivada.
cards-browser-card-show-less = Mostrar menos
cards-browser-card-show-all = Mostrar todo
cards-browser-card-archived-page = Página archivada
cards-browser-card-download = Descargar
cards-browser-card-archived-copy-of = Copia archivada de { $artifact_url }
cards-browser-card-this-page-was-not-archived = Esta página no fue archivada (estado: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } con una tarjeta
cards-entities-card-the-entity-list-was-cut = La lista de entidades se recortó.
cards-entities-card-open-the-card-for-this = Abrir la tarjeta para este valor ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Sin tarjeta: esta conversación nunca nombró el conjunto de datos del que provenían estos valores, y al espectador se le dirige por el conjunto de datos.
cards-entities-card-more-all-of-them-in = { $rest } más, todos ellos en el panel de entidades del documento.{ " " }
cards-entities-card-names-organisations-and-places-above = Los nombres, organizaciones y lugares de arriba son la interpretación de un modelo sobre el texto. Ninguna regla los validó, así que no hay nada que explicar y no abren nada.
cards-entities-card-nothing-extracted-from-this-document = Nada extraído de este documento.
chat-tool-cards-hide = Ocultar
chat-tool-cards-expand = Ampliar
chat-tool-cards-hide-raw-json = Ocultar JSON sin procesar
chat-tool-cards-show-raw-json = Mostrar JSON sin procesar
cards-result-cards-search-this = Buscar esto
cards-result-cards-search-every-collection = Buscar en todas las colecciones
cards-result-cards-form = Formulario { $index }: { $form }
cards-result-cards-show-full-text = Mostrar texto completo
cards-result-cards-quote = Citación: { $quote }
cards-result-cards-reason = Motivo: { $why }
cards-result-cards-open-question = Pregunta abierta: { $question }
cards-result-cards-the-explore-gave-this-answer =
    La exploración dio esta respuesta a su cuadro de investigación como un hallazgo { $kind ->
        [sourced] procedente de una fuente
        [inferred] inferido
        [not_found] no encontrado
       *[other] de tipo desconocido
    }.
cards-result-cards-it-left-no-open-question = No dejó ninguna pregunta abierta.
cards-result-cards-open-questions-for-the-board = Preguntas abiertas para el cuadro de investigación:
cards-result-cards-arguments = Argumentos
cards-result-cards-list-after-the-call = Lista tras la llamada: { $snapshot_goal }
cards-result-cards-replaces = { " " }· sustituye a { $replaces_id }
cards-result-cards-the-list-at-this-version = La lista en esta versión no está almacenada.
web-search-card-these-sources-returned-nothing-so = Estas fuentes no devolvieron nada, así que los resultados provienen de menos fuentes de las pretendidas
web-search-card-u-degraded = ⚠ { $degraded_len } degradado
web-search-card-form = Formulario { $index }: { $form }
web-search-card-no-results-from = Sin resultados de: { $degraded_text }
web-search-card-no-results-every-source-answered = Sin resultados. Todas las fuentes respondieron y ninguna tenía algo para esta consulta.
web-search-card-the-lowest-ranked-results-were = Los resultados de menor rango se descartaron para que esta llamada quepa en el transcriptor. El asistente vio todos ellos.
web-search-card-view-search-details = Ver detalles de la búsqueda.
web-search-card-the-stored-result-could-not = el resultado almacenado no se pudo leer de nuevo como JSON
web-search-card-nothing-was-stored-for-this = No se almacenó nada para esta consulta.
web-search-card-forms = Formularios: { $forms }
web-search-card-kind = Tipo: { $row_kind }
web-search-card-published = Publicado: { $row_published }
web-search-card-loading-search-detail-u = Cargando los detalles de la consulta…
web-search-card-could-not-load-the-search = No se pudieron cargar los detalles de la consulta: { $e }
web-search-card-malformed-detail = Detalles mal formados: { $e }
web-search-card-the-tool-returned-selected-results = La herramienta devolvió resultados seleccionados al modelo.
web-search-card-results-use-reciprocal-rank-fusion = Los resultados utilizan la fusión de rangos recíprocos.
web-search-card-returned-nothing = no devolvió nada: { $degraded }
web-search-card-all-candidates-use-fusion-order = Todos los candidatos utilizan el orden de fusión.
web-search-card-the-cross-encoder-ranks-selected = El codificador cruzado ordena los resultados seleccionados.
web-search-card-selected-results-use-fusion-order = Los resultados seleccionados utilizan el orden de fusión.
web-search-card-search-detail = Detalles de la consulta
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Buscar aquí
chat-tool-disclosure-search-every-collection = Buscar en todas las colecciones
chat-tool-disclosure-hide = Ocultar
chat-tool-disclosure-expand = Ampliar
chat-tool-disclosure-this-step-was-recorded-before = Este paso se registró antes de almacenar los argumentos y resultados de la herramienta. Solo está disponible el resumen que aparece a continuación.
chat-tool-disclosure-arguments = Argumentos
chat-tool-disclosure-result = Resultado
chat-tool-disclosure-hide-raw-json = Ocultar JSON sin procesar
chat-tool-disclosure-show-raw-json = Mostrar JSON sin procesar
chat-tool-disclosure-input-json = JSON de entrada
chat-tool-disclosure-output-json = JSON de salida
chat-transcript-ask-a-question-about-the = Haz una pregunta sobre los documentos de tus colecciones.
chat-transcript-suggested-next = Siguiente sugerido…
chat-transcript-earlier-answer = Respuesta anterior
chat-transcript-tokens-the-conversation-carries-the = Tokens que lleva la conversación, el contexto individual más grande facturado en esta ronda y cuánto se utilizó del intervalo del modelo
chat-transcript-instruction-to-the-agent = Instrucción para el agente
chat-transcript-the-context-stays-above-the = El contexto se mantiene encima del objetivo de { $target }.
chat-transcript-summary-parts-failed-the-record = { $failed } partes del resumen fallaron. El registro solo contiene las listas.
chat-transcript-show-the-record = Mostrar el registro
chat-transcript-hide-reasoning = Ocultar el razonamiento
chat-transcript-show-reasoning = Mostrar el razonamiento
chat-transcript-from-u-hide = { $count } { $noun } de { $tool } — ocultar
chat-transcript-from-u-show = { $count } { $noun } de { $tool } — mostrar
chat-transcript-u-hide = { $summary } — ocultar
chat-transcript-u-show = { $summary } — mostrar
chat-transcript-citations-of-this-conversation-give = Las citaciones de esta conversación asignan { $doc_handle } a más de un documento. La respuesta lo asigna a ninguno de ellos.
chat-transcript-report = Informar sobre { $label }
chat-transcript-open-in-the-workspace = Abrir en el espacio de trabajo
chat-transcript-this-version-could-not-be = Esta versión no se pudo leer. A continuación se muestra el texto del chat de la respuesta.
chat-transcript-files = Archivos
chat-transcript-version = { $file_name }, versión { $file_version }
chat-web-find-exact-text = Buscar texto exacto
chat-web-previous-match = Coincidencia anterior
chat-web-next-match = Coincidencia siguiente
chat-web-close-preview = Cerrar vista previa
chat-web-the-captured-page-could-not = La página capturada no se pudo cargar.
chat-web-loading = Cargando…
chat-workspace-pane-workspace = Espacio de trabajo
chat-workspace-pane-close-the-workspace = Cerrar el espacio de trabajo
chat-workspace-pane-close = Cerrar
chat-workspace-pane-loading-the-files-u = Cargando los archivos…
chat-workspace-pane-the-files-could-not-be = Los archivos no se pudieron cargar: { $error }
chat-workspace-pane-this-conversation-has-no-files = Esta conversación no tiene archivos.
chat-workspace-pane-version = versión { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Elija un archivo para leerlo.
chat-workspace-pane-loading-the-file-u = Cargando el documento…
chat-workspace-pane-the-file-could-not-be = No se ha podido cargar el documento: { $error }
chat-workspace-pane-version-2 = { $found_name }, versión { $found_version }
chat-board-create-collections = Colecciones
chat-board-create-loading-collections-u = Cargando colecciones…
chat-board-create-hoover-search-new-board = Búsqueda de Hoover - Cuadro nuevo
chat-board-create-ai-chat = Chat de IA
chat-board-create-new-investigation-board = Cuadro de investigación nuevo
chat-board-create-a-board-runs-its-goals = Un cuadro ejecuta sus objetivos como una secuencia de exploraciones de agente. Cada exploración es un chat que termina en un hallazgo de cuadro. Revisas la respuesta de cada objetivo y puedes rechazar hallazgos y añadir pistas mientras se ejecuta.
chat-board-create-title = Título
chat-board-create-goal = Objetivo
chat-board-create-remove-this-goal = Quitar este objetivo
chat-board-create-remove = Quitaar
chat-board-create-add-a-goal = Añadir un objetivo
chat-board-create-context-optional = Contexto (opcional)
chat-board-create-hints-one-per-line-optional = Pistil, una por línea (opcional)
chat-board-create-sources = Fuentes
chat-board-create-internet-tools = Herramientas de Internet
chat-board-create-creating-board = Creando cuadro...
chat-board-create-create-board = Crear cuadro
ai-chat-board-hoover-search-board = Búsqueda de Hoover - Cuadro
ai-chat-board-loading-the-board-u = Cargando el cuadro…
ai-chat-board-show-the-board-overview = Mostrar el resumen del cuadro
ai-chat-board-zoom-out = Reducir
ai-chat-board-zoom-in = Aumentar
ai-chat-board-u-ai-chat = ← Chat de IA
ai-chat-board-settings = Ajustes
ai-chat-board-board-settings = Ajustes del cuadro
ai-chat-board-internet-tools = Herramientas de Internet
ai-chat-board-the-next-explores-of-the = Las próximas exploraciones del cuadro pueden buscar en la web y leer páginas web. Las exploraciones en ejecución conservan el ajuste con el que comenzaron.
ai-chat-board-collections = Colecciones
ai-chat-board-the-collections-are-fixed-when = Las colecciones se fijan cuando se crea el cuadro.
ai-chat-board-confirm-drop = Confirmar retirada
ai-chat-board-drop-the-board = Retirar el cuadro
ai-chat-board-close = Cerrar
ai-chat-board-the-board-used-its-explore = El cuadro agotó su límite de exploración
ai-chat-board-the-board-used-explores-the = El cuadro utilizó { $explore_limit } exploraciones, el límite de un cuadro. No inicia más trabajo. Aún puedes decidir las respuestas propuestas.
ai-chat-board-create-a-new-board-to = Crea un nuevo cuadro para continuar la investigación
ai-chat-board-goal = Objetivo
ai-chat-board-goals = Objetivos
ai-chat-board-add-new-goal = Añadir un objetivo nuevo...
ai-chat-board-a-new-goal = Un objetivo nuevo
ai-chat-board-add-goal = Añadir objetivo
ai-chat-board-a-board-has-at-most = Un cuadro tiene como máximo { $max_goals } objetivos. Crea un nuevo cuadro para otro objetivo.
ai-chat-board-background-context = Contexto de antecedentes
ai-chat-board-continue-with-a-correction = Continuar con una corrección
ai-chat-board-correction-what-is-wrong-or = Corrección: qué está mal o falta. El cuadro continúa con ello.
ai-chat-board-the-board-waits-for-your = El cuadro espera tu revisión
ai-chat-board-the-board-used-its-budget = El cuadro utilizó su presupuesto de { $snap_max_explores } exploraciones.
ai-chat-board-the-assessments-gave-no-usable = Las evaluaciones no dieron ninguna dirección útil.
ai-chat-board-accept-or-reject-the-proposed = Acepta o rechaza la respuesta propuesta de cada objetivo de arriba. Una respuesta rechazada permite al cuadro continuar de inmediato.
ai-chat-board-no-proposed-answer-waits-for = No hay ninguna respuesta propuesta pendiente de tu decisión.
ai-chat-board-reopen-the-board-to-continue = Vuelve a abrir el cuadro para continuar los objetivos abiertos. Conserva sus hallazgos y respuestas.
ai-chat-board-close-the-board-to-accept = Cierra el cuadro para aceptar todas las respuestas propuestas y detenerlo, o continúalo con una corrección.
ai-chat-board-close-the-board = Cerrar el cuadro
ai-chat-board-or-reopen-the-board-to = O vuelve a abrir el cuadro para continuar los objetivos abiertos sin una corrección.
ai-chat-board-the-board-is-complete = El cuadro está completo
ai-chat-board-a-goal-has-no-accepted = Un objetivo no tiene respuesta aceptada. Vuelve a abrir el cuadro para continuar. El cuadro conserva sus hallazgos y respuestas.
ai-chat-board-add-a-hint = Añadir una pista
ai-chat-board-the-next-assessment-reads-every = La próxima evaluación lee cada pista. Una pista también responde a una exploración que hizo una pregunta.
ai-chat-board-add-hint = Añadir sugerencia
ai-chat-board-events = Eventos
ai-chat-board-newest-first = Más recientes primero
ai-chat-board-date = Fecha
ai-chat-board-actor = Autor
ai-chat-board-event = Evento
ai-chat-board-show-details = Mostrar detalles
ai-chat-board-open = Abrir
ai-chat-board-show-the-newest-events = Mostrar los { $event_rows } eventos más recientes
ai-chat-board-show-all-events = Mostrar todos los { $snap_events_len } eventos
ai-chat-board-statistics = Estadísticas
ai-chat-board-explores = Exploraciones
ai-chat-board-model-steps-per-explore = Pasos del modelo por exploración
ai-chat-board-assessments = Evaluaciones
ai-chat-board-intents = Intenciones
ai-chat-board-findings = Hallazgos
ai-chat-board-created = Creado
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } rechazó este hallazgo el { $format_utc_ms_fact_rejected_ms }. El cuadro ya no lo utiliza.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } rechazó este hallazgo. El cuadro ya no lo utiliza.
ai-chat-board-no-reason-was-given = No se dio ningún motivo.
ai-chat-board-reason = Motivo: { $fact_rejected_reason }
ai-chat-board-open-questions = Preguntas abiertas
ai-chat-board-explored-in = Explorado en
ai-chat-board-explore-this-question = Explorar esta pregunta
ai-chat-board-your-questions = Tus preguntas
ai-chat-board-ask-about-the-background-context = Preguntar sobre el contexto de antecedentes
ai-chat-board-ask-about-this-finding = Preguntar sobre este hallazgo
ai-chat-board-a-follow-up-question-about = Una pregunta de seguimiento sobre este nodo
ai-chat-board-ask = Preguntar
ai-chat-board-checks-that-changed-this-finding = Comprobaciones que modificaron este hallazgo
ai-chat-board-reject-this-correction = Rechazar esta corrección
ai-chat-board-reject-this-finding = Rechazar este hallazgo
ai-chat-board-not-answered-the-board-was = Sin responder. El cuadro se cerró sin respuesta para este objetivo. Una pista o una reapertura la vuelven a abrir.
ai-chat-board-no-answer-yet = Todavía sin responder.
ai-chat-board-the-findings-of-this-answer = Los hallazgos de esta respuesta son búsquedas que no encontraron nada. Acepta el resultado para registrar que los registros no responden al objetivo, o recházalo para continuar la investigación.
ai-chat-board-open-an-assessment-to-read = { "." } Abre una evaluación para leer por qué.
ai-chat-board-from-the-findings = De los hallazgos{ " " }
ai-chat-board-accept-answer = Aceptar respuesta
ai-chat-board-why-the-answer-is-wrong = Por qué la respuesta es incorrecta o incompleta
ai-chat-board-reject-answer = Rechazar respuesta
ai-chat-board-intent = Intención
ai-chat-board-attempts-declared = Intentos: { $intent_attempts }. Declarado { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = La exploración preguntó
ai-chat-board-add-a-hint-in-the = Añade una pista en la vista general del cuadro para responderla.
ai-chat-board-last-error = Último fallo
ai-chat-board-brief = Breve
ai-chat-board-open-the-explore-chat = Abrir el chat de exploración
ai-chat-board-loading-the-assessment-u = Cargando la evaluación…
ai-chat-board-assessment = Evaluación { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modelo { $a_model }. Resultado { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Comprobaciones que lo modificaron
ai-chat-board-prompt = Instrucción
ai-chat-board-this-assessment-ran-before-the = Esta evaluación se ejecutó antes de que se almacenaran las instrucciones.
ai-chat-board-response = Respuesta
ai-chat-history-hoover-search-chat-history = Búsqueda Hoover - Historial de chat
ai-chat-history-u-back = ← Atrás
ai-chat-history-conversation-history = Historial de conversación
ai-chat-history-show-board-chats = Mostrar chats del cuadro
ai-chat-history-loading-u = Cargando…
ai-chat-history-could-not-load-history = No se pudo cargar el historial: { $e }
ai-chat-history-no-conversations-yet = Aún no hay conversaciones.
ai-chat-history-board = Cuadro de historial de chat
ai-chat-history-new-chat = Chat nuevo
ai-chat-history-messages-updated = { $s_message_count } mensajes · actualizados el { $s_updated_at }
ai-chat-history-delete-conversation = Eliminar conversación
ai-chat-history-delete = Eliminar
ai-chat-homepage-hoover-search-ai-chat = Búsqueda Hoover - Chat IA
ai-chat-homepage-what-are-you-researching = ¿Qué estás investigando?
ai-chat-homepage-view-all-conversations = Ver todas las conversaciones
ai-chat-homepage-starting-conversation-u = Iniciando conversación…
ai-chat-homepage-investigation-boards = Cuadros de investigación
ai-chat-homepage-new-board = Cuadro nuevo
ai-chat-homepage-loading-boards-u = Cargando cuadros…
ai-chat-homepage-could-not-load-the-boards = No se pudieron cargar los cuadros de investigación: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = No tienes ningún cuadro. Un cuadro lleva a cabo una investigación larga como una secuencia de exploraciones del agente, y revisas sus respuestas.
ai-chat-homepage-updated = Actualizado el { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Búsqueda Hoover - Chat IA
ai-chat-session-this-conversation-could-not-be = No se ha podido cargar esta conversación.
ai-chat-session-loading-u = Cargando…
ai-chat-session-u-chats = ← Chats
ai-chat-session-history = Historial
ai-chat-session-show-the-files-that-the = Muestra los archivos que el asistente escribió en esta conversación
ai-chat-session-workspace = Espacio de trabajo
ai-chat-session-this-answer-was-interrupted-before = Esta respuesta se interrumpió antes de completarse porque la página o el servidor se detuvieron a mitad de la vuelta. Vuelve a preguntar para reintentarlo.
ai-chat-session-dismiss = Descartar
ai-chat-session-board-explore-chats-are-read = Las exploraciones de chat del cuadro son de solo lectura.{ " " }
ai-chat-session-open-the-board = Abre el cuadro de investigación
chat-locked-options-on = { $label }: activado
chat-locked-options-off = { $label }: desactivado
chat-tool-cards-running-u = ejecutando…
cards-result-cards-quote-found = Cita encontrada
cards-result-cards-quote-not-found = Cita no encontrada
cards-result-cards-quote-not-checked = Cita no verificada
web-search-card-results = { $results_len } resultados
chat-tool-disclosure-running-u = Procesando…
chat-transcript-call = llamada
chat-transcript-calls = llamadas
ai-chat-board-a-board-without-collections-needs = Un cuadro sin colecciones necesita herramientas de internet.
ai-chat-board-of = { $snap_explores_used } de { $snap_max_explores }
ai-chat-board-assessment-2 = evaluación { $number }
ai-chat-history-messages = { $s_message_count } mensajes
web-search-card-reranked-in = El cross-encoder reordenó los resultados en { $ms } ms.
web-search-card-engine-results = { $name }: { $count } en { $ms } ms
web-search-card-score-was-rank = puntuación { $score } · era RRF #{ $rank }
chat-activity-the-turn-waits-for-a = La ronda espera un modelo disponible.
chat-activity-the-turn-waits-for-a-2 = La ronda espera un espacio de herramienta disponible.
chat-locked-options-start-a-new-chat-to = Inicia un chat nuevo para cambiar esta configuración.
chat-locked-options-internet-tools = Herramientas de internet
chat-session-card-new-chat = Chat nuevo
chat-tool-cards-first-frame-of-the-video = Primer fotograma del vídeo
chat-tool-cards-screenshot-of = Captura de pantalla de
chat-tool-cards-image = Imagen
cards-result-cards-the-agent-asked-a-question = El agente hizo una pregunta.
chat-transcript-hide = Ocultar
chat-transcript-show = Mostrar
chat-transcript-unverified-quote-the-quoted-span = Cita no verificada. El texto citado es demasiado corto para verificarlo.
chat-transcript-unverified-quote-the-document-text = Cita no verificada. No se pudo leer el texto del documento.
chat-transcript-unverified-quote-this-wording-was = Cita no verificada. Esta redacción no se encontró en el documento.
chat-board-create-select-a-collection-or-turn = Selecciona una colección o activa las herramientas de internet.
chat-board-create-select-at-least-one-collection = Selecciona al menos una colección.
ai-chat-board-active = Activo
ai-chat-board-paused = Pausado
ai-chat-board-waits-for-review = Espera revisión
ai-chat-board-completed = Completado
ai-chat-board-dropped = Descartado
ai-chat-board-unknown = Desconocido
ai-chat-board-pause-the-board = Pausar el cuadro de investigación
ai-chat-board-resume-the-board = Reanudar el cuadro de investigación
ai-chat-board-none = Ninguno
ai-chat-board-reopen-with-the-remaining-budget = Volver a abrir con el presupuesto restante
ai-chat-board-finding = Hallazgo
ai-chat-board-why-the-correction-is-wrong = Por qué la corrección es incorrecta
ai-chat-board-reject-correction = Rechazar la corrección
ai-chat-board-why-the-finding-is-wrong = Por qué el hallazgo es incorrecto
ai-chat-board-reject-finding = Rechazar el hallazgo
ai-chat-board-answer = Respuesta
ai-chat-board-proposed-answer = Respuesta propuesta
ai-chat-homepage-active = Activo
ai-chat-homepage-paused = Pausado
ai-chat-homepage-waits-for-review = Espera revisión
ai-chat-homepage-completed = Completado
ai-chat-homepage-dropped = Descartado
ai-chat-homepage-unknown = Desconocido
cards-result-cards-submitted-by-board =
    Enviado por el cuadro de investigación: { $kind ->
        [sourced] una fuente
        [inferred] una inferencia
        [not_found] no encontrada
       *[other] un tipo desconocido
    } hallazgo del informe
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Una fuente
        [inferred] Una inferencia
        [not_found] No encontrada
       *[other] Un tipo desconocido
    } hallazgo para el cuadro de investigación
chat-transcript-compacting = Compactando el contexto: { $before } tokens hasta un objetivo de { $target }.
chat-transcript-compaction-failed = El resumen de los pasos anteriores falló. El modelo recibió los pasos anteriores sin cambios, { $after } tokens.
chat-transcript-compacted = Contexto compactado: { $steps } pasos resumidos, { $before } tokens a { $after }.
ai-chat-board-reopen-with-more = Volver a abrir con { $grant } exploraciones más
ai-chat-board-goal-number = Objetivo { $number }
ai-chat-board-from-assessment-on = De la evaluación { $number } en { $date }.
ai-chat-board-from-assessment = De la evaluación { $number }.
chat-board-create-goal-2 = Meta { $index_1 }
ai-chat-session-lost-contact-with-the-chat = perdió el contacto con el chat: { $e }
ai-chat-session-could-not-stop-the-answer = no pudo detener la respuesta: { $e } — todavía está en ejecución
ai-chat-board-later-assessments-dropped-an-answer = { $n } evaluaciones posteriores descartaron una respuesta para esta meta:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokens de instrucción y { $a_completion_tokens } tokens de completado
ai-chat-homepage-completed-goals-not-answered = Completadas, { $n } metas sin responder
board-graph-intent = intención, { $state }
chat-workspace-pane-characters = { $chars } caracteres
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } ejecutando herramienta { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } ejecutando herramienta { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Respondida después de { $retries_len } intento fallido{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } intento fallido{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, versión { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] buscó { $n } término
       *[other] buscó { $n } términos
    }
tool-run-summary-read =
    { $n ->
        [one] leyó { $n } documento
       *[other] leyó { $n } documentos
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] buscó en la web por { $n } término
       *[other] buscó en la web por { $n } términos
    }
tool-run-summary-read-web =
    { $n ->
        [one] leyó { $n } página web
       *[other] leyó { $n } páginas web
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } acción de navegador
       *[other] { $n } acciones de navegador
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listó las entidades de { $n } documento
       *[other] listó las entidades de { $n } documentos
    }
tool-run-summary-cited =
    { $n ->
        [one] citó { $n } documento
       *[other] citó { $n } documentos
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citó { $n } página web
       *[other] citó { $n } páginas web
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] leyó { $n } texto de habilidad y herramienta
       *[other] leyó { $n } textos de habilidades y herramientas
    }
tool-run-summary-saved =
    { $n ->
        [one] guardó { $n } nota
       *[other] guardó { $n } notas
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } llamada a la lista de tareas
       *[other] { $n } llamadas a la lista de tareas
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instrucción para el agente
       *[other] { $n } instrucciones para el agente
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } otra llamada
       *[other] { $n } otras llamadas
    }
tool-run-summary-failed = { $failures } fallidas
tool-run-summary-took = tardó { $duration_text_ms }
chat-session-card-messages = { $session_message_count } mensajes
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } elemento
       *[other] { $count } elementos
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } campo
       *[other] { $count } campos
    }
chat-tool-disclosure-searched-collections = colecciones buscadas{ $filters }
chat-tool-disclosure-searched-collections-2 = colecciones buscadas · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } documentos citados
chat-tool-disclosure-read-document = documento leído · { $path }
chat-tool-disclosure-searched-the-web = web buscada · { $q }
chat-tool-disclosure-opened-page = página abierta · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = llamado { $other }
chat-tool-disclosure-called-2 = llamado { $other } · { $short }
cards-browser-card-opened = { $url } abierta
cards-browser-card-could-not-open = no se pudo abrir { $url }
cards-browser-card-clicked = clic en { $element }
cards-browser-card-could-not-click = no se pudo hacer clic en { $element }
cards-browser-card-typed-into = texto introducido en { $element }
cards-browser-card-could-not-type-into = no se pudo introducir texto en { $element }
cards-browser-card-typed = “{ $text }” escrito
cards-browser-card-could-not-type = no se pudo escribir “{ $text }”
cards-browser-card-pressed = pulsado { $key }
cards-browser-card-could-not-press = no se pudo pulsar { $key }
cards-browser-card-chose-an-option-in = opción elegida en { $element }
cards-browser-card-could-not-choose-an-option = no se pudo elegir una opción en { $element }
cards-browser-card-hovered = { $element } con el cursor encima
cards-browser-card-could-not-hover = no se pudo dejar el cursor sobre { $element }
cards-browser-card-failed = { $bare } — falló
cards-entities-card-listed-entities-document = entidades listadas · { $count } documento{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · parte { $part } de { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } documentos
cards-result-cards-forms = { $tool_name } · { $forms } formularios
cards-result-cards-in = { " " }en { $collections }
cards-result-cards-page = { " " }· página { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documentos · { $missing } citas no encontradas
cards-result-cards-version-unchanged = { $tool_name } · versión { $version } · sin cambios
cards-result-cards-version = { $tool_name } · versión { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultados en, { $json_u64_doc_total_after_dedupe } tras la deduplicación
