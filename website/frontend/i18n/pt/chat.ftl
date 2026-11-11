# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = O assistente está a trabalhar...
chat-composer-ask-the-bot = Pergunte ao assistente...
chat-composer-internet-tools = Ferramentas de internet
chat-composer-agent-language-title = O agente responde em { $language }. Altere o idioma nas definições, num novo separador.
chat-composer-try-again-in-s = Tente novamente dentro de { $secs } s
chat-composer-stop-the-answer-the-partial = Parar a resposta (a parte já escrita não é guardada na conversa)
chat-composer-starting-the-conversation-u = A iniciar a conversa…
chat-composer-send = Enviar
chat-conversation-find-search-in-conversation = Pesquisar na conversa
chat-conversation-find-previous-match = Correspondência anterior
chat-conversation-find-next-match = Correspondência seguinte
chat-conversation-find-investigation-board = Quadro de investigação
doc-ref-card-not-openable = Não é possível abrir: { $reason }.
doc-ref-card-the-search-term-was = O termo de pesquisa era{" "}
doc-ref-card-open = Abrir
doc-ref-card-not-openable-2 = Não é possível abrir
chat-markdown-text-show-the-cited-source = Mostrar a fonte citada
chat-markdown-text-no-citation-of-this-conversation = Nenhuma citação desta conversa deu este identificador, por isso nenhum documento corresponde a ele.
chat-markdown-text-citations-of-this-conversation-gave = As citações desta conversa deram este identificador a mais do que um documento, por isso não liga a nenhum deles.
cards-browser-card-open-the-archived-page = Abrir a página arquivada
cards-browser-card-the-page-itself-was-not = A própria página não foi arquivada (estado: { $artifact_status }). A captura de ecrã acima é o que foi guardado.
cards-browser-card-click-the-screenshot-to-open = Clique na captura de ecrã para abrir a página arquivada.
cards-browser-card-show-less = Mostrar menos
cards-browser-card-show-all = Mostrar tudo
cards-browser-card-archived-page = Página arquivada
cards-browser-card-download = Transferir
cards-browser-card-archived-copy-of = Cópia arquivada de { $artifact_url }
cards-browser-card-this-page-was-not-archived = Esta página não foi arquivada (estado: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } com ficha
cards-entities-card-the-entity-list-was-cut = A lista de entidades foi cortada.
cards-entities-card-open-the-card-for-this = Abrir a ficha deste valor ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Sem ficha: esta conversa nunca indicou o conjunto de dados de onde estes valores vieram, e o visualizador é endereçado por conjunto de dados.
cards-entities-card-more-all-of-them-in = Mais { $rest }, todos no painel de entidades do documento.{" "}
cards-entities-card-names-organisations-and-places-above = Os nomes, as organizações e os locais acima são a leitura que um modelo fez do texto. Nenhuma regra os validou, por isso não há nada a explicar e não abrem nada.
cards-entities-card-nothing-extracted-from-this-document = Nada foi extraído deste documento.
chat-tool-cards-hide = Ocultar
chat-tool-cards-expand = Expandir
chat-tool-cards-hide-raw-json = Ocultar o JSON em bruto
chat-tool-cards-show-raw-json = Mostrar o JSON em bruto
cards-result-cards-search-this = Pesquisar isto
cards-result-cards-search-every-collection = Pesquisar em todas as coleções
cards-result-cards-form = Forma { $index }: { $form }
cards-result-cards-show-full-text = Mostrar o texto completo
cards-result-cards-quote = Citação textual: { $quote }
cards-result-cards-reason = Motivo: { $why }
cards-result-cards-open-question = Questão em aberto: { $question }
cards-result-cards-the-explore-gave-this-answer = A exploração deu esta resposta ao seu quadro como uma conclusão { $kind ->
        [sourced] com fontes
        [inferred] inferida
        [not_found] do tipo «não encontrado»
       *[other] de tipo desconhecido
    }.
cards-result-cards-it-left-no-open-question = Não deixou nenhuma questão em aberto.
cards-result-cards-open-questions-for-the-board = Questões em aberto para o quadro:
cards-result-cards-arguments = Argumentos
cards-result-cards-list-after-the-call = Lista depois da chamada: { $snapshot_goal }
cards-result-cards-replaces = {" "}· substitui { $replaces_id }
cards-result-cards-the-list-at-this-version = A lista nesta versão não está guardada.
web-search-card-these-sources-returned-nothing-so = Estas fontes não devolveram nada, por isso os resultados vêm de menos fontes do que o pretendido
web-search-card-u-degraded = ⚠ { $degraded_len } degradadas
web-search-card-form = Forma { $index }: { $form }
web-search-card-no-results-from = Sem resultados de: { $degraded_text }
web-search-card-no-results-every-source-answered = Sem resultados. Todas as fontes responderam e nenhuma tinha algo para esta consulta.
web-search-card-the-lowest-ranked-results-were = Os resultados com a classificação mais baixa foram retirados para que esta chamada caiba na transcrição. O assistente viu todos.
web-search-card-view-search-details = Ver os detalhes da pesquisa.
web-search-card-the-stored-result-could-not = não foi possível ler de volta o resultado guardado como JSON
web-search-card-nothing-was-stored-for-this = Nada foi guardado para esta chamada.
web-search-card-forms = Formas: { $forms }
web-search-card-kind = Tipo: { $row_kind }
web-search-card-published = Publicado: { $row_published }
web-search-card-loading-search-detail-u = A carregar os detalhes da pesquisa…
web-search-card-could-not-load-the-search = Não foi possível carregar os detalhes da pesquisa: { $e }
web-search-card-malformed-detail = Detalhes malformados: { $e }
web-search-card-the-tool-returned-selected-results = A ferramenta devolveu resultados selecionados ao modelo.
web-search-card-results-use-reciprocal-rank-fusion = Os resultados usam a fusão de classificações recíprocas.
web-search-card-returned-nothing = não devolveu nada: { $degraded }
web-search-card-all-candidates-use-fusion-order = Todos os candidatos usam a ordem da fusão.
web-search-card-the-cross-encoder-ranks-selected = O codificador cruzado classifica os resultados selecionados.
web-search-card-selected-results-use-fusion-order = Os resultados selecionados usam a ordem da fusão.
web-search-card-search-detail = Detalhes da pesquisa
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Pesquisar isto
chat-tool-disclosure-search-every-collection = Pesquisar em todas as coleções
chat-tool-disclosure-hide = Ocultar
chat-tool-disclosure-expand = Expandir
chat-tool-disclosure-this-step-was-recorded-before = Este passo foi registado antes de os argumentos e os resultados das ferramentas serem guardados. Só está disponível o resumo abaixo.
chat-tool-disclosure-arguments = Argumentos
chat-tool-disclosure-result = Resultado
chat-tool-disclosure-hide-raw-json = Ocultar o JSON em bruto
chat-tool-disclosure-show-raw-json = Mostrar o JSON em bruto
chat-tool-disclosure-input-json = JSON de entrada
chat-tool-disclosure-output-json = JSON de saída
chat-transcript-ask-a-question-about-the = Faça uma pergunta sobre os documentos das suas coleções.
chat-transcript-suggested-next = Sugestões seguintes...
chat-transcript-earlier-answer = Resposta anterior
chat-transcript-tokens-the-conversation-carries-the = Tokens que a conversa contém, o maior contexto único cobrado neste turno e a parte da janela do modelo que isso ocupou
chat-transcript-instruction-to-the-agent = Instrução ao agente
chat-transcript-the-context-stays-above-the = {" "}O contexto fica acima do objetivo de { $target }.
chat-transcript-summary-parts-failed-the-record = {" "}{ $failed } partes do resumo falharam. O registo contém apenas as listas.
chat-transcript-show-the-record = Mostrar o registo
chat-transcript-hide-reasoning = Ocultar o raciocínio
chat-transcript-show-reasoning = Mostrar o raciocínio
chat-transcript-from-u-hide = { $count } { $count ->
        [one] documento
       *[other] documentos
    } de { $tool } — ocultar
chat-transcript-from-u-show = { $count } { $count ->
        [one] documento
       *[other] documentos
    } de { $tool } — mostrar
chat-transcript-u-hide = { $summary } — ocultar
chat-transcript-u-show = { $summary } — mostrar
chat-transcript-citations-of-this-conversation-give = As citações desta conversa dão { $doc_handle } a mais do que um documento. A resposta não o liga a nenhum deles.
chat-transcript-report = Relatório { $label }
chat-transcript-open-in-the-workspace = Abrir no espaço de trabalho
chat-transcript-this-version-could-not-be = Não foi possível ler esta versão. Segue-se o texto da resposta na conversa.
chat-transcript-files = Ficheiros
chat-transcript-version = { $file_name }, versão { $file_version }
chat-web-find-exact-text = Encontrar o texto exato
chat-web-previous-match = Correspondência anterior
chat-web-next-match = Correspondência seguinte
chat-web-close-preview = Fechar a pré-visualização
chat-web-the-captured-page-could-not = Não foi possível carregar a página capturada.
chat-web-loading = A carregar…
chat-workspace-pane-workspace = Espaço de trabalho
chat-workspace-pane-close-the-workspace = Fechar o espaço de trabalho
chat-workspace-pane-close = Fechar
chat-workspace-pane-loading-the-files-u = A carregar os ficheiros…
chat-workspace-pane-the-files-could-not-be = Não foi possível carregar os ficheiros: { $error }
chat-workspace-pane-this-conversation-has-no-files = Esta conversa não tem ficheiros.
chat-workspace-pane-version = versão { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Escolha um ficheiro para o ler.
chat-workspace-pane-loading-the-file-u = A carregar o ficheiro…
chat-workspace-pane-the-file-could-not-be = Não foi possível carregar o ficheiro: { $error }
chat-workspace-pane-version-2 = { $found_name }, versão { $found_version }
chat-board-create-collections = Coleções
chat-board-create-loading-collections-u = A carregar coleções…
chat-board-create-hoover-search-new-board = Pesquisa Hoover - Novo quadro
chat-board-create-ai-chat = Conversa com IA
chat-board-create-new-investigation-board = Novo quadro de investigação
chat-board-create-a-board-runs-its-goals = Um quadro executa os seus objetivos como uma sequência de explorações do agente. Cada exploração é uma conversa que termina numa conclusão do quadro. Reveja a resposta de cada objetivo e, enquanto o quadro decorre, pode rejeitar conclusões e adicionar pistas.
chat-board-create-title = Título
chat-board-create-goal = Objetivo
chat-board-create-remove-this-goal = Remover este objetivo
chat-board-create-remove = Remover
chat-board-create-add-a-goal = Adicionar um objetivo
chat-board-create-context-optional = Contexto (opcional)
chat-board-create-hints-one-per-line-optional = Pistas, uma por linha (opcional)
chat-board-create-sources = Fontes
chat-board-create-internet-tools = Ferramentas de internet
chat-board-create-creating-board = A criar o quadro...
chat-board-create-create-board = Criar quadro
chat-board-create-board-language = Idioma do quadro
ai-chat-board-hoover-search-board = Pesquisa Hoover - Quadro
ai-chat-board-loading-the-board-u = A carregar o quadro…
ai-chat-board-show-the-board-overview = Mostrar a vista geral do quadro
ai-chat-board-zoom-out = Reduzir
ai-chat-board-zoom-in = Ampliar
ai-chat-board-u-ai-chat = ← Conversa com IA
ai-chat-board-settings = Definições
ai-chat-board-board-settings = Definições do quadro
ai-chat-board-internet-tools = Ferramentas de internet
ai-chat-board-the-next-explores-of-the = As próximas explorações do quadro podem pesquisar na web e ler páginas web. As explorações em curso mantêm a definição com que começaram.
ai-chat-board-collections = Coleções
ai-chat-board-the-collections-are-fixed-when = As coleções ficam fixas quando o quadro é criado.
ai-chat-board-language = Idioma
ai-chat-board-the-language-is-fixed-when = O idioma fica fixo quando o quadro é criado.
ai-chat-board-the-agent-language-of-the-owner = O idioma do agente do proprietário
ai-chat-board-confirm-drop = Confirmar o descarte
ai-chat-board-drop-the-board = Descartar o quadro
ai-chat-board-close = Fechar
ai-chat-board-the-board-used-its-explore = O quadro usou o seu limite de explorações
ai-chat-board-the-board-used-explores-the = O quadro usou { $explore_limit } explorações, o limite de um quadro. Não inicia mais trabalho. Ainda pode decidir sobre as respostas propostas.
ai-chat-board-create-a-new-board-to = Crie um novo quadro para continuar a investigação
ai-chat-board-goal = Objetivo
ai-chat-board-goals = Objetivos
ai-chat-board-add-new-goal = Adicionar novo objetivo...
ai-chat-board-a-new-goal = Um novo objetivo
ai-chat-board-add-goal = Adicionar objetivo
ai-chat-board-a-board-has-at-most = Um quadro tem no máximo { $max_goals } objetivos. Crie um novo quadro para outro objetivo.
ai-chat-board-background-context = Contexto de base
ai-chat-board-continue-with-a-correction = Continuar com uma correção
ai-chat-board-correction-what-is-wrong-or = Correção: o que está errado ou em falta. O quadro continua com ela.
ai-chat-board-the-board-waits-for-your = O quadro aguarda a sua revisão
ai-chat-board-the-board-used-its-budget = O quadro usou o seu orçamento de { $snap_max_explores } explorações.
ai-chat-board-the-assessments-gave-no-usable = As avaliações não deram nenhuma direção utilizável.
ai-chat-board-accept-or-reject-the-proposed = Aceite ou rejeite a resposta proposta para cada objetivo acima. Uma resposta rejeitada permite ao quadro continuar de imediato.
ai-chat-board-no-proposed-answer-waits-for = Nenhuma resposta proposta aguarda a sua decisão.
ai-chat-board-reopen-the-board-to-continue = Reabra o quadro para continuar os objetivos em aberto. Ele mantém as suas conclusões e respostas.
ai-chat-board-close-the-board-to-accept = Feche o quadro para aceitar todas as respostas propostas e o parar, ou continue-o com uma correção.
ai-chat-board-close-the-board = Fechar o quadro
ai-chat-board-or-reopen-the-board-to = Ou reabra o quadro para continuar os objetivos em aberto sem uma correção.
ai-chat-board-the-board-is-complete = O quadro está completo
ai-chat-board-a-goal-has-no-accepted = Um objetivo não tem resposta aceite. Reabra o quadro para o continuar. O quadro mantém as suas conclusões e respostas.
ai-chat-board-add-a-hint = Adicionar uma pista
ai-chat-board-the-next-assessment-reads-every = A próxima avaliação lê todas as pistas. Uma pista também responde a uma exploração que fez uma pergunta.
ai-chat-board-add-hint = Adicionar pista
ai-chat-board-events = Eventos
ai-chat-board-newest-first = Mais recentes primeiro
ai-chat-board-date = Data
ai-chat-board-actor = Autor
ai-chat-board-event = Evento
ai-chat-board-show-details = Mostrar detalhes
ai-chat-board-open = Abrir
ai-chat-board-show-the-newest-events = Mostrar os { $event_rows } eventos mais recentes
ai-chat-board-show-all-events = Mostrar todos os { $snap_events_len } eventos
ai-chat-board-statistics = Estatísticas
ai-chat-board-explores = Explorações
ai-chat-board-model-steps-per-explore = Passos do modelo por exploração
ai-chat-board-assessments = Avaliações
ai-chat-board-intents = Intenções
ai-chat-board-findings = Conclusões
ai-chat-board-created = Criado
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } rejeitou esta conclusão em { $format_utc_ms_fact_rejected_ms }. O quadro já não a usa.
ai-chat-board-this-finding-was-replaced-by = Esta conclusão foi substituída por { $new } em { $date }. O quadro já não a usa.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } rejeitou esta conclusão. O quadro já não a usa.
ai-chat-board-no-reason-was-given = Não foi indicado nenhum motivo.
ai-chat-board-reason = Motivo: { $fact_rejected_reason }
ai-chat-board-open-questions = Questões em aberto
ai-chat-board-explored-in = Explorado em{" "}
ai-chat-board-explore-this-question = Explorar esta questão
ai-chat-board-your-questions = As suas perguntas
ai-chat-board-ask-about-the-background-context = Perguntar sobre o contexto de base
ai-chat-board-ask-about-this-finding = Perguntar sobre esta conclusão
ai-chat-board-a-follow-up-question-about = Uma pergunta adicional sobre este nó
ai-chat-board-ask = Perguntar
ai-chat-board-checks-that-changed-this-finding = Verificações que alteraram esta conclusão
ai-chat-board-reject-this-correction = Rejeitar esta correção
ai-chat-board-reject-this-finding = Rejeitar esta conclusão
ai-chat-board-not-answered-the-board-was = Sem resposta. O quadro foi concluído sem uma resposta para este objetivo. Uma pista ou uma reabertura volta a abri-lo.
ai-chat-board-no-answer-yet = Ainda sem resposta.
ai-chat-board-the-findings-of-this-answer = As conclusões desta resposta são pesquisas que não encontraram nada. Aceite-a para registar que os registos não respondem ao objetivo, ou rejeite-a para continuar a investigação.
ai-chat-board-open-an-assessment-to-read = {"."} Abra uma avaliação para ler o motivo.
ai-chat-board-from-the-findings = Das conclusões{" "}
ai-chat-board-accept-answer = Aceitar resposta
ai-chat-board-why-the-answer-is-wrong = Porque é que a resposta está errada ou incompleta
ai-chat-board-reject-answer = Rejeitar resposta
ai-chat-board-intent = Intenção
ai-chat-board-attempts-declared = Tentativas: { $intent_attempts }. Declarada em { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = A exploração perguntou
ai-chat-board-add-a-hint-in-the = Adicione uma pista na vista geral do quadro para lhe responder.
ai-chat-board-last-error = Último erro
ai-chat-board-brief = Resumo
ai-chat-board-open-the-explore-chat = Abrir a conversa da exploração
ai-chat-board-loading-the-assessment-u = A carregar a avaliação…
ai-chat-board-assessment = Avaliação { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modelo { $a_model }. Resultado { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Verificações que a alteraram
ai-chat-board-prompt = Instrução
ai-chat-board-this-assessment-ran-before-the = Esta avaliação foi executada antes de as instruções serem guardadas.
ai-chat-board-response = Resposta
ai-chat-history-hoover-search-chat-history = Pesquisa Hoover - Histórico de conversas
ai-chat-history-u-back = ← Voltar
ai-chat-history-conversation-history = Histórico de conversas
ai-chat-history-show-board-chats = Mostrar as conversas dos quadros
ai-chat-history-loading-u = A carregar…
ai-chat-history-could-not-load-history = Não foi possível carregar o histórico: { $e }
ai-chat-history-no-conversations-yet = Ainda não há conversas.
ai-chat-history-board = Quadro
ai-chat-history-new-chat = Nova conversa
ai-chat-history-messages-updated = { $s_message_count ->
    [one] { $s_message_count } mensagem · atualizada em { $s_updated_at }
    *[other] { $s_message_count } mensagens · atualizada em { $s_updated_at }
    }

ai-chat-history-delete-conversation = Eliminar conversa
ai-chat-history-delete = Eliminar
ai-chat-homepage-hoover-search-ai-chat = Pesquisa Hoover - Conversa com IA
ai-chat-homepage-what-are-you-researching = O que está a investigar?
ai-chat-homepage-view-all-conversations = Ver todas as conversas
ai-chat-homepage-starting-conversation-u = A iniciar a conversa…
ai-chat-homepage-investigation-boards = Quadros de investigação
ai-chat-homepage-new-board = Novo quadro
ai-chat-homepage-loading-boards-u = A carregar quadros…
ai-chat-homepage-could-not-load-the-boards = Não foi possível carregar os quadros: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Não tem nenhum quadro. Um quadro executa uma investigação longa como uma sequência de explorações do agente. Reveja as suas respostas.
ai-chat-homepage-updated = Atualizado { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Pesquisa Hoover - Conversa com IA
ai-chat-session-this-conversation-could-not-be = Não foi possível carregar esta conversa.
ai-chat-session-loading-u = A carregar…
ai-chat-session-u-chats = ← Conversas
ai-chat-session-history = Histórico
ai-chat-session-show-the-files-that-the = Mostrar os ficheiros que o assistente escreveu nesta conversa
ai-chat-session-workspace = Espaço de trabalho
ai-chat-session-this-answer-was-interrupted-before = Esta resposta foi interrompida antes de terminar, porque a página ou o servidor pararam a meio do turno. Pergunte de novo para tentar outra vez.
ai-chat-session-dismiss = Dispensar
ai-chat-session-board-explore-chats-are-read = As conversas de exploração do quadro são só de leitura.{" "}
ai-chat-session-open-the-board = Abrir o quadro
chat-locked-options-on = { $label }: ativado
chat-locked-options-off = { $label }: desativado
chat-tool-cards-running-u = em execução…
cards-result-cards-quote-found = Citação textual encontrada
cards-result-cards-quote-not-found = Citação textual não encontrada
cards-result-cards-quote-not-checked = Citação textual não verificada
web-search-card-results = { $results_len } resultados
chat-tool-disclosure-running-u = em execução…
chat-transcript-call = chamada
chat-transcript-calls = chamadas
ai-chat-board-a-board-without-collections-needs = Um quadro sem coleções precisa de ferramentas de internet.
ai-chat-board-of = { $snap_explores_used } de { $snap_max_explores }
ai-chat-board-assessment-2 = avaliação { $number }
ai-chat-history-messages = { $s_message_count ->
    [one] { $s_message_count } mensagem
    *[other] { $s_message_count } mensagens
    }

web-search-card-reranked-in = O codificador cruzado reclassificou os resultados em { $ms } ms.
web-search-card-engine-results = { $name }: { $count } em { $ms } ms
web-search-card-score-was-rank = pontuação { $score } · era RRF #{ $rank }
chat-activity-the-turn-waits-for-a = O turno aguarda uma vaga livre do modelo.
chat-activity-the-turn-waits-for-a-2 = O turno aguarda uma vaga livre de ferramenta.
chat-locked-options-start-a-new-chat-to = Inicie uma nova conversa para alterar esta definição.
chat-locked-options-internet-tools = Ferramentas de internet
chat-session-card-new-chat = Nova conversa
chat-tool-cards-first-frame-of-the-video = Primeiro fotograma do vídeo
chat-tool-cards-screenshot-of = Captura de ecrã de
chat-tool-cards-image = Imagem
cards-result-cards-the-agent-asked-a-question = O agente fez uma pergunta.
chat-transcript-hide = Ocultar
chat-transcript-show = Mostrar
chat-transcript-unverified-quote-the-quoted-span = Citação textual não verificada. O trecho citado é demasiado curto para ser verificado.
chat-transcript-unverified-quote-the-document-text = Citação textual não verificada. Não foi possível ler o texto do documento.
chat-transcript-unverified-quote-this-wording-was = Citação textual não verificada. Esta formulação não foi encontrada no documento.
chat-board-create-select-a-collection-or-turn = Selecione uma coleção ou ative as ferramentas de internet.
chat-board-create-select-at-least-one-collection = Selecione pelo menos uma coleção.
ai-chat-board-active = Ativo
ai-chat-board-paused = Em pausa
ai-chat-board-waits-for-review = Aguarda revisão
ai-chat-board-completed = Concluído
ai-chat-board-dropped = Descartado
ai-chat-board-unknown = Desconhecido
ai-chat-board-pause-the-board = Pausar o quadro
ai-chat-board-resume-the-board = Retomar o quadro
ai-chat-board-none = Nenhum
ai-chat-board-reopen-with-the-remaining-budget = Reabrir com o orçamento restante
ai-chat-board-finding = Conclusão
ai-chat-board-why-the-correction-is-wrong = Porque é que a correção está errada
ai-chat-board-reject-correction = Rejeitar correção
ai-chat-board-why-the-finding-is-wrong = Porque é que a conclusão está errada
ai-chat-board-reject-finding = Rejeitar conclusão
ai-chat-board-answer = Resposta
ai-chat-board-proposed-answer = Resposta proposta
ai-chat-homepage-active = Ativo
ai-chat-homepage-paused = Em pausa
ai-chat-homepage-waits-for-review = Aguarda revisão
ai-chat-homepage-completed = Concluído
ai-chat-homepage-dropped = Descartado
ai-chat-homepage-unknown = Desconhecido
cards-result-cards-submitted-by-board = Submetida pelo quadro: uma conclusão { $kind ->
        [sourced] com fontes
        [inferred] inferida
        [not_found] do tipo «não encontrado»
       *[other] de tipo desconhecido
    } do relatório
cards-result-cards-finding-for-board = Conclusão { $kind ->
        [sourced] com fontes
        [inferred] inferida
        [not_found] do tipo «não encontrado»
       *[other] de tipo desconhecido
    } para o quadro
chat-transcript-compacting = A compactar o contexto: { $before } tokens para um objetivo de { $target }.
chat-transcript-compaction-failed = O resumo dos passos anteriores falhou. O modelo recebeu os passos anteriores sem alterações, { $after } tokens.
chat-transcript-compacted = Contexto compactado: {$steps} passos resumidos, { $before } tokens para { $after }.
ai-chat-board-reopen-with-more = Reabrir com mais { $grant } explorações
ai-chat-board-goal-number = Objetivo { $number }
ai-chat-board-from-assessment-on = Da avaliação { $number } em { $date }.
ai-chat-board-from-assessment = Da avaliação { $number }.
chat-board-create-goal-2 = Objetivo { $index_1 }
ai-chat-session-lost-contact-with-the-chat = perdeu-se o contacto com a conversa: { $e }
ai-chat-session-could-not-stop-the-answer = não foi possível parar a resposta: { $e } — ainda está em execução
ai-chat-board-later-assessments-dropped-an-answer = { $n } avaliações posteriores descartaram uma resposta para este objetivo:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokens de instrução e { $a_completion_tokens } de conclusão
ai-chat-homepage-completed-goals-not-answered = Concluído, {$n} objetivos sem resposta
board-graph-intent = intenção, { $state }
chat-workspace-pane-characters = { $chars } carateres
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } { $if_joined_live_end_1_tr_chat_transcript_ } de ferramenta em execução
chat-transcript-running-tool-2 = { $turn_tool_rows_len } { $if_turn_tool_rows_len_1_tr_chat_transcri } de ferramenta em execução
chat-transcript-answered-after-failed-attempt = Respondido após { $retries_len ->
        [one] { $retries_len } tentativa falhada
       *[other] { $retries_len } tentativas falhadas
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-failed-attempt = { $retries_len ->
        [one] { $retries_len } tentativa falhada
       *[other] { $retries_len } tentativas falhadas
    }{ $if_retries_len_1_else_s ->
       *[other] {""}
    }
chat-transcript-version-2 = { $report_name }, versão { $report_version }
tool-run-summary-searched = { $n ->
        [one] pesquisou { $n } termo
       *[other] pesquisou { $n } termos
    }
tool-run-summary-read = { $n ->
        [one] leu { $n } documento
       *[other] leu { $n } documentos
    }
tool-run-summary-searched-the-web-for = { $n ->
        [one] pesquisou na web { $n } termo
       *[other] pesquisou na web { $n } termos
    }
tool-run-summary-read-web = { $n ->
        [one] leu { $n } página web
       *[other] leu { $n } páginas web
    }
tool-run-summary-browser = { $n ->
        [one] { $n } ação do navegador
       *[other] { $n } ações do navegador
    }
tool-run-summary-listed-the-entities-of = { $n ->
        [one] listou as entidades de { $n } documento
       *[other] listou as entidades de { $n } documentos
    }
tool-run-summary-cited = { $n ->
        [one] citou { $n } documento
       *[other] citou { $n } documentos
    }
tool-run-summary-cited-web = { $n ->
        [one] citou { $n } página web
       *[other] citou { $n } páginas web
    }
tool-run-summary-read-and-tool-texts = { $n ->
        [one] leu { $n } competência e textos de ferramentas
       *[other] leu { $n } competências e textos de ferramentas
    }
tool-run-summary-saved = { $n ->
        [one] guardou { $n } nota
       *[other] guardou { $n } notas
    }
tool-run-summary-todo-list = { $n ->
        [one] { $n } chamada da lista de tarefas
       *[other] { $n } chamadas da lista de tarefas
    }
tool-run-summary-to-the-agent = { $n ->
        [one] { $n } instrução ao agente
       *[other] { $n } instruções ao agente
    }
tool-run-summary-other = { $n ->
        [one] { $n } outra chamada
       *[other] { $n } outras chamadas
    }
tool-run-summary-failed = { $failures } falharam
tool-run-summary-took = demorou { $duration_text_ms }
chat-session-card-messages = { $session_message_count ->
    [one] { $session_message_count } mensagem
    *[other] { $session_message_count } mensagens
    }

chat-tool-disclosure-item = { $count ->
        [one] { $count } item
       *[other] { $count } itens
    }
chat-tool-disclosure-field = { $count ->
        [one] { $count } campo
       *[other] { $count } campos
    }
chat-tool-disclosure-searched-collections = pesquisou coleções{ $filters }
chat-tool-disclosure-searched-collections-2 = pesquisou coleções · { $query }{ $filters }
chat-tool-disclosure-cited-documents = citou { $n } documentos
chat-tool-disclosure-read-document = leu o documento · { $path }
chat-tool-disclosure-searched-the-web = pesquisou na web · { $q }
chat-tool-disclosure-opened-page = abriu a página · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = chamou { $other }
chat-tool-disclosure-called-2 = chamou { $other } · { $short }
cards-browser-card-opened = abriu { $url }
cards-browser-card-could-not-open = não conseguiu abrir { $url }
cards-browser-card-clicked = clicou em { $element }
cards-browser-card-could-not-click = não conseguiu clicar em { $element }
cards-browser-card-typed-into = escreveu em { $element }
cards-browser-card-could-not-type-into = não conseguiu escrever em { $element }
cards-browser-card-typed = escreveu “{ $text }”
cards-browser-card-could-not-type = não conseguiu escrever “{ $text }”
cards-browser-card-pressed = premiu { $key }
cards-browser-card-could-not-press = não conseguiu premir { $key }
cards-browser-card-chose-an-option-in = escolheu uma opção em { $element }
cards-browser-card-could-not-choose-an-option = não conseguiu escolher uma opção em { $element }
cards-browser-card-hovered = passou o rato sobre { $element }
cards-browser-card-could-not-hover = não conseguiu passar o rato sobre { $element }
cards-browser-card-failed = { $bare } — falhou
cards-entities-card-listed-entities-document = entidades listadas · { $count ->
        [one] { $count } documento
       *[other] { $count } documentos
    }{ $if_count_1_else_s ->
       *[other] {""}
    }
chat-tool-cards-read-more-part-of = read_more · parte { $part } de { $name } #{ $seq }
cards-result-cards-documents = {" "}· { $value } documentos
cards-result-cards-forms = { $tool_name } · { $forms } formas
cards-result-cards-in = {" "}em { $collections }
cards-result-cards-page = {" "}· página { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documentos · { $missing } citações textuais não encontradas
cards-result-cards-version-unchanged = { $tool_name } · versão { $version } · inalterada
cards-result-cards-version = { $tool_name } · versão { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultados à entrada, { $json_u64_doc_total_after_dedupe } após a eliminação de duplicados

board-status-on = Ativado

board-status-off = Desativado

chat-transcript-generic-tool = a ferramenta
