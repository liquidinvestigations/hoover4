# Translation of en/notes.ftl. Change it together with the English catalog.

# As notas que o worker escreve numa execução, e o texto de um turno que o worker termina.
# O modelo lê cada nota. A transcrição mostra as notas e o fim à pessoa.
# O worker lê apenas texto simples e variáveis { $name } (`tasks.P_agent.notes`).

## Descoberta

note-discovery-l2 = As duas últimas pesquisas não encontraram nenhuma fonte nova. Lê agora as melhores páginas de resultados: coloca até 6 dos seus URL numa única chamada de read_page, na lista `urls`. Volta a pesquisar apenas com uma pergunta diferente.
note-discovery-l3-web = Respondeste antes de ler qualquer página de fonte. Chama read_page uma vez com os URL das páginas que sustentam os teus itens, até 6 na lista `urls`. Depois escreve a resposta de novo com as fontes que a sustentam.
note-discovery-l3-documents = Respondeste antes de ler qualquer documento. Lê com read_documents os documentos que sustentam os teus itens, vários hashes de ficheiro numa só chamada. Depois escreve a resposta de novo com as fontes que a sustentam.
note-discovery-l4 = Lê agora as páginas de resultados que podem responder ao pedido: coloca até 6 dos seus URL numa única chamada de read_page, na lista `urls`. Uma chamada lê-as todas ao mesmo tempo.

## Capturas de páginas

note-capture-empty = A captura de { $urls } não contém texto de artigo. Lê outra fonte. Não cites esta página.

## Fontes

note-web-tools-absent = Este turno não tem ferramentas web, por isso não pode ler páginas web públicas. Usa as coleções selecionadas e indica que parte do pedido elas não respondem.
note-sources-documents = Pesquisa primeiro as coleções de documentos permitidas. Lê os documentos relevantes.
note-sources-documents-before-web = Pesquisa primeiro as coleções de documentos permitidas. Lê os documentos relevantes. Lê esses documentos antes de usares a web.

## Elementos nomeados

note-absent-collection = Nenhuma coleção permitida se chama { $name }. As coleções permitidas são { $collections }.
note-absent-name = As coleções selecionadas não têm nenhuma correspondência indexada para { $name }.
note-absent-close-forms = Formas próximas indexadas: { $forms }. Não uses uma forma próxima como o nome pedido. Quando pesquisares uma, indica-a na resposta como uma grafia diferente.
note-absent-close-form = { $form } ({ $count } documentos)
note-absent-web = As ferramentas web deste turno podem pesquisar o nome.

## Progresso da pesquisa

note-progress-level = Nível de progresso da pesquisa { $level }.
note-progress-searches = Pesquisas já executadas:
note-progress-search = { $name } { $args }: { $items } itens, { $matches } correspondências de palavras-chave.
note-progress-available = Passos de pesquisa ainda disponíveis:
note-progress-complete = Os passos de pesquisa disponíveis estão concluídos.
note-progress-write-now = Escreve agora a resposta ou o relatório. Indica o que as fontes lidas não contêm e nomeia as pesquisas.
note-progress-answer-next = A próxima resposta tem de ser a resposta final. Indica os factos em falta e as pesquisas que executaste.
note-progress-step-quoted = Pesquisa cada nome como expressão entre aspas com search_collections.
note-progress-step-variants = Pesquisa palavras sem aspas e variantes do nome. Lê as contagens de palavras e os candidatos de grafia.
note-progress-step-filters = Remove os filtros um a um e executa uma pesquisa sem filtros.
note-progress-step-facets = Verifica os valores dos filtros com search_facet_values.
note-progress-step-dates = Verifica as datas com search_histogram.
note-progress-step-passages = Pesquisa uma descrição do conteúdo com search_passages.
note-progress-step-folder = Usa { $tool } para a pasta, o caminho ou o ficheiro pedido.
note-progress-step-read-hits = Lê os 1 a 3 melhores resultados com { $tool }.
note-progress-step-web-search = Pesquisa na web com web_search e lê as melhores páginas de resultados.
note-progress-step-page-find = Pesquisa o texto guardado de uma página longa com read_page e find.
note-progress-step-page-retry = Lê outro endereço de resultado, ou a cópia arquivada de uma página que falhou.
note-advice-stuck = Uma verificação da conversa estima que as pesquisas recentes repetem os seus resultados. A competência no_results descreve outras formas de uma pesquisa.
note-advice-absent = Uma verificação da conversa estima que os resultados não contêm o que a tarefa pede. Indica o âmbito pesquisado antes de comunicares uma ausência.
note-advice-completion = Uma verificação da conversa estima que os resultados podem responder à tarefa. Compara cada parte pedida com as fontes que leste antes de responderes.
note-progress-ended = A execução terminou após pesquisas repetidas sem progresso.
note-progress-ended-none = Não foi encontrada nenhuma fonte com correspondência de palavras-chave.
note-progress-ended-some = As pesquisas encontraram { $count } fontes com correspondência de palavras-chave. O agente não concluiu a sua resposta.
note-progress-ended-searches = Pesquisas executadas:
