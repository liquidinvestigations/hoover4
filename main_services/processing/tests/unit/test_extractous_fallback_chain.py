"""The four-step extractous fallback chain: step order, skips, and giving up.

`_get_pool()` is replaced with a fake keyed by the temporary path's extension, so these
stay in the fast tier: no JVM, no native Extractous call. `_extract_with_hinted_type`
still runs for real and still builds the real hinted path through
`extension_for_mime_type`, so the extension each fake result is keyed on is the one the
chain actually asks for, not a guess.
"""

import os

import pytest
from temporalio.exceptions import ApplicationError

from tasks.P3_parse_files import parse_tika


class _FakePool:
    """`extract(path)` answers by the path's extension.

    A path whose extension is not in `results` raises `KeyError`, so a step this test
    did not expect to reach fails loudly instead of returning a default.
    """

    def __init__(self, results):
        self._results = results
        self.calls = []

    def extract(self, path):
        self.calls.append(path)
        outcome = self._results[os.path.splitext(path)[1]]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _install(monkeypatch, pool, candidates):
    monkeypatch.setattr(parse_tika, "_get_pool", lambda: pool)
    monkeypatch.setattr(parse_tika, "_detector_candidate_types", lambda file_path: candidates)


def _rfc822_parse_error():
    return RuntimeError(
        "extractous failed for /tmp/x: 'ParseError(\"Parse error occurred : "
        "Failed to parse an email message\")'"
    )


@pytest.fixture
def fixture_path(tmp_path):
    # `.dat`: an extension `extension_for_mime_type` maps no candidate type to in
    # these tests, so step 4's call (which uses this path unchanged) never collides
    # with a hinted attempt's temporary extension.
    path = tmp_path / "epstein_sample.dat"
    path.write_text("From: a\nTo: b\n\nnot really an email, just header-shaped text.\n")
    return str(path)


def test_step_1_fails_step_2_succeeds(monkeypatch, fixture_path):
    """The measured shape: the first candidate is `message/rfc822` and fails there."""
    _install(
        monkeypatch,
        pool=_FakePool({
            ".eml": _rfc822_parse_error(),
            ".pdf": ("recovered at step 2", {"Content-Type": ["application/pdf"]}),
        }),
        candidates=[
            ("the file detector's first match", "message/rfc822"),
            ("the file detector's second match", "application/pdf"),
        ],
    )
    text, meta = parse_tika._extract_with_extractous(fixture_path)
    assert text == "recovered at step 2"
    assert meta == {"Content-Type": ["application/pdf"]}


def test_reaches_step_3_the_extension_implied_type(monkeypatch, fixture_path):
    pool = _FakePool({
        ".eml": _rfc822_parse_error(),
        ".pdf": RuntimeError("extractous failed: not really a pdf"),
        ".txt": ("recovered at step 3", {}),
    })
    _install(
        monkeypatch,
        pool=pool,
        candidates=[
            ("the file detector's first match", "message/rfc822"),
            ("the file detector's second match", "application/pdf"),
            ("the file extension", "text/plain"),
        ],
    )
    text, meta = parse_tika._extract_with_extractous(fixture_path)
    assert text == "recovered at step 3"
    assert [os.path.splitext(c)[1] for c in pool.calls] == [".eml", ".pdf", ".txt"]


def test_reaches_step_4_extractous_own_detection(monkeypatch, fixture_path):
    """Every hinted candidate fails; the un-hinted call on the original path succeeds."""
    pool = _FakePool({
        ".eml": _rfc822_parse_error(),
        ".pdf": RuntimeError("extractous failed: not really a pdf"),
        ".txt": RuntimeError("extractous failed: not really plain text either"),
        ".dat": ("recovered at step 4", {"Content-Type": ["message/rfc822"]}),
    })
    _install(
        monkeypatch,
        pool=pool,
        candidates=[
            ("the file detector's first match", "message/rfc822"),
            ("the file detector's second match", "application/pdf"),
            ("the file extension", "text/plain"),
        ],
    )
    text, meta = parse_tika._extract_with_extractous(fixture_path)
    assert text == "recovered at step 4"
    # the fourth call carries the original path, unchanged, no rename
    assert pool.calls[-1] == fixture_path


def test_giving_up_names_every_attempt_once(monkeypatch, fixture_path):
    pool = _FakePool({
        ".eml": _rfc822_parse_error(),
        ".pdf": RuntimeError("extractous failed: not really a pdf"),
        ".dat": RuntimeError("extractous failed: no detector was right"),
    })
    _install(
        monkeypatch,
        pool=pool,
        candidates=[
            ("the file detector's first match", "message/rfc822"),
            ("the file detector's second match", "application/pdf"),
        ],
    )
    with pytest.raises(RuntimeError) as excinfo:
        parse_tika._extract_with_extractous(fixture_path)
    message = str(excinfo.value)
    assert "3 attempt(s)" in message
    assert "the file detector's first match (message/rfc822)" in message
    assert "the file detector's second match (application/pdf)" in message
    assert "extractous's own detection, no type given" in message
    # one raise carries all three attempts, not one raise per attempt
    assert message.count("after 3 attempt(s)") == 1
    assert len(pool.calls) == 3


def test_a_timeout_aborts_the_chain_instead_of_trying_the_next_candidate(monkeypatch, fixture_path):
    pool = _FakePool({
        ".eml": ApplicationError("extractous timed out after 600s", non_retryable=True),
        ".pdf": ("never reached", {}),
    })
    _install(
        monkeypatch,
        pool=pool,
        candidates=[
            ("the file detector's first match", "message/rfc822"),
            ("the file detector's second match", "application/pdf"),
        ],
    )
    with pytest.raises(ApplicationError):
        parse_tika._extract_with_extractous(fixture_path)
    # only the first, timed-out candidate ran; the second was never attempted
    assert len(pool.calls) == 1


def test_a_duplicate_candidate_type_is_skipped_not_attempted(tmp_path):
    """`_detector_candidate_types` itself, against real detectors, on a plain-text file.

    `file` and the extension both name a `.txt` file `text/plain`, so the chain must
    collapse to one candidate, not repeat the type a second time as a distinct step.
    """
    path = tmp_path / "note.txt"
    path.write_text("This is an ordinary short memo with nothing ambiguous in it.\n")
    candidates = parse_tika._detector_candidate_types(str(path))
    types = [mime_type for _source, mime_type in candidates]
    assert types.count("text/plain") <= 1
