#!/bin/bash
# Run one chat turn for each agent language and record the detected answer language.
#
# Usage, from the repository root, with the local stack up:
#
#   scripts/i18n/check_agent_languages.sh OUT_DIR [PROMPT_NAME] [CODES]
#
# PROMPT_NAME is a prompt of website/tools/chat_observer.py (default: document-comparison,
# which searches two collections, reads documents and cites them). CODES is a
# comma-separated list (default: the 21 supported codes). The turns run one after another,
# because the agent language is a setting of the test user.
#
# For each code the script runs website/observe-chat.sh with --agent-language, then
# scripts/i18n/check_answer_language.py on the session of the turn. OUT_DIR gets:
#   <code>.observer.log   the observer output, with the run folder of the turn
#   <code>.session        the session id
#   <code>.jsonl          one detection result per answer, follow-up and title
#   <code>.answer.md      the stored answer text
#   <code>.prompt.txt     the system prompt that the turn pinned
#   summary.tsv           code, observer exit, answer language, score, follow-up matches
# Language detection is one signal of the answer language. Read the answers for quality.
set -uo pipefail

OUT="${1:?usage: check_agent_languages.sh OUT_DIR [PROMPT_NAME] [CODES]}"
PROMPT="${2:-document-comparison}"
CODES="${3:-en,de,es,fr,pl,pt,ar,he,hi,zh,it,nl,da,nb,sv,el,hr,ro,ru,ja,ko}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TARGET="${HOOVER4_SITE_URL:-http://hoover4-development-auth-backdoor:8080}"
mkdir -p "$OUT"
printf 'code\tobserver_exit\tanswer_language\tscore\tfollow_ups_matching\n' > "$OUT/summary.tsv"

for code in ${CODES//,/ }; do
    echo "== $code =="
    (cd "$ROOT/website" && ./observe-chat.sh --target "$TARGET" --prompts "$PROMPT" \
        --resolutions 1080p --no-followup --agent-language "$code") > "$OUT/$code.observer.log" 2>&1
    status=$?
    run=$(grep -o 'test_reports/chat_observer/run-[^ ]*/chat' "$OUT/$code.observer.log" | tail -1)
    conversation="$ROOT/website/$run/$PROMPT/conversation.json"
    session=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['session_url'].split('/c/')[1].split('/')[0])" "$conversation" 2>/dev/null)
    if [ -z "$session" ]; then
        printf '%s\t%s\t-\t-\t-\n' "$code" "$status" >> "$OUT/summary.tsv"
        continue
    fi
    echo "$session" > "$OUT/$code.session"
    docker exec -i hoover4-worker sh -lc "cd /app && uv run python - --expected $code $session" \
        < "$ROOT/scripts/i18n/check_answer_language.py" > "$OUT/$code.jsonl" 2>/dev/null
    docker exec hoover4-worker sh -lc "cd /app && uv run python -c \"
import json, sys
from database.clickhouse import get_global_client
with get_global_client() as c:
    answer = c.query(\\\"SELECT content FROM chat_messages FINAL WHERE session_id = {s:String} AND role = 'assistant' ORDER BY seq DESC LIMIT 1\\\", parameters={'s': '$session'}).result_rows
    usage = c.query(\\\"SELECT usage_json FROM agent_run_messages FINAL WHERE session_id = {s:String} AND idx = 0 LIMIT 1\\\", parameters={'s': '$session'}).result_rows
open('/tmp/answer.md', 'w').write(answer[0][0] if answer else '')
assets = json.loads(usage[0][0]).get('control', {}).get('assets', {}) if usage else {}
open('/tmp/prompt.txt', 'w').write(assets.get('system_prompt', ''))
\"" >/dev/null 2>&1
    docker cp hoover4-worker:/tmp/answer.md "$OUT/$code.answer.md" >/dev/null 2>&1
    docker cp hoover4-worker:/tmp/prompt.txt "$OUT/$code.prompt.txt" >/dev/null 2>&1
    python3 - "$OUT/$code.jsonl" "$code" "$status" >> "$OUT/summary.tsv" <<'EOF'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1]) if line.strip()]
answers = [r for r in rows if r["kind"] == "answer"]
follow = [r for r in rows if r["kind"] == "follow_up"]
last = answers[-1] if answers else {"language": "-", "score": "-"}
print(f"{sys.argv[2]}\t{sys.argv[3]}\t{last['language']}\t{last['score']}\t"
      f"{sum(r['match'] for r in follow)}/{len(follow)}")
EOF
done
cat "$OUT/summary.tsv"
