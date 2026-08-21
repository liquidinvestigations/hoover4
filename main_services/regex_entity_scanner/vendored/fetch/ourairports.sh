#!/usr/bin/env bash
# OurAirports — public domain (Unlicense).
# IATA and ICAO codes for 80k+ airports, which is what turns a three-letter token from a guess into
# a lookup. Bare three-letter tokens collide with everything, so membership is necessary but never
# sufficient: the rule that uses this also demands a cue word.
#
# We keep five columns. The rest is airport metadata we have no use for and would only be shipping.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

target="${DATA}/ourairports"
mkdir -p "$target"
download "https://davidmegginson.github.io/ourairports-data/airports.csv" "${STAGE}/airports.csv"

python3 - "$STAGE/airports.csv" "${target}/airports.csv" <<'PY'
import csv, sys

source, dest = sys.argv[1], sys.argv[2]
columns = ["ident", "type", "name", "iso_country", "iata_code"]
with open(source, newline="", encoding="utf-8") as handle, \
     open(dest, "w", newline="", encoding="utf-8") as out:
    reader = csv.DictReader(handle)
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    kept = 0
    for row in reader:
        # Closed airports and heliports without either code are noise for identifier matching.
        if row["type"] == "closed" or not (row["iata_code"] or row["ident"]):
            continue
        writer.writerow({column: row[column] for column in columns})
        kept += 1
print(f"  {kept} airports")
PY

stamp "$target" "https://davidmegginson.github.io/ourairports-data/airports.csv" "$(date -u +%Y-%m-%d)"
