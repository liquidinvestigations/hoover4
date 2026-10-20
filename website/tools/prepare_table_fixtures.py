#!/usr/bin/env python3
"""Write and ingest the synthetic fixtures of the agent table and text viewer stack tests.

Every file is synthetic. The script copies no conversation and no demo document.

`p64evals_fixtures` (collection `p64evals`, root `testdata/p64-evals/`):

* `monitored_bills_38.csv`: a header row and 38 bills, stored as `row_id` 1 to 39. It is a
  copy of the tracked unit-test fixture `main_services/processing/tests/unit/fixtures/`.
  The last data row, `SYN-038`, is the fifth bill in state SC.
* `events_headerless.csv`: 19 dated event rows and no header row. The table parser takes
  the first row as the header (`parse_table._observe`).
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
}

#: `(collection, dataset, directory under the test data root)`.
DATASETS = (
    ("p64evals", "fixtures", "p64-evals"),
    ("p65tables", "fixtures", "p65-tables"),
    ("p65tables", "text", "p65-text"),
    ("p65tables", "continuation_long", "p65-continuation-long"),
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
