"""Verify document page queries exclude synthetic filename rows.

Filename rows use page_id=-1 and support document searches.
Document page readers cannot deserialize those rows as u32.
The source lint examines SELECT templates with page-table references.
"""

import pathlib
import re

def _website_backend() -> pathlib.Path | None:
    """`website/backend/src`, or None when it is not mounted.

    The worker image mounts only `main_services/processing` at `/app`, so inside the
    container there is no website tree to grep and this whole module skips. On the host
    the repo root is four levels up. Both are legitimate; what is not legitimate is
    computing a path that does not exist and reporting green.
    """
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "website" / "backend" / "src"
        if candidate.is_dir():
            return candidate
    return None


WEBSITE_BACKEND = _website_backend()
REPO_ROOT = WEBSITE_BACKEND.parents[2] if WEBSITE_BACKEND else pathlib.Path("/")

#: The exclusion predicate, in the spelling the Rust side uses.
EXCLUSION = "extracted_by != 'filename_index'"

#: `FROM <something>_pages` or a bound pages table. The Rust queries interpolate a
#: validated table name, so the marker is the identifier rather than a literal.
PAGES_TABLE_RE = re.compile(r"FROM\s+\{pages_table\}|FROM\s+\{\w*pages\w*\}", re.IGNORECASE)


def _rust_sources() -> list[pathlib.Path]:
    if WEBSITE_BACKEND is None:
        return []
    return sorted(WEBSITE_BACKEND.rglob("*.rs"))


def _sql_blocks(text: str) -> list[str]:
    """Read SELECT templates that reference page tables."""
    blocks = []
    for chunk in text.split("format!("):
        literal = re.match(
            r'\s*(?:r(?P<hashes>\#*)"(?P<raw>.*?)"(?P=hashes)|"(?P<normal>(?:[^"\\]|\\.)*)")',
            chunk, re.DOTALL,
        )
        if literal is None:
            continue
        sql = literal.group("raw") if literal.group("raw") is not None else literal.group("normal")
        if re.search(r"\bSELECT\b", sql, re.IGNORECASE) and PAGES_TABLE_RE.search(sql):
            blocks.append(sql)
    return blocks


def test_query_templates_exclude_fragments_and_later_source_text():
    fragment = 'format!("FROM {pages}"); // SELECT is documented here.'
    assert _sql_blocks(fragment) == []
    assert _sql_blocks('format!("SELECT id FROM {pages}")') == ['SELECT id FROM {pages}']
    raw = 'format!(r#"SELECT id FROM {pages_table} WHERE name="value""#)'
    assert _sql_blocks(raw) == ['SELECT id FROM {pages_table} WHERE name="value"']
    unrelated = 'format!("error"); let query = "SELECT id FROM {pages}";'
    assert _sql_blocks(unrelated) == []


def test_the_website_backend_is_reachable_or_explicitly_skipped():
    """This test is worthless if it silently finds no files. The worker image mounts
    only `main_services/processing`, so skipping there is legitimate, vanishing without
    saying so is not."""
    if WEBSITE_BACKEND is None:
        import pytest
        pytest.skip("website sources not mounted (worker image); run this on the host")
    assert _rust_sources(), "found the website tree but no .rs files in it"



def test_every_pages_query_excludes_the_filename_row():
    if WEBSITE_BACKEND is None:
        import pytest
        pytest.skip("website sources not mounted")

    offenders = []
    for path in _rust_sources():
        text = path.read_text(errors="replace")
        for block in _sql_blocks(text):
            # A query that already filters `extracted_by = <something>` to one real
            # extractor cannot see the filename row either.
            if EXCLUSION in block or "extracted_by = {}" in block:
                continue
            offenders.append(path.relative_to(REPO_ROOT))
    assert not offenders, (
        "these files query a pages table without excluding the filename_index row "
        f"({EXCLUSION}): {sorted(set(map(str, offenders)))}"
    )


def test_the_indexer_and_the_readers_agree_on_the_spelling():
    """One side writing `filename_index` and the other excluding `filenames_index` is a
    bug with no symptom until someone searches for a filename."""
    from tasks.P6_index_data.activities import FILENAME_EXTRACTED_BY, FILENAME_PAGE_ID

    assert FILENAME_EXTRACTED_BY == "filename_index"
    assert FILENAME_PAGE_ID == -1
    assert FILENAME_EXTRACTED_BY in EXCLUSION

    if WEBSITE_BACKEND is None:
        return
    search_sql = (WEBSITE_BACKEND / "api" / "search" / "search_sql.rs").read_text()
    assert f'"{FILENAME_EXTRACTED_BY}"' in search_sql, (
        "the Rust constant no longer spells the extractor the same way the indexer does"
    )


def test_the_clickhouse_side_never_sees_the_row():
    """`text_content` is the ClickHouse page store, and the filename row is written ONLY
    to Manticore. P4 (entity extraction), P5 (chunk/embed) and the `nlp_processed`
    watermark all read `text_content`, so they are immune by construction. This pins
    that the indexer did not start writing it to ClickHouse as well."""
    import ast
    import inspect
    import textwrap

    from tasks.P6_index_data import activities as p6

    # Verify that metadata reads do not write a filename row into the text store.
    target = p6.document_metadata
    while hasattr(target, "__wrapped__"):
        target = target.__wrapped__
    tree = ast.parse(textwrap.dedent(inspect.getsource(target)))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    body = ast.dump(ast.Module(body=function.body[1:], type_ignores=[]))

    assert "insert_arrow" not in body, (
        "the filename row must not be written to ClickHouse; it is a Manticore-only "
        "search artefact and P4/P5 are immune to it only because of that"
    )
    assert "vfs_files" in body, "it must be built from the VFS paths"
