#!/usr/bin/env bash
# hoover-testdata (Liquid Investigations) — MIT, "Copyright (c) 2019 The Liquid Investigations
# Authors".
#
# Real mail, which is the one thing every other origin here is not: message ids, dates, addresses
# and Received chains as they were actually written, inside the header lines that carry them. Every
# other origin puts a token in a sentence somebody wrote for a test; this one is the sentence.
#
# The slice is mail files only, and it is named rather than implied, because the licence covers the
# repository and not the third-party documents inside it: `data/mbox`, the messages of
# `data/lists.mbox`, and the `.eml`/`.emlx` files of the ten `eml-*`/`emlx-*` directories.
# `data/disk-files` and the other sample collections are never taken — they are hundreds of
# megabytes of images and office documents pulled off the public internet.
#
# Within the slice, a message larger than the size cap is left behind as well. Those are messages
# whose bulk is a base64 attachment or a PGP payload — megabytes of encoded body behind one header
# block — and what this origin measures is header lines. Attachments, `.emlxpart` fragments and the
# PGP cleartext directory are never copied for the same reason.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

repo="https://github.com/liquidinvestigations/hoover-testdata"
src="${STAGE}/hoover-testdata"

# The largest message worth carrying for its headers, in bytes.
max_message=98304

mail_dirs=(
    data/mbox
    data/lists.mbox
    data/eml-1-promotional
    data/eml-10-broken-header
    data/eml-2-attachment
    data/eml-3-uppercaseheaders
    data/eml-5-long-names
    data/eml-7-recursive
    data/eml-8-double-encoded
    data/eml-9-pgp
    data/eml-bom
    data/emlx-4-missing-part
)

if [[ -d "${src}/.git" ]]; then
    note "updating hoover-testdata"
    git -C "$src" fetch --depth 1 origin HEAD >/dev/null 2>&1
    git -C "$src" reset --hard FETCH_HEAD >/dev/null 2>&1
else
    note "cloning hoover-testdata (sparse, the mail directories)"
    git clone --depth 1 --filter=blob:none --sparse --quiet --no-progress "${repo}.git" "$src" 2>/dev/null
    git -C "$src" sparse-checkout set "${mail_dirs[@]}" >/dev/null 2>&1
fi

target="${REFERENCE}/hoover-mail"
replace_dir "$target"

# The mbox files whole: one file is a mailing-list archive of many messages, and splitting it here
# would move work into the fetch that belongs in the extractor.
mkdir -p "${target}/mbox"
cp "${src}"/data/mbox/* "${target}/mbox/"

# Every message small enough to be worth its headers, flattened under the directory that names the
# shape it is there to exercise — uppercase headers, a broken subject, a byte-order mark.
for dir in "${src}"/data/eml-*/ "${src}"/data/emlx-*/ "${src}"/data/lists.mbox/; do
    name="$(basename "$dir")"
    while IFS= read -r -d '' message; do
        mkdir -p "${target}/${name}"
        cp "$message" "${target}/${name}/$(basename "$message")"
    done < <(find "$dir" \( -name '*.eml' -o -name '*.emlx' \) -size -"${max_message}"c -print0)
done

curl --fail --silent --show-error --location \
    --output "${LICENSES}/hoover-testdata.LICENSE" \
    "https://raw.githubusercontent.com/liquidinvestigations/hoover-testdata/master/LICENSE"
stamp "$target" "${repo} (the mail slice)" "$(git_head "$src")"
note "$(find "$target" -type f ! -name .upstream | wc -l) mail files, $(du -sh "$target" | cut -f1)"
