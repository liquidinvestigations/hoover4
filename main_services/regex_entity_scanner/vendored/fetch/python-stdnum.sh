#!/usr/bin/env bash
# python-stdnum — LGPL-2.1+, which upgrades cleanly into an AGPLv3 work.
# 200+ number formats with their real check-digit algorithms: IBAN, BIC, EU VAT, company
# registration numbers across some sixty jurisdictions, LEI, ISIN, national identity numbers, IMO,
# MMSI, ISO 6346 containers, IMEI. Each module is a compact format-plus-validator pair, which makes
# this the specification we port from — a check digit turns "matched something plausible" into
# "verified", and that is the difference between a join key and index noise.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/arthurdejong/python-stdnum.git python-stdnum)"
target="${REFERENCE}/python-stdnum"
replace_dir "$target"
cp -r "${src}/stdnum" "${target}/stdnum"
# The bundled data files are large downloads refreshed at install time upstream, not part of the
# specification we port. `iban.dat` is the exception and is transformed below.
find "${target}/stdnum" -name '*.dat' -delete
cp "${src}/COPYING" "${LICENSES}/python-stdnum.LICENSE"
stamp "$target" "https://github.com/arthurdejong/python-stdnum" "$(git_head "$src")"
note "$(find "${target}/stdnum" -name '*.py' | wc -l) format modules"

# The IBAN registry is runtime data rather than reference material: mod-97 alone accepts one
# malformed candidate in ninety-seven, and it is the per-country length and structure that turn an
# IBAN match into a verified one. Upstream keeps it as their own transcription of the SWIFT
# registry, which is the only openly redistributable form of that table.
iban="${DATA}/iban"
mkdir -p "$iban"
python3 - "${src}/stdnum/iban.dat" "${iban}/registry.json" <<'PY'
import json
import re
import sys

source, dest = sys.argv[1], sys.argv[2]

# The BBAN structure is a run of `<length>!<class>` groups: 4!a is four letters, 16!c sixteen
# alphanumerics, 8!n eight digits.
group = re.compile(r"([1-9][0-9]*)!([nac])")
field = re.compile(r'(\w+)="([^"]*)"')

registry = {}
for line in open(source, encoding="utf-8"):
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    code, rest = line.split(" ", 1)
    fields = dict(field.findall(rest))
    structure = fields.get("bban")
    if not structure:
        continue
    groups = group.findall(structure)
    entry = {
        "country": fields.get("country", ""),
        # Two letters, two check digits, then the BBAN.
        "length": 4 + sum(int(length) for length, _ in groups),
        "structure": structure,
    }
    # The bank identifier is the leading BBAN group wherever the structure has more than one, which
    # is the only positional information this source carries. Branch identifier positions are not
    # in it, so no branch is published rather than guessed.
    if len(groups) > 1:
        entry["bank"] = [4, 4 + int(groups[0][0])]
    registry[code] = entry

with open(dest, "w", encoding="utf-8") as out:
    json.dump(registry, out, indent=1, sort_keys=True)
    out.write("\n")
print(f"  {len(registry)} IBAN countries")
PY
stamp "$iban" "https://github.com/arthurdejong/python-stdnum (stdnum/iban.dat)" \
    "$(git_head "$src")"
