#!/usr/bin/env bash
# is_email (Dominic Sayers) — BSD-3.
#
# `test/tests.xml` is 164 addresses, each with the category and the diagnosis upstream's validator
# returns for it. The categories are what make it usable as more than a valid/invalid split:
# `ISEMAIL_ERR` is an address that is wrong under any reading, `ISEMAIL_VALID_CATEGORY` is one that
# is right under every reading, and the graded middle is upstream saying "legal under RFC 5322 and
# a bad idea" — quoted local parts, comments, folding whitespace, IP-literal domains. That middle
# is the shape of the limit the email rule takes deliberately, and the two ends are the largest
# body of email precision and recall evidence available under a permissive licence.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

repo="https://github.com/dominicsayers/isemail"
raw="https://raw.githubusercontent.com/dominicsayers/isemail/master"
target="${REFERENCE}/isemail"
replace_dir "${target}/test"

download "${raw}/test/tests.xml" "${target}/test/tests.xml"
download "${raw}/license.md" "${LICENSES}/isemail.LICENSE"
stamp "$target" "$repo" "$(remote_head "$repo")"
note "$(grep -c '<test id=' "${target}/test/tests.xml") addresses"
