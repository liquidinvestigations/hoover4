#!/usr/bin/env bash
# libphonenumber (Google) — Apache-2.0.
# The metadata itself reaches us through the `phonenumber` crate, which tracks upstream and keeps us
# on an update path; regulators reassign number ranges continuously, so a frozen copy would rot.
#
# What we vendor is the part the crate does not provide: `PhoneNumberMatcher`, the reference
# implementation of finding numbers in free text. It is the two-stage design in its original form —
# a loose candidate pattern, then parse, validate, and a set of post-checks on the surrounding
# characters — and porting its heuristics is the highest-value custom work in the phone rule.
#
# Alongside it we take the test material the conformance run scores against: the `<exampleNumber>`
# of every region and line type in `PhoneNumberMetadata.xml`, and the matcher's own free-text
# corpus. The metadata file is taken for its examples only — the ranges the phone rule validates
# against still come from the crate.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/google/libphonenumber.git libphonenumber)"
target="${REFERENCE}/libphonenumber"
replace_dir "$target"

java="${src}/java/libphonenumber/src/com/google/i18n/phonenumbers"
for file in PhoneNumberMatcher.java PhoneNumberUtil.java; do
    cp "${java}/${file}" "${target}/"
done
cp "${src}/resources/PhoneNumberMetadata.xml" "${target}/"
# The matcher test is the one that carries free text. `PhoneNumberUtilTest` asserts API behaviour
# on already-parsed numbers, so it says nothing a scanner can be scored against.
cp "${src}/java/libphonenumber/test/com/google/i18n/phonenumbers/PhoneNumberMatcherTest.java" \
    "${target}/"
cp "${src}/LICENSE" "${LICENSES}/libphonenumber.LICENSE"
stamp "$target" "https://github.com/google/libphonenumber" "$(git_head "$src")"
note "$(grep -c '<exampleNumber' "${target}/PhoneNumberMetadata.xml") example numbers"
