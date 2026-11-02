# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = 机器人正在处理中…
chat-composer-ask-the-bot = 向机器人提问…
chat-composer-internet-tools = 互联网工具
chat-composer-agent-language-title = 代理以 { $language } 作答。在新标签页的设置中更改语言。
chat-composer-try-again-in-s = { $secs } 秒后重试
chat-composer-stop-the-answer-the-partial = 停止作答（部分内容不会保存到对话中）
chat-composer-starting-the-conversation-u = 正在启动对话…
chat-composer-send = 发送
chat-conversation-find-search-in-conversation = 在对话中搜索
chat-conversation-find-previous-match = 上一个匹配项
chat-conversation-find-next-match = 下一个匹配项
chat-conversation-find-investigation-board = 调查板
doc-ref-card-not-openable = 无法打开：{ $reason }。
doc-ref-card-the-search-term-was = 搜索词为
doc-ref-card-open = 打开
doc-ref-card-not-openable-2 = 无法打开
chat-markdown-text-show-the-cited-source = 显示所引用的来源
chat-markdown-text-no-citation-of-this-conversation = 本对话未给出任何引用，因此该标识没有对应的文档支撑。
chat-markdown-text-citations-of-this-conversation-gave = 本对话的多个引用均指向该标识，因此它不链接到其中任何文档。
cards-browser-card-open-the-archived-page = 打开已存档页面
cards-browser-card-the-page-itself-was-not = 该页面本身未被存档（状态：{ $artifact_status }）。上方截图为所保留的内容。
cards-browser-card-click-the-screenshot-to-open = 点击截图以打开已存档页面。
cards-browser-card-show-less = 显示更少
cards-browser-card-show-all = 显示全部
cards-browser-card-archived-page = 已存档页面
cards-browser-card-download = 下载
cards-browser-card-archived-copy-of = { $artifact_url } 的已存档副本
cards-browser-card-this-page-was-not-archived = 该页面未被存档（状态：{ $artifact_status }）。
cards-entities-card-with-a-card = { $openable }，带有一张卡片
cards-entities-card-the-entity-list-was-cut = 实体列表已被截断。
cards-entities-card-open-the-card-for-this = 打开该值（{ $rule_id }）的卡片
cards-entities-card-no-card-this-conversation-never = 没有卡片：本次对话从未说明这些值来自哪个数据集，而查看者是以数据集身份被称呼的。
cards-entities-card-more-all-of-them-in = { $rest } 个，全部位于文档的实体面板中。{ " " }
cards-entities-card-names-organisations-and-places-above = 上面的名称、组织和地点是模型对正文的解读。没有任何规则对它们进行校验，因此无可解释，点击它们也不会打开任何内容。
cards-entities-card-nothing-extracted-from-this-document = 未从该文档提取任何内容。
chat-tool-cards-hide = 隐藏
chat-tool-cards-expand = 展开
chat-tool-cards-hide-raw-json = 隐藏原始 JSON
chat-tool-cards-show-raw-json = 显示原始 JSON
cards-result-cards-search-this = 搜索此内容
cards-result-cards-search-every-collection = 搜索所有数据集集合
cards-result-cards-form = 表单 { $index }：{ $form }
cards-result-cards-show-full-text = 显示全文
cards-result-cards-quote = 引用：{ $quote }
cards-result-cards-reason = 理由：{ $why }
cards-result-cards-open-question = 待解决问题：{ $question }
cards-result-cards-the-explore-gave-this-answer =
    探索向调查板提供了如下 { $kind ->
        [sourced] 有来源的
        [inferred] 推断出的
        [not_found] 未找到的
       *[other] 未知类型的
    } 发现。
cards-result-cards-it-left-no-open-question = 未留下任何待解决问题。
cards-result-cards-open-questions-for-the-board = 留给调查板的待解决问题：
cards-result-cards-arguments = 论证
cards-result-cards-list-after-the-call = 调用后的列表：{ $snapshot_goal }
cards-result-cards-replaces = { " " }· 替换 { $replaces_id }
cards-result-cards-the-list-at-this-version = 该版本的列表未存储。
web-search-card-these-sources-returned-nothing-so = 这些来源未返回任何结果，因此结果来自少于预期的数量
web-search-card-u-degraded = ⚠ { $degraded_len } 个降级项
web-search-card-form = 表单 { $index }：{ $form }
web-search-card-no-results-from = 无结果，来源：{ $degraded_text }
web-search-card-no-results-every-source-answered = 无结果。所有来源均已响应，但都没有针对此查询的内容。
web-search-card-the-lowest-ranked-results-were = 排名最低的结果已被丢弃，以便本次调用能够容纳进转录文本。助手已看到全部结果。
web-search-card-view-search-details = 查看搜索详情。
web-search-card-the-stored-result-could-not = 存储的结果无法读回为 JSON
web-search-card-nothing-was-stored-for-this = 本次调用未存储任何内容。
web-search-card-forms = 表单：{ $forms }
web-search-card-kind = 类型：{ $row_kind }
web-search-card-published = 发布时间：{ $row_published }
web-search-card-loading-search-detail-u = 正在加载搜索详情…
web-search-card-could-not-load-the-search = 无法加载搜索详情：{ $e }
web-search-card-malformed-detail = 详情格式错误：{ $e }
web-search-card-the-tool-returned-selected-results = 该工具向模型返回了筛选结果。
web-search-card-results-use-reciprocal-rank-fusion = 结果采用倒数秩融合算法。
web-search-card-returned-nothing = 未返回任何内容：{ $degraded }
web-search-card-all-candidates-use-fusion-order = 所有候选项均按融合顺序排列。
web-search-card-the-cross-encoder-ranks-selected = 交叉编码器对筛选结果进行排序。
web-search-card-selected-results-use-fusion-order = 筛选结果按融合顺序排列。
web-search-card-search-detail = 搜索详情
web-search-card-rrf = RRF 第 { $row_rrf_rank } 名
chat-tool-disclosure-search-this = 搜索此项
chat-tool-disclosure-search-every-collection = 搜索所有数据集集合
chat-tool-disclosure-hide = 隐藏
chat-tool-disclosure-expand = 展开
chat-tool-disclosure-this-step-was-recorded-before = 此步骤在存储工具参数和结果之前已记录。仅下方摘要可用。
chat-tool-disclosure-arguments = 参数
chat-tool-disclosure-result = 结果
chat-tool-disclosure-hide-raw-json = 隐藏原始 JSON
chat-tool-disclosure-show-raw-json = 显示原始 JSON
chat-tool-disclosure-input-json = 输入 JSON
chat-tool-disclosure-output-json = 输出 JSON
chat-transcript-ask-a-question-about-the = 就数据集中的文档提出问题。
chat-transcript-suggested-next = 建议下一步…
chat-transcript-earlier-answer = 更早的答案
chat-transcript-tokens-the-conversation-carries-the = 对话所携带的 token，本轮计费的最大单一上下文，以及模型窗口中使用的占比
chat-transcript-instruction-to-the-agent = 给代理的指令
chat-transcript-the-context-stays-above-the = 上下文保持在 { $target } 的目标上方。
chat-transcript-summary-parts-failed-the-record = { $failed } 个摘要部分失败。记录仅保存列表。
chat-transcript-show-the-record = 显示记录
chat-transcript-hide-reasoning = 隐藏推理
chat-transcript-show-reasoning = 显示推理
chat-transcript-from-u-hide = { $count } 个来自 { $tool } 的 { $noun } — 隐藏
chat-transcript-from-u-show = { $count } 个来自 { $tool } 的 { $noun } — 显示
chat-transcript-u-hide = { $summary } — 隐藏
chat-transcript-u-show = { $summary } — 显示
chat-transcript-citations-of-this-conversation-give = 本次对话的引用将 { $doc_handle } 指向多个文档。答案未将其链接到其中任何一个。
chat-transcript-report = 报告 { $label }
chat-transcript-open-in-the-workspace = 在工作区中打开
chat-transcript-this-version-could-not-be = 此版本无法读取。答案的聊天文本如下。
chat-transcript-files = 文件
chat-transcript-version = { $file_name }、版本 { $file_version }
chat-web-find-exact-text = 查找确切文本
chat-web-previous-match = 上一个匹配
chat-web-next-match = 下一个匹配
chat-web-close-preview = 关闭预览
chat-web-the-captured-page-could-not = 无法加载捕获的页面。
chat-web-loading = 加载中…
chat-workspace-pane-workspace = 工作区
chat-workspace-pane-close-the-workspace = 关闭工作区
chat-workspace-pane-close = 关闭
chat-workspace-pane-loading-the-files-u = 正在加载文件…
chat-workspace-pane-the-files-could-not-be = 无法加载文件：{ $error }
chat-workspace-pane-this-conversation-has-no-files = 本次对话没有文件。
chat-workspace-pane-version = 版本 { $entry_version }，{ $length_text_entry_chars } 字符
chat-workspace-pane-choose-a-file-to-read = 选择要读取的文件。
chat-workspace-pane-loading-the-file-u = 正在加载文件…
chat-workspace-pane-the-file-could-not-be = 无法加载文件：{ $error }
chat-workspace-pane-version-2 = { $found_name } 版本 { $found_version }
chat-board-create-collections = 数据集集合
chat-board-create-loading-collections-u = 正在加载数据集集合…
chat-board-create-hoover-search-new-board = Hoover 搜索 - 新调查板
chat-board-create-ai-chat = AI 聊天
chat-board-create-new-investigation-board = 新调查板
chat-board-create-a-board-runs-its-goals = 调查板按顺序执行其目标，每个目标是一次智能体探索，每次探索是一个以一条调查板发现结尾的聊天。你可以审阅每个目标的答案，并在运行过程中拒绝发现、添加提示。
chat-board-create-title = 标题
chat-board-create-goal = 目标
chat-board-create-remove-this-goal = 移除此目标
chat-board-create-remove = 移除
chat-board-create-add-a-goal = 添加目标
chat-board-create-context-optional = 上下文（可选）
chat-board-create-hints-one-per-line-optional = 提示，每行一个（可选）
chat-board-create-sources = 来源
chat-board-create-internet-tools = 互联网工具
chat-board-create-creating-board = 正在创建调查板...
chat-board-create-create-board = 创建调查板
ai-chat-board-hoover-search-board = Hoover 搜索 - 调查板
ai-chat-board-loading-the-board-u = 正在加载调查板…
ai-chat-board-show-the-board-overview = 显示调查板概览
ai-chat-board-zoom-out = 缩小
ai-chat-board-zoom-in = 放大
ai-chat-board-u-ai-chat = ← AI 聊天
ai-chat-board-settings = 设置
ai-chat-board-board-settings = 调查板设置
ai-chat-board-internet-tools = 互联网工具
ai-chat-board-the-next-explores-of-the = 调查板的后续探索可以搜索网络并阅读网页。正在运行的探索会保留其启动时采用的设置。
ai-chat-board-collections = 数据集集合
ai-chat-board-the-collections-are-fixed-when = 调查板在创建时即固定数据集集合。
ai-chat-board-confirm-drop = 确认删除
ai-chat-board-drop-the-board = 删除调查板
ai-chat-board-close = 关闭
ai-chat-board-the-board-used-its-explore = 调查板已用完其探索额度
ai-chat-board-the-board-used-explores-the = 调查板已使用 { $explore_limit } 次探索，达到单个调查板的上限。不再开展更多工作。您仍可决定所建议的答案。
ai-chat-board-create-a-new-board-to = 创建新的调查板以继续调查
ai-chat-board-goal = 目标
ai-chat-board-goals = 目标
ai-chat-board-add-new-goal = 添加新目标...
ai-chat-board-a-new-goal = 新目标
ai-chat-board-add-goal = 添加目标
ai-chat-board-a-board-has-at-most = 一个调查板最多有 { $max_goals } 个目标。请创建新的调查板以设定其他目标。
ai-chat-board-background-context = 背景信息
ai-chat-board-continue-with-a-correction = 以更正继续
ai-chat-board-correction-what-is-wrong-or = 更正：说明错误或遗漏之处。调查板将据此继续。
ai-chat-board-the-board-waits-for-your = 调查板正在等待您的审阅
ai-chat-board-the-board-used-its-budget = 调查板已用完其 { $snap_max_explores } 次探索预算。
ai-chat-board-the-assessments-gave-no-usable = 评估未给出可用的方向。
ai-chat-board-accept-or-reject-the-proposed = 接受或拒绝上述每个目标所建议的答案。被拒绝的答案将让调查板立即继续。
ai-chat-board-no-proposed-answer-waits-for = 没有待您决定的所建议答案。
ai-chat-board-reopen-the-board-to-continue = 重新打开调查板以继续未完成的目标。它将保留其发现与答案。
ai-chat-board-close-the-board-to-accept = 关闭调查板以接受所有建议答案并停止，或以更正继续。
ai-chat-board-close-the-board = 关闭调查板
ai-chat-board-or-reopen-the-board-to = 或重新打开调查板，以不带更正继续未完成的目标。
ai-chat-board-the-board-is-complete = 调查板已完成
ai-chat-board-a-goal-has-no-accepted = 某个目标没有已接受的答案。请重新打开调查板以继续。它将保留其发现与答案。
ai-chat-board-add-a-hint = 添加提示
ai-chat-board-the-next-assessment-reads-every = 下一次评估将读取每条提示。提示也能回答某个提出问题的探索。
ai-chat-board-add-hint = 添加提示
ai-chat-board-events = 事件
ai-chat-board-newest-first = 最新优先
ai-chat-board-date = 日期
ai-chat-board-actor = 操作者
ai-chat-board-event = 事件
ai-chat-board-show-details = 显示详情
ai-chat-board-open = 打开
ai-chat-board-show-the-newest-events = 显示最新的 { $event_rows } 个事件
ai-chat-board-show-all-events = 显示全部 { $snap_events_len } 个事件
ai-chat-board-statistics = 统计
ai-chat-board-explores = 探索
ai-chat-board-model-steps-per-explore = 每次探索的模型步数
ai-chat-board-assessments = 评估
ai-chat-board-intents = 意图
ai-chat-board-findings = 发现
ai-chat-board-created = 已创建
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } 于 { $format_utc_ms_fact_rejected_ms } 拒绝了该发现。调查板不再使用它。
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } 拒绝了该发现。调查板不再使用它。
ai-chat-board-no-reason-was-given = 未给出原因。
ai-chat-board-reason = 原因：{ $fact_rejected_reason }
ai-chat-board-open-questions = 待解决问题
ai-chat-board-explored-in = 在{ " " }中探索
ai-chat-board-explore-this-question = 探索该问题
ai-chat-board-your-questions = 你的问题
ai-chat-board-ask-about-the-background-context = 询问背景上下文
ai-chat-board-ask-about-this-finding = 询问该发现
ai-chat-board-a-follow-up-question-about = 关于该节点的后续问题
ai-chat-board-ask = 询问
ai-chat-board-checks-that-changed-this-finding = 更改该发现的检查项
ai-chat-board-reject-this-correction = 拒绝此更正
ai-chat-board-reject-this-finding = 拒绝此发现
ai-chat-board-not-answered-the-board-was = 未作答。调查板在未回答此目标的情况下完成。添加提示或重新打开将再次激活它。
ai-chat-board-no-answer-yet = 尚无答案。
ai-chat-board-the-findings-of-this-answer = 此答案的发现为未找到任何内容的搜索。接受以记录这些记录未回答该目标，或拒绝以继续调查。
ai-chat-board-open-an-assessment-to-read = { "." } 打开评估以阅读原因。
ai-chat-board-from-the-findings = 来自发现{ " " }
ai-chat-board-accept-answer = 接受答案
ai-chat-board-why-the-answer-is-wrong = 答案错误或不完备的原因
ai-chat-board-reject-answer = 拒绝答案
ai-chat-board-intent = 意图
ai-chat-board-attempts-declared = 尝试次数：{ $intent_attempts }。声明于 { $format_utc_ms_intent_created_ms }。
ai-chat-board-the-explore-asked = 探索提出的问题
ai-chat-board-add-a-hint-in-the = 在调查板概览中添加提示以作答。
ai-chat-board-last-error = 最近错误
ai-chat-board-brief = 摘要
ai-chat-board-open-the-explore-chat = 打开探索聊天
ai-chat-board-loading-the-assessment-u = 正在加载评估…
ai-chat-board-assessment = 评估 { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }。模型 { $a_model }。结果 { $a_outcome }。{ $a_latency_ms } 毫秒，{ $tokens }。
ai-chat-board-checks-that-changed-it = 更改它的检查项
ai-chat-board-prompt = 提示
ai-chat-board-this-assessment-ran-before-the = 此评估在提示被存储之前运行。
ai-chat-board-response = 响应
ai-chat-history-hoover-search-chat-history = Hoover 搜索 - 聊天历史
ai-chat-history-u-back = ← 返回
ai-chat-history-conversation-history = 对话历史
ai-chat-history-show-board-chats = 显示调查板聊天
ai-chat-history-loading-u = 正在加载…
ai-chat-history-could-not-load-history = 无法加载历史：{ $e }
ai-chat-history-no-conversations-yet = 暂无对话。
ai-chat-history-board = 调查板
ai-chat-history-new-chat = 新建聊天
ai-chat-history-messages-updated = { $s_message_count } 条消息 · 更新于 { $s_updated_at }
ai-chat-history-delete-conversation = 删除对话
ai-chat-history-delete = 删除
ai-chat-homepage-hoover-search-ai-chat = Hoover 搜索 - AI 聊天
ai-chat-homepage-what-are-you-researching = 你正在研究什么？
ai-chat-homepage-view-all-conversations = 查看所有对话
ai-chat-homepage-starting-conversation-u = 正在启动对话…
ai-chat-homepage-investigation-boards = 调查板
ai-chat-homepage-new-board = 新建调查板
ai-chat-homepage-loading-boards-u = 正在加载调查板…
ai-chat-homepage-could-not-load-the-boards = 无法加载调查板：{ $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = 你还没有调查板。调查板通过一系列代理探索来开展长期调查，你会审阅其结果。
ai-chat-homepage-updated = 更新于 { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover 搜索 - AI 聊天
ai-chat-session-this-conversation-could-not-be = 无法加载该对话。
ai-chat-session-loading-u = 正在加载…
ai-chat-session-u-chats = ← 聊天
ai-chat-session-history = 历史记录
ai-chat-session-show-the-files-that-the = 显示助手在本对话中生成的文件
ai-chat-session-workspace = 工作区
ai-chat-session-this-answer-was-interrupted-before = 该回答在结束前被中断，因为页面或服务在回合中途停止。再次提问以重试。
ai-chat-session-dismiss = 关闭
ai-chat-session-board-explore-chats-are-read = 调查板探索聊天为只读。{ " " }
ai-chat-session-open-the-board = 打开调查板
chat-locked-options-on = { $label }：开启
chat-locked-options-off = { $label }：关闭
chat-tool-cards-running-u = 运行中…
cards-result-cards-quote-found = 找到引用
cards-result-cards-quote-not-found = 未找到引用
cards-result-cards-quote-not-checked = 未核实引用
web-search-card-results = { $results_len } 条结果
chat-tool-disclosure-running-u = 运行中…
chat-transcript-call = 通话
chat-transcript-calls = 通话
ai-chat-board-a-board-without-collections-needs = 没有数据集集合的调查板需要联网工具。
ai-chat-board-of = { $snap_explores_used } / { $snap_max_explores }
ai-chat-board-assessment-2 = 评估 { $number }
ai-chat-history-messages = { $s_message_count } 条消息
web-search-card-reranked-in = 交叉编码器在 { $ms } 毫秒内对结果重新排序。
web-search-card-engine-results = { $name }：{ $count } 条，耗时 { $ms } 毫秒
web-search-card-score-was-rank = 得分 { $score } · 原 RRF 排名 #{ $rank }
chat-activity-the-turn-waits-for-a = 本轮等待空闲模型槽位。
chat-activity-the-turn-waits-for-a-2 = 本轮等待空闲工具槽位。
chat-locked-options-start-a-new-chat-to = 开始新聊天以更改此设置。
chat-locked-options-internet-tools = 联网工具
chat-session-card-new-chat = 新聊天
chat-tool-cards-first-frame-of-the-video = 视频首帧
chat-tool-cards-screenshot-of = 截图：
chat-tool-cards-image = 图片
cards-result-cards-the-agent-asked-a-question = 代理提出问题。
chat-transcript-hide = 隐藏
chat-transcript-show = 显示
chat-transcript-unverified-quote-the-quoted-span = 未核实引用。引用的片段过短，无法核实。
chat-transcript-unverified-quote-the-document-text = 未核实引用。无法读取文档文本。
chat-transcript-unverified-quote-this-wording-was = 未核实引用。文档中未找到此表述。
chat-board-create-select-a-collection-or-turn = 选择数据集集合或开启联网工具。
chat-board-create-select-at-least-one-collection = 至少选择一个数据集集合。
ai-chat-board-active = 进行中
ai-chat-board-paused = 已暂停
ai-chat-board-waits-for-review = 待审核
ai-chat-board-completed = 已完成
ai-chat-board-dropped = 已丢弃
ai-chat-board-unknown = 未知
ai-chat-board-pause-the-board = 暂停调查板
ai-chat-board-resume-the-board = 恢复调查板
ai-chat-board-none = 无
ai-chat-board-reopen-with-the-remaining-budget = 以剩余预算重新打开
ai-chat-board-finding = 发现
ai-chat-board-why-the-correction-is-wrong = 更正为何有误
ai-chat-board-reject-correction = 拒绝更正
ai-chat-board-why-the-finding-is-wrong = 发现为何有误
ai-chat-board-reject-finding = 拒绝发现
ai-chat-board-answer = 答案
ai-chat-board-proposed-answer = 建议答案
ai-chat-homepage-active = 进行中
ai-chat-homepage-paused = 已暂停
ai-chat-homepage-waits-for-review = 待审核
ai-chat-homepage-completed = 已完成
ai-chat-homepage-dropped = 已丢弃
ai-chat-homepage-unknown = 未知
cards-result-cards-submitted-by-board =
    由调查板提交：来自报告的 { $kind ->
        [sourced] 有来源的
        [inferred] 推断出的
        [not_found] 未找到的
       *[other] 未知类型的
    } 发现
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] 有来源的
        [inferred] 推断出的
        [not_found] 未找到的
       *[other] 未知类型的
    } 发现，供调查板使用
chat-transcript-compacting = 正在压缩上下文：将 { $before } 个标记压缩至目标 { $target }。
chat-transcript-compaction-failed = 对先前步骤的摘要失败。模型原样接收了先前步骤，共 { $after } 个标记。
chat-transcript-compacted = 上下文已压缩：已摘要 { $steps } 个步骤，由 { $before } 个标记压缩至 { $after }。
ai-chat-board-reopen-with-more = 以额外 { $grant } 次探索重新打开
ai-chat-board-goal-number = 目标 { $number }
ai-chat-board-from-assessment-on = 来自 { $date } 的评估 { $number }。
ai-chat-board-from-assessment = 来自评估 { $number }。
chat-board-create-goal-2 = 目标 { $index_1 }
ai-chat-session-lost-contact-with-the-chat = 与聊天失去联系：{ $e }
ai-chat-session-could-not-stop-the-answer = 无法停止答案：{ $e } — 仍在运行
ai-chat-board-later-assessments-dropped-an-answer = 后续 { $n } 次评估为该目标丢弃了一个答案：
ai-chat-board-prompt-and-completion-tokens = { $a_prompt_tokens } 个提示和 { $a_completion_tokens } 个完成令牌
ai-chat-homepage-completed-goals-not-answered = 已完成，{ $n } 个目标未作答
board-graph-intent = 意图，{ $state }
chat-workspace-pane-characters = { $chars } 个字符
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } 运行工具 { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } 运行工具 { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = 在 { $retries_len } 次失败尝试后{ $if_retries_len_1_else_s }得到回答
chat-transcript-failed-attempt = { $retries_len } 次失败尝试{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }，版本 { $report_version }
tool-run-summary-searched =
    { $n ->
       *[other] 搜索了 { $n } 个关键词
    }
tool-run-summary-read =
    { $n ->
       *[other] 读取了 { $n } 份文档
    }
tool-run-summary-searched-the-web-for =
    { $n ->
       *[other] 在网络上搜索 { $n } 个关键词
    }
tool-run-summary-read-web =
    { $n ->
       *[other] 读取了 { $n } 个网页
    }
tool-run-summary-browser =
    { $n ->
       *[other] { $n } 次浏览器操作
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
       *[other] 列出了 { $n } 份文档的实体
    }
tool-run-summary-cited =
    { $n ->
       *[other] 引用了 { $n } 份文档
    }
tool-run-summary-cited-web =
    { $n ->
       *[other] 引用了 { $n } 个网页
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
       *[other] 读取了 { $n } 个技能和工具文本
    }
tool-run-summary-saved =
    { $n ->
       *[other] 保存了 { $n } 条备注
    }
tool-run-summary-todo-list =
    { $n ->
       *[other] { $n } 次待办列表调用
    }
tool-run-summary-to-the-agent =
    { $n ->
       *[other] { $n } 条给代理的指令
    }
tool-run-summary-other =
    { $n ->
       *[other] { $n } 次其他调用
    }
tool-run-summary-failed = { $failures } 次失败
tool-run-summary-took = 耗时 { $duration_text_ms }
chat-session-card-messages = { $session_message_count } 条消息
chat-tool-disclosure-item =
    { $count ->
       *[other] { $count } 条项目
    }
chat-tool-disclosure-field =
    { $count ->
       *[other] { $count } 个字段
    }
chat-tool-disclosure-searched-collections = 已搜索的集合{ $filters }
chat-tool-disclosure-searched-collections-2 = 已搜索的集合 · { $query }{ $filters }
chat-tool-disclosure-cited-documents = 已引用 { $n } 份文档
chat-tool-disclosure-read-document = 已读取文档 · { $path }
chat-tool-disclosure-searched-the-web = 已搜索网络 · { $q }
chat-tool-disclosure-opened-page = 已打开页面 · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = 已调用 { $other }
chat-tool-disclosure-called-2 = 已调用 { $other } · { $short }
cards-browser-card-opened = 已打开 { $url }
cards-browser-card-could-not-open = 无法打开 { $url }
cards-browser-card-clicked = 已点击 { $element }
cards-browser-card-could-not-click = 无法点击 { $element }
cards-browser-card-typed-into = 已在 { $element } 中输入
cards-browser-card-could-not-type-into = 无法在 { $element } 中输入
cards-browser-card-typed = 已输入“{ $text }”
cards-browser-card-could-not-type = 无法输入“{ $text }”
cards-browser-card-pressed = 已按下 { $key }
cards-browser-card-could-not-press = 无法按下 { $key }
cards-browser-card-chose-an-option-in = 已在 { $element } 中选择选项
cards-browser-card-could-not-choose-an-option = 无法在 { $element } 中选择选项
cards-browser-card-hovered = 已悬停在 { $element }
cards-browser-card-could-not-hover = 无法悬停在 { $element }
cards-browser-card-failed = { $bare } — 失败
cards-entities-card-listed-entities-document = 已列出实体 · { $count } 份文档{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · { $name } 的第 { $part } 部分 #{ $seq }
cards-result-cards-documents = { " " }· { $value } 份文档
cards-result-cards-forms = { $tool_name } · { $forms } 个表单
cards-result-cards-in = { " " }在 { $collections } 中
cards-result-cards-page = { " " }· 第 { $value } 页
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } 个文档 · 未找到 { $missing } 处引用
cards-result-cards-version-unchanged = { $tool_name } · 版本 { $version } · 未更改
cards-result-cards-version = { $tool_name } · 版本 { $version }
web-search-card-results-in-after-deduplication = 去重前共 { $json_u64_doc_total_before_dedupe } 条结果，去重后为 { $json_u64_doc_total_after_dedupe }
