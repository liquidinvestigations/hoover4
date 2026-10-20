#!/usr/bin/env python3
"""Write and ingest the synthetic fixtures of the agent table and text viewer stack tests.

Every file is synthetic. The script copies no conversation and no demo document.

`p64evals_fixtures` (collection `p64evals`, root `testdata/p64-evals/`):

* `monitored_bills_38.csv`: a header row and 38 bills, stored as `row_id` 1 to 39. It is a
  copy of the tracked unit-test fixture `main_services/processing/tests/unit/fixtures/`.
  The last data row, `SYN-038`, is the fifth bill in state SC.
* `events_headerless.csv`: 19 dated event rows and no header row. Table reader version 1
  took the first row as the header. Version 2 reads it as a data row, because its id and
  date cells have the kinds of the rows below (`parse_table.first_row_is_data`).
* `events_with_header.csv`: the same rows after a header row.
* `project_export.json`: a JSON project export with 12 tasks. It has no sheet.
* `long_report.pdf`: 60 pages. Page 57 alone holds the name "Quillon Varga".

`p65tables_fixtures` (collection `p65tables`, root `testdata/p65-tables/`):

* `office_values_250.csv`: a header row and 250 data rows. Its `office` column has 214
  distinct values, more than one `tables/column_values` page holds, and 9 blank cells.
  The value `Harbour Annex` occurs in the last data row only.

`p65tables_text` (collection `p65tables`, root `testdata/p65-text/`):

* `stale_page.txt` and `duplicate_page.txt`: one text segment each with the word `quokka`
  and Unicode text. The stack tests write a newer stored version of each segment, so the
  index row holds an older text than `text_content`, and add an index row with the newer
  text for `duplicate_page.txt`.

`p65tables_continuation_long` (collection `p65tables`, root `testdata/p65-continuation-long/`):

* `continuation_pages.pdf`: 6,602 pages. Only pages 1 and 6,602 have text, and both hold
  the word `quokka`. The stack test of match continuation adds index rows with `quokka`
  for the pages without stored text. A match step reads 1,000 index rows. The viewer reads
  one step when a page opens and 4 steps in each match action, so the second action from
  one stored match reaches the other.

`p66tables_fixtures` (collection `p66tables`, root `testdata/p66-tables/`), for the readings
of row 1 of a delimited file. Table reader version 3 or later must parse it. `READINGS`
gives the stored reading of each file:

* `labelled_offices.csv`: the header `case_id,office,amount` and 30 data rows. The text label
  above the integer column establishes the header. The last data row is `C-030` in
  `Harbour Annex`, the only row of that office.
* `people_text_only.csv`: 12 rows of names and cities and no header. Text cells cannot show
  whether row 1 is a header, so both readings stay. The first row's name, `Alice Moreau`,
  occurs again in row 7, and its city, `Paris`, in rows 4 and 9.
* `region_years.csv`: the header `region,2018,2020` above 6 rows of four-digit numbers. The
  years have the digit count of the data, so both readings stay, and the grid reads row 1
  as data.
* `digit_ids.csv`: 15 rows that start at id 9, so the digit count changes below row 1. Both
  readings stay, and the grid reads row 1 as the header.
* `consecutive_pairs.csv`: 10 rows of consecutive integers. Both readings stay.
* `dated_quotes.csv`: the header `opened,title,amount` above 8 dated rows with quoted commas,
  blank cells and an integer and decimal column. The labels establish the header.
* `empty.csv`: no bytes. It has no table.

`--check` verifies the written files against `EXPECTED`. `--ingest` also creates each
missing collection and ingests each missing dataset with `main_services/run.sh`. A stack
test that needs a fixture fails when its dataset is absent.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BILLS = REPO / "main_services/processing/tests/unit/fixtures/monitored_bills_38.csv"

#: The SHA3-256 of each file, which is its `file_hash` in the collection.
EXPECTED = {
    "p64-evals/monitored_bills_38.csv": "d1ed78d2b98c3a31db5f4671c1c91a792d39ad389f40727ab21319f9fcc667c9",
    "p64-evals/events_headerless.csv": "4f37b1d6d20de58add25bb57a2159a7852cdbebbc7b1780f2f848b79ac2b8308",
    "p64-evals/events_with_header.csv": "eae06777f2880603548d96ecaddaab4926e730db9a8025d142a28663bfb583af",
    "p64-evals/project_export.json": "3f6a8d3eb324dea9a4680ca2e043dd1d7ad310304366ae8ab776eb78b372a8ba",
    "p64-evals/long_report.pdf": "2dfe3910709300a63b46f58b9c818a25233ec151b263fb78a2154aec562fc349",
    "p65-tables/office_values_250.csv": "dcefc40ee45969cc0c3a3242d60d56fb5bd616f4b16911201f3c3e6406139de8",
    "p65-text/stale_page.txt": "0d2362dcd7a90dae54ba7402b8827679861e74fac6ba4d7fee3d51b2df51786b",
    "p65-text/duplicate_page.txt": "ede987805ad672852e372b697b5e9cbd3437ca01ae3cc8a2e361854ef34272c3",
    "p65-continuation-long/continuation_pages.pdf": "5909a559f67a2bc5c3364e7a5b4b497924c1ec4c0951e0514b3b21c44b17727d",
    "p66-tables/labelled_offices.csv": "9a7220d3c97c0395fc82c81fbe89521b824b1817b9bc000a5596392e096e0510",
    "p66-tables/people_text_only.csv": "ef5e3684b832d90b6a4f17177dcf6cb6bee48ba3b87caacab68b9c4b5d8e01fe",
    "p66-tables/region_years.csv": "65af4a62c19cdd7fb61631f826c4f09eff401b9623e7bf5a5d262376d19c6322",
    "p66-tables/digit_ids.csv": "1c4ea644ad9b3f36ce97fcf71fd7b60c75a26c8d9ed1255dea75c6dadee2073b",
    "p66-tables/consecutive_pairs.csv": "99091f25b2aad798cf2e1e3c9f41de48d1141fcaffb2dc60a4b53aaa3c912b25",
    "p66-tables/dated_quotes.csv": "be7033574b9cd7e12a3a7778e95b8123d7b5dfd130e096f1ec995e6007dc4fa4",
    "p66-tables/empty.csv": "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a",
}

#: The stored reading of row 1 of each `p66-tables` file, as `(header_state,
#: header_candidates, header_row, stored rows)`. `header_row` is the display choice of the
#: website grid. `empty.csv` has no table, so it has no reading.
READINGS = {
    "labelled_offices.csv": ("established", [1], 1, 31),
    "people_text_only.csv": ("ambiguous", [0, 1], 1, 12),
    "region_years.csv": ("ambiguous", [0, 1], 0, 7),
    "digit_ids.csv": ("ambiguous", [0, 1], 1, 15),
    "consecutive_pairs.csv": ("ambiguous", [0, 1], 1, 10),
    "dated_quotes.csv": ("established", [1], 1, 9),
}

#: `(collection, dataset, directory under the test data root)`.
DATASETS = (
    ("p64evals", "fixtures", "p64-evals"),
    ("p65tables", "fixtures", "p65-tables"),
    ("p65tables", "text", "p65-text"),
    ("p65tables", "continuation_long", "p65-continuation-long"),
    ("p66tables", "fixtures", "p66-tables"),
)

#: The pages of `continuation_pages.pdf`. Only the first and the last page have text.
CONTINUATION_PAGES = 6602

EVENTS = [(8780100 + n * 37, f"2021-{(n % 12) + 1:02d}-{(n % 27) + 1:02d}", title) for n, title in enumerate([
    "Spring Reception", "Innovation Breakfast", "Juneteenth Reception", "Teachers Seminar",
    "University Panel", "Holiday Party", "Trade Mission Briefing", "Film Screening",
    "Water Technology Forum", "Student Leaders Dinner", "Interfaith Lunch", "Museum Evening",
    "Independence Day Reception", "Cyber Security Roundtable", "Science Fair Visit",
    "Book Launch", "Music Evening", "Health Innovation Talk", "Farewell Reception"])]


def _pdf(pages: int, marked: int, words: str) -> bytes:
    return _pdf_lines({n: f"Synthetic report page {n}." + (f" {words} signed the memo." if n == marked else "")
                       for n in range(1, pages + 1)}, pages)


def _pdf_lines(lines: dict[int, str], pages: int) -> bytes:
    """A PDF of `pages` pages. A page in `lines` shows its line, and every other page is blank."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for n in range(1, pages + 1):
        line = lines.get(n)
        stream = f"BT /F1 12 Tf 72 720 Td ({line}) Tj ET".encode() if line else b""
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content = len(objects)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                       b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content)
        kids.append(len(objects))
    objects[1] = (b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
                  + b"] /Count %d >>" % pages)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def office_rows() -> list[tuple[str, str, str]]:
    """`(case_id, office, amount)` of the 250 data rows. Every 25th row before the last has
    a blank office. The 241 other rows hold 214 distinct offices."""
    rows = []
    for n in range(1, 251):
        if n == 250:
            office = "Harbour Annex"
        elif n % 25 == 0:
            office = ""
        else:
            office = f"Office {((n - 1) % 220) + 1:03d}"
        rows.append((f"C-{n:03d}", office, str(n * 10)))
    return rows


PEOPLE = [("Alice Moreau", "Paris"), ("Bruno Keller", "Rome"), ("Chen Wei", "Oslo"), ("Dara Quinn", "Paris"),
          ("Emil Novak", "Lisbon"), ("Fatima Zahra", "Rome"), ("Alice Moreau", "Vienna"), ("Goran Ilic", "Oslo"),
          ("Hana Sato", "Paris"), ("Ivo Petrov", "Madrid"), ("Jonas Berg", "Rome"), ("Kira Volkova", "Oslo")]


def labelled_offices() -> list[tuple[str, str, str]]:
    """`(case_id, office, amount)` of the 30 data rows. Only the last row is in `Harbour Annex`."""
    return [(f"C-{n:03d}", "Harbour Annex" if n == 30 else f"Office {(n - 1) % 7 + 1}", str(n * 15))
            for n in range(1, 31)]


def _csv(rows, header=None) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.writer(handle)
    if header:
        writer.writerow(header)
    writer.writerows(rows)
    return handle.getvalue().encode()


def files() -> dict[str, bytes]:
    tasks = []
    for n in range(1, 13):
        done = n <= 7
        tasks.append({"gid": f"12000{n:02d}", "name": f"Synthetic outreach task {n}",
                      "completed": done,
                      "completed_at": f"2020-{n:02d}-15T10:00:00Z" if done else None,
                      "due_on": f"2020-{n:02d}-20"})
    return {
        "p64-evals/monitored_bills_38.csv": BILLS.read_bytes(),
        "p64-evals/events_headerless.csv": _csv(EVENTS),
        "p64-evals/events_with_header.csv": _csv(EVENTS, ["event_id", "date", "title"]),
        "p64-evals/project_export.json": json.dumps({"data": tasks}, indent=2).encode(),
        "p64-evals/long_report.pdf": _pdf(60, 57, "Quillon Varga"),
        "p65-tables/office_values_250.csv": _csv(office_rows(), ["case_id", "office", "amount"]),
        "p65-text/stale_page.txt": "Știință — the quokka report names the old harbour.\n".encode(),
        "p65-text/duplicate_page.txt": "Știință — the quokka memo names the old pier.\n".encode(),
        "p66-tables/labelled_offices.csv": _csv(labelled_offices(), ["case_id", "office", "amount"]),
        "p66-tables/people_text_only.csv": _csv(PEOPLE),
        "p66-tables/region_years.csv": _csv(
            [(region, str(1000 + 111 * n), str(2000 + 97 * n)) for n, region in
             enumerate(["North", "South", "East", "West", "Central", "Coast"], start=1)], ["region", "2018", "2020"]),
        "p66-tables/digit_ids.csv": _csv([(str(9 + n), f"item {n + 1}") for n in range(15)]),
        "p66-tables/consecutive_pairs.csv": _csv([(str(2 * n + 1), str(2 * n + 2)) for n in range(10)]),
        "p66-tables/dated_quotes.csv": _csv(
            [("2021-01-05", "Opening, North", "10"), ("2021-02-07", "", "12.5"), ("2021-03-09", "Reception", ""),
             ("2021-04-11", "Briefing, South", "7"), ("2021-05-13", "Panel", "3.25"), ("2021-06-15", "", "4"),
             ("2021-07-17", "Dinner, East", "11"), ("2021-08-19", "Farewell", "9")], ["opened", "title", "amount"]),
        "p66-tables/empty.csv": b"",
        "p65-continuation-long/continuation_pages.pdf": _pdf_lines(
            {1: "Synthetic continuation page 1 names the quokka.",
             CONTINUATION_PAGES: f"Synthetic continuation page {CONTINUATION_PAGES} names the quokka."},
            CONTINUATION_PAGES),
    }


def check(root: Path) -> list[str]:
    """The files under `root` that are absent or differ from the generated bytes."""
    wrong = []
    for name, data in files().items():
        path = root / name
        if not path.is_file() or path.read_bytes() != data:
            wrong.append(name)
        elif hashlib.sha3_256(data).hexdigest() != EXPECTED[name]:
            wrong.append(name)
    return wrong


def write(root: Path) -> None:
    for name, data in files().items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != data:
            path.write_bytes(data)
        print(f"{hashlib.sha3_256(data).hexdigest()}  {name}")


def _main_py(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", "-i", "hoover4-worker", "uv", "run", "main.py", *args],
                          text=True, capture_output=True, check=False)


def _dataset_present(collection_dataset: str) -> bool:
    query = ("SELECT count() FROM Hoover4_Processing.dataset FINAL "
             f"WHERE collection_dataset = '{collection_dataset}' AND is_deleted = 0")
    result = subprocess.run(
        ["docker", "exec", "-i", "clickhouse", "sh", "-c",
         'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "$1"', "_", query],
        text=True, capture_output=True, check=True)
    return result.stdout.strip() != "0"


def ingest() -> int:
    """Create each missing collection and ingest each missing dataset. A present dataset is
    not rescanned, because a rescan also ingests files that later runs added to its root."""
    listing = _main_py("list-collections")
    if listing.returncode != 0:
        print(listing.stdout + listing.stderr, file=sys.stderr)
        return listing.returncode
    existing = {line.split()[0] for line in listing.stdout.splitlines() if line.strip()}
    for collection, dataset, directory in DATASETS:
        if _dataset_present(f"{collection}_{dataset}"):
            print(f"present: {collection}_{dataset}")
            continue
        if collection not in existing:
            created = _main_py("create-collection", collection, "--fullname", f"Table fixtures {collection}")
            print(created.stdout + created.stderr)
            if created.returncode != 0:
                return created.returncode
        added = _main_py("add-disk-dataset", collection, dataset, f"/testdata/{directory}", "--wait")
        print(added.stdout + added.stderr)
        if added.returncode != 0:
            return added.returncode
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO / "testdata",
                        help="the test data root that the worker mounts as /testdata")
    parser.add_argument("--check", action="store_true", help="verify the files and write nothing")
    parser.add_argument("--ingest", action="store_true", help="also ingest the datasets")
    args = parser.parse_args()
    if args.check:
        wrong = check(args.root)
        for name in wrong:
            print(f"absent or different: {name}", file=sys.stderr)
        return 1 if wrong else 0
    write(args.root)
    if check(args.root):
        print("a written file differs from its expected hash", file=sys.stderr)
        return 1
    return ingest() if args.ingest else 0


if __name__ == "__main__":
    sys.exit(main())
