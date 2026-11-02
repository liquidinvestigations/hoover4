# Translation of en/chat.ftl. Change it together with the English catalog.

chat-activity-the-bot-is-working = ボットが作業中…
chat-composer-ask-the-bot = ボットに質問…
chat-composer-internet-tools = インターネットツール
chat-composer-agent-language-title = エージェントは { $language } で回答します。設定で言語を変更できます（新しいタブで開きます）。
chat-composer-try-again-in-s = { $secs } 秒後に再試行してください
chat-composer-stop-the-answer-the-partial = 回答を停止します（部分入力は会話に保存されません）
chat-composer-starting-the-conversation-u = 会話を開始しています…
chat-composer-send = 送信
chat-conversation-find-search-in-conversation = 会話内を検索
chat-conversation-find-previous-match = 前の一致
chat-conversation-find-next-match = 次の一致
chat-conversation-find-investigation-board = 調査ボード
doc-ref-card-not-openable = 開けません：{ $reason }。
doc-ref-card-the-search-term-was = 検索用語は{ " " }
doc-ref-card-open = 開く
doc-ref-card-not-openable-2 = 開けません
chat-markdown-text-show-the-cited-source = 出典ソースを表示
chat-markdown-text-no-citation-of-this-conversation = この会話の出典にこのハンドルが記載されていないため、これに対応するドキュメントはありません。
chat-markdown-text-citations-of-this-conversation-gave = この会話の出典にこのハンドルが複数のドキュメントに記載されているため、いずれにもリンクしません。
cards-browser-card-open-the-archived-page = アーカイブ済みページを開く
cards-browser-card-the-page-itself-was-not = ページ自体はアーカイブされていません（ステータス：{ $artifact_status }）。上のスクリーンショットは保存された内容です。
cards-browser-card-click-the-screenshot-to-open = スクリーンショットをクリックしてアーカイブ済みページを開きます。
cards-browser-card-show-less = 一部を表示
cards-browser-card-show-all = すべてを表示
cards-browser-card-archived-page = アーカイブ済みページ
cards-browser-card-download = ダウンロード
cards-browser-card-archived-copy-of = { $artifact_url } のアーカイブ済みコピー
cards-browser-card-this-page-was-not-archived = このページはアーカイブされていません（ステータス：{ $artifact_status }）。
cards-entities-card-with-a-card = カードあり：{ $openable }
cards-entities-card-the-entity-list-was-cut = エンティティリストは切り詰められています。
cards-entities-card-open-the-card-for-this = この値 ({ $rule_id }) のカードを開く
cards-entities-card-no-card-this-conversation-never = カードなし: この会話では、これらの値の元となったデータセットを一度も名付けておらず、閲覧者はデータセット名で呼ばれます。
cards-entities-card-more-all-of-them-in = { $rest } 件、すべてドキュメントのエンティティパネルにあります。{ " " }
cards-entities-card-names-organisations-and-places-above = 上記の名前、組織、場所は、モデルが本文を読み取った結果です。ルールで検証されていないため、説明する内容もなく、開いても何も表示されません。
cards-entities-card-nothing-extracted-from-this-document = このドキュメントから抽出された内容はありません。
chat-tool-cards-hide = 隠す
chat-tool-cards-expand = 展開
chat-tool-cards-hide-raw-json = 生JSONを隠す
chat-tool-cards-show-raw-json = 生JSONを表示
cards-result-cards-search-this = これを検索
cards-result-cards-search-every-collection = すべてのコレクションを検索
cards-result-cards-form = フォーム { $index }: { $form }
cards-result-cards-show-full-text = 全文を表示
cards-result-cards-quote = 引用: { $quote }
cards-result-cards-reason = 理由: { $why }
cards-result-cards-open-question = 未解決の質問: { $question }
cards-result-cards-the-explore-gave-this-answer =
    エクスプローラーは、ボードに対して { $kind ->
        [sourced] 出典あり
        [inferred] 推論による
        [not_found] 未検出
       *[other] 不明な種類
    } の発見結果としてこの回答を出しました。
cards-result-cards-it-left-no-open-question = 未解決の質問は残っていません。
cards-result-cards-open-questions-for-the-board = ボードへの未解決の質問:
cards-result-cards-arguments = 論点
cards-result-cards-list-after-the-call = 呼び出し後の一覧: { $snapshot_goal }
cards-result-cards-replaces = { " " }· が { $replaces_id } を置き換えます
cards-result-cards-the-list-at-this-version = このバージョンの一覧は保存されていません。
web-search-card-these-sources-returned-nothing-so = これらのソースは何も返さなかったため、結果は想定より少ないソースから取得されています
web-search-card-u-degraded = ⚠ { $degraded_len } 劣化
web-search-card-form = フォーム { $index }: { $form }
web-search-card-no-results-from = 結果なし: { $degraded_text }
web-search-card-no-results-every-source-answered = 結果なし。すべてのソースが応答しましたが、このクエリに対する内容はありませんでした。
web-search-card-the-lowest-ranked-results-were = 最下位ランクの結果は、この呼び出しがトランスクリプトに収まるように除外されました。アシスタントはそれらすべてを確認しています。
web-search-card-view-search-details = 検索詳細を表示。
web-search-card-the-stored-result-could-not = 保存された結果を JSON として読み取ることができませんでした
web-search-card-nothing-was-stored-for-this = この呼び出しには何も保存されていません。
web-search-card-forms = フォーム: { $forms }
web-search-card-kind = 種類: { $row_kind }
web-search-card-published = 公開: { $row_published }
web-search-card-loading-search-detail-u = 検索詳細を読み取り中…
web-search-card-could-not-load-the-search = 検索詳細を読み取ることができませんでした: { $e }
web-search-card-malformed-detail = 形式不正の詳細: { $e }
web-search-card-the-tool-returned-selected-results = ツールは選択された結果をモデルに返しました。
web-search-card-results-use-reciprocal-rank-fusion = 結果は相互ランク融合を使用します。
web-search-card-returned-nothing = 何も返しません: { $degraded }
web-search-card-all-candidates-use-fusion-order = 全候補は融合順序を使用します。
web-search-card-the-cross-encoder-ranks-selected = クロスエンコーダーは選択された結果をランク付けします。
web-search-card-selected-results-use-fusion-order = 選択された結果は融合順序を使用します。
web-search-card-search-detail = 検索詳細
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = これを検索
chat-tool-disclosure-search-every-collection = 全コレクションを検索
chat-tool-disclosure-hide = 隠す
chat-tool-disclosure-expand = 展開
chat-tool-disclosure-this-step-was-recorded-before = このステップは、ツールの引数と結果が保存される前に記録されました。以下に示す要約のみが利用できます。
chat-tool-disclosure-arguments = 引数
chat-tool-disclosure-result = 結果
chat-tool-disclosure-hide-raw-json = 生JSONを隠す
chat-tool-disclosure-show-raw-json = 生JSONを表示
chat-tool-disclosure-input-json = 入力JSON
chat-tool-disclosure-output-json = 出力JSON
chat-transcript-ask-a-question-about-the = コレクション内のドキュメントについて質問してください。
chat-transcript-suggested-next = 推奨される次…
chat-transcript-earlier-answer = 以前の回答
chat-transcript-tokens-the-conversation-carries-the = 会話が付随するトークン。このターンで請求された最大の単一コンテキストと、モデルのウィンドウのうちそれが使用した量
chat-transcript-instruction-to-the-agent = エージェントへの指示
chat-transcript-the-context-stays-above-the = コンテキストは { $target } の目標の上に留まります。
chat-transcript-summary-parts-failed-the-record = { $failed } 件の要約パーツが失敗しました。レコードにはリストのみが含まれます。
chat-transcript-show-the-record = レコードを表示
chat-transcript-hide-reasoning = 推論を非表示
chat-transcript-show-reasoning = 推論を表示
chat-transcript-from-u-hide = { $count } { $noun } — { $tool } 由来 — 非表示
chat-transcript-from-u-show = { $count } { $noun } — { $tool } 由来 — 表示
chat-transcript-u-hide = { $summary } — 非表示
chat-transcript-u-show = { $summary } — 表示
chat-transcript-citations-of-this-conversation-give = この会話の出典は { $doc_handle } を複数のドキュメントに付与します。回答はどれにも結び付けません。
chat-transcript-report = { $label } を報告
chat-transcript-open-in-the-workspace = ワークスペースで開く
chat-transcript-this-version-could-not-be = このバージョンは読み取れませんでした。回答のチャットテキストが続きます。
chat-transcript-files = ファイル
chat-transcript-version = { $file_name }、バージョン { $file_version }
chat-web-find-exact-text = 正確なテキストを検索
chat-web-previous-match = 前の一致
chat-web-next-match = 次の一致
chat-web-close-preview = プレビューを閉じる
chat-web-the-captured-page-could-not = 取得したページを読み取れませんでした。
chat-web-loading = 読み取り中…
chat-workspace-pane-workspace = ワークスペース
chat-workspace-pane-close-the-workspace = ワークスペースを閉じる
chat-workspace-pane-close = 閉じる
chat-workspace-pane-loading-the-files-u = ファイルを読み取り中…
chat-workspace-pane-the-files-could-not-be = ファイルを読み取れませんでした：{ $error }
chat-workspace-pane-this-conversation-has-no-files = この会話にはファイルがありません。
chat-workspace-pane-version = バージョン { $entry_version }、{ $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = 読み込むファイルを選択してください。
chat-workspace-pane-loading-the-file-u = ファイルを読み込み中…
chat-workspace-pane-the-file-could-not-be = ファイルを読み込めませんでした：{ $error }
chat-workspace-pane-version-2 = { $found_name }、バージョン { $found_version }
chat-board-create-collections = コレクション
chat-board-create-loading-collections-u = コレクションを読み込み中…
chat-board-create-hoover-search-new-board = Hoover Search - 新しいボード
chat-board-create-ai-chat = AI チャット
chat-board-create-new-investigation-board = 新しい調査ボード
chat-board-create-a-board-runs-its-goals = ボードは、エージェントによる探索のシーケンスとして目標を実行します。各探索は、1つの発見結果で終わるチャットです。各目標の回答を確認でき、実行中に発見結果を拒否したりヒントを追加したりできます。
chat-board-create-title = タイトル
chat-board-create-goal = 目標
chat-board-create-remove-this-goal = この目標を削除
chat-board-create-remove = 削除
chat-board-create-add-a-goal = 目標を追加
chat-board-create-context-optional = コンテキスト（任意）
chat-board-create-hints-one-per-line-optional = ヒント、1行に1つ（任意）
chat-board-create-sources = ソース
chat-board-create-internet-tools = インターネットツール
chat-board-create-creating-board = ボードを作成中...
chat-board-create-create-board = ボードを作成
ai-chat-board-hoover-search-board = Hoover Search - ボード
ai-chat-board-loading-the-board-u = ボードを読み込み中…
ai-chat-board-show-the-board-overview = ボードの概要を表示
ai-chat-board-zoom-out = 縮小
ai-chat-board-zoom-in = 拡大
ai-chat-board-u-ai-chat = ← AI チャット
ai-chat-board-settings = 設定
ai-chat-board-board-settings = ボードの設定
ai-chat-board-internet-tools = インターネットツール
ai-chat-board-the-next-explores-of-the = ボードの次の探索では、ウェブを検索したりウェブページを読んだりできます。実行中の探索は、開始時の設定を保持します。
ai-chat-board-collections = コレクション
ai-chat-board-the-collections-are-fixed-when = コレクションは、ボードが作成された時点で固定されます。
ai-chat-board-confirm-drop = ドロップの確認
ai-chat-board-drop-the-board = ボードをドロップ
ai-chat-board-close = 閉じる
ai-chat-board-the-board-used-its-explore = ボードは探索の上限を使用しました
ai-chat-board-the-board-used-explores-the = ボードは { $explore_limit } 回の探索を使用しました。これは1つのボードの上限です。これ以上作業は行われません。提案された回答をまだ決定できます。
ai-chat-board-create-a-new-board-to = 調査を続けるために新しいボードを作成してください
ai-chat-board-goal = 目標
ai-chat-board-goals = 目標
ai-chat-board-add-new-goal = 新しい目標を追加...
ai-chat-board-a-new-goal = 新しい目標
ai-chat-board-add-goal = 目標を追加
ai-chat-board-a-board-has-at-most = ボードには最大 { $max_goals } 個の目標があります。別の目標には新しいボードを作成してください。
ai-chat-board-background-context = 背景コンテキスト
ai-chat-board-continue-with-a-correction = 修正して続ける
ai-chat-board-correction-what-is-wrong-or = 修正: 誤りや不足している内容。ボードはこれ続けています。
ai-chat-board-the-board-waits-for-your = ボードはあなたの確認を待っています
ai-chat-board-the-board-used-its-budget = ボードは { $snap_max_explores } 回の探索という予算を使用しました。
ai-chat-board-the-assessments-gave-no-usable = 評価で実用的な方向性が得られませんでした。
ai-chat-board-accept-or-reject-the-proposed = 上記の各目標に対する提案された回答を受け入れるか拒否してください。拒否された回答により、ボードはすぐに続きます。
ai-chat-board-no-proposed-answer-waits-for = あなたの判断を待つ提案された回答はありません。
ai-chat-board-reopen-the-board-to-continue = ボードを再度開いて、開いている目標を続けてください。発見結果と回答は保持されます。
ai-chat-board-close-the-board-to-accept = ボードを閉じて、すべての提案された回答を受け入れて停止するか、修正で続けてください。
ai-chat-board-close-the-board = ボードを閉じる
ai-chat-board-or-reopen-the-board-to = 修正なしで開いている目標を続けるには、ボードを再度開いてください。
ai-chat-board-the-board-is-complete = ボードは完了しました
ai-chat-board-a-goal-has-no-accepted = 目標に受け入れられた回答がありません。ボードを再度開いて続けてください。ボードは発見結果と回答を保持します。
ai-chat-board-add-a-hint = ヒントを追加
ai-chat-board-the-next-assessment-reads-every = 次の評価はすべてのヒントを読み取ります。ヒントは、質問を投げかけた探索にも答えます。
ai-chat-board-add-hint = ヒントを追加
ai-chat-board-events = イベント
ai-chat-board-newest-first = 新しい順
ai-chat-board-date = 日付
ai-chat-board-actor = 実行主体
ai-chat-board-event = イベント
ai-chat-board-show-details = 詳細を表示
ai-chat-board-open = 開く
ai-chat-board-show-the-newest-events = 最新の { $event_rows } 件のイベントを表示
ai-chat-board-show-all-events = すべての { $snap_events_len } 件のイベントを表示
ai-chat-board-statistics = 統計
ai-chat-board-explores = 探索
ai-chat-board-model-steps-per-explore = 探索あたりのモデルのステップ
ai-chat-board-assessments = 評価
ai-chat-board-intents = 意図
ai-chat-board-findings = 発見結果
ai-chat-board-created = 作成
ai-chat-board-rejected-this-finding-on-the = { $rejected_by } が { $format_utc_ms_fact_rejected_ms } でこの発見結果を却下しました。ボードはもうこれを使用しません。
ai-chat-board-rejected-this-finding-the-board = { $rejected_by } がこの発見結果を却下しました。ボードはもうこれを使用しません。
ai-chat-board-no-reason-was-given = 理由は指定されていません。
ai-chat-board-reason = 理由: { $fact_rejected_reason }
ai-chat-board-open-questions = 未解決の質問
ai-chat-board-explored-in = 探索先
ai-chat-board-explore-this-question = この質問を探索
ai-chat-board-your-questions = あなたの質問
ai-chat-board-ask-about-the-background-context = 背景の状況について質問
ai-chat-board-ask-about-this-finding = この発見結果について質問
ai-chat-board-a-follow-up-question-about = このノードに関する後続の質問
ai-chat-board-ask = 質問する
ai-chat-board-checks-that-changed-this-finding = この発見結果を変更したチェック
ai-chat-board-reject-this-correction = この修正を拒否
ai-chat-board-reject-this-finding = この発見結果を拒否
ai-chat-board-not-answered-the-board-was = 回答なし。ボードはこの目標に対して回答せず終了しました。ヒントや再開封で再び開きます。
ai-chat-board-no-answer-yet = まだ回答なし。
ai-chat-board-the-findings-of-this-answer = この回答の発見結果は、何も見つけなかった検索です。受け入れると、記録が目標に回答していないことを記録します。拒否すると調査を続けます。
ai-chat-board-open-an-assessment-to-read = { "." } 理由を読むため評価を開く。
ai-chat-board-from-the-findings = 発見結果から{ " " }
ai-chat-board-accept-answer = 回答を受け入れる
ai-chat-board-why-the-answer-is-wrong = 回答が誤りまたは不十分な理由
ai-chat-board-reject-answer = 回答を拒否
ai-chat-board-intent = 意図
ai-chat-board-attempts-declared = 試行: { $intent_attempts }。宣言 { $format_utc_ms_intent_created_ms }。
ai-chat-board-the-explore-asked = エクスプローラーが尋ねた
ai-chat-board-add-a-hint-in-the = ボード概要にヒントを追加して回答する。
ai-chat-board-last-error = 最後のエラー
ai-chat-board-brief = 概要
ai-chat-board-open-the-explore-chat = エクスプローラーチャットを開く
ai-chat-board-loading-the-assessment-u = 評価を読み込み中…
ai-chat-board-assessment = 評価 { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }。モデル { $a_model }。結果 { $a_outcome }。{ $a_latency_ms } ms、{ $tokens }。
ai-chat-board-checks-that-changed-it = これを変更したチェック
ai-chat-board-prompt = プロンプト
ai-chat-board-this-assessment-ran-before-the = この評価はプロンプトが保存される前に実行されました。
ai-chat-board-response = 応答
ai-chat-history-hoover-search-chat-history = Hoover Search - チャット履歴
ai-chat-history-u-back = ← 戻る
ai-chat-history-conversation-history = 会話履歴
ai-chat-history-show-board-chats = ボードのチャットを表示
ai-chat-history-loading-u = 読み込み中…
ai-chat-history-could-not-load-history = 履歴を読み込めませんでした：{ $e }
ai-chat-history-no-conversations-yet = 会話はまだありません。
ai-chat-history-board = ボード
ai-chat-history-new-chat = 新しいチャット
ai-chat-history-messages-updated = { $s_message_count } 件のメッセージ · 更新 { $s_updated_at }
ai-chat-history-delete-conversation = 会話を削除
ai-chat-history-delete = 削除
ai-chat-homepage-hoover-search-ai-chat = Hoover Search - AI チャット
ai-chat-homepage-what-are-you-researching = 何を調査していますか？
ai-chat-homepage-view-all-conversations = すべての会話を表示
ai-chat-homepage-starting-conversation-u = 会話を開始しています…
ai-chat-homepage-investigation-boards = 調査ボード
ai-chat-homepage-new-board = 新しいボード
ai-chat-homepage-loading-boards-u = ボードを読み込んでいます…
ai-chat-homepage-could-not-load-the-boards = ボードを読み込めませんでした：{ $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = ボードがありません。ボードは、エージェントによる探索を連続させて長期調査を実行し、その回答を確認します。
ai-chat-homepage-updated = 更新 { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover Search - AI チャット
ai-chat-session-this-conversation-could-not-be = 会話を読み込めませんでした。
ai-chat-session-loading-u = 読み込んでいます…
ai-chat-session-u-chats = ← チャット
ai-chat-session-history = 履歴
ai-chat-session-show-the-files-that-the = この会話でアシスタントが書き込んだファイルを表示します
ai-chat-session-workspace = ワークスペース
ai-chat-session-this-answer-was-interrupted-before = この回答は完了前に中断されました。ページまたはサーバーが処理途中停止したためです。もう一度尋ねて再試行してください。
ai-chat-session-dismiss = 閉じる
ai-chat-session-board-explore-chats-are-read = ボードの探索チャットは読み取り専用です。{ " " }
ai-chat-session-open-the-board = ボードを開く
chat-locked-options-on = { $label }：オン
chat-locked-options-off = { $label }：オフ
chat-tool-cards-running-u = 実行中…
cards-result-cards-quote-found = 引用が見つかりました
cards-result-cards-quote-not-found = 引用が見つかりません
cards-result-cards-quote-not-checked = 引用は確認されていません
web-search-card-results = { $results_len } 件の結果
chat-tool-disclosure-running-u = 実行中…
chat-transcript-call = 通話
chat-transcript-calls = 通話
ai-chat-board-a-board-without-collections-needs = コレクションがないボードにはインターネットツールが必要です。
ai-chat-board-of = { $snap_explores_used } / { $snap_max_explores }
ai-chat-board-assessment-2 = 評価 { $number }
ai-chat-history-messages = { $s_message_count } 件のメッセージ
web-search-card-reranked-in = クロスエンコーダーが { $ms } ミリ秒で結果を再ランク付けしました。
web-search-card-engine-results = { $name }: { $count } 件を { $ms } ミリ秒で
web-search-card-score-was-rank = スコア { $score } ・ RRF #{ $rank }
chat-activity-the-turn-waits-for-a = 一連の処理が空いているモデルの空きスロットを待っています。
chat-activity-the-turn-waits-for-a-2 = 一連の処理が空いているツールの空きスロットを待っています。
chat-locked-options-start-a-new-chat-to = この設定を変更するには、新しいチャットを開始してください。
chat-locked-options-internet-tools = ツール
chat-session-card-new-chat = 新しいチャット
chat-tool-cards-first-frame-of-the-video = 動画の最初のフレーム
chat-tool-cards-screenshot-of = のスクリーンショット
chat-tool-cards-image = 画像
cards-result-cards-the-agent-asked-a-question = エージェントが質問しました。
chat-transcript-hide = 隠す
chat-transcript-show = 表示
chat-transcript-unverified-quote-the-quoted-span = 未確認の引用です。引用された範囲が短すぎて確認できません。
chat-transcript-unverified-quote-the-document-text = 未確認の引用です。ドキュメントのテキストを読み取ることができませんでした。
chat-transcript-unverified-quote-this-wording-was = 未確認の引用です。この表現はドキュメントに見つかりませんでした。
chat-board-create-select-a-collection-or-turn = コレクションを選択するか、インターネットツールをオンにします。
chat-board-create-select-at-least-one-collection = 少なくとも1つのコレクションを選択してください。
ai-chat-board-active = 稼働中
ai-chat-board-paused = 一時停止中
ai-chat-board-waits-for-review = 審査待ち
ai-chat-board-completed = 完了
ai-chat-board-dropped = 破棄
ai-chat-board-unknown = 不明
ai-chat-board-pause-the-board = ボードを一時停止
ai-chat-board-resume-the-board = ボードを再開
ai-chat-board-none = なし
ai-chat-board-reopen-with-the-remaining-budget = 残りの予算で再開
ai-chat-board-finding = 発見結果
ai-chat-board-why-the-correction-is-wrong = 修正が誤りである理由
ai-chat-board-reject-correction = 修正を拒否
ai-chat-board-why-the-finding-is-wrong = 発見結果が誤りである理由
ai-chat-board-reject-finding = 発見結果を拒否
ai-chat-board-answer = 回答
ai-chat-board-proposed-answer = 提案された回答
ai-chat-homepage-active = 稼働中
ai-chat-homepage-paused = 一時停止中
ai-chat-homepage-waits-for-review = 審査待ち
ai-chat-homepage-completed = 完了
ai-chat-homepage-dropped = 破棄
ai-chat-homepage-unknown = 不明
cards-result-cards-submitted-by-board =
    ボードから提出された: { $kind ->
        [sourced] 出典あり
        [inferred] 推論based
        [not_found] 未検出
       *[other] 不明な種類
    } 発見結果（レポートより）
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] 出典あり
        [inferred] 推論based
        [not_found] 未検出
       *[other] 不明な種類
    } 発見結果（ボード用）
chat-transcript-compacting = コンテキストを圧縮しています: { $before } トークンを目標 { $target } に。
chat-transcript-compaction-failed = 以前のステップの要約に失敗しました。モデルは以前のステップをそのまま受け取り、{ $after } トークンになりました。
chat-transcript-compacted = コンテキストを圧縮しました: { $steps } ステップを要約、{ $before } トークンから { $after } に。
ai-chat-board-reopen-with-more = { $grant } 分の探索を追加して再開
ai-chat-board-goal-number = 目標 { $number }
ai-chat-board-from-assessment-on = 評価 { $number }（{ $date }）由来。
ai-chat-board-from-assessment = 評価 { $number } 由来。
chat-board-create-goal-2 = 目標 { $index_1 }
ai-chat-session-lost-contact-with-the-chat = チャットとの接続が失われました：{ $e }
ai-chat-session-could-not-stop-the-answer = 回答を停止できませんでした：{ $e } — まだ実行中です
ai-chat-board-later-assessments-dropped-an-answer = この目標に対する後続の評価 { $n } 件が回答を除外しました：
ai-chat-board-prompt-and-completion-tokens = プロンプト { $a_prompt_tokens }、コンプリーション { $a_completion_tokens } トークン
ai-chat-homepage-completed-goals-not-answered = 完了、{ $n } 件の目標が未回答
board-graph-intent = 意図、{ $state }
chat-workspace-pane-characters = { $chars } 文字
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } 実行中のツール { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } 実行中のツール { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = { $if_retries_len_1_else_s } 回の試行が失敗した後に回答しました（試行回数: { $retries_len }）
chat-transcript-failed-attempt = { $retries_len } 回の試行が失敗しました{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }、バージョン { $report_version }
tool-run-summary-searched =
    { $n ->
       *[other] 用語 { $n } 件を検索
    }
tool-run-summary-read =
    { $n ->
       *[other] ドキュメント { $n } 件を読んだ
    }
tool-run-summary-searched-the-web-for =
    { $n ->
       *[other] ウェブで用語 { $n } 件を検索
    }
tool-run-summary-read-web =
    { $n ->
       *[other] ウェブページ { $n } 件を読んだ
    }
tool-run-summary-browser =
    { $n ->
       *[other] ブラウザー操作 { $n } 回
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
       *[other] ドキュメント { $n } 件のエンティティを列挙
    }
tool-run-summary-cited =
    { $n ->
       *[other] ドキュメント { $n } 件を出典
    }
tool-run-summary-cited-web =
    { $n ->
       *[other] ウェブページ { $n } 件を出典
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
       *[other] スキルおよびツールテキスト { $n } 件を読んだ
    }
tool-run-summary-saved =
    { $n ->
       *[other] メモ { $n } 件を保存
    }
tool-run-summary-todo-list =
    { $n ->
       *[other] TODOリスト呼び出し { $n } 回
    }
tool-run-summary-to-the-agent =
    { $n ->
       *[other] エージェントへの指示 { $n } 回
    }
tool-run-summary-other =
    { $n ->
       *[other] その他の呼び出し { $n } 回
    }
tool-run-summary-failed = { $failures } 件の失敗
tool-run-summary-took = { $duration_text_ms } にかかりました
chat-session-card-messages = { $session_message_count } 件のメッセージ
chat-tool-disclosure-item =
    { $count ->
       *[other] { $count } 件の項目
    }
chat-tool-disclosure-field =
    { $count ->
       *[other] { $count } 件のフィールド
    }
chat-tool-disclosure-searched-collections = 検索したコレクション { $filters }
chat-tool-disclosure-searched-collections-2 = 検索したコレクション · { $query } { $filters }
chat-tool-disclosure-cited-documents = { $n } 件のドキュメントを出典
chat-tool-disclosure-read-document = ドキュメントを読みました · { $path }
chat-tool-disclosure-searched-the-web = web を検索しました · { $q }
chat-tool-disclosure-opened-page = ページを開きました · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = 呼び出しました { $other }
chat-tool-disclosure-called-2 = 呼び出しました { $other } · { $short }
cards-browser-card-opened = { $url } を開きました
cards-browser-card-could-not-open = { $url } を開けませんでした
cards-browser-card-clicked = { $element } をクリックしました
cards-browser-card-could-not-click = { $element } をクリックできませんでした
cards-browser-card-typed-into = { $element } に入力しました
cards-browser-card-could-not-type-into = { $element } に入力できませんでした
cards-browser-card-typed = “{ $text }” と入力しました
cards-browser-card-could-not-type = “{ $text }” と入力できませんでした
cards-browser-card-pressed = { $key } を押しました
cards-browser-card-could-not-press = { $key } を押できませんでした
cards-browser-card-chose-an-option-in = { $element } のオプションを選択しました
cards-browser-card-could-not-choose-an-option = { $element } のオプションを選択できませんでした
cards-browser-card-hovered = { $element } にカーソルを合わせました
cards-browser-card-could-not-hover = { $element } にカーソルを合わせませんでした
cards-browser-card-failed = { $bare } — 失敗
cards-entities-card-listed-entities-document = エンティティをリストしました · { $count } 件のドキュメント { $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · { $name } の { $part } 部 #{ $seq }
cards-result-cards-documents = { " " }· { $value } ドキュメント
cards-result-cards-forms = { $tool_name } · { $forms } フォーム
cards-result-cards-in = { " " }{ $collections } 内
cards-result-cards-page = { " " }· ページ { $value }
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } ドキュメント · { $missing } 出典が見つかりません
cards-result-cards-version-unchanged = { $tool_name } · バージョン { $version } · 変更なし
cards-result-cards-version = { $tool_name } · バージョン { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe } 件の結果、重複排除後 { $json_u64_doc_total_after_dedupe }
