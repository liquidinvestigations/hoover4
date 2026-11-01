# Machine translation of en/chat.ftl. Do not edit by hand: change the English catalog
# and run scripts/i18n/translate_catalogs.py. See translations.json for the producer.

chat-activity-the-bot-is-working = 봇이 작업 중입니다...
chat-composer-ask-the-bot = 봇에 질문하기...
chat-composer-internet-tools = 인터넷 도구
chat-composer-agent-language-title = 에이전트가 { $language }로 답변합니다. 설정에서 새 탭으로 언어를 변경하세요.
chat-composer-try-again-in-s = { $secs }초 후 다시 시도하세요
chat-composer-stop-the-answer-the-partial = 답변 중단 (일부 내용은 대화에 저장되지 않음)
chat-composer-starting-the-conversation-u = 대화 시작…
chat-composer-send = 보내기
chat-conversation-find-search-in-conversation = 대화에서 검색
chat-conversation-find-previous-match = 이전 일치 항목
chat-conversation-find-next-match = 다음 일치 항목
chat-conversation-find-investigation-board = 수사 보드
doc-ref-card-not-openable = 열 수 없습니다: { $reason }.
doc-ref-card-the-search-term-was = 검색어가
doc-ref-card-open = 열기
doc-ref-card-not-openable-2 = 열 수 없습니다
chat-markdown-text-show-the-cited-source = 인용된 출처 표시
chat-markdown-text-no-citation-of-this-conversation = 이 대화의 인용에서 이 식별자를 제공한 문서가 없어 관련 문서가 없습니다.
chat-markdown-text-citations-of-this-conversation-gave = 이 대화의 인용에서 여러 문서에 이 식별자를 제공하여 어떤 문서로도 연결되지 않습니다.
cards-browser-card-open-the-archived-page = 보관된 페이지 열기
cards-browser-card-the-page-itself-was-not = 페이지 자체는 보관되지 않았습니다(상태: { $artifact_status }). 위의 스크린샷은 보존된 내용입니다.
cards-browser-card-click-the-screenshot-to-open = 스크린샷을 클릭하여 보관된 페이지를 여세요.
cards-browser-card-show-less = 간략히 표시
cards-browser-card-show-all = 전체 표시
cards-browser-card-archived-page = 보관된 페이지
cards-browser-card-download = 다운로드
cards-browser-card-archived-copy-of = { $artifact_url }의 보관된 사본
cards-browser-card-this-page-was-not-archived = 이 페이지는 보관되지 않았습니다(상태: { $artifact_status }).
cards-entities-card-with-a-card = 카드가 있는 { $openable }
cards-entities-card-the-entity-list-was-cut = 개체 목록이 잘렸습니다.
cards-entities-card-open-the-card-for-this = 이 값의 카드 열기 ({ $rule_id })
cards-entities-card-no-card-this-conversation-never = 카드 없음: 이 대화에서 이 값이 나온 데이터셋을 한 번도 지칭하지 않았고, 뷰어가 데이터셋으로 지정됩니다.
cards-entities-card-more-all-of-them-in = { $rest }개 더, 모두 문서의 개체 패널에 있습니다.{ " " }
cards-entities-card-names-organisations-and-places-above = 위의 이름, 조직, 장소는 모델이 본문으로 읽은 내용입니다. 어떤 규칙도 검증하지 않았으므로 설명할 것도 없고 아무것도 열리지 않습니다.
cards-entities-card-nothing-extracted-from-this-document = 이 문서에서 추출된 내용이 없습니다.
chat-tool-cards-hide = 숨기기
chat-tool-cards-expand = 확장
chat-tool-cards-hide-raw-json = 원본 JSON 숨기기
chat-tool-cards-show-raw-json = 원본 JSON 표시
cards-result-cards-search-this = 이 검색
cards-result-cards-search-every-collection = 모든 컬렉션 검색
cards-result-cards-form = 폼 { $index }: { $form }
cards-result-cards-show-full-text = 전체 텍스트 표시
cards-result-cards-quote = 인용: { $quote }
cards-result-cards-reason = 이유: { $why }
cards-result-cards-open-question = 미해결 질문: { $question }
cards-result-cards-the-explore-gave-this-answer =
    탐색이 보드에 다음 답변을 제공했습니다: { $kind ->
        [sourced] 출처가 있는
        [inferred] 추론된
        [not_found] 찾지 못한
       *[other] 알 수 없는 종류
    } 발견 사항.
cards-result-cards-it-left-no-open-question = 미해결 질문이 없습니다.
cards-result-cards-open-questions-for-the-board = 보드의 미해결 질문:
cards-result-cards-arguments = 근거
cards-result-cards-list-after-the-call = 호출 후 목록: { $snapshot_goal }
cards-result-cards-replaces = { " " }· { $replaces_id } 대체
cards-result-cards-the-list-at-this-version = 이 버전의 목록은 저장되어 있지 않습니다.
web-search-card-these-sources-returned-nothing-so = 이 출처에서 반환한 내용이 없어 의도한 것보다 적은 출처에서 결과가 제공됩니다
web-search-card-u-degraded = ⚠ { $degraded_len } 손상됨
web-search-card-form = 폼 { $index }: { $form }
web-search-card-no-results-from = 결과 없음: { $degraded_text }
web-search-card-no-results-every-source-answered = 결과 없음. 모든 출처가 응답했지만 이 쿼리에 대한 내용은 없었습니다.
web-search-card-the-lowest-ranked-results-were = 이 호출이 트랜스크립트에 맞도록 가장 낮은 순위의 결과가 삭제되었습니다. 어시스턴트가 모두 확인했습니다.
web-search-card-view-search-details = 검색 상세 보기.
web-search-card-the-stored-result-could-not = 저장된 결과를 JSON로 다시 읽을 수 없습니다
web-search-card-nothing-was-stored-for-this = 이 호출에 대한 내용은 저장되지 않았습니다.
web-search-card-forms = 양식: { $forms }
web-search-card-kind = 유형: { $row_kind }
web-search-card-published = 게시: { $row_published }
web-search-card-loading-search-detail-u = 검색 세부 정보 로드 중…
web-search-card-could-not-load-the-search = 검색 세부 정보를 로드할 수 없습니다: { $e }
web-search-card-malformed-detail = 잘못된 세부 정보: { $e }
web-search-card-the-tool-returned-selected-results = 도구가 선택한 결과를 모델에 반환했습니다.
web-search-card-results-use-reciprocal-rank-fusion = 결과는 상호 순위 융합을 사용합니다.
web-search-card-returned-nothing = 아무것도 반환하지 않음: { $degraded }
web-search-card-all-candidates-use-fusion-order = 모든 후보가 융합 순서를 사용합니다.
web-search-card-the-cross-encoder-ranks-selected = 크로스 인코더가 선택한 결과를 순위 지정합니다.
web-search-card-selected-results-use-fusion-order = 선택한 결과가 융합 순서를 사용합니다.
web-search-card-search-detail = 검색 세부 정보
web-search-card-rrf = RRF #{ $row_rrf_rank }
chat-tool-disclosure-search-this = 이 항목 검색
chat-tool-disclosure-search-every-collection = 모든 컬렉션 검색
chat-tool-disclosure-hide = 숨기기
chat-tool-disclosure-expand = 펼치기
chat-tool-disclosure-this-step-was-recorded-before = 이 단계는 도구 인자와 결과가 저장되기 전에 기록되었습니다. 아래 요약만 사용할 수 있습니다.
chat-tool-disclosure-arguments = 인자
chat-tool-disclosure-result = 결과
chat-tool-disclosure-hide-raw-json = 원본 JSON 숨기기
chat-tool-disclosure-show-raw-json = 원본 JSON 표시
chat-tool-disclosure-input-json = 입력 JSON
chat-tool-disclosure-output-json = 출력 JSON
chat-transcript-ask-a-question-about-the = 컬렉션의 문서에 대해 질문하세요.
chat-transcript-suggested-next = 제안된 다음 단계…
chat-transcript-earlier-answer = 이전 답변
chat-transcript-tokens-the-conversation-carries-the = 대화에서 수행한 토큰, 이번 단계에서 청구된 최대 단일 컨텍스트 및 모델 창에서 사용된 양
chat-transcript-instruction-to-the-agent = 에이전트에 대한 지침
chat-transcript-the-context-stays-above-the = { " " }컨텍스트는 { $target } 목표 위에 유지됩니다.
chat-transcript-summary-parts-failed-the-record = { " " }{ $failed }개의 요약 부분이 실패했습니다. 기록에는 목록만 있습니다.
chat-transcript-show-the-record = 기록 표시
chat-transcript-hide-reasoning = 추론 숨기기
chat-transcript-show-reasoning = 추론 표시
chat-transcript-from-u-hide = { $count } { $noun } — { $tool }에서 숨기기
chat-transcript-from-u-show = { $count } { $noun } — { $tool }에서 표시
chat-transcript-u-hide = { $summary } — 숨기기
chat-transcript-u-show = { $summary } — 표시
chat-transcript-citations-of-this-conversation-give = 이 대화의 인용이 { $doc_handle }을(를) 여러 문서에 부여합니다. 답변은 그중 어느 것에도 연결하지 않습니다.
chat-transcript-report = { $label } 보고
chat-transcript-open-in-the-workspace = 작업 공간에서 열기
chat-transcript-this-version-could-not-be = 이 버전은 읽을 수 없습니다. 답변의 대화 텍스트가 이어집니다.
chat-transcript-files = 파일
chat-transcript-version = { $file_name }, 버전 { $file_version }
chat-web-find-exact-text = 정확한 텍스트 찾기
chat-web-previous-match = 이전 일치 항목
chat-web-next-match = 다음 일치 항목
chat-web-close-preview = 미리보기 닫기
chat-web-the-captured-page-could-not = 캡처한 페이지를 로드할 수 없습니다.
chat-web-loading = 로드 중…
chat-workspace-pane-workspace = 작업 공간
chat-workspace-pane-close-the-workspace = 작업 공간 닫기
chat-workspace-pane-close = 닫기
chat-workspace-pane-loading-the-files-u = 파일 로드 중…
chat-workspace-pane-the-files-could-not-be = 파일을 로드할 수 없습니다: { $error }
chat-workspace-pane-this-conversation-has-no-files = 이 대화에는 파일이 없습니다.
chat-workspace-pane-version = 버전 { $entry_version }, { $length_text_entry_chars }
chat-workspace-pane-choose-a-file-to-read = 읽을 파일을 선택하세요.
chat-workspace-pane-loading-the-file-u = 파일을 불러오는 중…
chat-workspace-pane-the-file-could-not-be = 파일을 불러올 수 없습니다: { $error }
chat-workspace-pane-version-2 = { $found_name }, 버전 { $found_version }
chat-board-create-collections = 컬렉션
chat-board-create-loading-collections-u = 컬렉션을 불러오는 중…
chat-board-create-hoover-search-new-board = Hoover 검색 - 새 보드
chat-board-create-ai-chat = AI 채팅
chat-board-create-new-investigation-board = 새 수사 보드
chat-board-create-a-board-runs-its-goals = 보드는 에이전트 탐색의 순서로 목표를 실행합니다. 각 탐색은 하나의 보드 발견 사항으로 끝나는 채팅입니다. 각 목표의 답변을 검토하고, 실행 중에 발견 사항을 거부하거나 힌트를 추가할 수 있습니다.
chat-board-create-title = 제목
chat-board-create-goal = 목표
chat-board-create-remove-this-goal = 이 목표 삭제
chat-board-create-remove = 삭제
chat-board-create-add-a-goal = 목표 추가
chat-board-create-context-optional = 맥락(선택 사항)
chat-board-create-hints-one-per-line-optional = 힌트, 줄당 하나(선� 선택 사항)
chat-board-create-sources = 출처
chat-board-create-internet-tools = 인터넷 도구
chat-board-create-creating-board = 보드를 만드는 중...
chat-board-create-create-board = 보드 만들기
ai-chat-board-hoover-search-board = Hoover 검색 - 보드
ai-chat-board-loading-the-board-u = 보드를 불러오는 중…
ai-chat-board-show-the-board-overview = 보드 개요 표시
ai-chat-board-zoom-out = 축소
ai-chat-board-zoom-in = 확대
ai-chat-board-u-ai-chat = ← AI 채팅
ai-chat-board-settings = 설정
ai-chat-board-board-settings = 보드 설정
ai-chat-board-internet-tools = 인터넷 도구
ai-chat-board-the-next-explores-of-the = 보드의 다음 탐색은 웹을 검색하고 웹 페이지를 읽을 수 있습니다. 진행 중인 탐색은 시작된 때의 설정을 유지합니다.
ai-chat-board-collections = 컬렉션
ai-chat-board-the-collections-are-fixed-when = 컬렉션은 보드가 생성될 때 고정됩니다.
ai-chat-board-confirm-drop = 드롭 확인
ai-chat-board-drop-the-board = 보드 드롭
ai-chat-board-close = 닫기
ai-chat-board-the-board-used-its-explore = 보드가 탐색 한도를 사용했습니다
ai-chat-board-the-board-used-explores-the = 보드가 { $explore_limit }개의 탐색을 사용했습니다. 이는 한 보드의 한도입니다. 더 이상 작업을 시작하지 않습니다. 제안된 답변은 여전히 결정할 수 있습니다.
ai-chat-board-create-a-new-board-to = 조사를 계속하려면 새 보드를 만드세요
ai-chat-board-goal = 목표
ai-chat-board-goals = 목표
ai-chat-board-add-new-goal = 새 목표 추가...
ai-chat-board-a-new-goal = 새 목표
ai-chat-board-add-goal = 목표 추가
ai-chat-board-a-board-has-at-most = 보드에는 최대 { $max_goals }개의 목표가 있습니다. 다른 목표로 새 보드를 만드세요.
ai-chat-board-background-context = 배경 정보
ai-chat-board-continue-with-a-correction = 수정하여 계속
ai-chat-board-correction-what-is-wrong-or = 수정: 잘못되거나 누락된 내용. 보드가 이를 이어갑니다.
ai-chat-board-the-board-waits-for-your = 보드가 검토를 기다립니다
ai-chat-board-the-board-used-its-budget = 보드가 { $snap_max_explores }개의 탐색을 포함한 예산을 사용했습니다.
ai-chat-board-the-assessments-gave-no-usable = 평가가 사용 가능한 방향을 주지 않았습니다.
ai-chat-board-accept-or-reject-the-proposed = 위의 각 목표에 대한 제안된 답변을 수락하거나 거부하세요. 거부된 답변은 보드가 즉시 계속 진행하게 합니다.
ai-chat-board-no-proposed-answer-waits-for = 결정 대기 중인 제안된 답변이 없습니다.
ai-chat-board-reopen-the-board-to-continue = 열린 목표를 계속하려면 보드를 다시 여세요. 발견 사항과 답변을 유지합니다.
ai-chat-board-close-the-board-to-accept = 보드를 닫아 모든 제안된 답변을 수락하고 중단하거나, 수정하여 계속 진행하세요.
ai-chat-board-close-the-board = 보드 닫기
ai-chat-board-or-reopen-the-board-to = 또는 수정 없이 열린 목표를 계속하려면 보드를 다시 여세요.
ai-chat-board-the-board-is-complete = 보드가 완성되었습니다
ai-chat-board-a-goal-has-no-accepted = 목표에 수락된 답변이 없습니다. 보드를 다시 열어 계속하세요. 보드는 발견 사항과 답변을 유지합니다.
ai-chat-board-add-a-hint = 힌트 추가
ai-chat-board-the-next-assessment-reads-every = 다음 평가는 모든 단서를 읽습니다. 단서는 질문에 대한 탐색에도 답합니다.
ai-chat-board-add-hint = 단서 추가
ai-chat-board-events = 이벤트
ai-chat-board-newest-first = 최신순
ai-chat-board-date = 날짜
ai-chat-board-actor = 수행자
ai-chat-board-event = 이벤트
ai-chat-board-show-details = 세부 정보 표시
ai-chat-board-open = 열기
ai-chat-board-show-the-newest-events = 최신 { $event_rows }개 이벤트 표시
ai-chat-board-show-all-events = 모든 { $snap_events_len }개 이벤트 표시
ai-chat-board-statistics = 통계
ai-chat-board-explores = 탐색
ai-chat-board-model-steps-per-explore = 탐색당 모델 단계
ai-chat-board-assessments = 평가
ai-chat-board-intents = 의도
ai-chat-board-findings = 발견 사항
ai-chat-board-created = 생성됨
ai-chat-board-rejected-this-finding-on-the = { $rejected_by }이(가) { $format_utc_ms_fact_rejected_ms }에서 이 발견 사항을 거부했습니다. 보드에서 더 이상 사용하지 않습니다.
ai-chat-board-rejected-this-finding-the-board = { $rejected_by }이(가) 이 발견 사항을 거부했습니다. 보드에서 더 이상 사용하지 않습니다.
ai-chat-board-no-reason-was-given = 이유가 제공되지 않았습니다.
ai-chat-board-reason = 이유: { $fact_rejected_reason }
ai-chat-board-open-questions = 미해결 질문
ai-chat-board-explored-in = 다음에서 탐색
ai-chat-board-explore-this-question = 이 질문 탐색
ai-chat-board-your-questions = 질문
ai-chat-board-ask-about-the-background-context = 배경 맥락에 대해 물으세요
ai-chat-board-ask-about-this-finding = 이 발견 사항에 대해 물으세요
ai-chat-board-a-follow-up-question-about = 이 노드에 대한 후속 질문
ai-chat-board-ask = 물으세요
ai-chat-board-checks-that-changed-this-finding = 이 발견 사항을 변경한 검사
ai-chat-board-reject-this-correction = 이 수정 거부
ai-chat-board-reject-this-finding = 이 발견 사항 거부
ai-chat-board-not-answered-the-board-was = 답변이 없습니다. 이 목표에 대한 답변 없이 보드가 종료되었습니다. 힌트나 재개시를 답변을 열어 다시 활성화합니다.
ai-chat-board-no-answer-yet = 아직 답변이 없습니다.
ai-chat-board-the-findings-of-this-answer = 이 답변의 발견 사항은 아무것도 찾지 못한 검색입니다. 받아들이면 기록이 목표를 답하지 않음을 기록하고, 거부하면 조사를 계속합니다.
ai-chat-board-open-an-assessment-to-read = { "." } 이유를 읽으려면 평가를 엽니다.
ai-chat-board-from-the-findings = 발견 사항에서{ " " }
ai-chat-board-accept-answer = 답변 받아들이기
ai-chat-board-why-the-answer-is-wrong = 답변이 틀렸거나 불완전한 이유
ai-chat-board-reject-answer = 답변 거부
ai-chat-board-intent = 의도
ai-chat-board-attempts-declared = 시도: { $intent_attempts }. 선언된 { $format_utc_ms_intent_created_ms }.
ai-chat-board-the-explore-asked = 탐색이 물었습니다
ai-chat-board-add-a-hint-in-the = 보드 개요에 답하기 위한 힌트를 추가합니다.
ai-chat-board-last-error = 마지막 오류
ai-chat-board-brief = 간략
ai-chat-board-open-the-explore-chat = 탐색 채팅 열기
ai-chat-board-loading-the-assessment-u = 평가 로딩 중…
ai-chat-board-assessment = 평가 { $reason_no }
ai-chat-board-model-outcome-ms = { $format_utc_ms_a_created_ms }. 모델 { $a_model }. 결과 { $a_outcome }. { $a_latency_ms } ms, { $tokens }.
ai-chat-board-checks-that-changed-it = 이를 변경한 검사
ai-chat-board-prompt = 프롬프트
ai-chat-board-this-assessment-ran-before-the = 이 평가는 프롬프트가 저장되기 전에 실행되었습니다.
ai-chat-board-response = 응답
ai-chat-history-hoover-search-chat-history = Hoover 검색 - 채팅 기록
ai-chat-history-u-back = ← 뒤로
ai-chat-history-conversation-history = 대화 기록
ai-chat-history-show-board-chats = 보드 채팅 표시
ai-chat-history-loading-u = 로딩 중…
ai-chat-history-could-not-load-history = 역사를 불러올 수 없습니다: { $e }
ai-chat-history-no-conversations-yet = 아직 대화가 없습니다.
ai-chat-history-board = 보드
ai-chat-history-new-chat = 새 채팅
ai-chat-history-messages-updated = { $s_message_count }개 메시지 · 업데이트 시점 { $s_updated_at }
ai-chat-history-delete-conversation = 대화 삭제
ai-chat-history-delete = 삭제
ai-chat-homepage-hoover-search-ai-chat = Hoover 검색 - AI 채팅
ai-chat-homepage-what-are-you-researching = 무엇을 연구하시겠습니까?
ai-chat-homepage-view-all-conversations = 모든 대화 보기
ai-chat-homepage-starting-conversation-u = 대화 시작…
ai-chat-homepage-investigation-boards = 조사 보드
ai-chat-homepage-new-board = 새 보드
ai-chat-homepage-loading-boards-u = 보드 불러오는 중…
ai-chat-homepage-could-not-load-the-boards = 보드를 불러올 수 없습니다: { $user_facing_message_e }
ai-chat-homepage-you-have-no-board-a = 보드가 없습니다. 보드는 여러 에이전트 탐색을 순서대로 실행하는 장기 조사이며, 답변을 검토합니다.
ai-chat-homepage-updated = 업데이트 시점 { $format_utc_ms_board_updated_ms }
ai-chat-session-hoover-search-ai-chat = Hoover 검색 - AI 채팅
ai-chat-session-this-conversation-could-not-be = 이 대화를 불러올 수 없습니다.
ai-chat-session-loading-u = 불러오는 중…
ai-chat-session-u-chats = ← 채팅
ai-chat-session-history = 역사
ai-chat-session-show-the-files-that-the = 이 대화에서 어시스턴트가 작성한 파일 보기
ai-chat-session-workspace = 작업 공간
ai-chat-session-this-answer-was-interrupted-before = 이 답변은 페이지나 서버가 중간에 멈춰 완성되기 전에 중단되었습니다. 다시 물어보아 다시 시도하십시오.
ai-chat-session-dismiss = 닫기
ai-chat-session-board-explore-chats-are-read = 보드 탐색 채팅은 읽기 전용입니다.{ " " }
ai-chat-session-open-the-board = 보드 열기
chat-locked-options-on = { $label }: 켜짐
chat-locked-options-off = { $label }: 꺼짐
chat-tool-cards-running-u = 실행 중…
cards-result-cards-quote-found = 인용 발견
cards-result-cards-quote-not-found = 인용을 찾을 수 없음
cards-result-cards-quote-not-checked = 인용을 확인하지 않음
web-search-card-results = { $results_len }개 결과
chat-tool-disclosure-running-u = 실행 중…
chat-transcript-call = 호출
chat-transcript-calls = 호출
ai-chat-board-a-board-without-collections-needs = 컬렉션이 없는 보드에는 인터넷 도구가 필요합니다.
ai-chat-board-of = { $snap_max_explores } 중 { $snap_explores_used }
ai-chat-board-assessment-2 = 평가 { $number }
ai-chat-history-messages = { $s_message_count }개 메시지
web-search-card-reranked-in = 크로스 인코더가 { $ms }ms 안에 결과를 재순위화했습니다.
web-search-card-engine-results = { $name }: { $count }개, { $ms }ms
web-search-card-score-was-rank = 점수 { $score } · 이전 RRF 순위 { $rank }위
chat-activity-the-turn-waits-for-a = 이번 턴이 사용 가능한 모델 슬롯을 기다리는 중입니다.
chat-activity-the-turn-waits-for-a-2 = 이번 턴이 사용 가능한 도구 슬롯을 기다리는 중입니다.
chat-locked-options-start-a-new-chat-to = 이 설정을 변경하려면 새 채팅을 시작하세요.
chat-locked-options-internet-tools = 인터넷 도구
chat-session-card-new-chat = 새 채팅
chat-tool-cards-first-frame-of-the-video = 동영상 첫 프레임
chat-tool-cards-screenshot-of = 스크린샷:
chat-tool-cards-image = 이미지
cards-result-cards-the-agent-asked-a-question = 에이전트가 질문했습니다.
chat-transcript-hide = 숨기기
chat-transcript-show = 표시
chat-transcript-unverified-quote-the-quoted-span = 미인증 인용. 인용된 구문이 너무 짧아 확인할 수 없습니다.
chat-transcript-unverified-quote-the-document-text = 미인증 인용. 문서 텍스트를 읽을 수 없습니다.
chat-transcript-unverified-quote-this-wording-was = 미인증 인용. 문서에서 이 표현을 찾을 수 없습니다.
chat-board-create-select-a-collection-or-turn = 컬렉션을 선택하거나 인터넷 도구를 켜세요.
chat-board-create-select-at-least-one-collection = 최소 하나의 컬렉션을 선택하세요.
ai-chat-board-active = 활성
ai-chat-board-paused = 일시정지
ai-chat-board-waits-for-review = 검토 대기
ai-chat-board-completed = 완료
ai-chat-board-dropped = 중단
ai-chat-board-unknown = 알 수 없음
ai-chat-board-pause-the-board = 보드 일시정지
ai-chat-board-resume-the-board = 보드 계속
ai-chat-board-none = 없음
ai-chat-board-reopen-with-the-remaining-budget = 남은 예산으로 다시 열기
ai-chat-board-finding = 발견 사항
ai-chat-board-why-the-correction-is-wrong = 수정이 잘못된 이유
ai-chat-board-reject-correction = 수정 거부
ai-chat-board-why-the-finding-is-wrong = 발견 사항이 잘못된 이유
ai-chat-board-reject-finding = 발견 사항 거부
ai-chat-board-answer = 답변
ai-chat-board-proposed-answer = 제안된 답변
ai-chat-homepage-active = 활성
ai-chat-homepage-paused = 일시정지
ai-chat-homepage-waits-for-review = 검토 대기
ai-chat-homepage-completed = 완료
ai-chat-homepage-dropped = 중단
ai-chat-homepage-unknown = 알 수 없음
cards-result-cards-submitted-by-board =
    보드가 제출한: { $kind ->
        [sourced] 출처가 있는
        [inferred] 추론된
        [not_found] 찾을 수 없는
       *[other] 알 수 없는 유형
    } 발견 사항 (보고서 기준)
cards-result-cards-finding-for-board =
    { $kind ->
        [sourced] 출처가 있는
        [inferred] 추론된
        [not_found] 찾을 수 없는
       *[other] 알 수 없는 유형
    } 보드 발견 사항
chat-transcript-compacting = 맥락 압축 중: { $before } 토큰을 목표 { $target }로.
chat-transcript-compaction-failed = 이전 단계의 요약에 실패했습니다. 모델이 이전 단계를 그대로 받아 { $after } 토큰.
chat-transcript-compacted = 맥락 압축 완료: { $steps }단계 요약, { $before } 토큰 → { $after }.
ai-chat-board-reopen-with-more = { $grant }번의 추가 탐색으로 다시 열기
ai-chat-board-goal-number = 목표 { $number }
ai-chat-board-from-assessment-on = { $date } 평가 { $number }에서.
ai-chat-board-from-assessment = 평가 { $number }에서.
chat-board-create-goal-2 = 목표 { $index_1 }
ai-chat-session-lost-contact-with-the-chat = 채팅과 연결이 끊어졌습니다: { $e }
ai-chat-session-could-not-stop-the-answer = 답변을 멈출 수 없습니다: { $e } — 아직 실행 중
ai-chat-board-later-assessments-dropped-an-answer = 이 목표에 대한 후속 평가 { $n }개가 답변을 삭제했습니다:
ai-chat-board-prompt-and-completion-tokens = 프롬프트 토큰 { $a_prompt_tokens } 및 완성 토큰 { $a_completion_tokens }
ai-chat-homepage-completed-goals-not-answered = 완료됨, { $n }개 목표 미답변
board-graph-intent = 의도, { $state }
chat-workspace-pane-characters = { $chars }자
chat-transcript-running-tool = { $tool_run_summary_messages_start_end_run_ } + { $joined_live_end } 실행 중 도구 { $if_joined_live_end_1_tr_chat_transcript_ }
chat-transcript-running-tool-2 = { $turn_tool_rows_len } 실행 중 도구 { $if_turn_tool_rows_len_1_tr_chat_transcri }
chat-transcript-answered-after-failed-attempt = { $retries_len }번의 실패한 시도 후 답변했습니다{ $if_retries_len_1_else_s }
chat-transcript-failed-attempt = { $retries_len } 실패한 시도{ $if_retries_len_1_else_s }
chat-transcript-version-2 = { $report_name }, 버전 { $report_version }
tool-run-summary-searched =
    { $n ->
       *[other] 용어 { $n }개 검색
    }
tool-run-summary-read =
    { $n ->
       *[other] 문서 { $n }개 읽기
    }
tool-run-summary-searched-the-web-for =
    { $n ->
       *[other] 웹에서 용어 { $n }개 검색
    }
tool-run-summary-read-web =
    { $n ->
       *[other] 웹 페이지 { $n }개 읽기
    }
tool-run-summary-browser =
    { $n ->
       *[other] 브라우저 작업 { $n }회
    }
tool-run-summary-listed-the-entities-of =
    { $n ->
       *[other] 문서 { $n }개의 개체 나열
    }
tool-run-summary-cited =
    { $n ->
       *[other] 문서 { $n }개 인용
    }
tool-run-summary-cited-web =
    { $n ->
       *[other] 웹 페이지 { $n }개 인용
    }
tool-run-summary-read-and-tool-texts =
    { $n ->
       *[other] 스킬 및 도구 텍스트 { $n }개 읽기
    }
tool-run-summary-saved =
    { $n ->
       *[other] 메모 { $n }개 저장
    }
tool-run-summary-todo-list =
    { $n ->
       *[other] 할 일 목록 호출 { $n }회
    }
tool-run-summary-to-the-agent =
    { $n ->
       *[other] 에이전트에 지시 { $n }회
    }
tool-run-summary-other =
    { $n ->
       *[other] 기타 호출 { $n }회
    }
tool-run-summary-failed = { $failures }회 실패
tool-run-summary-took = { $duration_text_ms } 소요
chat-session-card-messages = { $session_message_count }개 메시지
chat-tool-disclosure-item =
    { $count ->
       *[other] { $count }개 항목
    }
chat-tool-disclosure-field =
    { $count ->
       *[other] { $count }개 필드
    }
chat-tool-disclosure-searched-collections = 검색한 컬렉션{ $filters }
chat-tool-disclosure-searched-collections-2 = 검색한 컬렉션 · { $query }{ $filters }
chat-tool-disclosure-cited-documents = 인용한 { $n }개 문서
chat-tool-disclosure-read-document = 문서 읽기 · { $path }
chat-tool-disclosure-searched-the-web = 웹 검색 · { $q }
chat-tool-disclosure-opened-page = 페이지 열기 · { $u }
chat-tool-disclosure-whois = whois · { $d }
chat-tool-disclosure-called = 호출한 { $other }
chat-tool-disclosure-called-2 = 호출한 { $other } · { $short }
cards-browser-card-opened = { $url } 열기
cards-browser-card-could-not-open = { $url } 열 수 없음
cards-browser-card-clicked = { $element } 클릭
cards-browser-card-could-not-click = { $element } 클릭할 수 없음
cards-browser-card-typed-into = { $element }에 입력
cards-browser-card-could-not-type-into = { $element }에 입력할 수 없음
cards-browser-card-typed = “{ $text }” 입력
cards-browser-card-could-not-type = “{ $text }” 입력할 수 없음
cards-browser-card-pressed = { $key } 누름
cards-browser-card-could-not-press = { $key } 누를 수 없음
cards-browser-card-chose-an-option-in = { $element }에서 옵션 선택
cards-browser-card-could-not-choose-an-option = { $element }에서 옵션을 선택할 수 없음
cards-browser-card-hovered = { $element }에 마우스 올림
cards-browser-card-could-not-hover = { $element }에 마우스 올릴 수 없음
cards-browser-card-failed = { $bare } — 실패
cards-entities-card-listed-entities-document = 개체 목록 · { $count } 문서{ $if_count_1_else_s }
chat-tool-cards-read-more-part-of = read_more · { $name }의 { $part }부분 #{ $seq }
cards-result-cards-documents = { " " }· { $value } 문서
cards-result-cards-forms = { $tool_name } · { $forms } 폼
cards-result-cards-in = { " " }{ $collections }에서
cards-result-cards-page = { " " }· { $value } 페이지
cards-result-cards-cite-documents-documents-quotes-not = cite_documents · { $citations_len } 문서 · { $missing } 인용을 찾지 못했습니다
cards-result-cards-version-unchanged = { $tool_name } · 버전 { $version } · 변경 없음
cards-result-cards-version = { $tool_name } · 버전 { $version }
web-search-card-results-in-after-deduplication = { $json_u64_doc_total_before_dedupe }개의 결과가 있습니다. 중복 제거 후 { $json_u64_doc_total_after_dedupe }개
