"""Every pipeline read of `text_content` must be `FINAL`.

`text_content` is a `ReplacingMergeTree` keyed on
`(collection_dataset, file_hash, extracted_by, page_id)` with **no version column**, so a
re-parse leaves two rows for the same segment until a background merge collapses them.
Until then a bare `SELECT` returns both.

The consequence is different in each stage and invisible in all three:

* **P4** sends the page to the NER model twice and writes two sets of `entity_hit` rows.
* **P5** chunks it twice; the two copies produce *identical* chunk keys, so neither is
  excluded by the left-anti join against `text_chunk_vectors` on a first run — the page is
  embedded twice at full GPU cost and both vectors are inserted.
* **P6** indexes it twice; the Manticore row id is deterministic so the index survives, but
  the work doubles and the stored page text becomes whichever copy came back last.

None of this fails, none of it logs, and it only happens in the window before a merge — so
it reproduces on a busy reprocess and never on a quiet stack. That is exactly the kind of
defect a source-shape assertion is worth more than a runtime test for.
"""

import re
from pathlib import Path

import pytest

TASKS = Path(__file__).resolve().parents[2] / "tasks"

#: (stage, file) whose `text_content` reads are pipeline reads and must be FINAL.
PIPELINE_READERS = [
    ("P4", TASKS / "P4_extract_entities" / "activities.py"),
    ("P5", TASKS / "P5_chunk_embed" / "activities.py"),
    ("P6", TASKS / "P6_index_data" / "activities.py"),
]

#: `FROM text_content`, optionally aliased, and whatever follows on that line.
_READ = re.compile(r"FROM\s+text_content(?:\s+AS\s+\w+)?(?P<tail>[^\n]*)", re.IGNORECASE)


@pytest.mark.parametrize("stage,path", PIPELINE_READERS, ids=[s for s, _ in PIPELINE_READERS])
def test_the_stage_reads_text_content_with_final(stage, path):
    source = path.read_text()
    reads = list(_READ.finditer(source))
    assert reads, f"{stage}: no `FROM text_content` found — did the query move?"
    for match in reads:
        assert "FINAL" in match.group("tail").upper(), (
            f"{stage} reads text_content without FINAL: {match.group(0).strip()!r}. "
            "Duplicate pre-merge rows would be processed twice."
        )


def test_the_regex_would_actually_catch_a_bare_read():
    """A guard that cannot fail is worse than no guard."""
    bare = "SELECT text\n            FROM text_content\n            WHERE x = 1"
    match = _READ.search(bare)
    assert match and "FINAL" not in match.group("tail").upper()

    aliased = "FROM text_content AS t FINAL\n            LEFT ANTI JOIN nlp_processed AS n"
    match = _READ.search(aliased)
    assert match and "FINAL" in match.group("tail").upper()
