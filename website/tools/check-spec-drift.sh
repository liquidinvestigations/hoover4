#!/usr/bin/env bash
# Reports where the technical specification and the code disagree. Informs; never gates.
#
# Three joins, each on a name that already exists in the code:
#   routes   frontend route variants        <-> UI-<variant> ids in the interface inventory
#   config   keys in the settings template  <-> keys named in the configuration reference
#   options  variants of an enum backing a  <-> the options listed for that control
#            control's option list
#
# What it cannot see: a control that exists and does nothing, a row that is well formed and
# no longer true, a capability that moved. Those are found by walking the control tables in
# a browser, which is what those tables are for.
#
# The consumer half is a word search, not a call graph: a key whose name is also an ordinary
# word will find a "consumer" that merely mentions it. Read a clean result as "nothing is
# unreferenced", never as "every key is wired".
set -uo pipefail
cd "$(dirname "$0")/../.." 2>/dev/null || true
ROOT="${SPEC_ROOT:-$(git rev-parse --show-toplevel)}"
SPEC="${SPEC_DIR:-$ROOT/docs/technical-specification}"
ROUTES="$ROOT/website/frontend/src/routes.rs"
INI="$ROOT/hoover4.ini.release"
CONFREF="$ROOT/docs/operations/Configuration_Reference.md"
fail=0

hdr() { printf '\n== %s\n' "$1"; }

hdr "routes"
if [[ -f "$ROUTES" && -d "$SPEC/interface" ]]; then
  code=$(grep -oE '^\s{4}[A-Z][A-Za-z0-9]+ \{' "$ROUTES" | tr -d ' {' | sort -u)
  spec=$(grep -hoE '\bUI-[A-Za-z0-9]+' "$SPEC/interface"/*.md | sed 's/^UI-//' | sort -u)
  miss=$(comm -23 <(echo "$code") <(echo "$spec"))
  extra=$(comm -13 <(echo "$code") <(echo "$spec"))
  [[ -n "$miss"  ]] && { echo "$miss"  | sed 's/^/  page in code, not specified: /'; fail=1; }
  [[ -n "$extra" ]] && { echo "$extra" | sed 's/^/  page specified, not in code: /'; fail=1; }
  [[ -z "$miss$extra" ]] && echo "  ok ($(echo "$code" | wc -l) routes)"
else
  echo "  skipped (routes.rs or interface/ not found)"
fi

hdr "configuration"
if [[ -f "$INI" && -f "$CONFREF" ]]; then
  keys=$(grep -oE '^[a-z0-9_]+\s*=' "$INI" | tr -d ' =' | sort -u)
  doc=$(grep -hoE '`[a-z0-9_]+`' "$CONFREF" | tr -d '`' | sort -u)
  undoc=$(comm -23 <(echo "$keys") <(echo "$doc"))
  [[ -n "$undoc" ]] && { echo "$undoc" | sed 's/^/  setting not documented: /'; fail=1; }
  # Consumers are searched in SOURCE only. The generated `.env` files are excluded by the
  # include list on purpose: a key appears there because deploy.py rendered it, which is the
  # question, not the answer. `.venv` is excluded because a vendored package that happens to
  # use the same word would answer for every key that is a common noun.
  for k in $keys; do
    n=$(grep -rl --include='*.py' --include='*.rs' --include='*.sh' --include='*.yaml' \
          --exclude-dir=target --exclude-dir=node_modules --exclude-dir=__pycache__ \
          --exclude-dir=.venv --exclude-dir=vendored \
          -iE "\b${k}\b" "$ROOT/main_services" "$ROOT/website" "$ROOT/ai_services" \
          "$ROOT/deploy.py" 2>/dev/null | wc -l)
    [[ "$n" -eq 0 ]] && { echo "  setting read by nothing: $k"; fail=1; }
  done
  [[ "$fail" -eq 0 ]] && echo "  ok ($(echo "$keys" | wc -l) settings)"
else
  echo "  skipped (settings template or configuration reference not found)"
fi

hdr "enum-backed options"
if [[ -d "$SPEC/interface" ]]; then
  sk=$(grep -oE 'SortKey::[A-Z][A-Za-z]+' "$ROOT/website/common/src/search_query.rs" 2>/dev/null \
       | sed 's/SortKey:://' | grep -v '^ALL$' | sort -u)
  for v in $sk; do
    grep -qiE "\b${v}\b|File size|file_size" "$SPEC/interface/Search.md" 2>/dev/null \
      || { echo "  sort key not listed on the search page: $v"; fail=1; }
  done
  echo "  checked $(echo "$sk" | wc -w) sort keys"
fi

printf '\n%s\n' "$([[ $fail -eq 0 ]] && echo 'no drift reported' || echo 'drift reported above, read it and do not treat it as a gate')"
exit 0
