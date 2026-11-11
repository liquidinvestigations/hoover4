#!/bin/sh
# Runs in the LDAP main container. Counts the entries under the naming context and times 200 searches.
# A failed search or an empty result ends the script with a non-zero status.
set -eu
result=$(ldapsearch </dev/null -H ldapi:/// -Y EXTERNAL -b "" -s base -LLL namingContexts 2>/dev/null)
base=$(printf '%s\n' "$result" | sed -n 's/^namingContexts: //p' | head -1)
if [ -z "$base" ]; then
  echo "naming context missing"
  exit 1
fi
result=$(ldapsearch </dev/null -H ldapi:/// -Y EXTERNAL -b "$base" -LLL dn 2>/dev/null)
entries=$(printf '%s\n' "$result" | grep -c '^dn:' || true)
echo "context $base entries $entries"
min=${LDAP_MIN_ENTRIES:-1}
if [ "$entries" -lt "$min" ]; then
  echo "entry count $entries is below $min"
  exit 1
fi
last=$(cat /var/lib/univention-ldap/last_id 2>/dev/null || echo missing)
echo "last_id $last"
start=$(date +%s%N)
i=0
failed=0
while [ "$i" -lt 200 ]; do
  if result=$(ldapsearch -H ldapi:/// -Y EXTERNAL -b "cn=users,$base" -LLL "(uid=test.user)" uid </dev/null 2>/dev/null); then
    if ! printf '%s\n' "$result" | grep -qx 'uid: test.user'; then
      failed=$((failed + 1))
    fi
  else
    failed=$((failed + 1))
  fi
  i=$((i + 1))
done
echo "searches 200 failed $failed milliseconds $(( ($(date +%s%N) - start) / 1000000 ))"
if [ "$failed" -ne 0 ]; then
  exit 1
fi
