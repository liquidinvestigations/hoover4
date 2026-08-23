"""Every reader of a Manticore pages table must exclude the `filename_index` row.

That row is not a page. It carries a document's basenames so a query for a filename finds
the document, and it has `page_id = -1`. A value chosen to be unreachable for a real
extractor. The cost is that it leaks into every code path that assumes a pages row is a
page:

* the document endpoints deserialise `page_id` as `u32`, so `-1` is not an off-by-one,
  it fails the whole query;
* a "N other matches" count that includes it is one too high on every filename hit;
* a viewer that offers to jump to "page -1" has nowhere to go.

Grep-based, and deliberately so. The readers are in two languages across two crates, and
the alternative (trusting each author to remember) is exactly what this row makes
dangerous. It is ugly and it is effective.
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
    """Rust `format!` string literals that look like a Manticore query over pages.

    Split on `format!(` rather than parsed: this is a lint, not a compiler, and a false
    positive here costs one exclusion clause while a false negative costs a 500.
    """
    blocks = []
    for chunk in text.split("format!("):
        if PAGES_TABLE_RE.search(chunk[:2000]):
            blocks.append(chunk[:2000])
    return blocks


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

    # The AST of the function alone, with its docstring dropped: the docstring
    # deliberately NAMES `text_content` to say the row never comes from there, and a
    # substring search over the source would read that promise as a violation of itself.
    # `document_metadata` is where the row's TEXT comes from (its `basenames`) which is
    # what has to stay clear of the page store; the writer around it reads text_content
    # for the real pages.
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
    assert "text_content" not in body, (
        "the filename row is built from vfs_files basenames, never from page text "
        "(page text carries base64 and XPM junk)"
    )
    assert "vfs_files" in body, "it must be built from the VFS paths"
