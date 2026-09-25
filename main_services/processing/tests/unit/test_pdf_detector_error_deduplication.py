"""PDF parser failures are the single Error record for unreadable PDFs."""

from tasks.P3_parse_files import workflows


class TemporalCauseFailure(RuntimeError):
    """Test exception that exposes its nested failure through Temporal's ``cause``."""

    def __init__(self, message, cause):
        super().__init__(message)
        self.cause = cause


def test_pdf_failure_omits_the_duplicate_tika_error():
    local_error = RuntimeError("local detector failed")
    tika_error = RuntimeError("document is encrypted")
    pdf_error = TemporalCauseFailure(
        "PDF child workflow failed",
        RuntimeError("qpdf --show-npages failed: invalid password"),
    )
    assert pdf_error.__cause__ is None

    results = workflows._detector_results_for_error_capture(
        ["file", "tika"],
        [local_error, tika_error],
        ["pdf_process"],
        [pdf_error],
    )

    assert results == [local_error, None]


def test_tika_error_remains_when_pdf_parsing_succeeds():
    tika_error = RuntimeError("detector failed")

    results = workflows._detector_results_for_error_capture(
        ["file", "tika"],
        [None, tika_error],
        ["pdf_process"],
        [None],
    )

    assert results == [None, tika_error]


def test_tika_error_remains_after_a_non_qpdf_pdf_failure():
    tika_error = RuntimeError("detector failed")
    pdf_error = RuntimeError("storage write failed")

    results = workflows._detector_results_for_error_capture(
        ["file", "tika"],
        [None, tika_error],
        ["pdf_process"],
        [pdf_error],
    )

    assert results == [None, tika_error]
