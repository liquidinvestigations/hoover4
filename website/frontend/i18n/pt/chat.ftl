# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = O bot está a trabalhar...
chat-composer-ask-the-bot = Perguntar ao bot...
chat-composer-internet-tools = Ferramentas de Internet
chat-composer-agent-language-title = O agente responde em { $language }. Altere o idioma nas configurações, numa nova separada.
chat-composer-try-again-in-s = Tentar novamente dentro de { $secs } s
chat-composer-stop-the-answer-the-partial = Parar a resposta (a parcial não é guardada na conversa)
chat-composer-starting-the-conversation-u = A iniciar a conversa…
chat-composer-send = Enviar
chat-conversation-find-search-in-conversation = Pesquisar na conversa
chat-conversation-find-previous-match = Correspondência anterior
chat-conversation-find-next-match = Correspondência seguinte
chat-conversation-find-investigation-board = Quadro de Investigação
doc-ref-card-not-openable = Não é aberto: { $reason }.
doc-ref-card-the-search-term-was = O termo de pesquisa foi{ " " }
doc-ref-card-open = Abrir
doc-ref-card-not-openable-2 = Não é aberto
chat-markdown-text-show-the-cited-source = Mostrar a fonte citada
chat-markdown-text-no-citation-of-this-conversation = Nenhuma citação desta conversa atribuiu este identificador, pelo que nenhum documento lhe está associado.
chat-markdown-text-citations-of-this-conversation-gave = As citações desta conversa atribuíam este identificador a mais de um documento, pelo que não liga a nenhum deles.
cards-browser-card-open-the-archived-page = Abrir a página arquivada
cards-browser-card-the-page-itself-was-not = A página em si não foi arquivada (estado: { $artifact_status }). A captura de écran acima é o que foi preservado.
cards-browser-card-click-the-screenshot-to-open = Clique na captura de écran para abrir a página arquivada.
cards-browser-card-show-less = Mostrar menos
cards-browser-card-show-all = Mostrar tudo
cards-browser-card-archived-page = Página arquivada
cards-browser-card-download = Transferir
cards-browser-card-archived-copy-of = Cópia arquivada de { $artifact_url }
cards-browser-card-this-page-was-not-archived = Esta página não foi arquivada (estado: { $artifact_status }).
cards-entities-card-with-a-card = { $openable } com um cartão
cards-entities-card-the-entity-list-was-cut = A lista de entidades foi cortada.
cards-entities-card-open-the-card-for-this = Abrir o cartão para este valor ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = Sem cartão: esta conversa nunca indicou a origem destes valores no conjunto de dados, e o visualizador é tratado pelo conjunto de dados.
cards-entities-card-more-all-of-them-in = { $rest } mais, todos eles no painel de entidades do documento.
cards-entities-card-names-organisations-and-places-above = Os nomes, organizações e locais acima são a interpretação do modelo do texto. Nenhuma regra os validou, pelo que não há nada a explicar e não abrem nada.
cards-entities-card-nothing-extracted-from-this-document = Nada extraído deste documento.
chat-tool-cards-hide = Esconder
chat-tool-cards-expand = Alargar
chat-tool-cards-hide-raw-json = Esconder JSON bruto
chat-tool-cards-show-raw-json = Mostrar JSON bruto
cards-result-cards-search-this = Pesquisar isto
cards-result-cards-search-every-collection = Pesquisar todas as coleções
cards-result-cards-form = Formulário { $index }: { $form }
cards-result-cards-show-full-text = Mostrar texto completo
cards-result-cards-quote = Citação: { $quote }
cards-result-cards-reason = Motivo: { $why }
cards-result-cards-open-question = Questão em aberto: { $question }
cards-result-cards-the-explore-gave-this-answer =
    A exploração deu esta resposta ao seu quadro como { $kind ->
        [sourced] uma descoberta com fonte
        [inferred] uma descoberta inferida
        [not_found] uma descoberta não encontrada
       *[other] uma descoberta de tipo desconhecido
    }.
cards-result-cards-it-left-no-open-question = Não deixou nenhuma questão em aberto.
cards-result-cards-open-questions-for-the-board = Questões em aberto para o quadro:
cards-result-cards-arguments = Argumentos
cards-result-cards-list-after-the-call = Lista após a chamada: { $snapshot_goal }
cards-result-cards-replaces = · substitui { $replaces_id }
cards-result-cards-the-list-at-this-version = A lista nesta versão não está armazenada.
web-search-card-these-sources-returned-nothing-so = Estas fontes não devolveram nada, pelo que os resultados vêm de menos fontes do que o pretendido
web-search-card-u-degraded = ⚠ { $degraded_len } degradado
web-search-card-form = Formulário { $index }: { $form }
web-search-card-no-results-from = Sem resultados de: { $degraded_text }
web-search-card-no-results-every-source-answered = Sem resultados. Todas as fontes responderam e nenhuma tinha algo para esta consulta.
web-search-card-the-lowest-ranked-results-were = Os resultados de classificação mais baixa foram descartados para que esta chamada caiba no transcript. O assistente viu todos eles.
web-search-card-view-search-details = Ver detalhes da pesquisa.
web-search-card-the-stored-result-could-not = o resultado armazenado não pôde ser lido de novo como JSON
web-search-card-nothing-was-stored-for-this = Não foi armazenado nada para esta chamada.
web-search-card-forms = Formulários: { $forms }
web-search-card-kind = Tipo: { $row_kind }
web-search-card-published = Publicação: { $row_published }
web-search-card-loading-search-detail-u = A carregar os detalhes da pesquisa…
web-search-card-could-not-load-the-search = Não foi possível carregar os detalhes da pesquisa: { $e }
web-search-card-malformed-detail = Detalhe mal formado: { $e }
web-search-card-the-tool-returned-selected-results = A ferramenta devolveu resultados selecionados ao modelo.
web-search-card-results-use-reciprocal-rank-fusion = Os resultados utilizam a fusão de ranks recíprocos.
web-search-card-returned-nothing = devolveu nada: { $degraded }
web-search-card-all-candidates-use-fusion-order = Todos os candidatos utilizam a ordem de fusão.
web-search-card-the-cross-encoder-ranks-selected = O codificador cruzado classifica os resultados selecionados.
web-search-card-selected-results-use-fusion-order = Os resultados selecionados utilizam a ordem de fusão.
web-search-card-search-detail = Detalhes da pesquisa
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = Pesquisar isto
chat-tool-disclosure-search-every-collection = Pesquisar todas as coleções
chat-tool-disclosure-hide = Esconder
chat-tool-disclosure-expand = Alargar
chat-tool-disclosure-this-step-was-recorded-before = Este passo foi registado antes de os argumentos e resultados da ferramenta terem sido armazenados. Só está disponível o resumo abaixo.
chat-tool-disclosure-arguments = Argumentos
chat-tool-disclosure-result = Resultado
chat-tool-disclosure-hide-raw-json = Esconder JSON bruto
chat-tool-disclosure-show-raw-json = Mostrar JSON bruto
chat-tool-disclosure-input-json = JSON de entrada
chat-tool-disclosure-output-json = JSON de saída
chat-transcript-ask-a-question-about-the = Faça uma pergunta sobre os documentos das suas coleções.
chat-transcript-suggested-next = Próximo sugerido...
chat-transcript-earlier-answer = Resposta anterior
chat-transcript-tokens-the-conversation-carries-the = Tokens que a conversa transporta, o maior contexto único faturado neste turno e quanto da janela do modelo foi utilizado
chat-transcript-instruction-to-the-agent = Instrução para o agente
chat-transcript-the-context-stays-above-the = { " " }O contexto fica acima do alvo de { $target }.
chat-transcript-summary-parts-failed-the-record = { " " }{ $failed } partes do resumo falharam. O registo contém apenas as listas.
chat-transcript-show-the-record = Mostrar o registo
chat-transcript-hide-reasoning = Esconder o raciocínio
chat-transcript-show-reasoning = Mostrar o raciocínio
chat-transcript-from-u-hide = { $count } { $noun } de { $tool } — esconder
chat-transcript-from-u-show = { $count } { $noun } de { $tool } — mostrar
chat-transcript-u-hide = { $summary } — esconder
chat-transcript-u-show = { $summary } — mostrar
chat-transcript-citations-of-this-conversation-give = As citações desta conversa atribuem { $doc_handle } a mais de um documento. A resposta não o associa a nenhum deles.
chat-transcript-report = Reportar { $label }
chat-transcript-open-in-the-workspace = Abrir no espaço de trabalho
chat-transcript-this-version-could-not-be = Esta versão não pôde ser lida. O texto da conversa da resposta segue.
chat-transcript-files = Ficheiros
chat-transcript-version = { $file_name }, versão { $file_version }
chat-web-find-exact-text = Procurar texto exato
chat-web-previous-match = Correspondência anterior
chat-web-next-match = Correspondência seguinte
chat-web-close-preview = Fechar pré-visualização
chat-web-the-captured-page-could-not = A página capturada não pôde ser carregada.
chat-web-loading = A carregar…
chat-workspace-pane-workspace = Espaço de trabalho
chat-workspace-pane-close-the-workspace = Fechar o espaço de trabalho
chat-workspace-pane-close = Fechar
chat-workspace-pane-loading-the-files-u = A carregar os ficheiros…
chat-workspace-pane-the-files-could-not-be = Os ficheiros não pôde ser carregados: { $error }
chat-workspace-pane-this-conversation-has-no-files = Esta conversa não tem ficheiros.
chat-workspace-pane-version = versão { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = Escolha um ficheiro para o ler.
chat-workspace-pane-loading-the-file-u = A carregar o ficheiro…
chat-workspace-pane-the-file-could-not-be = Não foi possível carregar o ficheiro: { $error }
chat-workspace-pane-version-2 = { $found_name }, versão { $found_version }
chat-board-create-collections = Coleções
chat-board-create-loading-collections-u = A carregar coleções…
chat-board-create-hoover-search-new-board = Pesquisa Hoover - Novo quadro
chat-board-create-ai-chat = Conversa de IA
chat-board-create-new-investigation-board = Novo quadro de investigação
chat-board-create-a-board-runs-its-goals = Um quadro executa os seus objetivos como uma sequência de explorações do agente. Cada exploração é uma conversa que termina numa descoberta do quadro. Pode rever a resposta de cada objetivo e pode rejeitar descobertas e adicionar indicações enquanto corre.
chat-board-create-title = Título
chat-board-create-goal = Objetivo
chat-board-create-remove-this-goal = Remover este objetivo
chat-board-create-remove = Remover
chat-board-create-add-a-goal = Adicionar um objetivo
chat-board-create-context-optional = Contexto (opcional)
chat-board-create-hints-one-per-line-optional = Sugestões, uma por linha (opcional)
chat-board-create-sources = Fontes
chat-board-create-internet-tools = Ferramentas de Internet
chat-board-create-creating-board = A criar o quadro…
chat-board-create-create-board = Criar quadro
ai-chat-board-hoover-search-board = Hoover Search - Quadro
ai-chat-board-loading-the-board-u = A carregar o quadro…
ai-chat-board-show-the-board-overview = Mostrar a visão geral do quadro
ai-chat-board-zoom-out = Diminuir o zoom
ai-chat-board-zoom-in = Aumentar o zoom
ai-chat-board-u-ai-chat = ← Conversa de IA
ai-chat-board-settings = Configurações
ai-chat-board-board-settings = Configurações do quadro
ai-chat-board-internet-tools = Ferramentas de Internet
ai-chat-board-the-next-explores-of-the = As próximas explorações do quadro podem pesquisar na web e ler páginas da web. As explorações em execução mantêm a configuração com que começaram.
ai-chat-board-collections = Coleções
ai-chat-board-the-collections-are-fixed-when = As coleções são fixadas quando o quadro é criado.
ai-chat-board-confirm-drop = Confirmar largada
ai-chat-board-drop-the-board = Largar o quadro
ai-chat-board-close = Fechar
ai-chat-board-the-board-used-its-explore = O quadro utilizou o limite de exploração
ai-chat-board-the-board-used-explores-the = O quadro utilizou { $explore_limit } explorações, o limite de um quadro. Não inicia mais trabalho. Ainda pode decidir as respostas propostas.
ai-chat-board-create-a-new-board-to = Crie um novo quadro para continuar a investigação
ai-chat-board-goal = Objetivo
ai-chat-board-goals = Objetivos
ai-chat-board-add-new-goal = Adicionar novo objetivo...
ai-chat-board-a-new-goal = Um novo objetivo
ai-chat-board-add-goal = Adicionar objetivo
ai-chat-board-a-board-has-at-most = Um quadro tem no máximo { $max_goals } objetivos. Crie um novo quadro para outro objetivo.
ai-chat-board-background-context = Contexto de fundo
ai-chat-board-continue-with-a-correction = Continuar com uma correção
ai-chat-board-correction-what-is-wrong-or = Correção: o que está errado ou em falta. O quadro continua com ela.
ai-chat-board-the-board-waits-for-your = O quadro aguarda a sua revisão
ai-chat-board-the-board-used-its-budget = O quadro utilizou o seu orçamento de { $snap_max_explores } explorações.
ai-chat-board-the-assessments-gave-no-usable = As avaliações não deram nenhuma direção utilizável.
ai-chat-board-accept-or-reject-the-proposed = Aceite ou rejeite a resposta proposta de cada objetivo acima. Uma resposta rejeitada deixa o quadro continuar de imediato.
ai-chat-board-no-proposed-answer-waits-for = Não há resposta proposta à espera da sua decisão.
ai-chat-board-reopen-the-board-to-continue = Reabrir o quadro para continuar os objetivos em aberto. Mantém as suas descobertas e respostas.
ai-chat-board-close-the-board-to-accept = Fechar o quadro para aceitar todas as respostas propostas e terminá-lo, ou continuá-lo com uma correção.
ai-chat-board-close-the-board = Fechar o quadro
ai-chat-board-or-reopen-the-board-to = Ou reabrir o quadro para continuar os objetivos em aberto sem uma correção.
ai-chat-board-the-board-is-complete = O quadro está completo
ai-chat-board-a-goal-has-no-accepted = Um objetivo não tem resposta aceita. Reabrir o quadro para continuar. O quadro mantém as suas descobertas e respostas.
ai-chat-board-add-a-hint = Adicionar dica
ai-chat-board-the-next-assessment-reads-every = A próxima avaliação lê cada dica. Uma dica também responde a uma exploração que fez uma pergunta.
ai-chat-board-add-hint = Adicionar dica
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
ai-chat-board-model-steps-per-explore = Etapas do modelo por exploração
ai-chat-board-assessments = Avaliações
ai-chat-board-intents = Intenções
ai-chat-board-findings = Descobertas
ai-chat-board-created = Criado
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } rejeitou esta descoberta em { $format_utc_ms_fact_rejected_ms }. O quadro já não a utiliza.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } rejeitou esta descoberta. O quadro já não a utiliza.
ai-chat-board-no-reason-was-given = Não foi indicado nenhum motivo.
ai-chat-board-reason = Motivo: { $fact_rejected_reason }
ai-chat-board-open-questions = Questões em aberto
ai-chat-board-explored-in = Explorada em
ai-chat-board-explore-this-question = Explorar esta questão
ai-chat-board-your-questions = As suas questões
ai-chat-board-ask-about-the-background-context = Perguntar sobre o contexto de suporte
ai-chat-board-ask-about-this-finding = Perguntar sobre esta descoberta
ai-chat-board-a-follow-up-question-about = Uma pergunta de seguimento sobre este nó
ai-chat-board-ask = Perguntar
ai-chat-board-checks-that-changed-this-finding = Verificações que alteraram esta descoberta
ai-chat-board-reject-this-correction = Rejeitar esta correção
ai-chat-board-reject-this-finding = Rejeitar esta descoberta
ai-chat-board-not-answered-the-board-was = Sem resposta. O quadro foi concluído sem resposta para este objetivo. Uma dica ou o reabrir voltam a abri-lo.
ai-chat-board-no-answer-yet = Ainda sem resposta.
ai-chat-board-the-findings-of-this-answer = As descobertas desta resposta são pesquisas que não encontraram nada. Aceite para registar que os registos não respondem ao objetivo, ou rejeite para continuar a investigação.
ai-chat-board-open-an-assessment-to-read = { "." } Abra uma avaliação para saber porquê.
ai-chat-board-from-the-findings = Das descobertas{ " " }
ai-chat-board-accept-answer = Aceitar resposta
ai-chat-board-why-the-answer-is-wrong = Porque a resposta está errada ou incompleta
ai-chat-board-reject-answer = Rejeitar resposta
ai-chat-board-intent = Intento
ai-chat-board-attempts-declared = Tentativas: { $intent_attempts }. Declarado em { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = A exploração perguntou
ai-chat-board-add-a-hint-in-the = Adicione uma dica na visão geral do quadro para lhe responder.
ai-chat-board-last-error = Último erro
ai-chat-board-brief = Breve
ai-chat-board-open-the-explore-chat = Abrir a conversa de exploração
ai-chat-board-loading-the-assessment-u = A carregar a avaliação…
ai-chat-board-assessment = Avaliação { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. Modelo { $a_model }. Resultado { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = Verificações que o alteraram
ai-chat-board-prompt = Pedido
ai-chat-board-this-assessment-ran-before-the = Esta avaliação correu antes de os pedidos serem guardados.
ai-chat-board-response = Resposta
ai-chat-history-hoover-search-chat-history = Hoover Search - Histórico de conversas
ai-chat-history-u-back = ← Voltar
ai-chat-history-conversation-history = Histórico de conversas
ai-chat-history-show-board-chats = Mostrar conversas do quadro
ai-chat-history-loading-u = A carregar…
ai-chat-history-could-not-load-history = Não foi possível carregar o histórico: { $e }
ai-chat-history-no-conversations-yet = Ainda não há conversas.
ai-chat-history-board = Quadro
ai-chat-history-new-chat = Nova conversa
ai-chat-history-messages-updated = { $s_message_count } mensagens · atualizadas a { $s_updated_at }
ai-chat-history-delete-conversation = Eliminar conversa
ai-chat-history-delete = Eliminar
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - Conversa com IA
ai-chat-homepage-what-are-you-researching = O que está a pesquisar?
ai-chat-homepage-view-all-conversations = Ver todas as conversas
ai-chat-homepage-starting-conversation-u = A iniciar a conversa…
ai-chat-homepage-investigation-boards = Quadros de investigação
ai-chat-homepage-new-board = Novo quadro
ai-chat-homepage-loading-boards-u = A carregar os quadros…
ai-chat-homepage-could-not-load-the-boards = Não foi possível carregar os quadros: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = Não tem nenhum quadro. Um quadro conduz uma investigação longa como uma sequência de explorações do agente, e você revê as respetivas respostas.
ai-chat-homepage-updated = Atualizado a { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - Conversa com IA
ai-chat-session-this-conversation-could-not-be = Não foi possível carregar esta conversa.
ai-chat-session-loading-u = A carregar…
ai-chat-session-u-chats = ← Conversas
ai-chat-session-history = Histórico
ai-chat-session-show-the-files-that-the = Mostrar os ficheiros que o assistente escreveu nesta conversa
ai-chat-session-workspace = Espaço de trabalho
ai-chat-session-this-answer-was-interrupted-before = Esta resposta foi interrompida antes de ser concluída, porque a página ou o servidor pararam a meio do turno. Volte a pedir para tentar novamente.
ai-chat-session-dismiss = Ignorar
ai-chat-session-board-explore-chats-are-read = As conversas de exploração do quadro são somente leitura.{ " " }
ai-chat-session-open-the-board = Abrir o quadro
chat-locked-options-on = { $label }: ligado
chat-locked-options-off = { $label }: desligado
chat-tool-cards-running-u = a correr…
cards-result-cards-quote-found = Citação encontrada
cards-result-cards-quote-not-found = Citação não encontrada
cards-result-cards-quote-not-checked = Citação não verificada
web-search-card-results = { $results_len } resultados
chat-tool-disclosure-running-u = a processar…
chat-transcript-call = chamada
chat-transcript-calls = chamadas
ai-chat-board-a-board-without-collections-needs = Um quadro sem coleções precisa de ferramentas de internet.
ai-chat-board-of = { $snap_explores_used } de { $snap_max_explores }
ai-chat-board-assessment-2 = avaliação { $number }
ai-chat-history-messages = { $s_message_count } mensagens
web-search-card-reranked-in = O cross-encoder reordenou os resultados em { $ms } ms.
web-search-card-engine-results = { $name }: { $count } em { $ms } ms
web-search-card-score-was-rank = pontuação { $score } · era RRF #{ $rank }
chat-activity-the-turn-waits-for-a = A conversa aguarda uma livre de modelo.
chat-activity-the-turn-waits-for-a-2 = A conversa aguarda uma livre de ferramenta.
chat-locked-options-start-a-new-chat-to = Inicie uma nova conversa para alterar esta configuração.
chat-locked-options-internet-tools = Ferramentas de internet
chat-session-card-new-chat = Nova conversa
chat-tool-cards-first-frame-of-the-video = Primeiro quadro do vídeo
chat-tool-cards-screenshot-of = Captura de ecrã de
chat-tool-cards-image = Imagem
cards-result-cards-the-agent-asked-a-question = O agente fez uma pergunta.
chat-transcript-hide = Esconder
chat-transcript-show = Mostrar
chat-transcript-unverified-quote-the-quoted-span = Citação não verificada. O trecho citado é demasiado curto para ser verificado.
chat-transcript-unverified-quote-the-document-text = Citação não verificada. O texto do documento não pôde ser lido.
chat-transcript-unverified-quote-this-wording-was = Citação não verificada. Esta redação não foi encontrada no documento.
chat-board-create-select-a-collection-or-turn = Selecione uma coleção ou ligue as ferramentas de internet.
chat-board-create-select-at-least-one-collection = Selecione pelo menos uma coleção.
ai-chat-board-active = Ativo
ai-chat-board-paused = Pausado
ai-chat-board-waits-for-review = Aguarda revisão
ai-chat-board-completed = Concluído
ai-chat-board-dropped = Abandonado
ai-chat-board-unknown = Desconhecido
ai-chat-board-pause-the-board = Pausar o quadro
ai-chat-board-resume-the-board = Retomar o quadro
ai-chat-board-none = Nenhum
ai-chat-board-reopen-with-the-remaining-budget = Reabrir com o orçamento restante
ai-chat-board-finding = Descoberta
ai-chat-board-why-the-correction-is-wrong = Por que a correção está errada
ai-chat-board-reject-correction = Rejeitar correção
ai-chat-board-why-the-finding-is-wrong = Por que a descoberta está errada
ai-chat-board-reject-finding = Rejeitar descoberta
ai-chat-board-answer = Resposta
ai-chat-board-proposed-answer = Resposta proposta
ai-chat-homepage-active = Ativo
ai-chat-homepage-paused = Pausado
ai-chat-homepage-waits-for-review = Aguarda revisão
ai-chat-homepage-completed = Concluído
ai-chat-homepage-dropped = Abandonado
ai-chat-homepage-unknown = Desconhecido
cards-result-cards-submitted-by-board =
    Submetida pelo quadro: { $kind ->
        [sourced] uma fonte
        [inferred] uma inferida
        [not_found] uma não encontrada
       *[other] um tipo desconhecido
    } descoberta do relatório
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] Uma fonte
        [inferred] Uma inferida
        [not_found] Uma não encontrada
       *[other] Um tipo desconhecido
    } descoberta para o quadro
chat-transcript-compacting = A compactar o contexto: { $before } tokens para um alvo de { $target }.
chat-transcript-compaction-failed = O resumo dos passos anteriores falhou. O modelo recebeu os passos anteriores inalterados, { $after } tokens.
chat-transcript-compacted = Contexto compactado: { $steps } passos resumidos, { $before } tokens para { $after }.
ai-chat-board-reopen-with-more = Reabrir com { $grant } explorações adicionais
ai-chat-board-goal-number = Objetivo { $number }
ai-chat-board-from-assessment-on = Da avaliação { $number } em { $date }.
ai-chat-board-from-assessment = Da avaliação { $number }.
chat-board-create-goal-2 = Meta { $index_1 }
ai-chat-session-lost-contact-with-the-chat = perdeu a ligação com a conversa: { $e }
ai-chat-session-could-not-stop-the-answer = não foi possível interromper a resposta: { $e } — ainda está em curso
ai-chat-board-later-assessments-dropped-an-answer = { $n } avaliações posteriores abandonaram uma resposta para esta meta:
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } tokens de pedido e { $a_completion_tokens } tokens de conclusão
ai-chat-homepage-completed-goals-not-answered = Concluídas, { $n } metas sem resposta
board-graph-intent = intenção, { $state }
chat-workspace-pane-characters = { $chars } caracteres
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } a executar a ferramenta { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } a executar a ferramenta { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = Respondido após { $retries_len } tentativa(s) falhada(s){ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } tentativa{ $if_retries_len_1_else_s } falhada
chat-transcript-version-2 = { $report_name }, versão { $report_version }
tool-run-summary-searched =
    { $n ->
        [one] pesquisou { $n } termo
       *[other] pesquisou { $n } termos
    }
tool-run-summary-read =
    { $n ->
        [one] leu { $n } documento
       *[other] leu { $n } documentos
    }
tool-run-summary-searched-the-web-for =
    { $n ->
        [one] pesquisou a web por { $n } termo
       *[other] pesquisou a web por { $n } termos
    }
tool-run-summary-read-web =
    { $n ->
        [one] leu { $n } página web
       *[other] leu { $n } páginas web
    }
tool-run-summary-browser =
    { $n ->
        [one] { $n } ação de navegação
       *[other] { $n } ações de navegação
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
        [one] listou as entidades de { $n } documento
       *[other] listou as entidades de { $n } documentos
    }
tool-run-summary-cited =
    { $n ->
        [one] citou { $n } documento
       *[other] citou { $n } documentos
    }
tool-run-summary-cited-web =
    { $n ->
        [one] citou { $n } página web
       *[other] citou { $n } páginas web
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
        [one] leu { $n } texto de competência e de ferramenta
       *[other] leu { $n } textos de competência e de ferramenta
    }
tool-run-summary-saved =
    { $n ->
        [one] guardou { $n } nota
       *[other] guardou { $n } notas
    }
tool-run-summary-todo-list =
    { $n ->
        [one] { $n } chamada à lista de tarefas
       *[other] { $n } chamadas à lista de tarefas
    }
tool-run-summary-to-the-agent =
    { $n ->
        [one] { $n } instrução para o agente
       *[other] { $n } instruções para o agente
    }
tool-run-summary-other =
    { $n ->
        [one] { $n } outra chamada
       *[other] { $n } outras chamadas
    }
tool-run-summary-failed = { $failures } falhada(s)
tool-run-summary-took = levou { $duration_text_ms }
chat-session-card-messages = { $session_message_count } mensagens
chat-tool-disclosure-item =
    { $count ->
        [one] { $count } item
       *[other] { $count } itens
    }
chat-tool-disclosure-field =
    { $count ->
        [one] { $count } campo
       *[other] { $count } campos
    }
chat-tool-disclosure-searched-collections = coleções pesquisadas{ $filters }
chat-tool-disclosure-searched-collections-2 = coleções pesquisadas · { $query }{ $filters }
chat-tool-disclosure-cited-documents = { $n } documentos citados
chat-tool-disclosure-read-document = ler documento · { $path }
chat-tool-disclosure-searched-the-web = pesquisar a web · { $q }
chat-tool-disclosure-opened-page = abrir página · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = chamar { $other }
chat-tool-disclosure-called-2 = chamar { $other } · { $short }
cards-browser-card-opened = aberta { $url }
cards-browser-card-could-not-open = não foi possível abrir { $url }
cards-browser-card-clicked = clicada { $element }
cards-browser-card-could-not-click = não foi possível clicar em { $element }
cards-browser-card-typed-into = digitado em { $element }
cards-browser-card-could-not-type-into = não foi possível digitar em { $element }
cards-browser-card-typed = digitado “{ $text }”
cards-browser-card-could-not-type = não foi possível digitar “{ $text }”
cards-browser-card-pressed = pressionada { $key }
cards-browser-card-could-not-press = não foi possível pressionar { $key }
cards-browser-card-chose-an-option-in = opção escolhida em { $element }
cards-browser-card-could-not-choose-an-option = não foi possível escolher uma opção em { $element }
cards-browser-card-hovered = sobre { $element }
cards-browser-card-could-not-hover = não foi possível sobrepor a { $element }
cards-browser-card-failed = { $bare } — falhou
cards-entities-card-listed-entities-document = entidades listadas · { $count } documento{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · parte { $part } de { $name } #{ $seq }
cards-result-cards-documents = { " " }· { $value } documentos
cards-result-cards-forms = { $tool_name } · { $forms } formulários
cards-result-cards-in = { " " }em { $collections }
cards-result-cards-page = { " " }· página { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } documentos · { $missing } citações não encontradas
cards-result-cards-version-unchanged = { $tool_name } · versão { $version } · inalterado
cards-result-cards-version = { $tool_name } · versão { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } resultados em, { $json_u64_doc_total_after_dedupe } após deduplicação
