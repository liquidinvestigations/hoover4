# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l2 = 最近两次搜索没有找到新的来源。现在阅读最相关的结果页面：在一次 read_page 调用中，把其中最多 6 个页面的 URL 放进 `urls` 列表。只有换一个不同的问题时，才再次搜索。
note-discovery-l3-web = 你在没有阅读任何来源页面的情况下就作了回答。用支持你各项内容的页面的 URL 调用一次 read_page，`urls` 列表中最多放 6 个。然后用有依据的来源重新写出回答。
note-discovery-l3-documents = 你在没有阅读任何文档的情况下就作了回答。用 read_documents 阅读支持你各项内容的文档，一次调用中放入多个文件哈希。然后用有依据的来源重新写出回答。
note-discovery-l4 = 现在阅读可能回答该请求的结果页面：在一次 read_page 调用中，把其中最多 6 个页面的 URL 放进 `urls` 列表。一次调用会同时读取所有页面。

## Page captures

note-capture-empty = { $urls } 的抓取内容不含文章正文。请阅读其他来源。不要引用此页面。

## Sources

note-web-tools-absent = 本轮没有网络工具，因此无法读取公开网页。请使用所选的文档集，并说明请求中哪一部分它们无法回答。
note-sources-documents = 先搜索允许访问的文档集，并阅读其中相关的文档。
note-sources-documents-before-web = 先搜索允许访问的文档集，并阅读其中相关的文档。使用网络之前，先读完这些文档。

## Named things

note-absent-collection = 允许访问的文档集中没有名为 { $name } 的文档集。允许访问的文档集有：{ $collections }。
note-absent-name = 所选文档集中，没有与 { $name } 匹配的已索引内容。
note-absent-close-forms = 已索引的相近写法：{ $forms }。不要把相近写法当作所请求的名称。如果你搜索了某个相近写法，请在回答中说明它是另一种拼写。
note-absent-close-form = { $form }（{ $count } 个文档）
note-absent-web = 本轮的网络工具可以搜索这个名称。

## Search progress

note-progress-level = 搜索进度级别 { $level }。
note-progress-searches = 已运行的搜索：
note-progress-search = { $name } { $args }：{ $items } 项，{ $matches } 个关键词匹配。
note-progress-available = 仍可执行的搜索步骤：
note-progress-complete = 可执行的搜索步骤已全部完成。
note-progress-write-now = 现在写出回答或报告。说明所读的来源中没有哪些内容，并列出各次搜索。
note-progress-answer-next = 下一次回复必须是回答。说明缺少的事实和你运行过的搜索。
note-progress-step-quoted = 用 search_collections 把每个名称作为带引号的短语来搜索。
note-progress-step-variants = 搜索不带引号的词和名称变体。查看词频和拼写候选。
note-progress-step-filters = 逐个移除筛选条件，并运行不带筛选条件的搜索。
note-progress-step-facets = 用 search_facet_values 核实筛选条件的值。
note-progress-step-dates = 用 search_histogram 核实日期。
note-progress-step-passages = 用 search_passages 搜索内容描述。
note-progress-step-folder = 对所请求的文件夹、路径或文件使用 { $tool }。
note-progress-step-read-hits = 用 { $tool } 阅读最相关的 1 到 3 个命中结果。
note-progress-step-web-search = 用 web_search 搜索网络，并阅读最相关的结果页面。
note-progress-step-page-find = 用 read_page 和 find 搜索长页面中保留的文本。
note-progress-step-page-retry = 阅读另一个结果地址，或阅读失败页面的存档副本。
note-advice-stuck = 对话检查估计，最近的几次搜索在重复相同的结果。no_results 技能介绍了搜索的其他形式。
note-advice-absent = 对话检查估计，这些结果不包含任务所要求的内容。在报告缺失之前，先说明已搜索的范围。
note-advice-completion = 对话检查估计，这些结果可以回答该任务。回答之前，先把请求的每个部分与你读过的来源逐一对照。
note-progress-ended = 由于多次重复搜索都没有进展，本次运行已结束。
note-progress-ended-none = 没有找到匹配关键词的来源。
note-progress-ended-some = 这些搜索找到了 { $count } 个匹配关键词的来源。智能体没有完成它的回答。
note-progress-ended-searches = 已运行的搜索：
