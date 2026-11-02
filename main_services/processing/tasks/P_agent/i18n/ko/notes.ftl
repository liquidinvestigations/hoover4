# The notes that the worker writes into a run, and the text of a turn that the worker ends.
# The model reads each note. The transcript shows the notes and the ending to the person.
# The worker reads plain text and { $name } variables only (`tasks.P_agent.notes`).

## Discovery

note-discovery-l2 = 최근 두 번의 검색에서 새 출처를 찾지 못했습니다. 지금 가장 적합한 결과 페이지를 읽으십시오. 해당 URL을 최대 6개까지 `urls` 목록에 넣어 read_page를 한 번 호출하십시오. 검색은 다른 질문으로만 다시 하십시오.
note-discovery-l3-web = 출처 페이지를 하나도 읽기 전에 답변했습니다. 항목을 뒷받침하는 페이지의 URL을 최대 6개까지 `urls` 목록에 넣어 read_page를 한 번 호출하십시오. 그런 다음 이를 뒷받침하는 출처로 답변을 다시 작성하십시오.
note-discovery-l3-documents = 문서를 하나도 읽기 전에 답변했습니다. 항목을 뒷받침하는 문서를 read_documents로 읽으십시오. 한 번의 호출에 여러 파일 해시를 넣으십시오. 그런 다음 이를 뒷받침하는 출처로 답변을 다시 작성하십시오.
note-discovery-l4 = 요청에 답할 수 있는 결과 페이지를 지금 읽으십시오. 해당 URL을 최대 6개까지 `urls` 목록에 넣어 read_page를 한 번 호출하십시오. 한 번의 호출로 모든 페이지를 동시에 읽습니다.

## Page captures

note-capture-empty = { $urls }의 캡처에 기사 텍스트가 없습니다. 다른 출처를 읽으십시오. 이 페이지를 인용하지 마십시오.

## Sources

note-web-tools-absent = 이 턴에는 웹 도구가 없으므로 공개 웹 페이지를 읽을 수 없습니다. 선택한 컬렉션을 사용하고, 요청 중 컬렉션으로 답할 수 없는 부분을 명시하십시오.
note-sources-documents = 허용된 문서 컬렉션을 먼저 검색하십시오. 관련 문서를 읽으십시오.
note-sources-documents-before-web = 허용된 문서 컬렉션을 먼저 검색하십시오. 관련 문서를 읽으십시오. 웹을 사용하기 전에 해당 문서를 읽으십시오.

## Named things

note-absent-collection = 이름이 { $name }인 허용된 컬렉션은 없습니다. 허용된 컬렉션은 { $collections }입니다.
note-absent-name = 선택한 컬렉션에는 { $name }에 대해 색인된 일치 항목이 없습니다.
note-absent-close-forms = 색인된 유사한 형태: { $forms }. 유사한 형태를 요청받은 이름으로 사용하지 마십시오. 유사한 형태로 검색한 경우 답변에서 다른 철자라고 밝히십시오.
note-absent-close-form = { $form } (문서 { $count }개)
note-absent-web = 이 턴의 웹 도구로 해당 이름을 검색할 수 있습니다.

## Search progress

note-progress-level = 검색 진행 단계 { $level }.
note-progress-searches = 이미 실행한 검색:
note-progress-search = { $name } { $args }: 항목 { $items }개, 키워드 일치 { $matches }개.
note-progress-available = 아직 가능한 검색 단계:
note-progress-complete = 가능한 검색 단계를 모두 마쳤습니다.
note-progress-write-now = 지금 답변이나 보고서를 작성하십시오. 읽은 출처에 없는 내용을 밝히고 실행한 검색을 명시하십시오.
note-progress-answer-next = 다음 응답은 답변이어야 합니다. 확인하지 못한 사실과 실행한 검색을 밝히십시오.
note-progress-step-quoted = search_collections로 각 이름을 따옴표로 묶은 구문으로 검색하십시오.
note-progress-step-variants = 따옴표 없이 단어와 이름 변형으로 검색하십시오. 단어 수와 철자 후보를 읽으십시오.
note-progress-step-filters = 필터를 하나씩 제거하고 필터 없이 검색하십시오.
note-progress-step-facets = search_facet_values로 필터 값을 확인하십시오.
note-progress-step-dates = search_histogram으로 날짜를 확인하십시오.
note-progress-step-passages = search_passages로 내용 설명을 검색하십시오.
note-progress-step-folder = 요청받은 폴더, 경로 또는 파일에는 { $tool }을(를) 사용하십시오.
note-progress-step-read-hits = { $tool }(으)로 가장 좋은 검색 결과 1~3개를 읽으십시오.
note-progress-step-web-search = web_search로 웹을 검색하고 가장 좋은 결과 페이지를 읽으십시오.
note-progress-step-page-find = read_page와 find로 긴 페이지의 보관된 텍스트를 검색하십시오.
note-progress-step-page-retry = 다른 결과 주소를 읽거나, 실패한 페이지의 보관된 사본을 읽으십시오.
note-advice-stuck = 채팅 검사의 추정으로는 최근 검색이 같은 결과를 반복하고 있습니다. no_results 스킬이 검색의 다른 형태를 설명합니다.
note-advice-absent = 채팅 검사의 추정으로는 결과에 작업이 요구하는 내용이 없습니다. 없다고 보고하기 전에 검색한 범위를 밝히십시오.
note-advice-completion = 채팅 검사의 추정으로는 결과로 작업에 답할 수 있습니다. 답변하기 전에 요청받은 각 부분을 읽은 출처와 비교하십시오.
note-progress-ended = 진전 없는 검색이 반복되어 실행이 끝났습니다.
note-progress-ended-none = 키워드가 일치하는 출처를 찾지 못했습니다.
note-progress-ended-some = 검색에서 키워드가 일치하는 출처 { $count }개를 찾았습니다. 에이전트가 답변을 완성하지 못했습니다.
note-progress-ended-searches = 실행한 검색:
