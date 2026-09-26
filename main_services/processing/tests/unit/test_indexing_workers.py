"""The index process count: `HOOVER4_INDEXING_WORKERS`, else 4, never below 1."""

import logging

import pytest

from tasks.run_worker import DEFAULT_INDEXING_WORKERS, indexing_worker_processes


def test_unset_gives_the_default(monkeypatch):
    monkeypatch.delenv("HOOVER4_INDEXING_WORKERS", raising=False)
    assert DEFAULT_INDEXING_WORKERS == 4
    assert indexing_worker_processes() == 4


def test_empty_gives_the_default(monkeypatch):
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", "  ")
    assert indexing_worker_processes() == 4


@pytest.mark.parametrize("raw,expected", [("1", 1), ("8", 8), (" 3 ", 3)])
def test_a_number_is_used(monkeypatch, raw, expected):
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", raw)
    assert indexing_worker_processes() == expected


@pytest.mark.parametrize("raw", ["0", "-2"])
def test_a_count_below_one_gives_one(monkeypatch, raw):
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", raw)
    assert indexing_worker_processes() == 1


def test_a_value_that_is_not_a_number_gives_the_default_with_a_warning(monkeypatch, caplog):
    monkeypatch.setenv("HOOVER4_INDEXING_WORKERS", "x")
    with caplog.at_level(logging.WARNING):
        assert indexing_worker_processes() == 4
    assert "HOOVER4_INDEXING_WORKERS is not a number" in caplog.text
