#!/usr/bin/env bash
# Contract check for the eighteen agent routes under /api/agent/v1/.
#
# Runs every request through `curl` inside hoover4-website, against the
# already-running site on localhost:8080. Prints one PASS or FAIL line a
# case, and exits nonzero on the first failure. Read `website/Readme.md`,
# "Agent routes", for what the routes and the identity rule do.
#
# Setup, once, idempotent:
#   1. syncs a non-admin test user "agent-contract-user" in the group
#      "agent-contract-group", through the same header path a browser uses;
#   2. grants that group read access to the "testdata" and "other"
#      collections, directly in ClickHouse, because no local collection is
#      public and the admin write path needs an authenticated session this
#      script does not create. "reruns" stays ungranted, so it is the
#      forbidden-collection case.
#
# Needs the corpus `main_services/verify-stack.sh` ingests (testdata,
# other). Four table routes (tables/overview, tables/page,
# tables/column_values, tables/search_cells) find no table document in that
# corpus: the local stack has never ingested a spreadsheet. Those four cases
# accept the typed 404 a nonexistent file hash produces, which still proves
# the route, the identity branch and the permission check all run; a 200 for
# them needs a table fixture this script does not add.
set -uo pipefail

SITE="${HOOVER4_WEBSITE_CONTAINER:-hoover4-website}"
CH="${CH_CONTAINER:-clickhouse}"
BASE_URL="http://localhost:8080"
FAILED=0

curl_site() {
  docker exec "$SITE" curl -sS -w '\n%{http_code}' --max-time 20 "$@"
}

ch_query() {
  docker exec -i "$CH" sh -lc \
    'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "$1"' _ "$1"
}

# Runs one case: a name, the expected HTTP status, a curl argument list, and
# a Python snippet that reads the JSON body from stdin and exits nonzero if
# a required field is missing or the wrong shape. Prints PASS/FAIL and, on
# failure, stops the whole script: a later case may depend on setup a
# failure this early means never happened correctly.
run_case() {
  local name="$1" expected_status="$2"
  shift 2
  local py="$1"
  shift
  local response status body
  response="$(curl_site "$@")"
  status="${response##*$'\n'}"
  body="${response%$'\n'*}"
  if [ "$status" != "$expected_status" ]; then
    echo "FAIL $name: expected HTTP $expected_status, got $status: $body"
    FAILED=1
    exit 1
  fi
  if [ -n "$py" ] && ! printf '%s' "$body" | docker exec -i "$SITE" python3 -c "$py"; then
    echo "FAIL $name: HTTP $status but the body did not match: $body"
    FAILED=1
    exit 1
  fi
  echo "PASS $name (HTTP $status)"
}

AGENT_HEADER=(-H "x-hoover4-user: agent-contract-user")
JSON_HEADER=(-H "content-type: application/json")
POST=(-X POST)

# ---------------------------------------------------------------------------
# Setup: sync the test user and group, then grant two of the three local
# collections to the test group.
# ---------------------------------------------------------------------------

echo "== setup =="
docker exec "$SITE" curl -sS -o /dev/null -w '%{http_code}\n' --max-time 20 \
  -H 'X-Forwarded-User: agent-contract-user' \
  -H 'X-Forwarded-Groups: agent-contract-group' \
  "$BASE_URL/" >/dev/null
ch_query "INSERT INTO Hoover4_Processing.collection_group_permissions \
  (groupname, collectionname, created_at, updated_at, is_deleted) VALUES \
  ('agent-contract-group','testdata',now(),now(),0), \
  ('agent-contract-group','other',now(),now(),0)"
echo "test user and group grants are in place (testdata, other; reruns stays forbidden)"

# ---------------------------------------------------------------------------
# Identity refusals
# ---------------------------------------------------------------------------

echo "== identity refusals =="
run_case "proxy header is refused" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" -H 'X-Forwarded-User: someone' "$BASE_URL/api/agent/v1/collections/list"

run_case "session cookie is refused" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" --cookie 'hoover4_session=abcdef' "$BASE_URL/api/agent/v1/collections/list"

run_case "missing x-hoover4-user is refused" 401 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="unauthenticated", b' \
  "${POST[@]}" "$BASE_URL/api/agent/v1/collections/list"

run_case "unknown user is refused" 401 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="unauthenticated", b' \
  "${POST[@]}" -H 'x-hoover4-user: nobody-ever-synced' "$BASE_URL/api/agent/v1/collections/list"

# ---------------------------------------------------------------------------
# Permission: a collection outside the granted set is 403, not 404
# ---------------------------------------------------------------------------

echo "== permission =="
run_case "a forbidden collection is refused" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"reruns"}' "$BASE_URL/api/agent/v1/folders/overview"

# ---------------------------------------------------------------------------
# The eighteen routes, against the local testdata/other corpus
# ---------------------------------------------------------------------------

echo "== routes =="

TESTFILES_DOC="2ce1a51f0da95159ef2ea05b121c69545e6d1e9d8838fe3a93a84871e7d45924"
TWO_SOURCE_DOC="362795986fa1e723efab28ec1141f6446e4658d61b14fc1a927b7fb1f97724e5"
PDF_DOC="d21ccff5b16f15e99148bc3faaa2a2975b071a18fbd1562c9a429c634ad3aee3"
EMAIL_DOC="197784dcd954fcccb38fc810a43fde0e9f66047abf034f05a8764bd22983e6fb"
NO_SUCH_HASH="0000000000000000000000000000000000000000000000000000000000000000000000"

run_case "collections/list" 200 \
  'import json,sys; b=json.load(sys.stdin); names={c["collectionname"] for c in b["collections"]}; assert "testdata" in names, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "$BASE_URL/api/agent/v1/collections/list"

run_case "search/results" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["documents"] and b["total_count"]>0 and any(d["size"] is not None for d in b["documents"]), b; assert b["facet_counts"]["collection_dataset"] and b["facet_counts"]["file_types"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"query":""}' "$BASE_URL/api/agent/v1/search/results"

run_case "search/facet_values" 200 \
  'import json,sys; b=json.load(sys.stdin); assert "terms" in b and "resolved" in b, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"facet":"file_type"}' "$BASE_URL/api/agent/v1/search/facet_values"

run_case "search/date_histogram" 200 \
  'import json,sys; b=json.load(sys.stdin); assert "buckets" in b and b["date_field"]=="date", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"query":"","date_field":"date"}' "$BASE_URL/api/agent/v1/search/date_histogram"

run_case "search/entity_explainer" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["explanation"] is not None and b["explanation"]["title"], b; assert b["documents"] and all(d["file_hash"] and d["path"] for d in b["documents"]), b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","entity_type":"email.basic","entity_value":"{\"address\":\"author@nrim.go.jp\",\"domain\":\"nrim.go.jp\",\"kind\":\"email\",\"local\":\"author\"}"}' \
  "$BASE_URL/api/agent/v1/search/entity_explainer"

run_case "documents/read" 200 \
  'import json,sys; b=json.load(sys.stdin); assert len(b["documents"])==1 and b["documents"][0]["text"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":[\"$TESTFILES_DOC\"]}" "$BASE_URL/api/agent/v1/documents/read"

run_case "documents/sources" 200 \
  'import json,sys; b=json.load(sys.stdin); names={s["source"] for s in b["sources"]}; assert {"raw_text","extractous"} <= names, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TWO_SOURCE_DOC\"}" "$BASE_URL/api/agent/v1/documents/sources"

run_case "documents/metadata" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["path"] and b["download_links"]["original"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TESTFILES_DOC\"}" "$BASE_URL/api/agent/v1/documents/metadata"

run_case "documents/email" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["envelope"]["subject"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"other\",\"file_hash\":\"$EMAIL_DOC\"}" "$BASE_URL/api/agent/v1/documents/email"

run_case "documents/diff_sources" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["source_a"]=="raw_text" and b["source_b"]=="extractous", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TWO_SOURCE_DOC\",\"source_a\":\"raw_text\",\"source_b\":\"extractous\"}" \
  "$BASE_URL/api/agent/v1/documents/diff_sources"

run_case "documents/pdf_search" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["hit_count"]>0, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$PDF_DOC\",\"query\":\"the\",\"source\":\"\"}" \
  "$BASE_URL/api/agent/v1/documents/pdf_search"

run_case "tables/overview (no table document in the corpus)" 404 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="not_found", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\"}" "$BASE_URL/api/agent/v1/tables/overview"

run_case "tables/page (no table document in the corpus)" 404 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="not_found", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\",\"sheet\":0}" "$BASE_URL/api/agent/v1/tables/page"

run_case "tables/column_values (no table document in the corpus)" 404 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="not_found", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\",\"sheet\":0,\"column\":0}" \
  "$BASE_URL/api/agent/v1/tables/column_values"

run_case "tables/search_cells (no table document in the corpus)" 404 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="not_found", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\",\"sheet\":0,\"query\":\"x\"}" \
  "$BASE_URL/api/agent/v1/tables/search_cells"

run_case "folders/overview" 200 \
  'import json,sys; b=json.load(sys.stdin); names={d["name"] for d in b["datasets"]}; assert "testfiles" in names, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata"}' "$BASE_URL/api/agent/v1/folders/overview"

run_case "folders/list" 200 \
  'import json,sys; b=json.load(sys.stdin); names={f["name"] for f in b["files"]}; assert "easychair.txt" in names, b; assert all(c["child_count"] is not None for c in b["children"]), b; assert any(f["canonical_file_type"] for f in b["files"]), b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"testdata_testfiles"}' "$BASE_URL/api/agent/v1/folders/list"

run_case "folders/search" 200 \
  'import json,sys; b=json.load(sys.stdin); names={m["name"] for m in b["matches"]}; assert "easychair.txt" in names, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"testdata_testfiles","query":"easychair"}' "$BASE_URL/api/agent/v1/folders/search"

run_case "empty search list respects selected collection" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["documents"] and all(d["collectionname"]=="testdata" for d in b["documents"]), b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" -H 'X-Hoover4-Collections: testdata' "${JSON_HEADER[@]}" \
  -d '{"collectionname":[],"query":""}' "$BASE_URL/api/agent/v1/search/results"

run_case "dataset facet cannot replace selected collection" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" -H 'X-Hoover4-Collections: testdata' "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"query":"","facet_filters":{"collection_dataset":["other_emails"]}}' "$BASE_URL/api/agent/v1/search/results"

run_case "folder list rejects another collection dataset" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" -H 'X-Hoover4-Collections: testdata' "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"other_emails"}' "$BASE_URL/api/agent/v1/folders/list"

run_case "folder search rejects another collection dataset" 403 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="permission_denied", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" -H 'X-Hoover4-Collections: testdata' "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"other_emails","query":"mail"}' "$BASE_URL/api/agent/v1/folders/search"

run_case "invalid sort is refused" 400 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="invalid_argument", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"query":"","sort":{"field":"invalid","direction":"invalid"}}' "$BASE_URL/api/agent/v1/search/results"

run_case "selected document source stays selected" 200 \
  'import json,sys; b=json.load(sys.stdin); assert len(b["documents"])==1 and b["documents"][0]["source_used"]=="raw_text", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":[\"$TWO_SOURCE_DOC\"],\"source\":\"raw_text\"}" "$BASE_URL/api/agent/v1/documents/read"

run_case "search continuation rejects changed source" 409 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="source_changed", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata","other"],"query":"","expected_source":"stale"}' "$BASE_URL/api/agent/v1/search/results"

run_case "folder continuation rejects changed tree" 409 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="source_changed", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"testdata_testfiles","expected_source":"stale"}' "$BASE_URL/api/agent/v1/folders/list"

run_case "search rejects reversed dates" 400 \
  'import json,sys; assert json.load(sys.stdin)["error"]=="invalid_argument"' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"date_after":20,"date_before":10}' "$BASE_URL/api/agent/v1/search/results"

run_case "table page rejects invalid date filter" 400 \
  'import json,sys; assert json.load(sys.stdin)["error"]=="invalid_argument"' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\",\"sheet\":0,\"filters\":[{\"column\":1,\"date_min\":\"2026-99-99\"}]}" "$BASE_URL/api/agent/v1/tables/page"

run_case "table cell search rejects empty query" 400 \
  'import json,sys; assert json.load(sys.stdin)["error"]=="invalid_argument"' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\",\"sheet\":0,\"query\":\"\"}" "$BASE_URL/api/agent/v1/tables/search_cells"

run_case "folder list rejects oversized position" 400 \
  'import json,sys; assert json.load(sys.stdin)["error"]=="invalid_argument"' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"testdata_testfiles","position":{"page":1000001}}' "$BASE_URL/api/agent/v1/folders/list"

echo "all agent API contract cases passed"
exit 0
