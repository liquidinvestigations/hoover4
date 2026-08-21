"""The embed activity must page its input, and must not size work by file.

A hash is a file and a file is not bounded: one 209 MB text document is a single hash
whose `text_content` expands to millions of chunks. Materialising all of them at once
took the worker container past its memory limit, the kernel killed the process inside
the cgroup, Temporal lost the activity, and the retry did the same thing again -- a loop
that cannot finish. Batching by the CALLER cannot fix it, because one hash is
indivisible there, so the paging has to live in the activity.
"""

import ast
from pathlib import Path

import tasks.P5_chunk_embed.activities as p5


def _activity_source() -> str:
    source = Path(p5.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "chunk_embed_for_hashes":
            return ast.get_source_segment(source, node) or ""
    raise AssertionError("chunk_embed_for_hashes not found")


def test_the_page_size_is_a_segment_count_not_a_file_count():
    assert isinstance(p5.SEGMENT_PAGE_ROWS, int)
    assert 0 < p5.SEGMENT_PAGE_ROWS <= 5000, (
        "a page has to stay small enough that one page of segments fits in memory "
        f"regardless of how large a single file is; got {p5.SEGMENT_PAGE_ROWS}"
    )


def test_text_content_is_read_a_page_at_a_time():
    body = _activity_source()
    assert "LIMIT {page_rows:UInt32}" in body, (
        "the text_content read is unbounded again; one large file will exhaust memory"
    )
    # Keyset, not OFFSET: OFFSET re-reads everything before it, which is quadratic over
    # a multi-million-segment file.
    assert "(file_hash, extracted_by, page_id) >" in body, (
        "paging must be keyset on the ORDER BY prefix, not OFFSET"
    )


def test_the_anti_join_is_scoped_to_the_page():
    body = _activity_source()
    assert "page_keys:Array(Tuple(String, String, UInt32))" in body, (
        "the already-embedded lookup is scoped by file_hash again, so a single huge "
        "file brings its whole vector key set back into memory"
    )
