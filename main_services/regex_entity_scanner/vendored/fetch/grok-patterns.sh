#!/usr/bin/env bash
# logstash-patterns-core — Apache-2.0.
# Battle-tested building blocks for the machine formats that fill logs and mail headers: syslog and
# common-log timestamps, IPs, URIs, paths, UUIDs, MACs. Machine formats are the highest-precision
# date material in any corpus, and these are the shapes worth special-casing.
#
# The specs are taken alongside the patterns. Each one pairs a pattern with the log lines it is
# expected to match, which is where the date formats appear in their native habitat — Apache,
# syslog, firewall and application logs rather than isolated tokens — and that is what the
# conformance cases are extracted from.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/logstash-plugins/logstash-patterns-core.git logstash-patterns-core)"
target="${REFERENCE}/grok"
replace_dir "$target"
cp -r "${src}/patterns" "${target}/patterns"
cp -r "${src}/spec/patterns" "${target}/spec"
cp "${src}/LICENSE" "${LICENSES}/logstash-patterns-core.LICENSE"
stamp "$target" "https://github.com/logstash-plugins/logstash-patterns-core" "$(git_head "$src")"
note "$(ls "${target}/spec" | wc -l) spec files"
