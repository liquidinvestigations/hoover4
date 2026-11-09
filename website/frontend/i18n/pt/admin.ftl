# Translation of en/admin.ftl. Change it together with the English catalog.

admin-guard-administration-access-required = É necessário acesso à administração
admin-guard-signed-in-as = Sessão iniciada como { $u_username }.
admin-guard-ask-an-administrator-for-access = Peça a um administrador acesso a esta secção.
admin-shell-dashboard = Painel de controlo
admin-shell-collections = Coleções
admin-shell-operations = Operações
admin-shell-errors-failures = Erros/Falhas
admin-shell-feedback = Comentários
admin-shell-users = Utilizadores
admin-shell-groups = Grupos
admin-shell-settings = Definições
admin-shell-llm = LLM
admin-shell-ai-status = Estado da IA
admin-shell-metrics = Métricas
admin-shell-administration = Administração
dataset-create-panel-add-a-dataset = Adicionar um conjunto de dados
dataset-create-panel-the-dataset-mounts-could-not = Não foi possível ler as montagens de conjuntos de dados, por isso não há nada para escolher: { $err }
dataset-create-panel-loading-the-dataset-mounts = A carregar as montagens de conjuntos de dados.
dataset-create-panel-no-dataset-mount-is-configured = Nenhuma montagem de conjuntos de dados está configurada.
dataset-create-panel-the-mount-folder-could-not = Não foi possível ler a pasta da montagem, por isso não há nada para escolher: { $err }
dataset-create-panel-no-subfolders-were-found-in = Não foram encontradas subpastas nesta montagem.{" "}
dataset-create-panel-folder = Pasta
dataset-create-panel-select-a-folder = Selecione uma pasta
dataset-create-panel-new-folder = Nova pasta
dataset-create-panel-entries-already-a-dataset = { $option_name } ({ $option_entry_count } entradas), já é um conjunto de dados
dataset-create-panel-entries = { $option_name } ({ $option_entry_count } entradas)
dataset-create-panel-the-server-creates-this-folder = O servidor cria esta pasta na montagem quando cria o conjunto de dados.{" "}
dataset-create-panel-the-list-shows-the-direct = A lista mostra as subpastas diretas da montagem.
dataset-create-panel-dataset-name = Nome do conjunto de dados
dataset-create-panel-a-name-has-lowercase-letters = Um nome tem letras minúsculas, algarismos e carateres de sublinhado. As letras maiúsculas passam a minúsculas,{" "}
dataset-create-panel-the-dataset-is-saved-as = O conjunto de dados é guardado como: { $saved_name }
dataset-create-panel-this-collection-has-a-dataset = Esta coleção já tem um conjunto de dados com o nome { $saved_name }.
dataset-create-panel-accept-uploads = Aceitar carregamentos
dataset-create-panel-creating-u = A criar…
dataset-create-panel-create-and-ingest = Criar e ingerir
dataset-create-panel-mount = Montagem
dataset-ocr-panel-last-operation = Última operação: { $current_kind }, { $current_state }
dataset-ocr-panel-started = , iniciada em { $current_started_at }
dataset-ocr-panel-no-progress-for-minutes-check = Sem progresso há { $current_stale_seconds_60 } minutos. Verifique o fluxo de trabalho do Temporal e cancele a operação se estiver bloqueada.
dataset-ocr-panel-loading-u = A carregar…
dataset-ocr-panel-stored-text-variants = Variantes de texto guardadas
dataset-ocr-panel-searchable-pdfs = PDF pesquisáveis
dataset-ocr-panel-u-u-files-u-mb = { $variant_engine } · { $variant_languages } · { $variant_pdf_count } ficheiros · { $variant_total_bytes_1024_1024 } MB
live-chats-panel-live-llm-chats = Conversas LLM em direto
live-chats-panel-agent-turns-running-right-now = Turnos do agente em execução neste momento, os mais longos primeiro. Atualiza a cada 2 s. É lido do Temporal, por isso um turno iniciado antes do último reinício do sítio web também aparece aqui.
live-chats-panel-loading-u = A carregar…
live-chats-panel-no-chats-running = Nenhuma conversa em execução.
live-chats-panel-user = Utilizador
live-chats-panel-conversation = Conversa
live-chats-panel-question = Pergunta
live-chats-panel-internet = Internet
live-chats-panel-running = Em execução
live-chats-panel-started = Iniciada
live-chats-panel-cancels-the-workflow-the-turn = Cancela o fluxo de trabalho. O turno termina com uma marca de paragem na transcrição e não desaparece.
live-chats-panel-kill = Terminar
processing-updates-panel-loading-u = A carregar…
processing-updates-panel-open-the-operation = Abrir a operação
processing-updates-panel-the-pipeline-has-not-calculated = O pipeline ainda não calculou estas atualizações.
processing-updates-panel-calculated-at-in-ms = Calculado em { $view_checked_at } em { $view_check_ms } ms.{" "}
processing-updates-panel-automatic-updates-are-off-on = As atualizações automáticas estão desativadas nesta instalação. Inicie as atualizações com o botão.
processing-updates-panel-step = Passo
processing-updates-panel-count = Contagem
processing-updates-panel-state = Estado
processing-updates-panel-last-run = Última execução
processing-updates-panel-runs = Execuções: { $step_runs }
processing-updates-panel-a-run-again-would-select = Uma nova execução selecionaria aproximadamente este número de { $step_unit }.
processing-updates-panel-on-a-run-again = { $step_pending } { $unit } numa nova execução
processing-updates-panel-never = Nunca
processing-updates-panel-update-collection = Atualizar coleção
processing-updates-panel-update-processing = Atualizar processamento
processing-updates-panel-check-again = Verificar novamente
processing-updates-panel-dataset = Conjunto de dados
processing-updates-panel-processing-updates = Atualizações do processamento
admin-ai-status-admin-ai-status = Administração: estado da IA
admin-ai-status-ai-status = Estado da IA
admin-ai-status-the-configured-service-and-the = O serviço configurado e o serviço que realmente responde. Uma recorrência ao serviço de CPU só aparece aqui.
admin-ai-status-loading-u = A carregar…
admin-ai-status-config-fingerprint = Impressão digital da configuração
admin-ai-status-website-worker = Sítio web / worker
admin-ai-status-ai-server = Servidor de IA
admin-ai-status-match = Coincide
admin-ai-status-embeddings-probe = Sonda de incorporação
admin-ai-status-dims = { $status_embeddings_serving_model } · { $status_embeddings_serving_dim } dimensões
admin-ai-status-llm-configured = LLM configurado
admin-ai-status-capabilities = Capacidades
admin-ai-status-capability = Capacidade
admin-ai-status-configured = Configurado
admin-ai-status-serving = Em serviço
admin-ai-status-model = Modelo
admin-ai-status-reachable = Acessível
admin-ai-status-detail = Detalhe
admin-ai-status-no = NÃO
admin-ai-status-vector-shard-dims-vs-probe = Dimensões do fragmento de vetores vs sonda
admin-ai-status-no-collections-yet = Ainda não há coleções.
admin-ai-status-collection = Coleção
admin-ai-status-shard = Fragmento
admin-ai-status-matches-probe = Coincide com a sonda
admin-ai-status-browser-router = Router do navegador
admin-ai-status-live-sessions = Sessões ativas: { $status_browser_live_sessions } / { $status_browser_max_sessions }
admin-ai-status-recent-llm-traffic-24-h = Tráfego LLM recente (24 h)
admin-ai-status-no-llm-call-events-yet = Ainda não há llm_call_events.
admin-ai-status-user = Utilizador
admin-ai-status-calls = Chamadas
admin-ai-status-errors = Erros
admin-ai-status-service-use-24-h = Utilização do serviço % (24 h)
admin-ai-status-busy-seconds-in-the-last = Segundos ocupados nas últimas 24 horas, como percentagem do dia.
admin-ai-status-no-samples-yet = Ainda não há amostras.
admin-ai-status-service = Serviço
admin-ai-status-busy-s = Ocupado s
admin-ai-status-use = Utilização %
admin-collection-detail-admin-collection = Administração: coleção { $collection_id }
admin-collection-detail-failed-to-load-collection = Não foi possível carregar a coleção
admin-collection-detail-loading = A carregar...
admin-collection-detail-datasets = Conjuntos de dados
admin-collection-detail-dataset = Conjunto de dados
admin-collection-detail-documents = Documentos
admin-collection-detail-size = Tamanho
admin-collection-detail-indexed = Indexados
admin-collection-detail-errors = Erros
admin-collection-detail-state = Estado
admin-collection-detail-created = Criado
admin-collection-detail-settings = Definições
admin-collection-detail-the-collection-database-is-not = A base de dados da coleção ainda não está pronta.
admin-collection-detail-the-last-storage-provisioning-failed = O último aprovisionamento de armazenamento falhou: { $detail_provisioning_error }
admin-collection-detail-processing-progress-and-estimates = Progresso e estimativas do processamento
admin-collection-detail-display-name = Nome de apresentação
admin-collection-detail-display-name-2 = nome de apresentação
admin-collection-detail-save = Guardar
admin-collection-detail-access = Acesso
admin-collection-detail-public-every-signed-in-user = Pública. Todos os utilizadores com sessão iniciada podem pesquisar e ler esta coleção.
admin-collection-detail-restricted-only-members-of-the = Restrita. Só os membros dos grupos abaixo podem pesquisar e ler esta coleção.
admin-collection-detail-the-collection-is-now-public = A coleção é agora pública.
admin-collection-detail-the-collection-is-now-restricted = A coleção é agora restrita.
admin-collection-detail-make-restricted = Tornar restrita
admin-collection-detail-make-public = Tornar pública
admin-collection-detail-group-permissions = Permissões dos grupos
admin-collection-detail-no-group-can-read-this = Nenhum grupo pode ainda ler esta coleção.
admin-collection-detail-revoke = Revogar
admin-collection-detail-grant-group-u = Conceder ao grupo…
admin-collection-detail-grant = Conceder
admin-collection-detail-danger-zone = Zona de perigo
admin-collection-detail-a-collection-can-only-be = Uma coleção só pode ser eliminada enquanto não tiver conjuntos de dados.
admin-collection-detail-deleting-the-collection-also-drops = Eliminar a coleção elimina também a sua base de dados{" "}
admin-collection-detail-hoover4-collection = Hoover4_Collection_{ $cname }
admin-collection-detail-and-everything-in-it-this = {" "}e tudo o que ela contém. Isto não pode ser anulado. Escreva o nome da coleção para confirmar.
admin-collection-detail-collection-name = Nome da coleção
admin-collection-detail-delete-collection = Eliminar coleção
admin-collection-detail-features = Funcionalidades
admin-collection-detail-vectors = Vetores
admin-collection-detail-this-installation-runs-no-embedding = Esta instalação não executa nenhum serviço de vetores de incorporação, por isso nenhuma coleção usa vetores.
admin-collection-detail-vectors-find-passages-by-meaning = Os vetores encontram passagens pelo significado. Desativado, deixa de criar novos vetores e a pesquisa deixa de usar os guardados, que permanecem. Ativado, calcula os vetores em falta de cada conjunto de dados, um conjunto de cada vez.
admin-collection-detail-this-collection-follows-the-installation = Esta coleção segue a instalação, que usa vetores. Os vetores encontram passagens pelo significado. Desativado, deixa de criar novos vetores e a pesquisa deixa de usar os guardados, que permanecem.
admin-collection-processing-could-not-load-this-panel = Não foi possível carregar este painel: { $message }
admin-collection-processing-admin-processing-of = Administração: processamento de { $collection_id }
admin-collection-processing-u-back-to-collection = ← Voltar à coleção
admin-collection-processing-processing-stages = Fases do processamento
admin-collection-processing-loading-u = A carregar…
admin-collection-processing-the-collection-database-is-still = A base de dados da coleção ainda está a ser aprovisionada.
admin-collection-processing-this-collection-has-no-datasets = Esta coleção ainda não tem conjuntos de dados.
admin-collection-processing-eta = Previsão { $humanize_seconds_eta }
admin-collection-processing-no-estimate-samples-yet-they = Ainda não há amostras de estimativa. São recolhidas enquanto o conjunto de dados é processado.
admin-collection-processing-estimated-completion = Conclusão estimada:{" "}
admin-collection-processing-in-a-best-effort-estimate = {" "}(dentro de { $humanize_seconds_c_eta_seconds }, uma estimativa de melhor esforço e não uma promessa de agendamento)
admin-collection-processing-no-current-estimate-the-pipeline = Sem estimativa atual. O pipeline terminou ou não está a fazer progressos mensuráveis.
admin-collection-processing-where-processing-time-goes = Onde se gasta o tempo de processamento
admin-collection-processing-no-task-executions-recorded-yet = Ainda não há execuções de tarefas registadas. Cada atividade que o pipeline executa escreve aqui uma linha, por isso uma tabela vazia significa que nada foi processado desde que a instrumentação foi implantada.
admin-collection-processing-summed-task-time = Tempo total das tarefas
admin-collection-processing-wall-clock = Tempo real
admin-collection-processing-achieved-parallelism = Paralelismo alcançado
admin-collection-processing-summed-task-time-divided-by = O tempo total das tarefas dividido pelo tempo real é o que o pipeline alcançou efetivamente em paralelo. Perto de 1 significa que a primeira tarefa abaixo é todo o custo e vale a pena otimizá-la. Perto do número de vagas dos workers significa que as vagas estão saturadas e que mais workers é a solução mais barata. O tempo real vai da primeira execução à última, incluindo o tempo inativo.
admin-collection-processing-task = Tarefa
admin-collection-processing-total = Total
admin-collection-processing-share = Percentagem
admin-collection-processing-executions = Execuções
admin-collection-processing-mean = Média
admin-collection-processing-max = Máx.
admin-collection-processing-failed = Falharam
admin-collection-processing-live-activity = Atividade em direto
admin-collection-processing-nothing-running-no-activity-finished = Nada em execução. Nenhuma atividade terminou nos últimos { $live_window_seconds } s e nenhum worker comunica algo em curso.
admin-collection-processing-in-flight = Em curso
admin-collection-processing-average-concurrency = Concorrência média
admin-collection-processing-task-time-in-window = Tempo de tarefas na janela
admin-collection-processing-share-of-processing-time-over = Percentagem do tempo de processamento nos últimos { $live_window_seconds } s, atualizada a cada 5 s. Uma execução que atravessa o limite da janela conta apenas pela parte que está dentro dela. Uma linha com execuções em curso mas sem percentagem começou antes da janela e ainda não terminou. Verifique a sua idade.
admin-collection-processing-share-of-window = Percentagem da janela
admin-collection-processing-task-time = Tempo de tarefas
admin-collection-processing-completed = Concluídas
admin-collection-processing-oldest-running = Mais antiga em execução
admin-collection-processing-temporal-workflows = Fluxos de trabalho do Temporal
admin-collection-processing-workflows-of-this-collection-s = Fluxos de trabalho dos conjuntos de dados desta coleção, incluindo os fluxos filhos.
admin-collection-processing-no-workflows-match-this-filter = Nenhum fluxo de trabalho corresponde a este filtro.
admin-collection-processing-workflow = Fluxo de trabalho
admin-collection-processing-type = Tipo
admin-collection-processing-status = Estado
admin-collection-processing-started = Iniciado
admin-collection-processing-closed = Terminado
admin-collection-processing-temporal = Temporal
admin-collection-processing-open-u = abrir ↗
admin-collection-processing-failed-tasks = Tarefas falhadas
admin-collection-processing-no-task-failures-recorded = Nenhuma falha de tarefa registada.
admin-collection-processing-dataset = Conjunto de dados
admin-collection-processing-errors = Erros
admin-collection-processing-documents = Documentos
admin-collection-processing-last-seen = Visto pela última vez
admin-collection-processing-sample = Amostra
admin-collection-processing-retry = Tentar novamente
admin-collection-processing-failures-per-document = Falhas por documento
admin-collection-processing-no-document-failures-recorded = Nenhuma falha de documento registada.
admin-collection-processing-document = Documento
admin-collections-list-admin-collections = Administração: coleções
admin-collections-list-collections = Coleções
admin-collections-list-loading-collections-u = A carregar coleções…
admin-collections-list-datasets = Conjuntos de dados
admin-collections-list-loading-datasets-u = A carregar conjuntos de dados…
admin-collections-list-add-a-collection = Adicionar uma coleção
admin-collections-list-name-for-example-enron = Nome, por exemplo enron
admin-collections-list-display-name = Nome de apresentação
admin-collections-list-add-collection = Adicionar coleção
admin-collections-list-a-name-has-lowercase-letters = Um nome tem letras minúsculas, algarismos e carateres de sublinhado. As letras maiúsculas passam a minúsculas,{" "}
admin-collections-list-the-collection-is-saved-as = A coleção é guardada como: { $new_name }
admin-collections-list-a-collection-with-the-name = Já existe uma coleção com o nome { $new_name }.
admin-collections-list-collection = Coleção
admin-collections-list-documents = Documentos
admin-collections-list-size = Tamanho
admin-collections-list-errors = Erros
admin-collections-list-state = Estado
admin-collections-list-access = Acesso
admin-collections-list-database-not-ready = Base de dados não pronta
admin-collections-list-public = Pública
admin-collections-list-1-group = 1 grupo
admin-collections-list-not-counted-yet = Ainda não contado
admin-collections-list-unknown = Desconhecido
admin-collections-list-no-collection-has-a-dataset = Nenhuma coleção tem um conjunto de dados.
admin-collections-list-dataset = Conjunto de dados
admin-collections-list-indexed = Indexados
admin-collections-list-created = Criado
admin-dashboard-admin-dashboard = Administração: painel de controlo
admin-dashboard-administration = Administração
admin-dashboard-users = Utilizadores
admin-dashboard-groups = Grupos
admin-dashboard-collections = Coleções
admin-dashboard-datasets = Conjuntos de dados
admin-dashboard-failed-to-load-counts = Não foi possível carregar as contagens: { $e }
admin-dataset-detail-admin-dataset = Administração: conjunto de dados { $dataset_id }
admin-dataset-detail-failed-to-load-dataset = Não foi possível carregar o conjunto de dados
admin-dataset-detail-loading = A carregar...
admin-dataset-detail-metadata = Metadados
admin-dataset-detail-display-name = Nome de apresentação
admin-dataset-detail-name = Nome
admin-dataset-detail-type = Tipo
admin-dataset-detail-path = Caminho
admin-dataset-detail-created = Criado
admin-dataset-detail-collection = Coleção
admin-dataset-detail-save = Guardar
admin-dataset-detail-statistics = Estatísticas
admin-dataset-detail-state = Estado
admin-dataset-detail-documents = Documentos
admin-dataset-detail-size = Tamanho
admin-dataset-detail-indexed = Indexados
admin-dataset-detail-errors = Erros
admin-dataset-detail-plans-finished = Planos concluídos
admin-dataset-detail-disk = Disco
admin-dataset-detail-rescan-disk-reads-the-dataset = Examinar o disco novamente lê outra vez a pasta do conjunto de dados, acrescenta os ficheiros novos e alterados e processa-os.
admin-dataset-detail-rescan-disk = Examinar o disco novamente
admin-dataset-detail-danger-zone = Zona de perigo
admin-dataset-detail-this-deletes-the-dataset-and = Isto elimina o conjunto de dados e todos os dados extraídos dele. Não pode ser anulado.
admin-dataset-detail-delete-dataset-and-its-data = Eliminar o conjunto de dados e os seus dados
admin-dataset-detail-accept-uploads = Aceitar carregamentos
admin-dataset-detail-the-folder-of-this-dataset = A pasta deste conjunto de dados não está numa montagem de conjuntos de dados com permissão de escrita, por isso não recebe carregamentos.
admin-dataset-detail-starting-u = A iniciar…
admin-failure-detail-admin-failure = Administração: falha { $op_id }
admin-failure-detail-loading-tree = A carregar a árvore…
admin-failure-detail-back-to-errors-and-failures = Voltar a erros e falhas
admin-failure-detail-operations = Operações
admin-failure-detail-scrubbed-copy-written-to-the = Cópia higienizada escrita na área de transferência.
admin-failure-detail-this-tree-is-truncated-at = Esta árvore está truncada. Pelo menos uma captura descartou nós.
admin-failure-detail-the-captured-tree-has-expired = A árvore capturada expirou. A linha da operação continua presente.
admin-failure-detail-no-captured-nodes-for-this = Nenhum nó capturado para esta operação.
admin-failure-detail-operation = Operação
admin-failure-detail-root-s-node-s = { $tree_operation_kind } · { $tree_operation_state } · { $root_count } raiz(es) · { $tree_nodes_len } nó(s)
admin-failure-detail-open-in-temporal = Abrir no Temporal
admin-failure-detail-scrubbed-copy = Cópia higienizada
admin-failure-detail-the-scrubbed-copy-replaces-dataset = A cópia higienizada substitui os caminhos dos conjuntos de dados por hashes e os valores longos pelos seus comprimentos.
admin-failure-detail-copy-scrubbed-record = Copiar registo higienizado
admin-failure-detail-tree = Árvore
admin-failure-detail-root = Raiz ·{" "}
admin-failure-detail-node-parent-depth-source-stage = nó { $node_node_index } · pai { $node_parent_index } · profundidade { $node_depth } · fonte { $node_source } · fase { $node_stage } · { $node_task_name }
admin-failure-detail-workflow-run-activity-attempt = fluxo de trabalho { $node_workflow_id } · execução { $node_run_id } · atividade { $node_activity_id } · tentativa { $node_attempt }
admin-failure-detail-node-s-dropped-at-this = { $node_nodes_dropped } nó(s) descartado(s) nesta captura
admin-failures-admin-errors-and-failures = Administração: erros e falhas
admin-failures-errors-failures = Erros/Falhas
admin-failures-loading-failures = A carregar falhas…
admin-failures-operational-failures = Falhas operacionais
admin-failures-no-operational-failures-at-this = Nenhuma falha operacional neste momento.
admin-failures-collection = Coleção
admin-failures-dataset = Conjunto de dados
admin-failures-task-name = Nome da tarefa
admin-failures-error-class = Classe de erro
admin-failures-operation-kind = Tipo de operação
admin-failures-from = De
admin-failures-to = Até
admin-failures-no-captured-failures-match-these = Nenhuma falha capturada corresponde a estes filtros.
admin-failures-signature = Assinatura
admin-failures-count = Contagem
admin-failures-class = Classe
admin-failures-task = Tarefa
admin-failures-last-seen = Visto pela última vez
admin-failures-newer = Mais recentes
admin-failures-page = Página { $current_page_1 }
admin-failures-older = Mais antigas
admin-failures-per-page = Por página
admin-failures-loading-instances = A carregar instâncias…
admin-failures-no-instances-for-this-signature = Nenhuma instância para esta assinatura.
admin-failures-node = {" "}nó { $inst_node_index } · { $inst_source } · { $inst_stage } · { $inst_captured_at }
admin-failures-document-errors = Erros de documentos
admin-failures-error-text = Texto do erro
admin-failures-loading-document-errors-u = A carregar erros de documentos…
admin-failures-no-document-errors-match-these = Nenhum erro de documento corresponde a estes filtros.
admin-failures-errors-by-dataset-and-task = Erros por conjunto de dados e tarefa
admin-failures-documents = Documentos
admin-failures-show-only-this-dataset-and = Mostrar apenas este conjunto de dados e esta tarefa
admin-failures-total = Total
admin-failures-errors = Erros
admin-failures-document = Documento
admin-failures-runs = Execuções
admin-failures-error = Erro
admin-failures-dataset-step = Passo do conjunto de dados
admin-failures-previous-page = Página anterior
admin-failures-page-of-1-error = Página { $page } de { $pages }, 1 erro
admin-failures-page-of-errors = Página { $page } de { $pages }, { $data_total } erros
admin-failures-next-page = Página seguinte
admin-feedback-admin-feedback = Administração: comentários
admin-feedback-feedback = Comentários
admin-feedback-search-titles-descriptions-accounts-and = Pesquisar títulos, descrições, contas e endereços
admin-feedback-search = Pesquisar
admin-feedback-loading-reports-u = A carregar relatos…
admin-feedback-1-report-matches = 1 relato corresponde.
admin-feedback-reports-match = { $data_total } relatos correspondem.
admin-feedback-received = Recebido
admin-feedback-type = Tipo
admin-feedback-title = Título
admin-feedback-from = De
admin-feedback-captures = Capturas
admin-feedback-state = Estado
admin-feedback-previous-page = Página anterior
admin-feedback-page-of = Página { $page } de { $pages }
admin-feedback-next-page = Página seguinte
admin-feedback-image = Imagem { $kb_row_screenshot_bytes }
admin-feedback-dom = DOM { $kb_row_dom_bytes }
admin-feedback-read = Lido
admin-feedback-unread = Não lido
admin-feedback-archived = Arquivado
admin-feedback-mark-unread = Marcar como não lido
admin-feedback-mark-read = Marcar como lido
admin-feedback-restore = Restaurar
admin-feedback-archive = Arquivar
admin-feedback-page = Página:{" "}
admin-feedback-the-report-has-no-description = O relato não tem descrição.
admin-feedback-open-the-page-image = Abrir a imagem da página
admin-feedback-open-the-dom-copy = Abrir a cópia do DOM
admin-feedback-page-image-of-the-report = Imagem da página do relato
admin-feedback-debug-context-and-browser-log = Contexto de depuração e registo do navegador
admin-feedback-loading-u = A carregar…
admin-group-detail-admin-group = Administração: grupo { $groupname }
admin-group-detail-failed-to-load-group = Não foi possível carregar o grupo
admin-group-detail-loading = A carregar...
admin-group-detail-group = Grupo
admin-group-detail-display-name = Nome de apresentação
admin-group-detail-display-name-2 = nome de apresentação
admin-group-detail-save = Guardar
admin-group-detail-members = Membros
admin-group-detail-saving-membership = A guardar a adesão...
admin-group-detail-username = Nome de utilizador
admin-group-detail-origin = Origem
admin-group-detail-group-admin = Administrador do grupo
admin-group-detail-uploader = Pode carregar
admin-group-detail-remove = Remover
admin-group-detail-username-to-add = nome de utilizador a adicionar
admin-group-detail-add-member = Adicionar membro
admin-group-detail-collection-access = Acesso às coleções
admin-group-detail-this-group-has-no-collection = Este grupo não tem permissões sobre coleções.
admin-group-detail-revoke = Revogar
admin-group-detail-grant-collection-u = Conceder coleção…
admin-group-detail-grant = Conceder
admin-group-detail-danger-zone = Zona de perigo
admin-group-detail-delete-group = Eliminar grupo
admin-groups-list-admin-groups = Administração: grupos
admin-groups-list-groups = Grupos
admin-groups-list-add-group = Adicionar grupo
admin-groups-list-display-name = nome de apresentação
admin-groups-list-use-lowercase-letters-digits-underscores = Utilize letras minúsculas, algarismos, carateres de sublinhado e hífenes no nome. O nome não pode ser alterado depois.
admin-groups-list-add-group-2 = Adicionar grupo +
admin-groups-list-group = Grupo
admin-groups-list-display-name-2 = Nome de apresentação
admin-groups-list-members = Membros
admin-groups-list-collections = Coleções
admin-groups-list-loading = A carregar...
admin-llm-config-admin-llm = Administração: LLM
admin-llm-config-llm = LLM
admin-llm-config-loading-u = A carregar…
admin-llm-config-no-llm-provider-is-configured = Nenhum fornecedor de LLM está configurado. Defina LLM_BASE_URL / LLM_MODEL em hoover4.ini e volte a implantar.
admin-llm-config-providers = Fornecedores
admin-llm-config-the-refresh-runs-in-the = A atualização decorre em segundo plano. Entretanto, a lista atual continua visível.
admin-llm-config-refresh-in-flight-u = {" "}Atualização em curso…
admin-llm-config-provider = Fornecedor
admin-llm-config-models = Modelos
admin-llm-config-freshest = Mais recente
admin-llm-config-status = Estado
admin-llm-config-refresh-catalog = Atualizar catálogo
admin-llm-config-agent-turns-board-assessments-and = Turnos do agente, avaliações de quadros e conversões de relatórios
admin-llm-config-titles-summaries-and-board-labels = Títulos, resumos e etiquetas de quadros
admin-llm-config-hoover4-ini-sets-these-models = hoover4.ini define estes modelos: o quality_model do fornecedor de LLM para os turnos do agente, as avaliações de quadros e as conversões de relatórios, quando está definido, e o seu modelo para o resto.
admin-llm-config-thinking = Raciocínio
admin-llm-config-the-model-reasons-before-each = O modelo raciocina antes de cada chamada de ferramenta e de cada resposta.
admin-llm-config-catalog = Catálogo
admin-llm-config-filter-models-u = Filtrar modelos…
admin-llm-config-model = Modelo
admin-llm-config-flags = Indicadores
admin-llm-config-calls-14d = Chamadas 14 d
admin-llm-config-ai-status = Estado da IA
admin-llm-config-shows-the-serving-health = {" "}mostra o estado de funcionamento do serviço.
admin-llm-reports-reports = Relatórios
admin-llm-reports-each-report-runs-when-you = Cada relatório é executado quando seleciona o seu botão.
admin-llm-reports-running-u = Em execução…
admin-llm-reports-run-report = Executar relatório
admin-llm-reports-read-at = Lido em { $read_at }
admin-llm-reports-errors = Erros
admin-llm-reports-failed-attempts-by-step-and = Tentativas falhadas por passo e classe de erro, e execuções do agente que falharam ou terminaram antes do tempo, por motivo de fim.
admin-llm-reports-source = Origem
admin-llm-reports-class = Classe
admin-llm-reports-no-errors-in-30-days = Sem erros em 30 dias.
admin-llm-reports-recent-errors = Erros recentes
admin-llm-reports-the-newest-100-failed-attempts = As 100 tentativas falhadas mais recentes de 7 dias. Abra uma linha para ler o seu erro.
admin-llm-reports-time = Hora
admin-llm-reports-user = Utilizador
admin-llm-reports-name = Nome
admin-llm-reports-error = Erro
admin-llm-reports-no-errors-in-7-days = Sem erros em 7 dias.
admin-llm-reports-show = Mostrar
admin-llm-reports-tool-calls = Chamadas de ferramentas
admin-llm-reports-one-row-for-each-tool = Uma linha por ferramenta, por chamadas em 30 dias. Um erro é uma chamada falhada.
admin-llm-reports-tool = Ferramenta
admin-llm-reports-calls-24-h = Chamadas 24 h
admin-llm-reports-error-24-h = Erro % 24 h
admin-llm-reports-avg-ms-24-h = Média ms 24 h
admin-llm-reports-calls-7-d = Chamadas 7 d
admin-llm-reports-error-7-d = Erro % 7 d
admin-llm-reports-avg-ms-7-d = Média ms 7 d
admin-llm-reports-calls-30-d = Chamadas 30 d
admin-llm-reports-error-30-d = Erro % 30 d
admin-llm-reports-avg-ms-30-d = Média ms 30 d
admin-llm-reports-no-tool-calls-in-30 = Sem chamadas de ferramentas em 30 dias.
admin-llm-reports-top-users = Principais utilizadores
admin-llm-reports-the-30-users-with-the = Os 30 utilizadores com mais tempo de modelo na janela.
admin-llm-reports-30-days = 30 dias
admin-llm-reports-7-days = 7 dias
admin-llm-reports-24-hours = 24 horas
admin-llm-reports-tool-time = Tempo de ferramentas
admin-llm-reports-model-calls = Chamadas ao modelo
admin-llm-reports-model-time = Tempo do modelo
admin-llm-reports-tokens-in = Tokens de entrada
admin-llm-reports-tokens-out = Tokens de saída
admin-llm-reports-no-agent-use-in-the = Sem utilização do agente na janela.
admin-llm-reports-system-one-checks = Verificações System one
admin-llm-reports-requests-are-grouped-by-hook = Os pedidos são agrupados por gancho e regra. As latências estão em milissegundos. As percentagens usam os pedidos dos últimos 30 dias.
admin-llm-reports-counts = Contagens
admin-llm-reports-recent-failures = Falhas recentes
admin-llm-reports-select-run-report-to-read = Selecione Executar relatório para ler as estatísticas.
admin-llm-reports-hook = Gancho
admin-llm-reports-rule = Regra
admin-llm-reports-outcome = Resultado
admin-llm-reports-questions = Perguntas
admin-llm-reports-median-ms = Mediana ms
admin-llm-reports-95th-percentile-ms = Percentil 95 ms
admin-llm-reports-error-2 = Erro %
admin-llm-reports-positive = Positivo %
admin-llm-reports-actions = Ações
admin-metrics-admin-metrics = Administração: métricas
admin-metrics-metrics = Métricas
admin-metrics-the-last-24-hours = As últimas 24 horas.
admin-metrics-loading-u = A carregar…
admin-metrics-manticore-load-now = Carga do Manticore (agora)
admin-metrics-ram-is-the-memory-of = A RAM é a memória das tabelas. A carga de threads refere-se aos últimos 1, 5 e 15 minutos.
admin-metrics-manticore-status-could-not-be = Não foi possível ler o estado do Manticore: { $error }
admin-metrics-thread-load-1-5-15 = Carga de threads (1, 5, 15 min)
admin-metrics-primary-thread-load-1-5 = Carga de threads primários (1, 5, 15 min)
admin-metrics-secondary-thread-load-1-5 = Carga de threads secundários (1, 5, 15 min)
admin-metrics-worker-threads-busy-total = Threads de trabalho ocupados / total
admin-metrics-work-queue = Fila de trabalho
admin-metrics-ram-held-by-tables = RAM ocupada pelas tabelas
admin-metrics-disk-used-by-tables = Disco usado pelas tabelas
admin-metrics-tables-merging = Tabelas em fusão
admin-metrics-tables-read = Tabelas lidas
admin-metrics-read-at = Lido em
admin-metrics-largest-tables-by-ram = Maiores tabelas por RAM
admin-metrics-table = Tabela
admin-metrics-ram = RAM
admin-metrics-disk = Disco
admin-metrics-disk-chunks = Blocos em disco
admin-metrics-merging = Em fusão
admin-metrics-usage-last-24-h = Utilização (últimas 24 h)
admin-metrics-events-by-type = Eventos por tipo
admin-metrics-event = Evento
admin-metrics-count = Contagem
admin-metrics-events-per-hour = Eventos por hora
admin-metrics-no-events-recorded-yet = Ainda não há eventos registados.
admin-metrics-busiest-users = Utilizadores mais ativos
admin-metrics-user = Utilizador
admin-metrics-events = Eventos
admin-metrics-events-2 = { $point_bucket }: { $point_count } eventos
admin-metrics-utc = UTC
admin-metrics-api-calls-last-24-h = Chamadas à API (últimas 24 h)
admin-metrics-no-api-calls-recorded-yet = Ainda não há chamadas à API registadas.
admin-metrics-function = Função
admin-metrics-calls = Chamadas
admin-metrics-errors = Erros
admin-metrics-error-rate = Taxa de erro
admin-metrics-bytes-in = Bytes de entrada
admin-metrics-bytes-out = Bytes de saída
admin-operation-detail-admin-operation = Administração: operação { $op_id }
admin-operation-detail-loading-operation = A carregar a operação…
admin-operation-detail-back-to-operations = Voltar às operações
admin-operation-detail-operation = Operação
admin-operation-detail-queued-at = { $row_kind } · { $row_state } · { $row_target } · em fila desde { $row_started_at }
admin-operation-detail-not-started = não iniciada
admin-operation-detail-re-run-counts-are-not = As contagens da nova execução não estão disponíveis.
admin-operation-detail-failed-document-s-task-failure = { $documents } documento(s) falhado(s), { $row_failed_tasks_unwrap_or_0 } falha(s) de tarefa
admin-operation-detail-failures-were-not-counted = As falhas não foram contadas.
admin-operation-detail-open-captured-failure-tree = Abrir a árvore de falhas capturada
admin-operation-detail-open-in-temporal = Abrir no Temporal
admin-operation-detail-plans = Planos
admin-operation-detail-plan-s-page = { $data_plans_total } plano(s), página { $page_1 }
admin-operation-detail-no-plans-were-recorded-for = Não foram registados planos para esta operação.
admin-operation-detail-dataset = Conjunto de dados
admin-operation-detail-plan-hash = Hash do plano
admin-operation-detail-source = Fonte
admin-operation-detail-finished = Concluído
admin-operation-detail-previous = Anterior
admin-operation-detail-next = Seguinte
admin-operation-detail-error-events = Eventos de erro
admin-operation-detail-error-event-s-page = { $data_events_total } evento(s) de erro, página { $page_1 }
admin-operation-detail-no-error-events-were-recorded = Não foram registados eventos de erro para esta operação.
admin-operation-detail-time = Hora
admin-operation-detail-hash = Hash
admin-operation-detail-task = Tarefa
admin-operation-detail-event = Evento
admin-operation-detail-error-excerpt = Excerto do erro
admin-operations-admin-operations = Administração: operações
admin-operations-operations = Operações
admin-operations-loading-operations = A carregar operações…
admin-operations-filters = Filtros
admin-operations-state = Estado
admin-operations-any-state = Qualquer estado
admin-operations-collection = Coleção
admin-operations-all-collections = Todas as coleções
admin-operations-choose-a-collection-to-see = Escolha uma coleção para ver as taxas de erro por tarefa.
admin-operations-operations-newest-first = Operações, as mais recentes primeiro
admin-operations-newer = Mais recentes
admin-operations-page = Página { $current_page_1 }
admin-operations-older = Mais antigas
admin-operations-failure-rate-by-task-type = Taxa de falhas por tipo de tarefa ({ $collectionname })
admin-operations-one-row-per-activity-execution = Uma linha por execução de atividade, incluindo as repetições. Uma taxa acima de{" "}
admin-operations-is-marked = {" "}é assinalada.
admin-operations-no-task-executions-recorded-for = Ainda não há execuções de tarefas registadas para esta coleção.
admin-operations-task = Tarefa
admin-operations-error-rate = Taxa de erro
admin-operations-failed-total-executions = Execuções falhadas / total
admin-operations-documents-affected = Documentos afetados
admin-operations-above-the-line = acima do limite
admin-operations-no-operations-recorded-for-this = Nenhuma operação registada para este filtro.
admin-operations-kind = Tipo
admin-operations-target = Alvo
admin-operations-workflow = Fluxo de trabalho
admin-operations-queued-at = Em fila desde
admin-operations-started = Iniciada
admin-operations-duration = Duração
admin-operations-progress = Progresso
admin-operations-eta = Previsão
admin-operations-outcome = Resultado
admin-operations-destructive = Destrutiva
admin-operations-repeated-run = Execução repetida
admin-operations-no-estimate-yet = ainda sem estimativa
admin-operations-cancel = Cancelar
admin-operations-type-to-confirm = escreva { $target } para confirmar
admin-operations-re-run = Executar novamente
admin-operations-waiting-for-a-free-slot = a aguardar uma vaga livre ou um alvo livre
admin-operations-counting-work = a contar o trabalho…
admin-operations-open-captured-tree = Abrir a árvore capturada
admin-operations-no-captured-tree = sem árvore capturada
admin-operations-no-failed-documents = nenhum documento falhado
admin-operations-document-s-failed = { $n } documento(s) falhado(s)
admin-operations-task-failure-s = { $t } falha(s) de tarefa
admin-operations-failures-not-counted = falhas não contadas
admin-operations-the-newest-ten-operations-of = As dez operações mais recentes desta coleção.{" "}
admin-operations-all-operations = Todas as operações
admin-settings-admin-settings = Administração: definições
admin-settings-server-settings = Definições do servidor
admin-settings-key = Chave
admin-settings-value = Valor
admin-settings-description = Descrição
admin-settings-save = Guardar
admin-settings-loading = A carregar...
admin-settings-deployment-configuration-read-only = Configuração da implantação (só de leitura)
admin-settings-not-set = (não definido)
admin-user-detail-admin-user = Administração: utilizador { $username }
admin-user-detail-failed-to-load-user = Não foi possível carregar o utilizador
admin-user-detail-loading = A carregar...
admin-user-detail-user = Utilizador
admin-user-detail-the-next-login-replaces-the = O próximo início de sessão substitui o nome completo, o correio eletrónico e o estado de superutilizador de um utilizador vindo do proxy de início de sessão.
admin-user-detail-llm-usage-u = Utilização do LLM →
admin-user-detail-full-name = Nome completo
admin-user-detail-full-name-2 = nome completo
admin-user-detail-email = Correio eletrónico
admin-user-detail-superuser = Superutilizador
admin-user-detail-save = Guardar
admin-user-detail-groups = Grupos
admin-user-detail-saving-membership = A guardar a adesão...
admin-user-detail-group = Grupo
admin-user-detail-origin = Origem
admin-user-detail-group-admin = Administrador do grupo
admin-user-detail-uploader = Pode carregar
admin-user-detail-remove = Remover
admin-user-detail-add-to-group-u = Adicionar ao grupo…
admin-user-detail-add = Adicionar
admin-user-detail-danger-zone = Zona de perigo
admin-user-detail-delete-user = Eliminar utilizador
admin-user-llm-admin-llm-use-by = Administração: utilização do LLM por { $username }
admin-user-llm-u-back-to-user = ← Voltar ao utilizador
admin-user-llm-loading-u = A carregar…
admin-user-llm-totals-all-time = Totais (desde sempre)
admin-user-llm-chat-sessions = Sessões de conversa
admin-user-llm-messages = Mensagens
admin-user-llm-tool-calls = Chamadas de ferramentas
admin-user-llm-model-and-tool-time = Tempo de modelo e de ferramentas
admin-user-llm-model-and-tool-time-of = tempo de modelo e de ferramentas dos passos do agente deste utilizador. As chamadas de ferramentas em paralelo contam por inteiro
admin-user-llm-rate-limit-usage-current-windows = Utilização dos limites de taxa (janelas atuais)
admin-user-llm-in-process-counters-of-the = Contadores em processo do contentor do sítio web em execução. Limite de conversas { $metrics_chat_per_minute }/min, limite de API { $metrics_api_per_minute }/min, com uma taxa sustentada decrescente nas janelas mais longas.
admin-user-llm-chat-messages = Mensagens de conversa
admin-user-llm-api-calls = Chamadas à API
admin-user-llm-window = Janela
admin-user-llm-used = Usado
admin-user-llm-budget = Orçamento
admin-user-llm-no-chat-sessions = Sem sessões de conversa.
admin-user-llm-title = Título
admin-user-llm-created = Criado
admin-users-list-admin-users = Administração: utilizadores
admin-users-list-users = Utilizadores
admin-users-list-search-users = Pesquisar utilizadores
admin-users-list-username = Nome de utilizador
admin-users-list-full-name = Nome completo
admin-users-list-email-address = Endereço de correio eletrónico
admin-users-list-superuser = Superutilizador
admin-users-list-groups = Grupos
admin-users-list-created = Criado
admin-users-list-last-login = Último início de sessão
admin-users-list-loading = A carregar...
dataset-create-panel-put-the-documents-in-a = Coloque os documentos numa pasta aí e recarregue esta página.
dataset-create-panel-the-name-cannot-start-with = O nome não pode começar por um ponto nem conter uma barra.
dataset-create-panel-and-a-dash-a-space = e um hífen, um espaço ou um ponto passa a ser um sublinhado. O nome não pode ser alterado depois.
live-chats-panel-off = desativado
processing-updates-panel-the-waiting-steps-change-each = Os passos em espera alteram { $view_unique_files } { $unique_unit } ({ $format_size_view_unique_bytes }), cada ficheiro contado uma vez, em { $view_executions } { $runs_word }.
admin-collections-list-and-a-dash-a-space = e um hífen, um espaço ou um ponto passa a ser um sublinhado. O nome não pode ser alterado depois.
admin-llm-config-fresh = atual
admin-llm-config-tools = ferramentas{" "}
admin-llm-config-vision = visão{" "}
admin-metrics-ms = { $f_p50_ms } ms
admin-metrics-ms-2 = { $f_p95_ms } ms
dataset-create-panel-read-only = { $option_name } (só de leitura)
live-chats-panel-on = ativado
processing-updates-panel-up-to-date-select-it = Atualizado. Selecione-o para o executar novamente.
admin-ai-status-yes = sim
admin-ai-status-no-2 = não
admin-ai-status-ms = { $t_median_latency_ms } ms
admin-collection-processing-errors-2 = { $ds_error_count } erros
admin-collection-processing-done = concluído
admin-collection-processing-failed-2 = { $stage_failed_documents } falharam
admin-collection-processing-left = em falta
admin-collection-processing-dataset-level = ao nível do conjunto de dados
admin-collections-list-groups = { $c_group_count } grupos
admin-failures-operation-s = { $group_operation_count } operação(ões)
admin-groups-list-groupname = nome do grupo
admin-llm-config-stale = desatualizado
admin-llm-config-thinking-is-on = O raciocínio está ativado
admin-llm-config-thinking-is-off = O raciocínio está desativado
admin-llm-config-shown = { $models_len } apresentados
admin-llm-config-reasoning = raciocínio
admin-llm-config-ms = { $m_median_latency_ms } ms
admin-metrics-of = { $load_table_count_load_unread_tables } de { $load_table_count }
admin-metrics-yes = sim
admin-metrics-no = não
admin-metrics-max = máx.
admin-metrics-ms-3 = { $f_max_ms } ms
admin-operation-detail-started = iniciada em { $run_started_at }
admin-operation-detail-yes = sim
admin-operation-detail-no = não
admin-operations-temporal = (Temporal)
admin-user-detail-email-2 = correio eletrónico
admin-user-llm-untitled = (sem título)
admin-dataset-ocr-panel-variant-pages = { $source } · { $pages } páginas
admin-processing-updates-panel-prerequisites-waiting = A coleção precisa primeiro de uma atualização: { $steps }. Os passos que escrevem no índice de pesquisa aguardam por ela.
admin-operations-no-task-type-failing = Nenhum tipo de tarefa falha acima de { $threshold }%.
admin-operations-task-types-failing = { $count } tipo(s) de tarefa a falhar acima de { $threshold }%.
processing-updates-panel-collection-updates = Atualizações da coleção
admin-collections-list-some-datasets-are-not-counted = Alguns conjuntos de dados ainda não foram contados.
admin-failures-hide = Ocultar
admin-failures-show = Mostrar
admin-settings-web-session-lifetime-in-seconds = Duração da sessão web em segundos (predefinição: 604800 = 1 semana)
admin-settings-turns-every-new-chat-turn = Desativa todos os novos turnos de conversa quando é false (predefinição: true). Um turno em curso termina. Tem efeito no próximo envio, sem nova implantação.
admin-settings-written-by-main-py-probe = Escrito por `main.py probe-embeddings`, e é o que o ponto de acesso REALMENTE serve. Editá-lo à mão não altera o servidor.
admin-settings-the-folder-whose-subfolders-the = A pasta cujas subpastas o formulário de conjuntos de dados lista. Alterá-la exige uma nova implantação.
admin-settings-from-hoover4-ini-changing-it = Vem de hoover4.ini. Alterá-lo exige uma nova implantação.
admin-feedback-bug = Erro
admin-operations-state-name = { $state ->
        [pending] pendente
        [queued] em fila
        [running] em execução
        [finished] concluída
        [errored] com erro
        [cancelled] cancelada
       *[other] { $state }
    }
admin-failure-detail-failure-tree-of = Árvore de falhas de { $op_id }
admin-failure-detail-showing-of-characters = a mostrar { $node_stack_trace_chars_count } de { $node_stack_trace_original_len } carateres
admin-operations-operation = Operação { $state }.
admin-operations-dispatched = Despachada { $new_id }.
admin-operations-rows = { $row_progress_done } / { $row_progress_total } linhas
admin-operations-plans = { $row_progress_done } / { $row_progress_total } planos
admin-group-detail-group-2 = Grupo { $groupname }
admin-settings-the-setting-was-saved-successfully = A definição “{ $k }” foi guardada com sucesso.
admin-metrics-kib = { $b_as_f64_1024_0 } KiB
admin-metrics-mib = { $b_as_f64_1024_0_1024_0 } MiB
admin-metrics-gib = { $b_as_f64_1024_0_1024_0_1024_0 } GiB
admin-llm-reports-utc = { $year }-{ $month }-{ $day } { $rem_3600 }:{ $rem_3600_60 }:{ $rem_60 } UTC
admin-groups-list-the-group-was-added-successfully = O grupo “{ $g }” foi adicionado com sucesso.
admin-user-detail-user-2 = Utilizador { $username }
admin-dataset-detail-dataset = Conjunto de dados { $dataset_id }
admin-dataset-detail-collections = Coleções › { $collection_id }
admin-dataset-detail-of = { $detail_stats_plans_finished } de { $detail_stats_plans_total }
admin-dataset-detail-the-upload-setting-could-not = Não foi possível ler a definição de carregamento: { $err }
admin-dataset-detail-operation-started = Operação iniciada: { $run_id }
admin-collection-detail-collection = Coleção { $collection_id }
admin-collection-detail-the-vectors-setting-could-not = Não foi possível ler a definição de vetores: { $err }
admin-collection-processing-processing-of = Processamento de { $collection_id }
admin-collection-processing-collections = Coleções › { $collection_id }
admin-collection-processing-executions-2 = { $b_total_executions } execuções
admin-collection-processing-ms = { $row_mean_ms } ms
admin-collection-processing-ms-2 = { $row_p95_ms } ms
admin-collection-processing-ms-2-2 = { $row_max_ms } ms
admin-collection-processing-as-of = a { $at }
admin-collection-processing-over-the-last-s = nos últimos { $live_window_seconds } s
admin-collection-processing-retry-started-run = Nova tentativa iniciada (execução { $run }).
admin-collection-processing-document-retry-started-run = Nova tentativa do documento iniciada (execução { $run }).
admin-operation-detail-operation-2 = Operação { $op_id }
admin-user-llm-llm-usage-of = Utilização do LLM de { $username }
admin-user-llm-users = Utilizadores › { $username }
processing-updates-panel-the-processing-updates-could-not = Não foi possível ler as atualizações do processamento: { $e }
processing-updates-panel-update-started = Atualização iniciada: { $op_id }
dataset-ocr-panel-of-plans = { $operation_progress_done } de { $operation_progress_total } planos
dataset-ocr-panel-adding = a adicionar { $added }
dataset-ocr-panel-removing = a remover { $removed }
dataset-ocr-panel-plan-s-reopened = { $plans } plano(s) reaberto(s)
processing-updates-unit = { $unit ->
    [folders] { $count ->
        [one] pasta
       *[other] pastas
    }
    [tables] { $count ->
        [one] tabela
       *[other] tabelas
    }
   *[files] { $count ->
        [one] ficheiro
       *[other] ficheiros
    }
}
processing-updates-step-runs = { $count ->
    [one] execução do passo
   *[other] execuções do passo
}
processing-update-search_schema-title = Esquema do índice de pesquisa
processing-update-search_schema-explanation = { $files ->
    [one] { $count } tabela de pesquisa da coleção não tem uma coluna de que o índice de pesquisa precisa.
   *[other] { $count } tabelas de pesquisa da coleção não têm uma coluna de que o índice de pesquisa precisa.
} A coluna é adicionada a cada tabela. A pesquisa continua a funcionar.
processing-update-search_schema-runs = Tabelas do índice de pesquisa
processing-update-unfinished-title = Processamento inacabado
processing-update-unfinished-explanation = { $files ->
    [one] { $count } ficheiro não foi processado até ao fim.
   *[other] { $count } ficheiros não foram processados até ao fim.
} Isto inclui ficheiros sem plano de processamento, por exemplo após uma ingestão interrompida. O processamento deles é concluído.
processing-update-unfinished-runs = Todas as fases de processamento destes ficheiros
processing-update-failed_files-title = Ficheiros falhados
processing-update-failed_files-explanation = { $files ->
    [one] { $count } ficheiro tem um erro de processamento.
   *[other] { $count } ficheiros têm um erro de processamento.
} As fases falhadas são executadas novamente para eles. A execução automática repete um ficheiro uma vez por cada nova versão da fase que falhou.
processing-update-failed_files-runs = As fases falhadas, depois a extração de entidades, a incorporação e a indexação
processing-update-virus_scan-title = Verificação de vírus
processing-update-virus_scan-explanation = { $files ->
    [one] { $count } ficheiro não tem veredicto do antivírus.
   *[other] { $count } ficheiros não têm veredicto do antivírus.
} São verificados. Um ficheiro que o verificador considere infetado é assinalado na pesquisa, e as transferências do seu original e do seu PDF pesquisável são recusadas.
processing-update-virus_scan-runs = Verificação antivírus, depois o atributo de pesquisa dos ficheiros infetados
processing-update-tables-title = Tabelas
processing-update-tables-explanation = { $files ->
    [one] { $count } ficheiro tem uma leitura de tabela anterior ou resultados dependentes incompletos. Os resultados guardados são atualizados.
    *[other] { $count } ficheiros têm leituras de tabelas anteriores ou resultados dependentes incompletos. Os resultados guardados são atualizados.
    }

processing-update-tables-runs = Leitura de tabelas, entidades, sinais, vetores e ambos os índices
processing-update-ocr-title = OCR
processing-update-ocr-explanation = Ficheiros que precisam de OCR automático: { $count }. O texto OCR anterior no idioma detetado é mantido sem novo OCR. As outras páginas recebem OCR com o modelo instalado do idioma detetado. As variantes anteriores são removidas quando a substituição está completa.
processing-update-ocr-runs = OCR e PDF pesquisáveis, depois a extração de entidades, a incorporação e a indexação do texto novo
processing-update-ocr_detection-title = Deteção de OCR
processing-update-ocr_detection-explanation = Ficheiros sem deteção atual de texto, escrita ou idioma: { $count }. Cada imagem e página PDF elegível é examinada em lotes limitados.
processing-update-ocr_detection-runs = Deteção, depois os atributos de pesquisa destes ficheiros
processing-update-pdf_text-title = Texto dos PDF pesquisáveis
processing-update-pdf_text-explanation = { $files ->
    [one] { $count } ficheiro tem PDF pesquisáveis com uma camada de texto anterior.
   *[other] { $count } ficheiros têm PDF pesquisáveis com uma camada de texto anterior.
} Essa camada copiava cada letra fora dos alfabetos da Europa Ocidental como um quadrado preto. Os PDF de línguas que só têm letras da Europa Ocidental mantêm-se. Os outros PDF são lidos, e as partes com quadrados pretos são criadas de novo. Um PDF de imagem usa as palavras de OCR guardadas. Uma página de PDF recebe um novo pedido de OCR.
processing-update-pdf_text-runs = Partes dos PDF pesquisáveis, depois a indexação do texto OCR dos PDF recriados
processing-update-page_text-title = Texto indexado das páginas
processing-update-page_text-explanation = Ficheiros com texto de pesquisa incompleto: { $count }. Um carácter de controlo numa página terminou o texto indexado. O texto completo é indexado.
processing-update-page_text-runs = Texto do índice de pesquisa destas páginas
processing-update-text_rows-title = Divisão do texto
processing-update-text_rows-explanation = Ficheiros com texto de uma divisão anterior: { $count }. O texto dos PDF passa para uma linha por cada parte do PDF, e o texto longo é cortado com uma sobreposição curta. Não corre novo OCR nem nova análise.
processing-update-text_rows-runs = Divisão do texto, depois a extração de entidades, a incorporação e a indexação do texto novo
processing-update-vectors-title = Vetores
processing-update-vectors-explanation = { $files ->
    [one] { $count } ficheiro com texto não tem vetores do modelo de incorporação que a instalação serve.
   *[other] { $count } ficheiros com texto não têm vetores do modelo de incorporação que a instalação serve.
} Os seus vetores são calculados e indexados.
processing-update-vectors-runs = Incorporação e indexação de vetores
processing-update-folder_counts-title = Contagens de pastas
processing-update-folder_counts-explanation = { $files ->
    [one] { $count } pasta não tem contagem de ficheiros nem tamanho, ou tem valores de uma versão anterior.
   *[other] { $count } pastas não têm contagem de ficheiros nem tamanho, ou têm valores de uma versão anterior.
} As contagens são calculadas novamente.
processing-update-folder_counts-runs = Árvore de pastas
admin-uploads-badge = Carregamentos
admin-uploads-badge-title = Aceita carregamentos

processing-update-archive_members-title = Membros dos arquivos

processing-update-archive_members-explanation = { $files ->
    [one] { $count } arquivo dividido precisa de uma lista atual de membros. Os membros e os resultados da pesquisa são atualizados.
    *[other] { $count } arquivos divididos precisam de listas atuais de membros. Os membros e os resultados da pesquisa são atualizados.
    }

processing-update-archive_members-runs = Extração de arquivos, reconciliação de membros e processamento dependente

processing-update-image_previews-title = Pré-visualizações de imagens

processing-update-image_previews-explanation = { $files ->
    [one] { $count } imagem de formato pouco comum não tem pré-visualização. A pré-visualização é criada novamente.
    *[other] { $count } imagens de formatos pouco comuns não têm pré-visualização. As pré-visualizações são criadas novamente.
    }

processing-update-image_previews-runs = Criação e verificação de pré-visualizações de imagens

processing-update-search_terms-title = Termos de pesquisa

processing-update-search_terms-explanation = { $files ->
    [one] { $count } tabela de pesquisa precisa de termos de filtro atuais. Os termos de idioma, OCR, escrita e sinais de alerta tornam-se pesquisáveis.
    *[other] Tabelas de pesquisa que precisam de termos de filtro atuais: { $count }. Os termos de idioma, OCR, escrita e sinais de alerta tornam-se pesquisáveis.
    }

processing-update-search_terms-runs = Indexação e verificação dos termos de filtro

automatic-ocr-title = OCR automático
automatic-ocr-refresh = Atualizar estado
automatic-ocr-coverage = Cobertura das páginas
automatic-ocr-pages = Páginas
automatic-ocr-models = Modelos de OCR
automatic-ocr-reason = Motivo
automatic-ocr-truncated = A lista de diagnóstico está incompleta.
automatic-ocr-presence = Tem texto OCR publicado
automatic-ocr-policy = O OCR seleciona modelos instalados pela escrita e pelo idioma detetados de cada página elegível. O Tesseract é usado primeiro, com EasyOCR para escritas não cobertas.
automatic-ocr-unknown = Não existe publicação atual registada. A deteção em falta e o processamento falhado não comprovam ausência.
automatic-ocr-retry = Use atualizações de processamento para repetir trabalho incompleto ou falhado após corrigir a causa. A cobertura não suportada exige modelos instalados compatíveis.
automatic-ocr-state = { $state ->
    [candidate] Pendente
    [planned] Planeado
    [failed] Falhou
    [incomplete] Incompleto
    [unsupported] Não suportado
    [published] Publicado
    [applied] Verificado
    [ready] Texto detetado
    [no_text] Sem texto detetado
    *[other] { $state }
    }

processing-update-entities-title = Entidades nomeadas
processing-update-entities-explanation = Ficheiros que precisam de extração de entidades ou resultados pesquisáveis atuais: { $count }. Os resultados anteriores são substituídos após a inferência.
processing-update-entities-runs = Extração de entidades nomeadas, atributos de texto e termos de entidades pesquisáveis

automatic-ocr-reason-label = { $reason ->
    [unknown_script] Escrita não identificada
    [tesseract_capabilities_unavailable] Cobertura do Tesseract indisponível
    [detected_language] O modelo corresponde ao idioma detetado
    [unknown_language_script_coverage] Idioma desconhecido. Foi selecionado um modelo de escrita.
    [language_script_mismatch_script_coverage] O idioma e a escrita diferem. Foi selecionado um modelo de escrita.
    [language_model_unavailable_script_coverage] Modelo de idioma indisponível. Foi selecionado um modelo de escrita.
    [easyocr_capabilities_unavailable] Cobertura do EasyOCR indisponível
    [tesseract_script_unavailable] O Tesseract não cobre a escrita. Foi selecionado EasyOCR.
    [script_coverage_unavailable] Nenhum modelo instalado cobre esta escrita.
    *[other] { $reason }
    }

processing-updates-check-requested = O sistema está a calcular as atualizações. As contagens mudam quando o cálculo termina.
