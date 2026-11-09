# Translation of en/notes.ftl. Change it together with the English catalog.

# As notas que o worker escreve numa execução, e o texto de um turno que o worker termina.
# O modelo lê cada nota. A transcrição mostra as notas e o fim à pessoa.
# O worker lê apenas texto simples e variáveis { $name } (`tasks.P_agent.notes`).

## Descoberta

note-discovery-l4 = Lê agora as páginas de resultados que podem responder ao pedido: coloca até 6 dos seus URL numa única chamada de read_page, na lista `urls`. Uma chamada lê-as todas ao mesmo tempo.

## Capturas de páginas


## Fontes


## Elementos nomeados


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
note-progress-ended = A execução terminou após pesquisas repetidas sem progresso.
note-progress-ended-none = Não foi encontrada nenhuma fonte com correspondência de palavras-chave.
note-progress-ended-some = As pesquisas encontraram { $count } fontes com correspondência de palavras-chave. O agente não concluiu a sua resposta.
note-progress-ended-searches = Pesquisas executadas:
