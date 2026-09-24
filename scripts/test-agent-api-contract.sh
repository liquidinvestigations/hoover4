#!/usr/bin/env bash
# Contract check for the agent routes under /api/agent/v1/.
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
# other), and the table fixture `testdata_tables`: one workbook with one sheet of
# more than 1,000,000 rows and more than 60 columns, and one cell longer than 2,000
# characters (see `website/Readme.md`, "Agent routes"). The folder paging
# cases read `/the-directory` of the `shapes` dataset, which holds more than
# 200 children and more than 500 names that contain "child".
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
# Every route, against the local testdata/other corpus
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
  'import json,sys; b=json.load(sys.stdin); assert b["terms"] and all(t["id"] and t["count"] for t in b["terms"]) and "resolved" in b, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"facet":"file_types"}' "$BASE_URL/api/agent/v1/search/facet_values"

run_case "search/histogram" 200 \
  'import json,sys; b=json.load(sys.stdin); assert "buckets" in b and b["date_field"]=="date", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":["testdata"],"query":"","field":"date"}' "$BASE_URL/api/agent/v1/search/histogram"

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

TABLE_DOC="$(ch_query "SELECT hash FROM Hoover4_Collection_testdata.table_documents FINAL \
  WHERE collection_dataset = 'testdata_tables' AND status = 'ok' AND row_count > 1000000 LIMIT 1" < /dev/null)"
if [ -z "$TABLE_DOC" ]; then
  echo "FAIL the table fixture testdata_tables is not ingested"
  exit 1
fi

run_case "tables/overview on the table fixture" 200 \
  'import json,sys; b=json.load(sys.stdin); s=b["sheets"][0]; assert b["total"]==1 and s["row_count"]>1000000 and len(s["columns"])>60 and b["source"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TABLE_DOC\"}" "$BASE_URL/api/agent/v1/tables/overview"

run_case "tables/page on the table fixture" 200 \
  'import json,sys; b=json.load(sys.stdin); assert len(b["rows"])==50 and b["next_position"]=={"kind":"Rows","row_start":50} and b["total_rows"]>1000000, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TABLE_DOC\",\"sheet\":0}" "$BASE_URL/api/agent/v1/tables/page"

run_case "tables/column_values on the table fixture" 200 \
  'import json,sys; b=json.load(sys.stdin); assert len(b["values"])==200 and b["next_position"]["kind"]=="ValueKey", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TABLE_DOC\",\"sheet\":0,\"column\":2}" \
  "$BASE_URL/api/agent/v1/tables/column_values"

run_case "tables/search_cells on the table fixture" 200 \
  'import json,sys; b=json.load(sys.stdin); assert b["hit_count"]==b["total"]==11 and len(b["hits"])==11 and b["next_position"] is None, b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$TABLE_DOC\",\"sheet\":0,\"query\":\"row12345\"}" \
  "$BASE_URL/api/agent/v1/tables/search_cells"

run_case "a table route answers 404 for a file hash with no table" 404 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="not_found", b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d "{\"collectionname\":\"testdata\",\"file_hash\":\"$NO_SUCH_HASH\"}" "$BASE_URL/api/agent/v1/tables/overview"

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

run_case "folder list refuses a Page position" 400 \
  'import json,sys; b=json.load(sys.stdin); assert b["error"]=="invalid_argument" and "NodeKey" in b["message"], b' \
  "${POST[@]}" "${AGENT_HEADER[@]}" "${JSON_HEADER[@]}" \
  -d '{"collectionname":"testdata","dataset":"testdata_testfiles","position":{"kind":"Page","page":1}}' "$BASE_URL/api/agent/v1/folders/list"

# ---------------------------------------------------------------------------
# Search and folder paging, positions and field parity. Each case runs one
# Python program inside hoover4-website, which calls the routes through
# post() and asserts on what they return.
# ---------------------------------------------------------------------------

echo "== search and folder paging =="

PY_PRELUDE='import json, urllib.request, urllib.error
def post(route, body):
    request = urllib.request.Request(
        "http://localhost:8080/api/agent/v1/" + route, json.dumps(body).encode(),
        {"content-type": "application/json", "x-hoover4-user": "agent-contract-user"})
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)
def refused(status, body, code, error):
    assert status == code and body["error"] == error, (status, body)
TESTDATA = {"collectionname": ["testdata"], "query": ""}'

# Runs one case: a name and a Python program that exits nonzero on failure.
py_case() {
  local name="$1" code="$2"
  if docker exec "$SITE" python3 -c "$PY_PRELUDE
$code"; then
    echo "PASS $name"
  else
    echo "FAIL $name"
    FAILED=1
    exit 1
  fi
}

py_case "integer-facet: a file type count equals the filtered total" '
status, base = post("search/results", TESTDATA)
assert status == 200, base
for facet in ("file_types", "file_paths"):
    value = base["facet_counts"][facet][0]
    assert value["id"] is not None, value
    status, body = post("search/results", {**TESTDATA, "facet_filters": {facet: [str(value["id"])]}})
    assert status == 200 and body["total_count"] == value["count"], (facet, value, body["total_count"])
'

py_case "integer-facet: a value that is not a term id is refused" '
refused(*post("search/results", {**TESTDATA, "facet_filters": {"file_types": ["text"]}}), 400, "invalid_argument")
refused(*post("search/results", {**TESTDATA, "facet_filters": {"no_such_facet": ["1"]}}), 400, "invalid_argument")
'

py_case "facet counts list every filter modal facet with term ids" '
status, body = post("search/results", TESTDATA)
assert status == 200, body
expected = {"collection_dataset", "file_types", "file_paths", "email_from", "email_to", "struct_flags",
            "ner_per", "ner_org", "ner_loc", "ner_misc", "re_email", "re_phone", "re_bank_account",
            "re_company_id", "re_money", "re_crypto_wallet"}
assert set(body["facet_counts"]) == expected, sorted(body["facet_counts"])
assert all(len(values) <= 21 for values in body["facet_counts"].values()), body["facet_counts"]
assert all(v["id"] is None for v in body["facet_counts"]["collection_dataset"]), body["facet_counts"]
assert all(v["id"] is not None for v in body["facet_counts"]["re_email"]), body["facet_counts"]
assert body["total"] == body["total_count"] and body["partial"] is False and body["source"], body
'

py_case "facet values: a field with no term dictionary filters by the needle" '
status, body = post("search/facet_values", {"collectionname": ["testdata"], "facet": "file_types", "query": "tex"})
assert status == 200 and body["terms"], body
assert all("tex" in t["text"].lower() and t["id"] and t["count"] for t in body["terms"]), body
status, body = post("search/facet_values", {"collectionname": ["testdata"], "facet": "re_email", "query": "easychair"})
assert status == 200 and body["terms"] and all(t["count"] for t in body["terms"]), body
'

py_case "search-ceiling: page 49 is the last page and page 50 is refused" '
status, body = post("search/results", {**TESTDATA, "position": {"kind": "Page", "page": 49}})
assert status == 200 and body["next_position"] is None and body["has_more"] is False, body
refused(*post("search/results", {**TESTDATA, "position": {"kind": "Page", "page": 50}}), 400, "invalid_argument")
'

py_case "search pages continue with a Page position" '
status, first = post("search/results", {"collectionname": ["testdata", "other"], "query": ""})
assert status == 200 and first["next_position"] == {"kind": "Page", "page": 1}, first
status, second = post("search/results", {"collectionname": ["testdata", "other"], "query": "",
                                         "position": first["next_position"], "expected_source": first["source"]})
assert status == 200 and second["page"] == 1, second
assert not {d["file_hash"] for d in first["documents"]} & {d["file_hash"] for d in second["documents"]}
'

py_case "a position of another kind is refused" '
refused(*post("search/results", {**TESTDATA, "position": {"kind": "Rows", "row_start": 0}}), 400, "invalid_argument")
refused(*post("search/results", {**TESTDATA, "position": {"kind": "NoSuchKind"}}), 400, "invalid_argument")
refused(*post("folders/list", {"collectionname": "testdata", "dataset": "testfiles", "position": {"kind": "Offset", "offset": 0}}), 400, "invalid_argument")
refused(*post("folders/search", {"collectionname": "testdata", "dataset": "testfiles", "query": "easy", "position": {"kind": "Page", "page": 1}}), 400, "invalid_argument")
'

py_case "a query the datastore refuses is 400 with its message" '
status, body = post("search/results", {**TESTDATA, "query": "a MAYBE"})
refused(status, body, 400, "invalid_argument")
assert "error" in body["message"], body
'

py_case "filename_only matches the file name and not the text" '
status, body = post("search/results", {**TESTDATA, "query": "easychair", "filename_only": True})
assert status == 200 and body["documents"], body
assert all("easychair" in d["path"].lower() for d in body["documents"]), body
status, text = post("search/results", {**TESTDATA, "query": "voronkov"})
status, names = post("search/results", {**TESTDATA, "query": "voronkov", "filename_only": True})
assert text["total_count"] > 0 and names["total_count"] == 0, (text["total_count"], names["total_count"])
'

py_case "date filters: unknown-only, mentioned range and the refused confirmed-only flag" '
status, unknown = post("search/results", {**TESTDATA, "date_unknown_only": True})
assert status == 200 and unknown["documents"], unknown
assert all(d["document_date"] is None for d in unknown["documents"]), unknown
status, dated = post("search/results", {**TESTDATA, "date_after": -10**12, "date_before": 10**12})
assert status == 200 and all(d["document_date"] is not None for d in dated["documents"]), dated
status, base = post("search/results", TESTDATA)
assert unknown["total_count"] + dated["total_count"] == base["total_count"], (unknown["total_count"], dated["total_count"], base["total_count"])
status, mentioned = post("search/results", {**TESTDATA, "mentioned_date_after": -10**12, "mentioned_date_before": 10**12})
assert status == 200 and mentioned["total_count"] <= base["total_count"], mentioned
refused(*post("search/results", {**TESTDATA, "date_confirmed_only": True}), 400, "invalid_argument")
refused(*post("search/results", {**TESTDATA, "mentioned_date_after": 20, "mentioned_date_before": 10}), 400, "invalid_argument")
'

py_case "search_histogram with size returns the four size buckets" '
status, body = post("search/histogram", {"collectionname": ["testdata"], "query": "", "field": "size"})
assert status == 200 and body["date_field"] == "size", body
assert len(body["buckets"]) == 4 and all(b["label"] for b in body["buckets"]), body
assert body["buckets"][-1]["end"] is None and body["buckets"][0]["start"] == 0, body
status, dates = post("search/histogram", {"collectionname": ["testdata"], "query": "", "field": "mentioned_date"})
assert status == 200 and dates["date_field"] == "mentioned_date", dates
refused(*post("search/histogram", {"collectionname": ["testdata"], "query": "", "field": "colour"}), 400, "invalid_argument")
'

py_case "folders accept the short dataset name and answer with it" '
status, body = post("folders/list", {"collectionname": "testdata", "dataset": "testfiles"})
assert status == 200 and body["dataset"] == "testfiles" and body["total"] >= 1 and body["next_position"] is None, body
status, body = post("folders/search", {"collectionname": "testdata", "dataset": "testfiles", "query": "easychair"})
assert status == 200 and body["dataset"] == "testfiles" and body["matches"], body
status, body = post("folders/overview", {"collectionname": "testdata", "dataset": "testfiles"})
assert status == 200 and body["indexed_count"] >= 1 and body["error_count"] >= 0 and body["source"], body
refused(*post("folders/list", {"collectionname": "testdata", "dataset": "emails"}), 403, "permission_denied")
'

py_case "folder list continues with NodeKey positions to the last child" '
status, root = post("folders/list", {"collectionname": "testdata", "dataset": "shapes"})
assert status == 200, root
folder = [c for c in root["children"] if c["name"] == "the-directory"][0]
assert folder["child_count"] > 200, folder
seen, position, pages = [], None, 0
while True:
    request = {"collectionname": "testdata", "dataset": "shapes", "node_id": folder["node_id"]}
    if position:
        request.update(position=position, expected_source=source)
    status, body = post("folders/list", request)
    assert status == 200, body
    pages += 1
    source, position = body["source"], body["next_position"]
    seen += [c["node_id"] for c in body["children"]] + [f["node_id"] for f in body["files"] if not f["is_container"]]
    if position is None:
        break
    assert position["kind"] == "NodeKey", position
assert pages > 1 and len(seen) == len(set(seen)) == body["total"] == folder["child_count"], (pages, len(seen), body["total"])
refused(*post("folders/list", {"collectionname": "testdata", "dataset": "shapes", "node_id": folder["node_id"], "expected_source": "stale"}), 409, "source_changed")
'

py_case "folder_search continues past 500 matches with Offset positions" '
seen, position, pages = [], None, 0
while True:
    request = {"collectionname": "testdata", "dataset": "shapes", "query": "child"}
    if position:
        request.update(position=position, expected_source=source)
    status, body = post("folders/search", request)
    assert status == 200, body
    pages += 1
    source, position = body["source"], body["next_position"]
    seen += [m["node_id"] for m in body["matches"]]
    if position is None:
        break
    assert position["kind"] == "Offset" and position["offset"] % 500 == 0, position
assert len(seen) > 500 and pages > 1 and len(seen) == len(set(seen)) == body["total"], (pages, len(seen), body["total"])
refused(*post("folders/search", {"collectionname": "testdata", "dataset": "shapes", "query": "child", "expected_source": "stale"}), 409, "source_changed")
refused(*post("folders/search", {"collectionname": "testdata", "dataset": "shapes", "query": "child", "position": {"kind": "Offset", "offset": 2000}}), 400, "invalid_argument")
'

echo "== documents =="

PY_PRELUDE="$PY_PRELUDE
PDF_DOC = \"$PDF_DOC\"
EMAIL_DOC = \"$EMAIL_DOC\"
TWO_SOURCE_DOC = \"$TWO_SOURCE_DOC\"
def walk(route, body, key):
    \"\"\"Follows next_position with expected_source to the last page, and returns the pages.\"\"\"
    pages = []
    request = dict(body)
    while True:
        status, page = post(route, request)
        assert status == 200, (route, request, page)
        pages.append(page)
        if page[\"next_position\"] is None:
            return pages
        assert len(pages) < 200, route
        request = {**body, \"position\": page[\"next_position\"], \"expected_source\": page[\"source\"]}"

py_case "the date_histogram alias is removed" '
request = urllib.request.Request("http://localhost:8080/api/agent/v1/search/date_histogram", b"{}", {"content-type": "application/json", "x-hoover4-user": "agent-contract-user"})
try:
    urllib.request.urlopen(request, timeout=40)
    raise AssertionError("the alias still answers")
except urllib.error.HTTPError as error:
    # The site answers a POST to a path with no route with 405, from its page fallback.
    assert error.code in (404, 405), error.code
'

py_case "read_documents opens the most-hits page and walks every page with TextPage positions" '
READ = {"collectionname": "testdata", "file_hash": [PDF_DOC], "source": "pdftotext"}
status, first = post("documents/read", {**READ, "query": "the"})
assert status == 200, first
doc = first["documents"][0]
assert doc["min_page"] == 1 and doc["max_page"] == 30 and doc["count_state"] == "read", doc
assert doc["hit_pages"] == sorted(doc["hit_pages"]) and 0 < len(doc["hit_pages"]) <= 50, doc["hit_pages"]
assert doc["page"] in doc["hit_pages"] and doc["hit_count"] > 0, doc
pages = walk("documents/read", READ, "documents")
read = [page["documents"][0]["page"] for page in pages]
assert read == list(range(1, 31)) and pages[0]["total"] == 30, read
assert all(page["documents"][0]["text"] for page in pages)
assert pages[0]["next_position"] == {"kind": "TextPage", "source": "pdftotext", "page_id": 2}, pages[0]["next_position"]
refused(*post("documents/read", {**READ, "expected_source": "stale"}), 409, "source_changed")
refused(*post("documents/read", {**READ, "page": 999}), 404, "not_found")
refused(*post("documents/read", {**READ, "position": {"kind": "Offset", "offset": 1}}), 400, "invalid_argument")
refused(*post("documents/read", {**READ, "file_hash": [PDF_DOC] * 21}), 400, "invalid_argument")
'

py_case "doc_search_text pages every hit with HitKey positions" '
SEARCH = {"collectionname": "testdata", "file_hash": PDF_DOC, "source": "pdftotext", "query": "the"}
pages = walk("documents/search_text", SEARCH, "hits")
hits = [(hit["page"], hit["ordinal"]) for page in pages for hit in page["hits"]]
assert len(pages) > 1 and all(len(page["hits"]) <= 50 for page in pages), len(pages)
assert hits == sorted(hits) and len(hits) == len(set(hits)) == pages[0]["hit_count"] == pages[0]["total"], (len(hits), pages[0]["hit_count"])
assert pages[-1]["next_position"] is None and pages[0]["next_position"]["kind"] == "HitKey"
refused(*post("documents/search_text", {**SEARCH, "expected_source": "stale"}), 409, "source_changed")
refused(*post("documents/search_text", {**SEARCH, "position": {"kind": "Page", "page": 1}}), 400, "invalid_argument")
'

py_case "doc_sources lists every source kind with counts, and the email entry once" '
status, body = post("documents/sources", {"collectionname": "testdata", "file_hash": PDF_DOC, "query": "the"})
assert status == 200, body
kinds = [source["kind"] for source in body["sources"]]
assert kinds.count("pdf") >= 1 and "text" in kinds, kinds
assert all(source["count_state"] == "counted" and source["hit_count"] is not None for source in body["sources"]), body["sources"]
assert body["partial"] is False and body["total"] == len(body["sources"])
status, plain = post("documents/sources", {"collectionname": "testdata", "file_hash": PDF_DOC})
assert all(source["count_state"] == "no_query" and source["hit_count"] is None for source in plain["sources"]), plain
status, mail = post("documents/sources", {"collectionname": "other", "file_hash": EMAIL_DOC, "query": "the"})
assert status == 200, mail
emails = [source for source in mail["sources"] if source["kind"] == "email"]
assert len(emails) == 1, mail["sources"]
body_text = [source for source in mail["sources"] if source["kind"] == "text" and source["source"] == "email_parser"]
if body_text:
    assert emails[0]["hit_count"] == body_text[0]["hit_count"], mail["sources"]
refused(*post("documents/sources", {"collectionname": "testdata", "file_hash": PDF_DOC, "expected_source": "stale"}), 409, "source_changed")
'

py_case "doc_metadata returns the location total and the container chain" '
status, body = post("documents/metadata", {"collectionname": "other", "file_hash": EMAIL_DOC})
assert status == 200, body
locations = body["file_locations"]
assert locations and body["file_locations_total"] >= len(locations), body
assert all(location["path"] and location["container_chain"] for location in locations), locations
'

py_case "doc_email returns the missing fields and centres the graph on node" '
status, body = post("documents/email", {"collectionname": "other", "file_hash": EMAIL_DOC})
assert status == 200, body
assert "parent" in body and body["total"] == len(body["attachments"]) and body["next_position"] is None, body
graph = body["graph"]
assert "cluster_size" in graph and "truncated" in graph
assert all({"from", "date", "truncated"} <= set(node) for node in graph["nodes"]), graph["nodes"]
assert all("evidence" in edge for edge in graph["edges"]), graph["edges"]
assert all("coarse_type" in attachment for attachment in body["attachments"])
# The local corpus has no email edges, so the case centres the graph on a second email.
SECOND_EMAIL = "25757c44c8047ad3240dcdc12a0381fe04ffda4f8b85c022ae303336f3ce1c2b"
status, moved = post("documents/email", {"collectionname": "other", "file_hash": EMAIL_DOC, "node": SECOND_EMAIL})
assert status == 200, moved
centre = [node["file_hash"] for node in moved["graph"]["nodes"] if node["is_centre"]]
assert centre == [SECOND_EMAIL] and moved["envelope"] == body["envelope"], centre
refused(*post("documents/email", {"collectionname": "other", "file_hash": EMAIL_DOC, "position": {"kind": "Page", "page": 0}}), 400, "invalid_argument")
refused(*post("documents/email", {"collectionname": "other", "file_hash": EMAIL_DOC, "expected_source": "stale"}), 409, "source_changed")
'

py_case "doc_diff_sources compares the named pages" '
DIFF = {"collectionname": "testdata", "file_hash": PDF_DOC, "source_a": "pdftotext", "source_b": "extractous"}
status, first = post("documents/diff_sources", DIFF)
assert status == 200 and first["page_a"] == 1 and first["page_b"] == 1, first
status, second = post("documents/diff_sources", {**DIFF, "page_a": 2})
assert status == 200 and second["page_a"] == 2 and second["unified_diff"] != first["unified_diff"], second
refused(*post("documents/diff_sources", {**DIFF, "page_a": 999}), 404, "not_found")
'

py_case "pdf_search filters a page range and pages the kept result by HitKey" '
PDF = {"collectionname": "testdata", "file_hash": PDF_DOC, "query": "the", "source": ""}
status, whole = post("documents/pdf_search", PDF)
assert status == 200 and whole["hit_count"] > 100 and len(whole["hit_positions"]) == 100, whole["hit_count"]
assert whole["next_position"]["kind"] == "HitKey", whole["next_position"]
pages = walk("documents/pdf_search", {**PDF, "page_from": 2, "page_to": 4}, "hit_positions")
hits = [(hit["page"], hit["start"]) for page in pages for hit in page["hit_positions"]]
assert hits and all(2 <= page <= 4 for page, _ in hits), hits[:5]
assert len(hits) == len(set(hits)) == pages[0]["total"] and hits == sorted(hits), (len(hits), pages[0]["total"])
refused(*post("documents/pdf_search", {**PDF, "page_from": 4, "page_to": 2}), 400, "invalid_argument")
refused(*post("documents/pdf_search", {**PDF, "expected_source": "stale"}), 409, "source_changed")
'

py_case "large-table: rows past the millionth, a column after the 60th and one long cell" '
H = "'"$TABLE_DOC"'"
T = {"collectionname": "testdata", "file_hash": H, "sheet": 0}
status, page = post("tables/page", {**T, "row_start": 1000045, "columns": [1, 62, 63]})
assert status == 200, page
assert [c["column_id"] for c in page["columns"]] == [1, 62, 63], page["columns"]
assert page["next_position"] == {"kind": "Rows", "row_start": 1000095}, page["next_position"]
long = [row for row in page["rows"] if isinstance(row["cells"].get("col62"), dict)]
assert len(long) == 1, page["rows"]
cut = long[0]["cells"]["col62"]
assert len(cut["text"]) == 2000 and cut["cut"]["total_bytes"] == 5000, cut["cut"]
status, last = post("tables/page", {**T, "position": page["next_position"], "expected_source": page["source"]})
assert status == 200 and last["next_position"] is None and last["rows"][-1]["row_number"] == 1000101, last["next_position"]
text, position = "", None
for _ in range(5):
    status, cell = post("tables/cell", {**T, "row": long[0]["row_id"], "column": 62, **({"position": position} if position else {})})
    assert status == 200, cell
    text += cell["text"]
    position = cell["next_position"]
    if position is None:
        break
assert len(text) == 5000 and text.startswith(cut["text"]), len(text)
refused(*post("tables/cell", {**T, "row": long[0]["row_id"], "column": 62, "position": {"kind": "Offset", "offset": 5000}}), 400, "invalid_argument")
'

py_case "table positions: Offset after a sort, ValueKey past 200 values, and the refused kinds" '
H = "'"$TABLE_DOC"'"
T = {"collectionname": "testdata", "file_hash": H, "sheet": 0}
status, page = post("tables/page", {**T, "sort": {"column": 4, "direction": "desc"}})
assert status == 200 and page["next_position"] == {"kind": "Offset", "offset": 50}, page["next_position"]
refused(*post("tables/page", {**T, "position": {"kind": "Offset", "offset": 50}}), 400, "invalid_argument")
refused(*post("tables/page", {**T, "sort": {"column": 4, "direction": "desc"}, "position": {"kind": "Rows", "row_start": 50}}), 400, "invalid_argument")
seen, position = [], None
for _ in range(3):
    status, values = post("tables/column_values", {**T, "column": 2, **({"position": position} if position else {})})
    assert status == 200, values
    seen += [value["value"] for value in values["values"]]
    position = values["next_position"]
    if position is None:
        break
assert len(seen) == 250 and len(set(seen)) == 250, len(seen)
status, needle = post("tables/column_values", {**T, "column": 3, "search": "row99999"})
assert status == 200 and all("row99999" in value["value"] for value in needle["values"]) and len(needle["values"]) == 11, needle
refused(*post("tables/page", {**T, "expected_source": "stale"}), 409, "source_changed")
'

echo "all agent API contract cases passed"
exit 0
